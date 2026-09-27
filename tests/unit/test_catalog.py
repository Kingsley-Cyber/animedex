"""Catalog resolution, backfill planning, and the census (v1.6) with a fake AniList (no network)."""

from __future__ import annotations

import json

import httpx
import pytest
import yaml

from animedex.catalog.anilist import AniList
from animedex.catalog.backfill import add_to_corpus, plan_backfill, read_list
from animedex.catalog.resolve import resolve, slug
from animedex.guards import load_corpus

pytestmark = pytest.mark.unit


def media(mid, english, year, *, fmt="TV", eps=12, pop=1000, score=80, country="JP", relations=(), end=None,
          status="FINISHED"):
    return {"id": mid, "idMal": mid, "title": {"romaji": english, "english": english, "native": None}, "synonyms": [],
            "format": fmt, "episodes": eps, "status": status, "countryOfOrigin": country, "popularity": pop,
            "averageScore": score, "startDate": {"year": year, "month": 4, "day": 1},
            "endDate": {"year": end or year, "month": 6, "day": 1}, "studios": {"nodes": [{"name": "Studio Test"}]},
            "relations": {"edges": [{"relationType": k, "node": {"id": i, "type": "ANIME", "format": f, "episodes": 12,
                                                                    "title": {"romaji": t, "english": t},
                                                                    "startDate": {"year": y, "month": 1},
                                                                    "endDate": {"year": y, "month": 3}}}
                                    for k, i, f, t, y in relations]}}


DB = {
    1: media(1, "Iron Tide", 2015, pop=900, relations=[("SEQUEL", 2, "TV", "Iron Tide Season 2", 2017),
                                                      ("ALTERNATIVE", 3, "TV", "Iron Tide", 2024)]),
    2: media(2, "Iron Tide Season 2", 2017, pop=500),
    3: media(3, "Iron Tide", 2024, pop=300, score=58, relations=[("ALTERNATIVE", 1, "TV", "Iron Tide", 2015)]),
    4: media(4, "Iron Tide: The Movie", 2016, fmt="MOVIE", pop=100),
    5: media(5, "Paper Crown", 2020, pop=700, country="CN", fmt="ONA"),
    6: media(6, "Glass Harbor", 2019, pop=800, score=85),
    7: media(7, "Night Loom", 2021, pop=650, relations=[("SEQUEL", 8, "TV", "Night Loom Season 2", 2023)]),
    8: media(8, "Night Loom Season 2", 2023, pop=400, status="NOT_YET_RELEASED"),
    9: media(9, "Salt Bridge", 2022, pop=600, relations=[("SEQUEL", 10, "TV", "Salt Bridge Season 2", 2099)]),
    10: media(10, "Salt Bridge Season 2", 2099, pop=10),
}


def fake_anilist() -> AniList:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        v = body["variables"]
        if "id" in v:
            return httpx.Response(200, json={"data": {"Media": DB[v["id"]]}})
        if "s" in v:
            q = v["s"].lower()
            hits = [m for m in DB.values() if q.split(":")[0].strip() in m["title"]["english"].lower()]
            return httpx.Response(200, json={"data": {"Page": {"media": hits}}})
        return httpx.Response(200, json={"data": {"Page": {"media": []}}})

    return AniList(transport=httpx.MockTransport(handler), min_interval_s=0, sleep=lambda s: None)


def test_version_in_parentheses_wins_and_sequels_become_seasons():
    cat = fake_anilist()
    old = resolve(cat, "Iron Tide (2015)")
    assert old.entry["title_id"] == "iron_tide_2015" and old.how == "version given"
    assert old.entry["scope"]["seasons"] == [1, 2] and "Iron Tide (alternative)" in old.entry["scope"]["exclude"]
    new = resolve(cat, "Iron Tide (2024)")
    assert new.entry["title_id"] == "iron_tide_2024" and new.likely == "flop"


def test_most_watched_match_without_a_version_lists_the_others():
    r = resolve(fake_anilist(), "Iron Tide")
    assert r.entry["year"] == 2015 and r.how == "most-watched match" and r.alternatives
    assert all("MOVIE" not in a or "Movie" in a for a in r.alternatives)


def test_china_origin_is_donghua_and_films_have_no_seasons():
    cat = fake_anilist()
    assert resolve(cat, "Paper Crown").entry["medium"] == "donghua"
    film = resolve(cat, "Iron Tide: The Movie (2016)")
    assert film.entry["format"] == "film" and film.entry["scope"]["seasons"] == [] and film.entry["scope"]["numbering"] is None


def test_announced_seasons_are_not_in_scope():
    cat = fake_anilist()
    assert resolve(cat, "Night Loom").entry["scope"]["seasons"] == [1]  # sequel listed but not yet released
    assert resolve(cat, "Salt Bridge").entry["scope"]["seasons"] == [1]  # sequel dated in the future


