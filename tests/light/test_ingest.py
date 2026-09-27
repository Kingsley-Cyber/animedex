"""Light path (owner instruction 2026-09-27): `make ingest` writes one study note per show from one call per
three shows; the outcome is the catalog's numbers under the existing label rule; existing notes are skipped;
a bad answer is quarantined and reported with its reason."""

from __future__ import annotations

import json

import pytest

from animedex import SCHEMA_VERSION
from animedex.catalog.resolve import Resolved
from animedex.config import ModelSpec, load_settings
from animedex.content_guards import GuardConfig
from animedex.light.ingest import run_ingest
from animedex.light.notes import note_problems, read_notes
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.pipeline.test_gather import WebMock

pytestmark = pytest.mark.pipeline

WIKI = "https://en.wikipedia.org/wiki/Ironvale_Circuit"
WIKIA = "https://ironvale.fandom.com/wiki/Marisol_Vey"
MAL = "https://myanimelist.net/anime/1"
LABEL = "ironvale_circuit_2021+lantern_debt_2019+glass_meridian_2016"


def entry(slug: str, title: str, year: int, medium: str = "anime") -> dict:
    return {"title_id": slug, "title": title, "year": year, "medium": medium, "format": "serialized",
            "scope": {"version": f"TV anime (12 eps, {year})", "seasons": [1], "numbering": "broadcast", "exclude": []},
            "role_tags": [], "catalog_ref": f"anilist:{len(slug)}"}


SHOWS = {"Ironvale Circuit": entry("ironvale_circuit_2021", "Ironvale Circuit", 2021),
         "Lantern Debt": entry("lantern_debt_2019", "Lantern Debt", 2019),
         "Glass Meridian (manga)": {**entry("glass_meridian_2016", "Glass Meridian", 2016, "manga"),
                                    "scope": {"version": "manga (14 volumes, 2016-2020)", "seasons": [], "numbering": "volumes",
                                              "range": [1, 14], "exclude": []}}}
NUMBERS = {"ironvale_circuit_2021": {"score": 81, "popularity": 50000}, "lantern_debt_2019": {"score": 60, "popularity": 900},
           "glass_meridian_2016": {"score": 70, "popularity": 4000}, "copper_vow_2018": {"score": 66, "popularity": 300}}
THREE = ["ironvale_circuit_2021", "lantern_debt_2019", "glass_meridian_2016"]
EXTRA = {"Copper Vow": entry("copper_vow_2018", "Copper Vow", 2018), "Copper Vow (2018)": entry("copper_vow_2018", "Copper Vow", 2018)}


def fake_resolve(line: str) -> Resolved | None:
    e = SHOWS.get(line) or EXTRA.get(line)
    if e is None:
        return None
    adapt = ({"status": "none", "screen_title": None, "catalog_ref": None, "source_ref": "https://anilist.co/manga/3"}
             if e["medium"] == "manga" else None)
    return Resolved(line, e, "test", likely=None, popularity=1000, adaptation=adapt)


def fake_numbers(res: Resolved) -> dict | None:
    return NUMBERS[res.entry["title_id"]]


def make_note_record(slug: str) -> dict:
    """A written note for a fixture show (what `make_note` produces)."""
    from animedex.light.notes import make_note

    title = {"ironvale_circuit_2021": "Ironvale Circuit", "lantern_debt_2019": "Lantern Debt",
             "copper_vow_2018": "Copper Vow", "glass_meridian_2016": "Glass Meridian (manga)"}[slug]
    res = fake_resolve(title)
    assert res is not None
    return make_note(note_for(res.entry["title"]), res, NUMBERS[slug], run_id="run_t", model="mock", prompt_version="1",
                     vocab=get_vocab(), cache_key=None, created_at="2026-09-27T00:00:00+00:00", web_urls={WIKI, WIKIA})


def note_for(title: str, **over) -> dict:
    n = {"show": title,
         "premise": "A courier who reroutes grid power through her arms pays for every rescue with a memory.",
         "engine": {"goal": "keep the harbor lit", "constraint": "every surge burns a memory",
                    "strategy": "ration the rescues", "cost": "her own past", "dilemma": "save strangers or keep herself"},
         "gate": "trained", "cost_of_power": "memory", "progression": "linear", "visible_counter": "gauge",
         "fight_medium": "energy", "story_engine": "ladder_climb",
         "mc_edge": "she spends what nobody else is willing to spend",
         "power_kit": {"medium": "the harbor's live grid current", "functions": ["reroute", "store", "discharge"],
                       "tools": ["arm conduits", "capacitor scars", "a grid tap"], "limits": "only near live wires"},
         "villain_type": "the grid's private owner", "setting": "a drowned harbor city on stilts",
         "elements": [{"element": "power drawn from public infrastructure",
                       "pattern": "a hero draws strength from shared infrastructure everyone else depends on"},
                      {"element": "memory as the price of every use",
                       "pattern": "each use erases a personal memory, so power spends the self"},
                      {"element": "the ration of rescues",
                       "pattern": "the hero rations rescues, and every refusal costs someone else"}],
         "sources": [WIKI, WIKIA]}
    n.update(over)
    return n


