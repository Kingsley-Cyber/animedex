"""`animedex diagnose` offline (owner ruling 2026-09-27, M5; AC-57): one structuring call, every gate as on
generated cards, the same judge call, an ablation pass; one line per check and a prescription for each
failure from the fixed operator/rung table. Private output under data/diagnose/."""

from __future__ import annotations

import json
import re

import pytest
import yaml
from typer.testing import CliRunner

from animedex import SCHEMA_VERSION
from animedex.cli import app
from animedex.config import ModelSpec, load_settings
from animedex.embeddings.base import MockEmbedder
from animedex.ideate.diagnose import LADDER, PRESCRIPTIONS, diagnose_id, run_diagnose
from animedex.ideate.llm import OPERATORS
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.conftest import write_state
from tests.pipeline.test_ideate import T1, state

pytestmark = pytest.mark.pipeline

CONCEPT = ("A courier can borrow any stranger's courage for one night, but the stranger forgets being brave, "
           "so every rescue leaves a town of people who never learn they were heroes.")
PROFILE = {"gate": "contract", "cost_of_power": "lifespan", "progression": "linear",
           "visible_counter": "collectible_count", "fight_medium": "energy", "power_is": "collective"}


def answer(system, user, schema, params, *, logline="A courier borrows strangers' courage for one night at a time."):
    props = schema.get("properties", {})
    if "theme_root" in props:  # structuring
        return {"logline": logline,
                "premise": "A night courier borrows the courage of strangers to win impossible fights; each lender "
                           "forgets the bravery, so the town never knows its own heroes.",
                "theme_root": "Who owns courage that nobody remembers?",
                "engine": {"goal": "keep the night routes safe", "constraint": "courage must be borrowed",
                           "strategy": "borrow from strangers only", "benefit": "wins fights she should lose",
                           "cost": "lenders forget their bravery", "dilemma": "save the town or let it know itself",
                           "dramatic_question": "Will anyone remember what the town was brave enough to do?"},
                "what_changed": "The hero's power is other people's forgotten courage.",
                "consequences": {"choices": "She picks lenders, not fights.", "relationships": "Strangers become debtors.",
                                 "outcomes": "The town forgets its courage."},
                "profile": PROFILE, "closest_existing": props["closest_existing"]["enum"][0],
                "why_not_a_clone": "The cost falls on lenders who never know they paid.", "broken_rule": "",
                "appetite": "quiet heroism", "why_different": None}
    if "cards" in props:  # the IDEATE judge, one card
        [ref] = props["cards"]["items"]["properties"]["ref"]["enum"]
        return {"cards": [{"ref": ref, "choices_differs": True, "relationships_differs": True, "outcomes_differs": False,
                           "choices_reason": "She chooses lenders.", "relationships_reason": "Debts replace bonds.",
                           "outcomes_reason": "Same victories.", "failure_conditions_triggered": [],
                           "coherence": "pass", "coherence_reason": "The forgetting is the theme.",
                           "runway_hurts_by_arc5": False, "runway_reason": "Borrowing gets easier as she grows.",
                           "why_different_verdict": "not_applicable", "why_different_reason": "",
                           "taste": [{"criterion": "T2", "evidence": "A known power, paid by strangers."}]}]}
    if "parts" in props:  # ablation
        parts = props["parts"]["items"]["properties"]["part"]["enum"]
        verdict = {"engine.cost": "load_bearing", "engine.dilemma": "load_bearing", "what_changed": "decoration"}
        return {"parts": [{"part": p, "verdict": verdict.get(p, "supporting"), "reason": "Removing it changes little."}
                          for p in parts]}
    raise AssertionError(f"unexpected schema {sorted(props)}")


def clients(repo, respond=answer, name="run_dg"):
    def make():
        return LLMClient(provider=MockProvider(default=respond), provider_name="mock",
                         spec=ModelSpec(provider="mock", model="v"), prompt_version="unset",
                         schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                         cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, name))
    return {"ideate_generate": make(), "ideate_judge": make()}


@pytest.fixture
def indexed(repo):
    write_state(repo, state())
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope", "role_tags")}
              for t in state()["title"]]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    return repo


