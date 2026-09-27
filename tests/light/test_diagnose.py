"""Light-path diagnose: the notes are the comparison set, the steering rules are judged, set_structure and
power_is report as not tracked, a hard rule failure gets its prescription, a soft one a warning."""

from __future__ import annotations

import json

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.config import ModelSpec, load_settings
from animedex.light.diagnose import (
    graveyard_matches,
    novelty_check,
    run_diagnose_light,
    tracked_set,
)
from animedex.light.notes import read_notes, write_note
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.light.test_ingest import make_note_record
from tests.light.test_quick import RULES

pytestmark = pytest.mark.pipeline

CONCEPT = ("A lighthouse keeper's daughter can borrow the strength of anyone whose debt she carries, and every "
           "borrowed blow leaves her owing them a day of her life.")


class FakeEmbedder:
    fallbacks: list = []

    def embed(self, texts):
        return [[1.0, 0.0] if "keeper" in t.lower() else [0.0, 1.0] for t in texts]


def structure_card(closest: str, why_different=None) -> dict:
    return {"logline": "A keeper's daughter borrows strength from the people who owe her, at a day of life per blow.",
            "premise": "Debt is the medium: the more people owe her, the harder she hits, and each hit costs her a day.",
            "theme_root": "what do we owe the people who carry us", "engine": {"goal": "keep the light lit",
            "constraint": "she owes a day for every blow", "strategy": "collect debts before storms", "benefit": "a town's strength",
            "cost": "her own years", "dilemma": "spend her life on the town or let the light go out",
            "dramatic_question": "how much of a life is a town worth"},
            "what_changed": "the power is owed, not owned",
            "consequences": {"choices": "she chooses whose debt to call", "relationships": "every ally is a creditor",
                             "outcomes": "victories shorten her life"},
            "profile": {"gate": "contract", "cost_of_power": "lifespan", "progression": "lateral", "set_structure": "closed_set",
                        "visible_counter": "gauge", "fight_medium": "unarmed", "power_is": "individual"},
            "closest_existing": closest, "why_not_a_clone": "the strength is borrowed from debtors, not drawn from a grid",
            "broken_rule": "", "appetite": "", "why_different": why_different}


def judge_answer(r1="pass", r2="fail") -> dict:
    return {"cards": [{"ref": "D1", "choices_differs": True, "relationships_differs": True, "outcomes_differs": False,
                       "choices_reason": "she picks debtors", "relationships_reason": "allies are creditors",
                       "outcomes_reason": "wins still shorten life", "coherence": "pass", "coherence_reason": "the cost drives the dilemma",
                       "runway_hurts_by_arc5": True, "runway_reason": "years run out",
                       "why_different_verdict": "not_applicable", "why_different_reason": "",
                       "rules": [{"id": "R1", "verdict": r1, "reason": "she wins on debt, not numbers"},
                                 {"id": "R2", "verdict": r2, "reason": "debt is a domain, but no host is named"},
                                 {"id": "R3", "verdict": "pass", "reason": "built from the fight"}]}]}


def ablation_answer(part_ids) -> dict:
    return {"parts": [{"part": p, "verdict": "load_bearing" if p == "engine.cost" else "supporting",
                       "reason": "carries the dilemma"} for p in part_ids]}


def setup(repo, slugs=("ironvale_circuit_2021", "lantern_debt_2019", "copper_vow_2018")):
    (repo.root / "steering").mkdir(exist_ok=True)
    (repo.root / "steering" / "rules.yaml").write_text(yaml.safe_dump({"rules": RULES}))
    for slug in slugs:
        write_note(repo, make_note_record(slug))


def clients_for(repo, card, judge, budget=None):
    log = RunLog(repo.raw_runs, "run_d")

    def judge_default(system, user, schema, params):
        props = schema.get("properties", {})
        if "parts" in props:
            return ablation_answer(props["parts"]["items"]["properties"]["part"]["enum"])
        return judge

    gen = MockProvider(default=lambda s, u, sch, p: card)
    jdg = MockProvider(default=judge_default)
    mocks = {"ideate_generate": gen, "ideate_judge": jdg}
    return {k: LLMClient(provider=m, provider_name="mock", spec=ModelSpec(provider="mock", model="m"), prompt_version="unset",
                         schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version, cache=ResponseCache(repo.cache),
                         runlog=log, budget=budget) for k, m in mocks.items()}, mocks