def answer() -> dict:
    return {"notes": [note_for("Ironvale Circuit"), note_for("Lantern Debt", story_engine="other: siege of the debt"),
                      note_for("Glass Meridian")]}


def client_for(repo, responses, urls=(WIKI, WIKIA)):
    mock = WebMock(set(urls), responses=responses)
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="s"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_n"))
    return client, mock


def ingest(repo, lines, responses, urls=(WIKI, WIKIA)):
    client, mock = client_for(repo, responses, urls)
    result = run_ingest(repo, load_settings(repo), get_vocab(), lines, client=client, resolve=fake_resolve,
                        numbers=fake_numbers, run_id="run_n", created_at="2026-09-27T20:00:00+00:00")
    return result, mock


def test_one_call_writes_three_notes_with_catalog_outcomes(repo):
    result, mock = ingest(repo, list(SHOWS), {("NOTES", LABEL): [answer()]})
    assert result.written == THREE and not result.failed and result.calls == 1, result.lines()
    assert len(mock.calls) == 1 and mock.calls[0]["params"]["web"]["max_searches"] == 6   # 2 per show, one call
    assert "show 1: Ironvale Circuit (2021, anime)" in mock.calls[0]["user"] and "values gate:" in mock.calls[0]["user"]
    notes = read_notes(repo)
    iv, ld, gm = notes["ironvale_circuit_2021"], notes["lantern_debt_2019"], notes["glass_meridian_2016"]
    assert iv["outcome"]["label"] == "hit" and ld["outcome"]["label"] == "flop" and gm["outcome"]["label"] == "mixed"
    assert gm["medium"] == "manga" and gm["outcome"]["adaptation"]["status"] == "none" and gm["scope"]["range"] == [1, 14]
    assert iv["gate"] == "trained" and ld["story_engine"] == "other: siege of the debt"
    assert [s["retrieved"] for s in iv["sources"]] == [True, True] and iv["sources"][0]["kind"] == "wikipedia"
    assert iv["provenance"]["pass"] == "NOTES" and iv["provenance"]["note_version"] == "1.0.0"
    assert len(iv["elements"]) == 3 and iv["power_kit"]["functions"] == ["reroute", "store", "discharge"]
    assert result.lines()[0].startswith("ingest: 3 note(s) written, 0 skipped")


def test_a_rerun_skips_existing_notes_and_reports_unknown_lines(repo):
    ingest(repo, list(SHOWS), {("NOTES", LABEL): [answer()]})
    result, mock = ingest(repo, [*SHOWS, "Nothing Here (1999)"], {})
    assert result.skipped == THREE and not mock.calls and result.written == []
    assert result.failed == [("Nothing Here (1999)", "not found in the catalog")]


def test_a_bad_answer_is_quarantined_and_every_show_of_the_call_is_reported(repo):
    bad = answer()
    bad["notes"][0]["power_kit"]["functions"] = ["reroute", "store"]                       # 2, not 3
    bad["notes"][1]["elements"][0]["pattern"] = "Lantern Debt's hero pays with memories"   # names the title
    result, mock = ingest(repo, list(SHOWS), {("NOTES", LABEL): [bad, bad]})
    assert len(mock.calls) == 2 and result.written == [] and result.calls == 1   # the call and its one repair
    assert [who for who, _ in result.failed] == THREE
    assert "exactly 3 items" in result.failed[0][1] or "strip the names" in result.failed[0][1]
    assert list((repo.quarantine / "NOTES" / "note").glob("*.json"))
    assert not read_notes(repo)


def test_note_problems_name_the_rules(repo):
    vocab, guards = get_vocab(), GuardConfig.from_settings(load_settings(repo))
    good = {"notes": [note_for("Ironvale Circuit")]}
    assert note_problems(good, ["Ironvale Circuit"], vocab, guards, {"ironvale circuit"}) == []
    bad = {"notes": [note_for("Ironvale Circuit", sources=[MAL, WIKIA], gate="bought",
                              premise=" ".join(["word"] * 26))]}
    problems = note_problems(bad, ["Ironvale Circuit"], vocab, guards, {"ironvale circuit"})
    assert any("myanimelist" in p for p in problems) and any("Wikipedia" in p for p in problems)
    assert any("notes[0].gate" in p for p in problems) and any("26 words exceeds the 25-word limit" in p for p in problems)
    wrong_order = {"notes": [note_for("Lantern Debt"), note_for("Ironvale Circuit")]}
    assert any("in the order given" in p for p in note_problems(wrong_order, ["Ironvale Circuit", "Lantern Debt"],
                                                                 vocab, guards, set()))
    json.dumps(good)
