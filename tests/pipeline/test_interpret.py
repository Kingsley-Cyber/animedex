"""INTERPRET (v1.7): the profile from gathered facts; cited in-scope facts settle fields; the outcome
comes from reception facts; VERIFY keeps only what is still unsourced. Synthetic data only (09)."""

from __future__ import annotations

import json

import pytest

from animedex import SCHEMA_VERSION
from animedex.config import ModelSpec, load_settings
from animedex.models import CorpusEntry
from animedex.ontology import get_vocab
from animedex.pipeline.interpret import render_facts, run_interpret
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.jsonl import read_jsonl
from animedex.store.runlog import RunLog
from tests.pipeline.test_p1 import ENTRY, make_draft

pytestmark = pytest.mark.pipeline

TID = "ironvale_circuit_2021"
WIKI = "https://en.wikipedia.org/wiki/Ironvale_Circuit"
GATHERED = {
    "title_id": TID,
    "facts": [{"id": "F01", "path": "power_combat.gate", "value": "trained", "season": None, "episode": None,
               "source_url": WIKI, "scope": "in_scope"},
              {"id": "F02", "path": "anime_production.source_medium", "value": "original", "season": None,
               "episode": None, "source_url": WIKI, "scope": "unplaced"}],
    "characters": [{"role": "protagonist", "name": "Marisol Vey",
                    "facts": [{"id": "C01", "field": "turning_point", "value": "loses her harbor memories",
                               "season": 1, "episode": 7, "source_url": WIKI, "scope": "in_scope"}]}],
    "reception": [{"id": "R01", "kind": "critic_review", "verdict": "praised pacing", "source_url": "https://reviews.example/iv"}],
    "reception_api": [{"id": "A01", "source": "anilist", "score": 81.0, "scorers": None, "rank": None,
                       "popularity": 5000, "url": "https://anilist.co/anime/22", "mal_id": 11, "anilist_id": 22,
                       "fetched_at": "2026-09-27T00:00:00+00:00", "api_url": "https://graphql.anilist.co"}],
}


def answer():
    draft = make_draft()
    draft["power_combat"]["gate"]["value"] = "trained"
    draft["evidence"] = [{"path": "power_combat.gate", "fact_ids": ["F01"]},
                         {"path": "anime_production.source_medium", "fact_ids": ["F02"]}]  # unplaced: no effect
    draft["outcome"] = {"label": "hit", "signals": [{"metric": "AniList average", "value": "81", "fact_id": "A01"},
                                                    {"metric": "critic verdict", "value": "praised", "fact_id": "R01"}],
                        "failure_reason": None, "failure_level": None, "failure_evidence": None,
                        "failure_evidence_fact": None,
                        "confounders": {k: "" for k in ("studio", "budget_signal", "source_popularity", "platform",
                                                        "release_context")}}
    return draft


def cast():
    none = {k: None for k in ("origin", "wound", "want", "need", "flaw", "moral_line", "relationship_to_power",
                              "origin_power_link", "arc_type", "backstory_reveal", "villain")}
    kit = {"power_kind": "medium", "medium": "city power grid", "functions": ["reroute power", "store charge", "overload"],
           "tools": [{"tool": "grid lash", "function": "reroute power"}], "limits": ["needs a live line"],
           "forms": [], "creativity_level": "inventive", "creativity_moves": [{"move": "charges a tram as armor",
                                                                             "fact_id": "C01"}],
           "drama_source": None, "evolution": "from single lines to the whole district"}
    return {"characters": [
        {**none, "role": "protagonist", "name": "Marisol Vey", "origin": "a courier raised on the harbor grid",
         "turning_points": [{"event": "loses her harbor memories", "season": 1, "episode": 7, "fact_id": "C01"},
                            {"event": "an event outside the scope", "season": 4, "episode": 2, "fact_id": None}],
         "power_kit": kit, "fact_ids": ["C01", "F02"]},
        {**none, "role": "protagonist", "name": "Second Lead", "turning_points": [], "power_kit": None, "fact_ids": []},
        {**none, "role": "main_rival", "name": "Tobin Ash", "turning_points": [], "power_kit": {**kit, "creativity_moves": []},
         "fact_ids": []}]}


def run(repo, **kw):
    (repo.candidates / "gathered").mkdir(parents=True, exist_ok=True)
    (repo.candidates / "gathered" / f"{TID}.json").write_text(json.dumps(GATHERED))
    mock = MockProvider(responses={("INTERPRET", TID): [answer()], ("INTERPRET", f"{TID}.characters"): [cast()]})
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="o"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_i"))
    result = run_interpret(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), load_settings(repo),
                           run_id="run_i", created_at="2026-09-27T12:00:00+00:00", **kw)
    return result, mock


