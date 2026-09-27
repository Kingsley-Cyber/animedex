"""Light path: `make quick` = research (skipped when the notes exist or the seed was researched before),
generate, check (drops cards that fail the consequence test or a hard rule), prior art only for surviving
"never done" claims; at most four calls; the cards land in build/quick/ ranked by the check."""

from __future__ import annotations

import json

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.budget import Budget
from animedex.config import ModelSpec, load_settings
from animedex.light.notes import read_notes, write_note
from animedex.light.quick import run_quick, seed_key
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.light.test_ingest import (
    WIKI,
    WIKIA,
    fake_numbers,
    fake_resolve,
    make_note_record,
    note_for,
)
from tests.light.webmock import WebMock

pytestmark = pytest.mark.pipeline

SEED = "a cold-open feral scaled transformation mid-fight"
PRIOR = "https://scales.fandom.com/wiki/Feral_Form"
RULES = [{"id": "R1", "strength": "hard", "rule": "the MC is legibly the strongest without holding the biggest number"},
         {"id": "R2", "strength": "soft", "rule": "power affinities come from domains of meaning, not elements"},
         {"id": "R3", "strength": "soft", "rule": "the premise is built out from the fight"}]


def card(i: int, closest: str, claim: str | None = None) -> dict:
    return {"logline": f"Card {i}: a dock worker whose scales grow only mid-fight must win before the change finishes.",
            "premise": "Every fight starts human and ends feral; the scales spread with each exchange and the hero must "
                       "end it before they reach the heart.",
            "engine": {"goal": "end fights fast", "constraint": "every exchange spreads the scales",
                       "strategy": "finish in three moves", "cost": "a patch of skin each fight",
                       "dilemma": "fight longer and lose herself or lose the fight"},
            "mc_edge": "she reads the change in her own body as a clock nobody else can see",
            "power_kit": {"medium": "the spreading scales", "functions": ["harden", "sense", "shed"],
                          "tools": ["scale count", "shed burst", "heart line"], "limits": "fades outside a fight"},
            "consequences": {"choices": "fights are chosen by how short they can be",
                             "relationships": "allies count her scales for her", "outcomes": "victories cost skin, not rank"},
            "closest_existing": closest, "why_not_a_clone": "the transformation is a timer, not a power-up",
            "never_done_claim": claim}


def verdict(ref: str, dims: int, r1: str = "pass", score: int = 70, closest: str = "ironvale_circuit_2021") -> dict:
    flags = [True] * dims + [False] * (3 - dims)
    return {"ref": ref, "choices_differs": flags[0], "relationships_differs": flags[1], "outcomes_differs": flags[2],
            "consequence_reason": "the timer changes what a fight is for",
            "rules": [{"id": "R1", "verdict": r1, "reason": "she wins on reading, not on numbers"},
                      {"id": "R2", "verdict": "pass", "reason": "scales mean debt"},
                      {"id": "R3", "verdict": "pass", "reason": "built from the fight image"}],
            "closest_slug": closest, "closeness": "medium", "closeness_reason": "same medium, other engine",
            "weakness": "the timer could feel arbitrary", "score": score}


def setup(repo, with_notes=("ironvale_circuit_2021", "lantern_debt_2019")):
    (repo.root / "steering").mkdir(exist_ok=True)
    (repo.root / "steering" / "rules.yaml").write_text(yaml.safe_dump({"rules": RULES}))
    for slug in with_notes:
        write_note(repo, make_note_record(slug))


def clients_for(repo, research_answer, cards, verdicts, prior=None, budget=None):
    log = RunLog(repo.raw_runs, "run_q")

    def notes_default(system, user, schema, params):
        props = schema.get("properties", {})
        if "picks" in props:
            return research_answer
        if "claims" in props:
            return prior
        return {"notes": [note_for("Copper Vow")]}   # named shows lacking notes

    web = WebMock({WIKI, WIKIA, PRIOR}, default=notes_default)
    gen = MockProvider(default=lambda s, u, sch, p: {"seed_kind": "fight_image", "cards": cards})
    judge = MockProvider(default=lambda s, u, sch, p: {"cards": verdicts})
    mocks = {"ingest": web, "generate": gen, "check": judge}
    clients = {k: LLMClient(provider=m, provider_name="mock", spec=ModelSpec(provider="mock", model="m"),
                            prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                            cache=ResponseCache(repo.cache), runlog=log, budget=budget) for k, m in mocks.items()}
    return clients, mocks


