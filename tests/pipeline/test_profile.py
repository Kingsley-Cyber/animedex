"""PROFILE (v1.10 speed pass, D-048): gather and interpret in one call for non-gold titles; gold titles are
refused; the verify list is the outcome and the moment locators; an agreement rerun writes elsewhere."""

from __future__ import annotations

import json

import pytest

from animedex import SCHEMA_VERSION
from animedex.catalog.reception import Reception
from animedex.config import ModelSpec, load_settings
from animedex.models import CorpusEntry
from animedex.ontology import get_vocab
from animedex.pipeline.profile import output_schema, run_profile
from animedex.providers.client import LLMClient
from animedex.store.cache import ResponseCache
from animedex.store.jsonl import read_jsonl
from animedex.store.runlog import RunLog
from tests.pipeline.test_gather import WIKI, WIKIA, WebMock
from tests.pipeline.test_interpret import TID, answer, cast
from tests.pipeline.test_p1 import ENTRY

pytestmark = pytest.mark.pipeline

REVIEW = "https://reviews.example/iv"


def merged_answer() -> dict:
    """What the merged call returns: facts with ids, then the profile citing them."""
    profile = answer()
    profile["evidence"] = [{"path": "power_combat.gate", "fact_ids": ["F1"]},
                           {"path": "anime_production.source_medium", "fact_ids": ["F2"]},  # unplaced: no effect
                           {"path": "core.tone", "fact_ids": ["F9"]}]                        # never admitted: ignored
    profile["outcome"]["signals"] = [{"metric": "AniList average", "value": "81", "fact_id": "A01"},
                                     {"metric": "critic verdict", "value": "praised", "fact_id": "R1"}]
    return {"facts": [{"id": "F1", "path": "power_combat.gate", "value": "trained", "season": None, "episode": None,
                       "chapter": None, "volume": None, "source_url": WIKI, "scope": "in_scope"},
                      {"id": "F2", "path": "anime_production.source_medium", "value": "original", "season": None,
                       "episode": None, "chapter": None, "volume": None, "source_url": WIKI, "scope": "unplaced"},
                      {"id": "F9", "path": "power_combat.progression", "value": "linear", "season": None, "episode": None,
                       "chapter": None, "volume": None, "source_url": "https://not-retrieved.example/p", "scope": "in_scope"}],
            "characters": [{"role": "protagonist", "name": "Marisol Vey",
                            "facts": [{"id": "C1", "field": "turning_point", "value": "loses her harbor memories",
                                       "season": 1, "episode": 7, "chapter": None, "volume": None, "source_url": WIKIA,
                                       "scope": "in_scope"}]}],
            "reception": [{"id": "R1", "kind": "critic_review", "verdict": "praised pacing", "source_url": REVIEW}],
            "profile": profile, "cast": cast()}


def client_for(repo, responses, name="run_pf"):
    mock = WebMock({WIKI, WIKIA, REVIEW}, responses=responses)
    return LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="o"),
                     prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                     cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, name)), mock


def reception(entry):
    rec = Reception(source="anilist", mal_id=11, anilist_id=22, score=81.0, scorers=None, rank=None, popularity=5000,
                    url="https://anilist.co/anime/22", fetched_at="2026-09-27T00:00:00+00:00")
    return [rec], []


def test_one_call_writes_facts_profile_verify_list_and_cast(repo):
    entry = CorpusEntry.model_validate(ENTRY)
    client, mock = client_for(repo, {("PROFILE", TID): [merged_answer()]})
    result = run_profile(repo, [entry], client, get_vocab(), load_settings(repo), run_id="run_pf", reception=reception,
                         created_at="2026-09-27T12:00:00+00:00")
    assert [t["title_id"] for t in result.titles] == [TID] and len(mock.calls) == 1  # no cast call
    assert "A01: anilist score 81.0 popularity 5000" in mock.calls[0]["user"]
    gathered = json.loads((repo.candidates / "gathered" / f"{TID}.json").read_text())
    assert [f["id"] for f in gathered["facts"]] == ["F1", "F2"] and gathered["provenance"]["pass"] == "PROFILE"
    assert gathered["reception_api"][0]["id"] == "A01" and gathered["reception"][0]["id"] == "R1"
    [title] = read_jsonl(repo.candidates / "title" / f"{TID}.jsonl")
    gate = title["power_combat"]["gate"]
    assert (gate["value"], gate["verification"], gate["source_ref"]) == ("trained", "gathered", WIKI)
    assert title["core"]["outcome"]["value"] == "hit" and title["core"]["outcome"]["verification"] == "gathered"
    verify = json.loads((repo.candidates / "verify" / f"{TID}.json").read_text())["verify"]
    assert verify and all(p.startswith("moments.") for p in verify)  # the outcome is settled: moments only
    assert all(fv["verification"] != "unverified" for fv in title["core"].values() if isinstance(fv, dict))
    chars = read_jsonl(repo.candidates / "character" / f"{TID}.jsonl")
    assert chars and chars[0]["role"] == "protagonist" and result.characters[TID] == len(chars)


def test_gold_titles_are_refused_and_an_agreement_rerun_writes_elsewhere(repo):
    gold = CorpusEntry.model_validate({**ENTRY, "role_tags": ["gold"]})
    client, mock = client_for(repo, {("PROFILE", TID): [merged_answer()]})
    result = run_profile(repo, [gold], client, get_vocab(), load_settings(repo), run_id="run_pf")
    assert result.skipped and "gold" in result.skipped[0][1] and not mock.calls
    entry = CorpusEntry.model_validate(ENTRY)
    out = repo.root / "eval" / "agreement" / "interpret" / "run_pf2"
    result = run_profile(repo, [entry], client, get_vocab(), load_settings(repo), run_id="run_pf2", reception=reception,
                         params={"rerun": 2}, out_dir=out)
    assert (out / f"{TID}.json").is_file() and not (repo.candidates / "gathered" / f"{TID}.json").exists()


def test_the_merged_schema_names_facts_and_frees_their_ids():
    entry = CorpusEntry.model_validate(ENTRY)
    schema = output_schema(get_vocab(), entry, ["power_combat.gate"])
    assert set(schema["required"]) == {"facts", "characters", "reception", "profile", "cast"}
    assert schema["properties"]["facts"]["items"]["properties"]["id"]["pattern"].startswith("^F")
    ev = schema["properties"]["profile"]["properties"]["evidence"]["items"]["properties"]["fact_ids"]["items"]
    assert "enum" not in ev