def test_cited_in_scope_facts_settle_fields_and_reception_settles_the_outcome(repo):
    result, mock = run(repo)
    assert len(mock.calls) == 2 and "F01: power_combat.gate = trained [in_scope]" in mock.calls[0]["user"]
    [title] = read_jsonl(repo.candidates / "title" / f"{TID}.jsonl")
    gate = title["power_combat"]["gate"]
    assert (gate["verification"], gate["source"], gate["source_ref"]) == ("gathered", "web", WIKI)
    assert title["anime_production"]["source_medium"]["verification"] != "gathered"  # an unplaced fact never settles
    assert title["core"]["outcome"]["verification"] == "gathered" and title["core"]["outcome"]["value"] == "hit"
    [outcome] = read_jsonl(repo.candidates / "outcome" / f"{TID}.jsonl")
    assert [s["source_ref"] for s in outcome["signals"]] == ["https://anilist.co/anime/22", "https://reviews.example/iv"]
    verify = json.loads((repo.candidates / "verify" / f"{TID}.json").read_text())["verify"]
    assert "power_combat.gate" not in verify and "core.outcome" not in verify
    assert result.sourced[TID] == 2 and result.outcomes == [TID]


def test_an_agreement_run_writes_only_to_its_own_folder(repo):
    out = repo.root / "eval" / "agreement" / "interpret" / "run_x"
    run(repo, out_dir=out, params={"rerun": 2})
    assert (out / f"{TID}.json").is_file() and not (repo.candidates / "title" / f"{TID}.jsonl").exists()


def test_facts_render_as_compact_lines_with_ids():
    text = render_facts(GATHERED)
    assert "C01: character protagonist (Marisol Vey) turning_point = loses her harbor memories s1e7 [in_scope]" in text
    assert "A01: reception anilist = score 81.0, popularity 5000" in text and "R01: critic_review verdict" in text


def test_the_cast_is_cleaned_to_pass_the_cast_rules(repo):
    result, _ = run(repo)
    chars = read_jsonl(repo.candidates / "character" / f"{TID}.jsonl")
    assert [c["role"] for c in chars] == ["protagonist", "main_rival"]  # the second protagonist is dropped
    hero, rival = chars
    assert hero["character_id"] == f"{TID}.c.01" and hero["source_refs"] == [WIKI]  # the unplaced fact isn't cited
    assert [tp["locator"] for tp in hero["turning_points"]] == [{"season": 1, "episode": 7}]  # season 4 is out of scope
    assert hero["power_kit"]["creativity_level"] == "inventive" and hero["power_kit"]["creativity_moves"][0]["source_ref"] == WIKI
    assert rival["power_kit"]["creativity_level"] == "literal"  # no sourced move: not creative on the record
    assert result.characters[TID] == 2 and any("second protagonist" in n for n in result.notes[TID])


def test_an_agreement_run_skips_the_cast(repo):
    out = repo.root / "eval" / "agreement" / "interpret" / "run_y"
    _, mock = run(repo, out_dir=out, params={"rerun": 2})
    assert len(mock.calls) == 1 and not (repo.candidates / "character").exists()


def test_a_source_required_field_without_a_fact_goes_to_verify(repo):
    flop = answer()
    flop["core"]["outcome"]["value"] = "flop"
    flop["core"]["promise_break"] = {"value": "the promised rise stalls halfway", "conf": 0.6,
                                     "uncertainty_reason": "no review states it", "epistemic": "interpretive"}
    flop["outcome"] = {**flop["outcome"], "label": "flop", "failure_reason": "pacing collapsed in the second half",
                       "failure_level": "execution", "failure_evidence": None, "failure_evidence_fact": None}
    (repo.candidates / "gathered").mkdir(parents=True, exist_ok=True)
    (repo.candidates / "gathered" / f"{TID}.json").write_text(json.dumps(GATHERED))
    mock = MockProvider(responses={("INTERPRET", TID): [flop], ("INTERPRET", f"{TID}.characters"): [cast()]})
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="o"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_f"))
    result = run_interpret(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), load_settings(repo),
                           run_id="run_f")
    assert result.titles and not result.quarantined  # held for VERIFY, not rejected at assembly
    verify = json.loads((repo.candidates / "verify" / f"{TID}.json").read_text())["verify"]
    [title] = read_jsonl(repo.candidates / "title" / f"{TID}.jsonl")
    assert "core.promise_break" in verify and title["core"]["promise_break"]["verification"] == "unverified"
