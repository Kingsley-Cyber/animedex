"""v1.9 print media (owner instruction 2026-09-27, D-046): manga, manhwa, webtoon and light novels as
mediums; chapter/volume scopes and locators; animation-only modules off; the adaptation signal; CQ-P01."""

from __future__ import annotations

import json

import httpx
import pytest
import yaml
from pydantic import ValidationError

from animedex.activation import violations
from animedex.catalog.anilist import AniList
from animedex.catalog.resolve import adaptation_of, print_medium, resolve
from animedex.models import CorpusEntry
from animedex.models.common import PRINT_MEDIA, Scope
from animedex.models.evidence import Adaptation, MomentLocator, Outcome
from animedex.ontology import get_cqs, get_vocab
from animedex.pipeline.common import scope_lines
from animedex.pipeline.partners import select_partners
from tests.conftest import make_title, prov, synthetic_state

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- vocab, scope, locators (AC-58, AC-59)
def test_print_mediums_and_numbering_are_in_the_vocab():
    vocab = get_vocab()
    assert set(PRINT_MEDIA) <= set(vocab.enum("medium")) and {"chapters", "volumes"} <= set(vocab.enum("scope.numbering"))
    assert vocab.version == "1.6.0"


def test_a_print_scope_uses_chapters_or_volumes_and_no_seasons():
    ok = Scope(version="manga (14 volumes, 2017-2023)", numbering="volumes", range=[1, 14])
    ok.check_for_format("serialized", "manga")
    with pytest.raises(ValueError, match="chapters or volumes"):
        Scope(version="x", seasons=[1], numbering="broadcast").check_for_format("serialized", "manhwa")
    with pytest.raises(ValueError, match="no seasons|not seasons"):
        Scope(version="x", seasons=[1], numbering="chapters").check_for_format("serialized", "webtoon")
    with pytest.raises(ValueError, match="print titles only"):
        Scope(version="x", seasons=[1], numbering="chapters").check_for_format("serialized", "anime")
    with pytest.raises(ValidationError):
        Scope(version="x", numbering="chapters", range=[5, 2])
    entry = CorpusEntry.model_validate({"title_id": "paper_moon_2019", "title": "Paper Moon", "year": 2019,
                                        "medium": "light_novel", "format": "serialized",
                                        "scope": {"version": "light novel (9 volumes, 2019-2024)", "seasons": [],
                                                  "numbering": "volumes", "range": [1, 9], "exclude": []}})
    assert entry.scope.range == [1, 9]


def test_locators_carry_chapter_and_volume_and_screen_ones_still_work():
    assert MomentLocator(chapter=12, volume=2).chapter == 12
    assert MomentLocator(season=1, episode=7).chapter is None


def test_the_outcome_carries_an_adaptation_signal_only_when_given():
    base = {"title_id": "paper_moon_2019", "label": "hit", "signals": [], "provenance": prov("VERIFY")}
    assert "adaptation" not in Outcome.model_validate(base).model_dump()
    with_it = Outcome.model_validate({**base, "adaptation": {"status": "announced", "screen_title": "Paper Moon",
                                                              "catalog_ref": "anilist:77", "source_ref": "https://anilist.co/manga/7"}})
    assert with_it.model_dump()["adaptation"]["status"] == "announced"
    with pytest.raises(ValidationError):
        Adaptation(status="maybe")


def test_animation_only_modules_stay_off_for_print_titles():
    vocab = get_vocab()
    assert not violations(vocab, "manga", "serialized", ["power_combat", "relationships", "series_engine"])
    assert any("sensory must not be active" in p for p in violations(vocab, "manga", "serialized", ["power_combat", "sensory"]))
    assert any("anime_production must not be active" in p
               for p in violations(vocab, "webtoon", "serialized", ["power_combat", "anime_production"]))
    assert any("sensory must be active" in p for p in violations(vocab, "anime", "serialized", ["power_combat"]))