def quick(repo, clients, *, shows=None, n=3, seed=SEED):
    return run_quick(repo, load_settings(repo), get_vocab(), seed=seed, shows=shows, n=n, clients=clients,
                     resolve=fake_resolve, numbers=fake_numbers, run_id="run_q", created_at="2026-09-27T21:00:00+00:00")


def test_first_run_researches_generates_checks_and_checks_prior_art_in_four_calls(repo):
    setup(repo)
    research = {"picks": [{"show": "Ironvale Circuit", "year": 2021, "in_index": True, "index_slug": "ironvale_circuit_2021",
                           "why": "same medium"},
                          {"show": "Copper Vow", "year": 2018, "in_index": False, "index_slug": None, "why": "same timer"},
                          {"show": "Lantern Debt", "year": 2019, "in_index": True, "index_slug": "lantern_debt_2019", "why": "cost"}],
                "notes": [note_for("Copper Vow")]}
    cards = [card(1, "ironvale_circuit_2021", "no show has used a transformation as a fight clock"),
             card(2, "lantern_debt_2019"), card(3, "copper_vow_2018")]
    verdicts = [verdict("C1", 3, score=80), verdict("C2", 1, score=90), verdict("C3", 2, r1="fail", score=95)]
    prior = {"claims": [{"ref": "C1", "found": True, "counterexample": "Feral Form", "url": PRIOR, "note": "a 2015 title does it"}]}
    clients, mocks = clients_for(repo, research, cards, verdicts, prior)
    res = quick(repo, clients)
    assert not res.stopped and res.calls == 4 and set(res.timings) == {"research", "generate", "check", "prior_art"}, res.lines()
    assert res.picks == ["ironvale_circuit_2021", "copper_vow_2018", "lantern_debt_2019"]
    assert "copper_vow_2018" in read_notes(repo) and res.notes_written == ["copper_vow_2018"]
    assert (repo.research / f"{seed_key(SEED)}.json").is_file()
    assert res.cards_in == 3 and res.survivors == 1 and len(res.dropped) == 2
    assert any("C2: consequence test 1 of 3" in d for d in res.dropped) and any("C3: hard rule failed (R1" in d for d in res.dropped)
    md = (repo.root / res.path).read_text()
    assert "## 1. Card 1" in md and "downgraded: Feral Form already does this" in md and PRIOR in md
    assert "## Dropped by the check" in md and WIKI in md
    record = json.loads((repo.root / res.json_path).read_text())
    assert record["survivors"] == ["C1"] and record["seed_kind"] == "fight_image"
    gen_user = mocks["generate"].calls[0]["user"]
    assert "rule R1 (hard)" in gen_user and "=== note copper_vow_2018" in gen_user and f"seed: {SEED}" in gen_user
    assert "=== CARD C1" in mocks["check"].calls[0]["user"]


def test_the_same_seed_again_skips_research_and_a_claimless_survivor_skips_prior_art(repo):
    setup(repo)
    research = {"picks": [{"show": "Ironvale Circuit", "year": 2021, "in_index": True, "index_slug": "ironvale_circuit_2021", "why": "x"},
                          {"show": "Lantern Debt", "year": 2019, "in_index": True, "index_slug": "lantern_debt_2019", "why": "y"},
                          {"show": "Copper Vow", "year": 2018, "in_index": False, "index_slug": None, "why": "z"}],
                "notes": [note_for("Copper Vow")]}
    cards = [card(1, "ironvale_circuit_2021"), card(2, "lantern_debt_2019")]
    verdicts = [verdict("C1", 2, score=60), verdict("C2", 3, score=75)]
    clients, mocks = clients_for(repo, research, cards, verdicts)
    first = quick(repo, clients, n=2)
    assert first.calls == 3 and first.research.startswith("ran")
    clients, mocks = clients_for(repo, research, cards, verdicts)
    second = quick(repo, clients, n=2)
    assert second.research.startswith("skipped (picks kept") and second.calls == 2 and "research" not in second.timings
    assert not mocks["ingest"].calls and second.picks == first.picks
    record = json.loads((repo.root / second.json_path).read_text())
    assert record["survivors"] == ["C2", "C1"]   # ranked by the check's score


