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


# ---------------------------------------------------------------- P1 1.1.0: rules decide modules
def entry_for(medium: str, fmt: str) -> CorpusEntry:
    scope = {"version": "synthetic", "seasons": [] if fmt == "film" else [1], "numbering": None if fmt == "film" else "broadcast"}
    return CorpusEntry.model_validate({"title_id": "lantern_debt_2019", "title": "Lantern Debt", "year": 2019,
                                       "medium": medium, "format": fmt, "scope": scope})


def test_schema_offers_only_modules_the_rules_allow():
    from animedex.pipeline.p1 import output_schema

    vocab = get_vocab()
    west = output_schema(vocab, entry_for("western_animation", "episodic"))
    assert "anime_production" not in west["properties"] and "film" not in west["properties"]
    assert {"sensory", "series_engine"} <= set(west["required"]) and "modules_active" not in west["properties"]
    film = output_schema(vocab, entry_for("film", "film"))
    assert "film" in film["required"] and "series_engine" not in film["properties"]
    live = output_schema(vocab, entry_for("live_action", "serialized"))
    assert "sensory" in live["properties"] and "sensory" not in live["required"]  # allowed only with power_combat


def test_normalize_drops_blank_and_forbidden_modules_and_derives_active():
    from animedex.pipeline.p1 import UNKNOWN_REASON, normalize_draft

    vocab = get_vocab()
    draft = make_draft(("power_combat", "relationships", "sensory", "anime_production", "series_engine", "film"))
    draft["modules_active"] = ["film"]  # the model's own list is ignored
    for f in draft["relationships"].values():
        f.update(value=None, conf=0, uncertainty_reason=None)
    out = normalize_draft(draft, entry_for("western_animation", "episodic"), vocab)
    assert out["modules_active"] == ["power_combat", "sensory", "series_engine"]
    assert "anime_production" not in out and "film" not in out and "relationships" not in out
    out["core"]["central_mystery"]["uncertainty_reason"] = None
    out["core"]["central_mystery"].update(value=None, conf=0)
    again = normalize_draft(out, entry_for("western_animation", "episodic"), vocab)
    assert again["core"]["central_mystery"]["uncertainty_reason"] == UNKNOWN_REASON


def test_sensory_outside_animation_follows_power_combat():
    from animedex.pipeline.p1 import normalize_draft

    vocab = get_vocab()
    no_power = make_draft(("sensory", "series_engine"))
    assert normalize_draft(no_power, entry_for("live_action", "serialized"), vocab)["modules_active"] == ["series_engine"]
    with_power = make_draft(("power_combat", "sensory", "series_engine"))
    assert normalize_draft(with_power, entry_for("live_action", "serialized"), vocab)["modules_active"] == [
        "power_combat", "sensory", "series_engine"]


def test_blank_placeholder_modules_no_longer_cost_a_repair(repo):
    # the live failure: every module block returned, inactive ones all-null without reasons
    draft = make_draft(("power_combat", "sensory", "anime_production", "series_engine", "comedy_satire", "film"))
    for block in ("comedy_satire", "film"):
        for f in draft[block].values():
            f.update(value=None, conf=0, uncertainty_reason=None)
    result, mock = run(repo, {KEY: [draft]})
    assert len(result.titles) == 1 and len(mock.calls) == 1
    assert result.titles[0]["modules_active"] == ["power_combat", "sensory", "anime_production", "series_engine"]


def test_null_values_carry_conf_zero_after_normalizing():
    from animedex.pipeline.p1 import normalize_draft

    draft = make_draft()
    draft["power_combat"]["ranking_ladder"] = fv(None, conf=0.4, reason=None)  # the live Avatar failure
    out = normalize_draft(draft, entry_for("anime", "serialized"), get_vocab())
    assert out["power_combat"]["ranking_ladder"]["conf"] == 0
    assert out["power_combat"]["ranking_ladder"]["uncertainty_reason"] == "no reliable recall"



def test_over_long_phrases_get_a_small_length_repair_not_a_full_rewrite(repo):
    long = make_draft()
    long["core"]["logline_hook"]["value"] = ("a courier who can see the whole city grid trades her memories for "
                                             "power every night")  # 17 words
    short = {"items": [{"path": "core.logline_hook", "text": "a courier trades her memories for city power"}]}
    result, mock = run(repo, {KEY: [long], ("P1", f"{KEY[1]}.shorten"): [short]})
    assert len(result.titles) == 1 and [c["record_id"] for c in mock.calls] == [KEY[1], f"{KEY[1]}.shorten"]
    assert result.titles[0]["core"]["logline_hook"]["value"] == "a courier trades her memories for city power"


def test_a_length_repair_that_stays_long_is_quarantined(repo):
    long = make_draft()
    long["core"]["logline_hook"]["value"] = "one two three four five six seven eight nine ten eleven twelve thirteen"
    still = {"items": [{"path": "core.logline_hook", "text": "one two three four five six seven eight nine ten eleven "
                                                              "twelve thirteen fourteen"}]}
    result, _ = run(repo, {KEY: [long], ("P1", f"{KEY[1]}.shorten"): [still, still]})
    assert result.titles == [] and "over 12 words" in result.quarantined[0][1]


def test_replay_rebuilds_candidates_from_the_stored_draft_without_a_call(repo):
    from animedex.store.jsonl import dumps_jsonl

    tid = "ironvale_circuit_2021"
    run(repo, {KEY: make_draft()})
    path = repo.candidates / "title" / f"{tid}.jsonl"
    first = path.read_text()
    [rec] = read_jsonl(path)
    rec["core"]["tone"]["verification"] = "web_confirmed"  # a later VERIFY rewrote the candidate in place
    path.write_text(dumps_jsonl([rec]))
    client, mock = client_for(repo, {})
    other = CorpusEntry.model_validate({**ENTRY, "title_id": "other_show_2020", "title": "Other Show", "year": 2020})
    result = run_p1(repo, [CorpusEntry.model_validate(ENTRY), other], client, get_vocab(), load_settings(repo),
                    run_id="run_replay", replay=True)
    assert not mock.calls and len(result.titles) == 1
    assert path.read_text() == first  # the same draft with the original run's provenance
    kept = repo.candidates / "title" / "superseded" / "run_replay" / f"{tid}.jsonl"
    assert read_jsonl(kept)[0]["core"]["tone"]["verification"] == "web_confirmed"  # replaced, never deleted
    assert result.failed == [("other_show_2020", "no P1 candidate to replay")]



def test_replay_reuses_a_cached_length_repair_and_never_calls(repo):
    long = make_draft()
    long["core"]["logline_hook"]["value"] = ("a courier who can see the whole city grid trades her memories for "
                                             "power every night")
    short = {"items": [{"path": "core.logline_hook", "text": "a courier trades her memories for city power"}]}
    run(repo, {KEY: [long], ("P1", f"{KEY[1]}.shorten"): [short]})
    first = (repo.candidates / "title" / f"{KEY[1]}.jsonl").read_text()
    client, mock = client_for(repo, {})
    result = run_p1(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), load_settings(repo),
                    run_id="run_replay", replay=True)
    assert not mock.calls and len(result.titles) == 1
    assert (repo.candidates / "title" / f"{KEY[1]}.jsonl").read_text() == first
    (repo.cache / "P1").rename(repo.cache / "P1_gone")  # nothing stored: a clean refusal, still no call
    again = run_p1(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), load_settings(repo),
                   run_id="run_replay2", replay=True)
    assert not mock.calls and again.failed == [(KEY[1], "its stored draft is not in the response cache")]
