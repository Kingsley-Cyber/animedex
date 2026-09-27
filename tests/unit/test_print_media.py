"""v1.9 print media (owner instruction 2026-09-27, D-046): manga, manhwa, webtoon and light novels as
mediums; chapter/volume scopes and locators; animation-only modules off; the adaptation signal; CQ-P01."""

from __future__ import annotations

import json

import httpx
import pytest

from animedex.catalog.anilist import AniList
from animedex.catalog.resolve import adaptation_of, print_medium, resolve

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- vocab, scope, locators (AC-58, AC-59)


# ---------------------------------------------------------------- catalog (AC-60)
def mmedia(mid, title, year, *, fmt="MANGA", country="JP", chapters=None, volumes=None, links=(), relations=(), pop=500,
           score=75, end=None):
    return {"id": mid, "idMal": mid, "title": {"romaji": title, "english": title, "native": None}, "synonyms": [],
            "format": fmt, "episodes": None, "chapters": chapters, "volumes": volumes, "status": "FINISHED",
            "countryOfOrigin": country, "popularity": pop, "averageScore": score,
            "startDate": {"year": year, "month": 1, "day": 1}, "endDate": {"year": end or year, "month": 6, "day": 1},
            "studios": {"nodes": []}, "externalLinks": [{"site": s} for s in links],
            "relations": {"edges": [{"relationType": k, "node": {"id": i, "type": t, "format": f, "episodes": 12,
                                                                    "status": st, "title": {"romaji": n, "english": n},
                                                                    "startDate": {"year": y, "month": 1},
                                                                    "endDate": {"year": y, "month": 3}}}
                                    for k, i, t, f, n, y, st in relations]}}


ANIME = {1: {"id": 1, "idMal": 1, "title": {"romaji": "Berserk", "english": "Berserk", "native": None}, "synonyms": [],
             "format": "TV", "episodes": 25, "chapters": None, "volumes": None, "status": "FINISHED", "countryOfOrigin": "JP",
             "popularity": 900, "averageScore": 84, "startDate": {"year": 1997, "month": 10, "day": 1},
             "endDate": {"year": 1998, "month": 3, "day": 1}, "studios": {"nodes": [{"name": "OLM"}]}, "externalLinks": [],
             "relations": {"edges": []}}}
PRINT = {
    10: mmedia(10, "Jagaaan", 2017, chapters=163, volumes=14, end=2021),
    11: mmedia(11, "Berserk", 1989, volumes=42, pop=2000, relations=[("ADAPTATION", 1, "ANIME", "TV", "Berserk", 1997, "FINISHED")]),
    12: mmedia(12, "Tower Song", 2018, country="KR", chapters=300, links=("Webtoon",),
               relations=[("ADAPTATION", 99, "ANIME", "TV", "Tower Song", 2027, "NOT_YET_RELEASED")]),
    13: mmedia(13, "Salt Diary", 2015, country="KR", chapters=120),
    14: mmedia(14, "Lantern Novel", 2020, fmt="NOVEL", volumes=9),
    15: mmedia(15, "Ash Ledger", 2016, links=("Piccoma", "Kakao")),   # a Japanese manga on Korean storefronts
}


def _handler(request: httpx.Request) -> httpx.Response:
    v = json.loads(request.content)["variables"]
    db = PRINT if v.get("t") == "MANGA" else ANIME
    if "id" in v:
        return httpx.Response(200, json={"data": {"Media": db[v["id"]]}})
    q = v.get("s", "").lower()
    hits = [m for m in db.values() if q in m["title"]["english"].lower()]
    return httpx.Response(200, json={"data": {"Page": {"media": hits}}})


def print_catalog(cls: type[AniList] = AniList) -> AniList:
    return cls(transport=httpx.MockTransport(_handler), min_interval_s=0, sleep=lambda s: None)


def test_a_print_only_title_resolves_to_the_print_original_with_a_chapter_or_volume_scope():
    r = resolve(print_catalog(), "Jagaaan")
    e = r.entry
    assert e["medium"] == "manga" and e["title_id"] == "jagaaan_2017" and e["format"] == "serialized"
    assert e["scope"]["numbering"] == "volumes" and e["scope"]["range"] == [1, 14] and e["scope"]["seasons"] == []
    assert "no screen version found" in r.how and r.adaptation == {"status": "none", "screen_title": None, "catalog_ref": None,
                                                                   "source_ref": "https://anilist.co/manga/10"}


def test_a_hint_forces_the_print_version_and_a_screen_match_still_wins_without_one():
    cat = print_catalog()
    assert resolve(cat, "Berserk (1997)").entry["medium"] == "anime"
    printed = resolve(cat, "Berserk (manga)")
    assert printed.entry["medium"] == "manga" and printed.adaptation["status"] == "adapted"
    assert printed.adaptation["screen_title"] == "Berserk" and printed.adaptation["catalog_ref"] == "anilist:1"


def test_print_mediums_come_from_country_format_and_links():
    cat = print_catalog()
    assert print_medium(cat.media(12, "MANGA")) == "webtoon"
    assert print_medium(cat.media(13, "MANGA")) == "manhwa"
    assert print_medium(cat.media(14, "MANGA")) == "light_novel"
    assert print_medium(cat.media(15, "MANGA")) == "manga"   # storefront links never make a webtoon
    assert adaptation_of(cat.media(12, "MANGA"))["status"] == "announced"
    assert resolve(cat, "Lantern Novel (light novel)").entry["scope"]["numbering"] == "volumes"


# ---------------------------------------------------------------- partners


# ---------------------------------------------------------------- census and CQ-P01 (AC-61)


