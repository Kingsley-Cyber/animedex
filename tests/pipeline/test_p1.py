"""P1 WHAT on the mock provider: AC-09 (activation rules), AC-10 (verify list, uncertainty
reasons), AC-11 (no quotes/dialogue; no framing claims in sensory fields)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from animedex import SCHEMA_VERSION
from animedex.activation import violations
from animedex.cli import app
from animedex.config import ModelSpec, load_settings
from animedex.models import CorpusEntry
from animedex.ontology import get_vocab
from animedex.pipeline.canonicalize import canonicalize
from animedex.pipeline.p1 import render_prompt, run_p1, verify_list
from animedex.providers.base import ProviderResponse, Usage
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.jsonl import read_jsonl
from animedex.store.runlog import RunLog

pytestmark = pytest.mark.pipeline

ENTRY = {"title_id": "ironvale_circuit_2021", "title": "Ironvale Circuit", "year": 2021, "medium": "anime",
         "format": "serialized", "scope": {"version": "synthetic TV", "seasons": [1], "numbering": "broadcast"},
         "role_tags": ["hit"]}


def fv(value: Any, conf: float = 0.85, reason: str | None = None, condition: str | None = None) -> dict:
    out = {"value": value, "conf": conf, "uncertainty_reason": reason, "epistemic": "interpretive"}
    if condition is not None:
        out["condition"] = condition
    return out


def make_draft(modules: tuple[str, ...] = ("power_combat", "sensory", "anime_production", "series_engine")) -> dict:
    vocab = get_vocab()
    draft: dict[str, Any] = {"modules_active": list(modules), "verify": []}
    for block in ["core", *modules]:
        draft[block] = {}
        for f in vocab.block_fields(block):
            value = vocab.enum(f.vocab)[0] if f.kind == "enum" else f"synthetic {f.name.replace('_', ' ')}"
            cond = "shows when the grid fails" if f.conditional else None
            draft[block][f.name] = fv(value, condition=cond) if f.conditional else fv(value)
    draft["core"]["central_mystery"] = fv(None, conf=0, reason="no open question in scope")
    draft["core"]["tone"] = fv("wry and tense", conf=0.5, reason="tone shifts across the season")
    draft["moments"] = [{"description": f"Synthetic moment {i} where the courier reroutes power.", "season": 1,
                         "episode": i, "timestamp": None, "moment_type": "reversal",
                         "why_it_hit": "A private skill turns into a public cost.", "conf": 0.7} for i in (1, 2, 3)]
    return draft


def client_for(repo, responses) -> tuple[LLMClient, MockProvider]:
    mock = MockProvider(responses=responses)
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="m"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_p1"))
    return client, mock


def run(repo, responses, entry=ENTRY):
    client, mock = client_for(repo, responses)
    result = run_p1(repo, [CorpusEntry.model_validate(entry)], client, get_vocab(), load_settings(repo),
                    run_id="run_p1", created_at="2026-09-26T12:00:00+00:00")
    return result, mock


KEY = ("P1", "ironvale_circuit_2021")


def test_p1_writes_candidates_and_mandatory_verify_list(repo):
    result, _ = run(repo, {KEY: make_draft()})
    [title] = result.titles
    assert len(result.moments) == 3
    verify = json.loads((repo.candidates / "verify" / "ironvale_circuit_2021.json").read_text())["verify"]
    must = {"core.outcome", "sensory.power_visual_signature", "sensory.choreography_style", "sensory.color_motif",
            "sensory.animation_signature", "core.tone", "core.central_mystery",
            *(f"moments.ironvale_circuit_2021.mo.0{i}.locator" for i in (1, 2, 3))}
    assert must <= set(verify)
    assert title["core"]["outcome"]["verification"] == "unverified"
    assert title["core"]["outcome"]["epistemic"] == "external_metric"
    assert title["core"]["logline_hook"]["verification"] == "not_required"
    assert all(m["verification"] == "unverified" for m in result.moments)
    assert title["provenance"]["pass"] == "P1" and title["provenance"]["cache_key"].startswith("sha256:")
    assert (repo.candidates / "title" / "ironvale_circuit_2021.jsonl").is_file()
    assert (repo.candidates / "moment" / "ironvale_circuit_2021.jsonl").is_file()


def test_low_confidence_without_reason_is_repaired_or_quarantined(repo):
    bad = make_draft()
    bad["core"]["tone"]["uncertainty_reason"] = None
    result, mock = run(repo, {KEY: [bad, bad]})
    assert result.titles == [] and result.quarantined and "uncertainty_reason" in result.quarantined[0][1]
    assert len(mock.calls) == 2


def test_repair_fixes_activation_rule_violation(repo):
    wrong = make_draft(("power_combat", "sensory", "series_engine"))  # anime without anime_production
    result, mock = run(repo, {KEY: [wrong, make_draft()]})
    assert len(result.titles) == 1 and len(mock.calls) == 2
    assert "anime_production must be active" in mock.calls[1]["user"]


@pytest.mark.parametrize("medium, fmt, active, expect_ok", [
    ("anime", "serialized", ["sensory", "anime_production", "series_engine"], True),
    ("anime", "film", ["sensory", "anime_production", "film"], True),
    ("live_action", "serialized", ["series_engine"], True),
    ("live_action", "serialized", ["power_combat", "series_engine"], False),   # power_combat -> sensory
    ("live_action", "serialized", ["power_combat", "sensory", "series_engine"], True),
    ("film", "film", ["film"], True),
    ("film", "film", ["film", "series_engine"], False),
    ("western_animation", "episodic", ["series_engine"], False),               # animated -> sensory
    ("adult_animation", "hybrid", ["sensory", "series_engine", "comedy_satire"], True),
    ("anime", "episodic", ["sensory", "series_engine"], False),                # anime -> anime_production
])
def test_activation_rules(medium, fmt, active, expect_ok):
    """AC-09 rule test: modules follow the 05 activation table."""
    assert (violations(get_vocab(), medium, fmt, active) == []) is expect_ok


def test_sensory_framing_claim_and_quotes_force_repair(repo):
    dirty = make_draft()
    dirty["sensory"]["choreography_style"]["value"] = "tight close-up on every clash"
    dirty["moments"][0]["description"] = 'He says "I will never stop running" and leaves.'
    result, mock = run(repo, {KEY: [dirty, make_draft()]})
    assert len(result.titles) == 1
    repair = mock.calls[1]["user"]
    assert "close-up" in repair and "quotation" in repair


def test_dialogue_line_in_moment_is_rejected(repo):
    dirty = make_draft()
    dirty["moments"][1]["why_it_hit"] = "Marisol: this grid answers to me now"
    result, _ = run(repo, {KEY: [dirty, dirty]})
    assert result.titles == [] and "dialogue" in result.quarantined[0][1]


def test_off_vocab_flows_to_proposal_through_canonicalize(repo):
    repo.corpus_file.write_text(yaml.safe_dump({"titles": [ENTRY]}))
    draft = make_draft()
    draft["power_combat"]["gate"] = fv("other:grid inheritance by oath", conf=0.6, reason="gate mixes two routes")
    result, _ = run(repo, {KEY: draft})
    assert result.titles[0]["power_combat"]["gate"]["value"] == "other:grid inheritance by oath"
    out = canonicalize(repo, "run_canon")
    assert out.written["title"] == ["ironvale_circuit_2021"] and out.written["moment"]
    stored = read_jsonl(repo.canonical / "titles.jsonl")[0]
    assert stored["power_combat"]["gate"]["value"] == "other"
    assert any("grid_inheritance_by_oath" in p.name for p in out.proposals)


def test_verify_list_ignores_advisory_paths_outside_the_profile(repo):
    result, _ = run(repo, {KEY: make_draft()})
    title = copy.deepcopy(result.titles[0])
    vl = verify_list(title, ["x.mo.01"], get_vocab(), load_settings(repo), ["film.closure", "core.tone", "nonsense"])
    assert "film.closure" not in vl and "nonsense" not in vl and "core.tone" in vl


def test_prompt_version_tracks_threshold_and_fragments(repo):
    vocab, settings = get_vocab(), load_settings(repo)
    base = render_prompt(repo, vocab, settings)
    assert "{conf_threshold}" not in base.system and "0.7" in base.system and "system_granted" in base.system
    settings.verify["conf_threshold"] = 0.6
    assert render_prompt(repo, vocab, settings).version != base.version
    frag = repo.prompts / "p1_modules" / "film.md"
    frag.write_text(frag.read_text() + "- extra note\n")
    assert render_prompt(repo, vocab, load_settings(repo)).version != base.version


def test_blind_guard_refuses_live_p1_on_unannotated_gold_title(git_repo):
    gold = {**ENTRY, "role_tags": ["gold", "hit"]}
    git_repo.corpus_file.write_text(yaml.safe_dump({"titles": [gold]}))

    class Live:
        name, live, calls = "live", True, 0

        def generate(self, *a, **k):
            Live.calls += 1
            return ProviderResponse(json.dumps(make_draft()), Usage(10, 10), "live/m")

    from animedex.budget import Budget, Price
    from animedex.guards import live_title_guard

    client = LLMClient(provider=Live(), provider_name="live", spec=ModelSpec(provider="live", model="m"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(git_repo.cache), runlog=RunLog(git_repo.raw_runs, "run_live"),
                       price=Price(1, 1), budget=Budget(10, 10, 10),
                       title_guard=live_title_guard(git_repo, load_settings(git_repo), get_vocab()))
    result = run_p1(git_repo, [CorpusEntry.model_validate(gold)], client, get_vocab(), load_settings(git_repo), run_id="r")
    assert Live.calls == 0 and result.refused and "blind guard" in result.refused[0][1]


def test_cli_dry_run_makes_no_calls(repo):
    repo.corpus_file.write_text(yaml.safe_dump({"titles": [ENTRY]}))
    result = CliRunner().invoke(app, ["p1", "--title", "ironvale_circuit_2021", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would call" in result.output and "Profile this title inside the scope." in result.output
    assert not repo.raw_runs.exists()
