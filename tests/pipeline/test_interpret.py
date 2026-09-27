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


def run(repo, **kw):
    (repo.candidates / "gathered").mkdir(parents=True, exist_ok=True)
    (repo.candidates / "gathered" / f"{TID}.json").write_text(json.dumps(GATHERED))
    mock = MockProvider(responses={("INTERPRET", TID): [answer()]})
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="o"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_i"))
    result = run_interpret(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), load_settings(repo),
                           run_id="run_i", created_at="2026-09-27T12:00:00+00:00", **kw)
    return result, mock


def test_cited_in_scope_facts_settle_fields_and_reception_settles_the_outcome(repo):
    result, mock = run(repo)
    assert len(mock.calls) == 1 and "F01: power_combat.gate = trained [in_scope]" in mock.calls[0]["user"]
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
