"""The notes, counted in place (DuckDB reads notes/*.json; nothing is built or copied): lanes, ranked gaps,
coverage and the unadapted print titles; `make export` writes spreadsheets; notes and cards stay private."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from animedex.config import load_settings
from animedex.light.counts import QUERIES, analyze, connect, export
from animedex.light.notes import write_note
from animedex.ontology import get_vocab, load_cqs
from animedex.paths import Paths
from tests.light.test_ingest import make_note_record

pytestmark = pytest.mark.pipeline

SLUGS = ("ironvale_circuit_2021", "lantern_debt_2019", "glass_meridian_2016")


def test_duckdb_reads_the_notes_in_place_and_answers_every_question(repo):
    for slug in SLUGS:
        write_note(repo, make_note_record(slug))
    con = connect(repo)
    rows = con.execute("SELECT slug, medium, outcome, gate, story_engine, adaptation FROM notes ORDER BY slug").fetchall()
    assert [r[0] for r in rows] == sorted(SLUGS) and rows[0][1:] == ("manga", "mixed", "trained", "ladder_climb", "none")
    write_note(repo, {**make_note_record("ironvale_circuit_2021"), "slug": "later_2022", "title": "Later"})
    assert con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 4          # read at query time: no build step
    con.close()
    answers, report = analyze(repo, get_vocab(repo), load_cqs(repo))
    assert set(answers) == set(QUERIES) == {q.id for q in load_cqs(repo).questions}
    assert any(r[0] == "ladder_climb" for r in answers["CQ-N01"]["rows"])
    gaps = answers["CQ-N02"]
    assert ["trained", "memory"] not in gaps["rows"] and ["innate", "lifespan"] in gaps["rows"]
    assert gaps["gap_ranking"]["n"] == 4
    assert answers["CQ-P01"]["rows"] == [["ladder_climb", "manga", "Glass Meridian", 2016, 4000]]
    text = report.read_text()
    assert "## Not tracked" in text and "set_structure" in text and "CQ-N03" in text


def test_no_notes_is_an_empty_index_not_an_error(repo):
    answers, _ = analyze(repo, get_vocab(repo), load_cqs(repo))
    assert answers["CQ-N01"]["rows"] == [] and answers["CQ-N05"]["rows"] == []


def test_export_writes_one_row_per_note_and_per_quick_card(repo):
    for slug in SLUGS:
        write_note(repo, make_note_record(slug))
    repo.quick.mkdir(parents=True)
    card = {"logline": "A courier pays for power with memory.", "premise": "p", "mc_edge": "e", "power_kit": {"medium": "grid"},
            "closest_existing": "ironvale_circuit_2021", "never_done_claim": None}
    (repo.quick / "20260927_120000_abcdef.json").write_text(json.dumps({
        "created_at": "2026-09-27T12:00:00+00:00", "seed": "a seed", "seed_kind": "lane", "survivors": ["C1"],
        "cards": {"C1": card, "C2": card}, "checks": {"C1": {"score": 80, "closeness": "far", "dims": 3, "rules": [],
                                                              "weakness": "w", "closest_slug": "lantern_debt_2019"}}}))
    notes_csv, cards_csv = export(repo)
    notes = list(csv.DictReader(notes_csv.open()))
    assert [n["slug"] for n in notes] == sorted(SLUGS) and notes[0]["power_functions"] == "reroute / store / discharge"
    assert notes[0]["source_1"].startswith("https://en.wikipedia.org")
    cards = list(csv.DictReader(cards_csv.open()))
    assert [(c["ref"], c["status"], c["rank"]) for c in cards] == [("C1", "survived", "1"), ("C2", "dropped", "")]
    assert cards[0]["closest"] == "lantern_debt_2019" and cards[0]["score"] == "80"


def test_notes_and_quick_cards_stay_private():
    root = Path(__file__).resolve().parents[2]
    ignore = (root / ".gitignore").read_text()
    assert "\nnotes/\n" in ignore and "/build/" in ignore
    mirrored = load_settings(Paths(root)).section("data_repo")["paths"]
    assert "notes" in mirrored and "build/quick" in mirrored