def test_the_light_diagnose_checks_against_notes_and_steering_rules(repo):
    setup(repo)
    clients, mocks = clients_for(repo, structure_card("lantern_debt_2019"), judge_answer())
    res = run_diagnose_light(repo, load_settings(repo), get_vocab(), text=CONCEPT, clients=clients, embedder=FakeEmbedder(),
                             run_id="run_d", date="2026-09-27", created_at="2026-09-27T22:00:00+00:00")
    by = {c.name: c for c in res.checks}
    assert not res.stopped and by["structure"].ok and "closest note: Lantern Debt" in by["structure"].why
    assert by["clone"].ok and "not tracked" in by["clone"].why and "set_structure" in by["clone"].why
    assert by["novelty"].ok is None and "fewer than 10" in by["novelty"].why          # 3 notes only
    assert by["graveyard"].ok and by["name leak"].ok
    assert by["H1 consequence test"].ok and "2 of 3" in by["H1 consequence test"].why
    assert by["rule R1 (hard)"].ok and by["rule R2 (soft)"].ok is False and by["rule R2 (soft)"].failure == "steering_soft"
    assert by["rule R3 (soft)"].ok and by["ablation"].ok
    assert "title lantern_debt_2019: anime;" in mocks["ideate_generate"].calls[0]["user"]
    judge_user = mocks["ideate_judge"].calls[0]["user"]
    assert "rule R1 (hard)" in judge_user and "=== note lantern_debt_2019" in judge_user and "=== CARD D1" in judge_user
    md = (repo.root / res.md_path).read_text()
    assert "steering/rules.yaml" in md and "rule R2 (soft)" in md and "ladder rung 'kit'" in md
    record = json.loads((repo.root / res.json_path).read_text())
    assert record["path"] == "light" and record["gates"]["nearest"] in read_notes(repo)


def test_a_hard_rule_failure_and_a_graveyard_match_get_their_prescriptions(repo):
    setup(repo)
    # every fixture note is a mixed/flop-labelled note sharing the tracked enums with the card below
    card = structure_card("lantern_debt_2019", why_different=None)
    card["profile"].update(gate="trained", cost_of_power="memory", progression="linear", visible_counter="gauge",
                           fight_medium="energy")
    judge = judge_answer(r1="fail")
    judge["cards"][0]["why_different_verdict"] = "fail"
    judge["cards"][0]["why_different_reason"] = "nothing named"
    clients, mocks = clients_for(repo, card, judge)
    res = run_diagnose_light(repo, load_settings(repo), get_vocab(), text=CONCEPT, clients=clients, embedder=FakeEmbedder(),
                             run_id="run_d", date="2026-09-27")
    by = {c.name: c for c in res.checks}
    assert by["clone"].ok is False and by["clone"].failure == "clone_structural"      # identical tracked enums
    assert by["graveyard"].ok is False and by["graveyard"].failure == "graveyard"     # flop notes, no why_different
    assert by["rule R1 (hard)"].ok is False and by["rule R1 (hard)"].failure == "steering_hard"
    assert any("ladder rung 'MC'" in line for line in res.lines)
    assert graveyard_matches(card, read_notes(repo)) and len(tracked_set(card["profile"])) == 5


def test_novelty_needs_ten_notes_and_finds_an_unseen_pair(repo):
    setup(repo)
    notes = read_notes(repo)
    for i in range(10):
        n = dict(notes["ironvale_circuit_2021"], slug=f"filler_{i}_2000", title=f"Filler {i}")
        write_note(repo, n)
    notes = read_notes(repo)
    card = structure_card("ironvale_circuit_2021")
    assert novelty_check(card, notes).ok is True                                   # contract+lifespan: no note has it
    card["profile"].update(gate="trained", cost_of_power="memory", progression="linear", visible_counter="gauge",
                           fight_medium="energy")
    assert novelty_check(card, notes).ok is False