def test_slug_never_doubles_the_year():
    assert slug("Hunter x Hunter (2011)", 2011) == "hunter_x_hunter_2011"
    assert slug("Re:Zero - Starting Life in Another World", 2016) == "re_zero_starting_life_in_another_world_2016"


def test_backfill_skips_known_titles_pairs_versions_and_warns_on_mix(repo, tmp_path):
    lst = tmp_path / "list.txt"
    lst.write_text("# my list\nIron Tide (2015)\nIron Tide (2024)\nGlass Harbor\nGlass Harbor\n\nNo Such Show\n")
    data = yaml.safe_load(repo.corpus_file.read_text())
    data["titles"].append({"title_id": "glass_harbor_2019", "title": "Glass Harbor", "year": 2019, "medium": "anime",
                           "format": "serialized", "scope": {"version": "TV", "seasons": [1], "numbering": "broadcast"}})
    repo.corpus_file.write_text(yaml.safe_dump(data))
    plan = plan_backfill(fake_anilist(), read_list(lst), load_corpus(repo), suggest=False)
    assert [r.entry["title_id"] for r in plan.new] == ["iron_tide_2015", "iron_tide_2024"]
    assert ("Glass Harbor", "already in the corpus as glass_harbor_2019") in plan.skipped
    assert plan.unresolved == ["No Such Show"]
    assert plan.pairs == [("iron_tide_2015", "iron_tide_2024")]  # same story, different execution
    assert plan.new[0].entry["partners"]["nearest_neighbor"] == "iron_tide_2024"
    assert any("anime or donghua" in w for w in plan.warnings)
    added = add_to_corpus(repo, plan, "list.txt")
    corpus = load_corpus(repo)
    assert set(added) <= set(corpus) and corpus["iron_tide_2024"].partners.nearest_neighbor == "iron_tide_2015"
    assert corpus["iron_tide_2015"].catalog_ref == "anilist:1"


def test_census_counts_titles_and_never_feeds_ideation(repo):
    from animedex import SCHEMA_VERSION
    from animedex.config import ModelSpec, load_settings
    from animedex.ontology import get_vocab
    from animedex.pipeline.canonicalize import canonicalize
    from animedex.pipeline.census import CensusItem, run_census
    from animedex.providers.client import LLMClient
    from animedex.providers.mock import MockProvider
    from animedex.store.cache import ResponseCache
    from animedex.store.canonical import CanonicalStore
    from animedex.store.runlog import RunLog

    items = [CensusItem(f"anilist:{i}", f"Show {i}", 2000 + i, "anime", "TV") for i in range(1, 13)]

    def answer(system, user, schema, params):
        ids = schema["properties"]["titles"]["items"]["properties"]["census_id"]["enum"]
        return {"titles": [{"census_id": i, "has_power_system": True, "gate": "trained", "cost_of_power": "physical_toll",
                            "progression": "linear", "visible_counter": "none", "fight_medium": "unarmed",
                            "power_is": "individual", "borrowed_system": "none"} for i in ids]}

    client = LLMClient(provider=MockProvider(default=answer), provider_name="mock",
                       spec=ModelSpec(provider="mock", model="v"), prompt_version="unset", schema_version=SCHEMA_VERSION,
                       vocab_version=get_vocab().version, cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "c"))
    res = run_census(repo, items, client, get_vocab(), load_settings(repo), run_id="run_c")
    assert res.counts["titles"] == 12 and len(res.done) == 2  # 10 per call
    canonicalize(repo, "run_cc")
    census = CanonicalStore(repo).read("census")
    assert len(census) == 12 and all(c["trust"] == "recall" for c in census)
    again = run_census(repo, items, client, get_vocab(), load_settings(repo), run_id="run_c2")
    assert again.counts.get("already_counted") == 12 and not again.done
    from animedex.ideate.context import build_context

    ctx = build_context(repo, load_settings(repo), get_vocab())
    assert ctx.census_size == 12 and not ctx.pool  # counts only: nothing reaches the atom pool


def test_anilist_stays_under_the_degraded_limit_and_caches_for_a_month(tmp_path):
    from animedex.catalog.anilist import CACHE_TTL_S, MIN_INTERVAL_S

    assert MIN_INTERVAL_S >= 2.0  # 30 requests a minute at most (owner rule)
    hits = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(1)
        return httpx.Response(200, json={"data": {"Media": DB[json.loads(request.content)["variables"]["id"]]}})

    now = [1_000_000.0]
    cat = AniList(transport=httpx.MockTransport(handler), min_interval_s=0, sleep=lambda s: None,
                  cache_dir=tmp_path / "anilist", clock=lambda: now[0])
    assert cat.media(1).title == cat.media(1).title == "Iron Tide"
    assert len(hits) == 1 and cat.requests == 1  # the second lookup came from the cache
    now[0] += CACHE_TTL_S + 1
    cat.media(1)
    assert len(hits) == 2  # a month later it refreshes

