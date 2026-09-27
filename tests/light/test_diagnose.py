"""`make diagnose`: the concept is written as a note on the ingest prompt, then checked on the check prompt
against its nearest notes and the steering rules; clone, novelty, graveyard and name leak need no call."""

from __future__ import annotations

import json

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.config import ModelSpec, load_settings
from animedex.light.diagnose import graveyard_matches, novelty_check, run_diagnose, tracked_set
from animedex.light.notes import read_notes, write_note
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.light.test_ingest import make_note_record, note_for
from tests.light.test_quick import RULES

pytestmark = pytest.mark.pipeline

CONCEPT = ("A lighthouse keeper's daughter can borrow the strength of anyone whose debt she carries, and every "
           "borrowed blow leaves her owing them a day of her life.")


class FakeEmbedder:
    fallbacks: list = []

    def embed(self, texts):
        return [[1.0, 0.0] if "keeper" in t.lower() else [0.0, 1.0] for t in texts]


def concept_note(**over) -> dict:
    n = note_for("concept", sources=[], premise="A keeper's daughter borrows strength from those who owe her, a day of life per blow.",
                 gate="contract", cost_of_power="lifespan", progression="lateral", visible_counter="gauge",
                 fight_medium="unarmed", story_engine="survival")
    n.update(over)
    return {"notes": [n]}


def verdict(r1="pass", r2="fail", dims=2) -> dict:
    flags = [True] * dims + [False] * (3 - dims)
    return {"cards": [{"ref": "D1", "choices_differs": flags[0], "relationships_differs": flags[1],
                       "outcomes_differs": flags[2], "consequence_reason": "she picks whose debt to call",
                       "rules": [{"id": "R1", "verdict": r1, "reason": "she wins on debt, not numbers"},
                                 {"id": "R2", "verdict": r2, "reason": "debt is a domain, but no host is named"},
                                 {"id": "R3", "verdict": "pass", "reason": "built from the fight"}],
                       "closest_slug": "lantern_debt_2019", "closeness": "medium", "closeness_reason": "same cost",
                       "weakness": "the ledger could feel like bookkeeping", "score": 72}]}


def setup(repo, slugs=("ironvale_circuit_2021", "lantern_debt_2019", "copper_vow_2018")):
    (repo.root / "steering").mkdir(exist_ok=True)
    (repo.root / "steering" / "rules.yaml").write_text(yaml.safe_dump({"rules": RULES}))
    for slug in slugs:
        write_note(repo, make_note_record(slug))


def clients_for(repo, structure, check):
    log = RunLog(repo.raw_runs, "run_d")
    mocks = {"ingest": MockProvider(default=lambda s, u, sch, p: structure),
             "check": MockProvider(default=lambda s, u, sch, p: check)}
    return {k: LLMClient(provider=m, provider_name="mock", spec=ModelSpec(provider="mock", model="m"), prompt_version="unset",
                         schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version, cache=ResponseCache(repo.cache),
                         runlog=log) for k, m in mocks.items()}, mocks


def diagnose(repo, clients, text=CONCEPT):
    return run_diagnose(repo, load_settings(repo), get_vocab(), text=text, clients=clients, embedder=FakeEmbedder(),
                        run_id="run_d", date="2026-09-27", created_at="2026-09-27T22:00:00+00:00")


def test_two_calls_structure_the_concept_as_a_note_and_check_it_against_the_notes_and_rules(repo):
    setup(repo)
    clients, mocks = clients_for(repo, concept_note(), verdict())
    res = diagnose(repo, clients)
    by = {c.name: c for c in res.checks}
    assert not res.stopped and by["structure"].ok and "gate contract" in by["structure"].why
    assert by["clone"].ok and by["novelty"].ok is None and "fewer than 10" in by["novelty"].why   # 3 notes only
    assert by["graveyard"].ok and by["name leak"].ok
    assert by["consequence test"].ok and "2 of 3" in by["consequence test"].why
    assert by["rule R1 (hard)"].ok and by["rule R2 (soft)"].ok is False and by["rule R2 (soft)"].failure == "steering_soft"
    assert len(mocks["ingest"].calls) == 1 and len(mocks["check"].calls) == 1
    assert mocks["ingest"].calls[0]["user"].startswith("job: concept") and CONCEPT[:40] in mocks["ingest"].calls[0]["user"]
    check_user = mocks["check"].calls[0]["user"]
    assert "rule R1 (hard)" in check_user and "=== note lantern_debt_2019" in check_user and "=== CARD D1" in check_user
    assert "consequences: not stated" in check_user
    md = (repo.root / res.md_path).read_text()
    assert "## As a note" in md and "What it can't survive without" in md and "Biggest weakness" in md
    record = json.loads((repo.root / res.json_path).read_text())
    assert record["note"]["gate"] == "contract" and record["check"]["score"] == 72
    assert any("closest: Lantern Debt (medium)" in line for line in res.lines)


def test_a_hard_rule_failure_a_clone_and_a_graveyard_match_get_their_fixes(repo):
    setup(repo)
    # the fixture notes are trained/memory/linear/gauge/energy; two of them are rated flop or mixed
    same = concept_note(gate="trained", cost_of_power="memory", progression="linear", visible_counter="gauge",
                        fight_medium="energy")
    clients, _ = clients_for(repo, same, verdict(r1="fail", dims=1))
    res = diagnose(repo, clients)
    by = {c.name: c for c in res.checks}
    assert by["clone"].ok is False and by["clone"].failure == "clone"
    assert by["graveyard"].ok is False and "Lantern Debt" in by["graveyard"].why
    assert by["consequence test"].ok is False and by["rule R1 (hard)"].failure == "steering_hard"
    assert any("legibly the strongest" in line for line in res.lines)
    assert graveyard_matches(same["notes"][0], read_notes(repo)) and len(tracked_set(same["notes"][0])) == 5


def test_novelty_needs_ten_notes_and_finds_an_unseen_pair(repo):
    setup(repo)
    notes = read_notes(repo)
    for i in range(10):
        write_note(repo, dict(notes["ironvale_circuit_2021"], slug=f"filler_{i}_2000", title=f"Filler {i}"))
    notes = read_notes(repo)
    concept = concept_note()["notes"][0]
    assert novelty_check(concept, notes, 10).ok is True                      # contract + lifespan: no note has it
    concept.update(gate="trained", cost_of_power="memory", progression="linear", visible_counter="gauge", fight_medium="energy")
    assert novelty_check(concept, notes, 10).ok is False


def test_a_gold_title_is_masked_while_the_blind_review_is_pending(repo):
    setup(repo)
    corpus = yaml.safe_load(repo.corpus_file.read_text()) or {}
    corpus["titles"] = [*(corpus.get("titles") or []), {"title_id": "lantern_debt_2019", "role_tags": ["gold"]}]
    repo.corpus_file.write_text(yaml.safe_dump(corpus))
    clients, _ = clients_for(repo, concept_note(), verdict())
    res = diagnose(repo, clients)
    text = "\n".join(res.lines) + (repo.root / res.md_path).read_text()
    assert "[gold title]" in text and "Lantern Debt" not in text
