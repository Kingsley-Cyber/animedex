"""Catalog resolution, backfill planning, and the census (v1.6) with a fake AniList (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from animedex.catalog.anilist import AniList
from animedex.catalog.resolve import resolve, slug

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