def test_diagnose_runs_every_gate_the_judge_and_ablation_in_three_calls(indexed):
    cs = clients(indexed)
    res = run_diagnose(indexed, load_settings(indexed), get_vocab(), text=CONCEPT, clients=cs, embedder=MockEmbedder(),
                       run_id="run_dg", date="2026-09-27")
    assert sum(len(c.provider.calls) for c in cs.values()) == 3  # structure, judge, ablation
    assert re.match(r"^diag_20260927_[0-9a-f]{8}$", res.diagnose_id) and res.diagnose_id == diagnose_id(CONCEPT,
                                                                                                         "2026-09-27")
    names = [c.name for c in res.checks]
    assert names == ["structure", "clone", "novelty", "graveyard", "name leak", "H1 consequence test", "coherence",
                     "runway", "ablation"]
    status = {c.name: c.status for c in res.checks}
    assert status["novelty"] == "FAIL"  # no atoms and no census: nothing backs an untried pair
    assert status["runway"] == "FAIL" and status["ablation"] == "FAIL"  # the twist is decoration
    assert status["clone"] == status["H1 consequence test"] == status["coherence"] == "PASS"
    lines = res.lines
    for c in res.checks:  # one line per check, and a prescription under every failure
        at = lines.index(next(line for line in lines if line.startswith(f"  {c.status} {c.name}:")))
        if c.status == "FAIL":
            assert lines[at + 1].startswith("       fix: ")
    assert "fix: operator combine_mechanisms" in "\n".join(lines)  # novelty
    assert "fix: ladder rung 'engine and escalation'" in "\n".join(lines)  # runway
    assert "fix: operator change_rule" in "\n".join(lines)  # the twist is decoration
    stored = json.loads((indexed.root / res.json_path).read_text())
    assert res.json_path.startswith("data/diagnose/") and stored["card"]["profile"] == PROFILE
    assert stored["concept"] == CONCEPT and len(stored["ablation"]) == 14  # 7 engine parts, twist, 6 profile (no broken rule)
    md = (indexed.root / res.md_path).read_text()
    assert "## Checks" in md and "| novelty | FAIL |" in md and "## Which parts carry it (ablation)" in md
    structure_user = cs["ideate_generate"].provider.calls[0]["user"]
    assert structure_user.startswith("concept: A courier") and f"title {T1}: anime;" in structure_user


def test_a_reused_name_fails_the_name_leak_check(indexed):
    def leaky(system, user, schema, params):
        return answer(system, user, schema, params, logline="Ironvale Circuit, but the courier borrows courage.")

    res = run_diagnose(indexed, load_settings(indexed), get_vocab(), text=CONCEPT, clients=clients(indexed, leaky),
                       embedder=MockEmbedder(), run_id="run_dl", date="2026-09-27")
    leak = next(c for c in res.checks if c.name == "name leak")
    assert leak.status == "FAIL" and leak.failure == "name_leak" and "fix: ladder rung 'world'" in "\n".join(res.lines)


def test_diagnose_keeps_gold_titles_out_while_the_blind_is_pending(indexed):
    data = yaml.safe_load(indexed.corpus_file.read_text())
    for t in data["titles"]:
        if t["title_id"] == T1:
            t["role_tags"] = ["gold", *t["role_tags"]]
    indexed.corpus_file.write_text(yaml.safe_dump(data))
    (indexed.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "pending", "runs_without_annotations": True}))
    cs = clients(indexed)
    res = run_diagnose(indexed, load_settings(indexed), get_vocab(), text=CONCEPT, clients=cs, embedder=MockEmbedder(),
                       run_id="run_dgold", date="2026-09-27")
    structure_user = cs["ideate_generate"].provider.calls[0]["user"]
    assert T1 not in structure_user  # the structuring call never sees a gold title
    out = "\n".join(res.lines) + (indexed.root / res.md_path).read_text()
    assert T1 not in out and "Ironvale Circuit" not in out


def test_every_prescription_is_an_operator_or_a_ladder_rung():
    assert LADDER == ("kit", "set", "MC", "villain and thematic argument", "world", "engine and escalation",
                      "promise and hooks", "pilot hook", "three key frames", "storyboard")
    for kind, target, advice in PRESCRIPTIONS.values():
        assert (kind == "operator" and target in OPERATORS) or (kind == "rung" and target in LADDER)
        assert advice.endswith(".")
    assert len(OPERATORS) == 8


def test_the_cli_needs_exactly_one_concept_source(repo):
    runner = CliRunner()
    assert runner.invoke(app, ["diagnose"]).exit_code == 2
    assert runner.invoke(app, ["diagnose", "--text", "x", "--file", "y.txt"]).exit_code == 2