def test_scope_lines_render_a_print_range():
    lines = scope_lines("Paper Moon", 2019, "manga", "serialized",
                        {"version": "manga (40 chapters, 2019-2021)", "seasons": [], "numbering": "chapters", "range": [1, 40], "exclude": ["adaptations"]})
    assert "chapters: 1-40" in lines and not any(line.startswith("seasons:") for line in lines)
    lines = scope_lines("Paper Moon", 2019, "manga", "serialized", {"version": "ongoing", "seasons": [], "numbering": "chapters", "range": None, "exclude": []})
    assert "chapters: everything published so far" in lines


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
    CorpusEntry.model_validate(e)


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
def test_print_never_fills_an_anime_titles_cross_medium_slot_but_gets_a_screen_partner():
    state = synthetic_state()
    manga = make_title("paper_moon_2019", "Paper Moon", medium="manga", fmt="serialized",
                       modules=("power_combat", "relationships", "series_engine"))
    manga["scope"] = {"version": "manga (40 chapters, 2019-2021)", "seasons": [], "numbering": "chapters", "range": [1, 40], "exclude": []}
    titles = {t["title_id"]: t for t in [*state["title"], manga]}
    vocab, outcomes = get_vocab(), {o["title_id"]: o for o in state["outcome"]}
    anime_partners = {p["role"]: p["title_id"] for p in select_partners(titles["ironvale_circuit_2021"], titles, outcomes, vocab)}
    assert anime_partners.get("cross_medium") != "paper_moon_2019"
    print_partners = {p["role"]: p["title_id"] for p in select_partners(manga, titles, outcomes, vocab)}
    assert print_partners.get("cross_medium") in {t for t, r in titles.items() if r["medium"] not in PRINT_MEDIA}


# ---------------------------------------------------------------- census and CQ-P01 (AC-61)
def test_cq_p01_lists_unadapted_print_titles_by_lane(repo):
    from animedex.analyze import run_analyze
    from animedex.analyze.cq import QUERIES
    from animedex.config import load_settings
    from animedex.store.canonical import CanonicalStore
    from tests.conftest import make_census, write_state

    assert "CQ-P01" in QUERIES and "CQ-P01" in get_cqs().ids
    write_state(repo, synthetic_state())
    rows = make_census(2, medium="manga", format="MANGA", story_engine="journey_quest", adaptation="none")
    screen = make_census(1, medium="anime")
    screen[0]["census_id"] = "anilist:900200"          # make_census numbers from 1: keep every id distinct
    adapted = make_census(1, medium="manhwa", format="MANGA", story_engine="journey_quest", adaptation="adapted")
    adapted[0]["census_id"] = "anilist:900100"
    CanonicalStore(repo).write("census", rows + screen + adapted)
    run_analyze(repo, load_settings(repo))
    answer = json.loads((repo.build / "cq_answers" / "CQ-P01.json").read_text())
    assert answer["columns"][:2] == ["lane", "medium"] and len(answer["rows"]) == 2
    assert all(r[0] == "journey_quest" and r[1] == "manga" for r in answer["rows"])


def test_print_census_items_carry_the_adaptation_status():
    from animedex.pipeline.census import item_from_media, top_print

    cat = print_catalog()
    item = item_from_media(cat.media(12, "MANGA"))
    assert (item.medium, item.adaptation, item.format) == ("webtoon", "announced", "MANGA")

    class Popular(AniList):
        def popular(self, page, *, country, per_page=50, since=1995, formats=None, media_type="ANIME"):
            assert media_type == "MANGA"
            if page != 1:
                return []
            ids = (10, 14) if country == "JP" else (13,) if country == "KR" else ()
            return [self.media(i, "MANGA") for i in ids]

    items = top_print(print_catalog(Popular), size=3, korean=1)
    assert [i.medium for i in items] == ["manga", "light_novel", "manhwa"] and all(i.adaptation == "none" for i in items)


def test_a_print_corpus_entry_round_trips_through_yaml(repo):
    r = resolve(print_catalog(), "Jagaaan (manga)")
    repo.corpus_file.write_text(yaml.safe_dump({"titles": [r.entry]}))
    from animedex.guards import load_corpus

    assert load_corpus(repo)["jagaaan_2017"].scope.numbering == "volumes"