def test_named_shows_skip_research_when_their_notes_exist_and_write_the_missing_ones(repo):
    setup(repo)
    cards = [card(1, "ironvale_circuit_2021")]
    clients, mocks = clients_for(repo, {}, cards, [verdict("C1", 3)])
    res = quick(repo, clients, shows=["Ironvale Circuit", "Lantern Debt"], n=1)
    assert res.research == "skipped (every named show has a note)" and res.calls == 2 and not mocks["ingest"].calls
    clients, mocks = clients_for(repo, {}, cards, [verdict("C1", 3)])
    res = quick(repo, clients, shows=["Ironvale Circuit", "Copper Vow", "Nowhere (1900)"], n=1)
    assert res.research.startswith("ran (notes for 1 named show") and "copper_vow_2018" in res.picks
    assert any("Nowhere (1900)" in p for p in res.problems) and mocks["ingest"].calls[0]["pass"] == "INGEST"


def test_the_call_cap_pauses_the_run_cleanly(repo):
    setup(repo)
    budget = Budget(1)
    budget.count_call()
    cards = [card(1, "ironvale_circuit_2021")]
    clients, mocks = clients_for(repo, {}, cards, [verdict("C1", 3)], budget=budget)
    for c in clients.values():
        c.provider.live, c.billing = True, "subscription"   # the call cap counts live subscription calls only
    res = quick(repo, clients, shows=["Ironvale Circuit"], n=1)
    assert res.stopped and "call cap reached" in res.stopped and res.path.endswith(".md")


def test_every_schema_the_light_path_sends_is_a_valid_json_schema():
    """The CLI validates `--json-schema` and refuses an empty enum; the mocks do not, so check it here."""
    from jsonschema import Draft202012Validator

    from animedex.light.notes import note_schema
    from animedex.light.quick import card_schema, check_schema, prior_art_schema, research_schema

    def enums(node):
        if isinstance(node, dict):
            if "enum" in node:
                yield node["enum"]
            for v in node.values():
                yield from enums(v)
        elif isinstance(node, list):
            for v in node:
                yield from enums(v)

    for schema in (research_schema(), note_schema(["Ironvale Circuit"]), card_schema(["ironvale_circuit_2021"]),
                   check_schema(["C1"], ["R1"], ["ironvale_circuit_2021"]), prior_art_schema(["C1"])):
        Draft202012Validator.check_schema(schema)
        assert all(len(e) >= 1 for e in enums(schema)), "an empty enum: the CLI refuses the schema"
    assert [e for e in enums(note_schema([])) if not e]   # what the old research schema sent


def test_two_runs_in_the_same_second_never_share_a_card_file(repo, monkeypatch):
    """Live 2026-09-27: two seeds started together and the later run overwrote the earlier cards."""
    import animedex.light.quick as q

    class Frozen(q.datetime):
        @classmethod
        def now(cls, tz=None):
            return q.datetime(2026, 9, 27, 18, 48, 15, tzinfo=tz)

    monkeypatch.setattr(q, "datetime", Frozen)
    setup(repo)
    cards = [card(1, "ironvale_circuit_2021")]
    paths_seen = []
    for seed in (SEED, "a lane: death-game survival", SEED):
        clients, _ = clients_for(repo, {}, cards, [verdict("C1", 3)])
        paths_seen.append(quick(repo, clients, shows=["Ironvale Circuit"], n=1, seed=seed).path)
    assert len(set(paths_seen)) == 3 and all("20260927_184815_" in p for p in paths_seen)
