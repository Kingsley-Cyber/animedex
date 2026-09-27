"""GATHER (v1.7): documented facts with source URLs; evidence rules without retries; API reception.
Every title and text here is synthetic (09)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from animedex import SCHEMA_VERSION
from animedex.catalog.reception import Reception
from animedex.config import ModelSpec, load_settings
from animedex.models import CorpusEntry
from animedex.ontology import get_vocab
from animedex.pipeline.gather import gather_paths, load_gathered, run_gather
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.pipeline.test_p1 import ENTRY

pytestmark = pytest.mark.pipeline

TID = "ironvale_circuit_2021"
WIKI, WIKIA = "https://en.wikipedia.org/wiki/Ironvale_Circuit", "https://ironvale.fandom.com/wiki/Grid_Arts"
MAL = "https://myanimelist.net/anime/1/Ironvale_Circuit"


class WebMock(MockProvider):
    def __init__(self, urls, **kw):
        super().__init__(**kw)
        self.urls, self.params = sorted(urls), []

    def generate(self, system, user, json_schema, params):
        self.params.append(params)
        resp = super().generate(system, user, json_schema, params)
        web = {"searches": 2, "fetches": 2, "queries": ["q0", "q1"], "fetched": self.urls[:1], "found": self.urls,
               "urls": self.urls}
        return dataclasses.replace(resp, meta={"web": web})


def fact(path, value, url=WIKI, scope="in_scope", season=None, episode=None):
    return {"path": path, "value": value, "season": season, "episode": episode, "source_url": url, "scope": scope}


def answer():
    return {"facts": [fact("power_combat.gate", "trained"),
                      fact("power_combat.signature_technique", "a courier reroutes grid power through her arms", WIKIA),
                      fact("power_combat.fight_medium", "unarmed", "https://not-retrieved.example/page"),  # dropped
                      fact("power_combat.progression", "linear", MAL),                                    # dropped
                      fact("anime_production.source_medium", "original", scope="unplaced"),
                      fact("core.tone", "wry")],                                                          # not gatherable
            "characters": [{"role": "protagonist", "name": "Marisol Vey",
                            "facts": [{"field": "turning_point", "value": "loses her memory of the harbor",
                                       "season": 1, "episode": 7, "source_url": WIKIA, "scope": "in_scope"}]}],
            "reception": [{"kind": "critic_review", "verdict": "praised pacing and grounded stakes", "source_url": WIKI}]}


def run(repo, responses):
    settings = load_settings(repo)
    mock = WebMock({WIKI, WIKIA, MAL}, responses=responses)
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="h"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_g"))
    rec = Reception(source="anilist", mal_id=11, anilist_id=22, score=81.0, scorers=None, rank=None, popularity=5000,
                    url="https://anilist.co/anime/22", fetched_at="2026-09-27T00:00:00+00:00")
    result = run_gather(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), settings, run_id="run_g",
                        reception=lambda e: ([rec], ["MAL API key missing: Jikan used"]),
                        created_at="2026-09-27T12:00:00+00:00")
    return result, mock


def test_only_retrieved_allowed_sources_count_and_nothing_is_retried(repo):
    result, mock = run(repo, {("GATHER", TID): [answer()]})
    [r] = result.titles
    assert len(mock.calls) == 1 and mock.params[0]["web"]["max_turns"] == 4 + 8 + 2
    g = load_gathered(repo, TID)
    assert [f["path"] for f in g["facts"]] == ["power_combat.gate", "power_combat.signature_technique",
                                               "anime_production.source_medium"]
    assert [f["id"] for f in g["facts"]] == ["F01", "F02", "F03"] and g["facts"][2]["scope"] == "unplaced"
    assert r.kept == 5 and r.unplaced == 1 and len(r.dropped) == 3
    assert any("never retrieved" in d for d in r.dropped) and any("myanimelist" in d for d in r.dropped)
    assert any("not a gatherable field" in d for d in r.dropped)
    assert g["characters"][0]["facts"][0]["id"] == "C01" and g["reception"][0]["id"] == "R01"
    assert g["reception_api"][0]["source"] == "anilist" and g["reception_api"][0]["id"] == "A01"
    assert "MAL API key missing: Jikan used" in g["notes"] and g["provenance"]["pass"] == "GATHER"


def test_the_input_lists_fields_with_limits_and_no_page_text_is_stored(repo):
    _, mock = run(repo, {("GATHER", TID): [answer()]})
    user = mock.calls[0]["user"]
    assert "field: power_combat.gate (one of:" in user and "scope_seasons: [1]" in user and "limits: at most 4" in user
    stored = json.dumps(load_gathered(repo, TID))
    assert "Synthetic reference page" not in stored  # only paraphrased values and URLs are kept


def test_gatherable_fields_are_the_config_list_that_the_vocab_has(repo):
    settings = load_settings(repo)
    paths = gather_paths(get_vocab(), settings)
    assert "power_combat.gate" in paths and "core.tone" not in paths
    assert all(get_vocab().lens_field(p) for p in paths)
