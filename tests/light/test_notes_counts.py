"""Light path storage (D-055, AC-69/AC-70): the DuckDB build holds a `notes` table from notes/, the notes questions
answer lanes, gaps and coverage from it, CQ-N04 reports "not tracked", and notes/ plus build/quick/ are private."""

from __future__ import annotations

import duckdb
import pytest

from animedex.analyze.cq import QUERIES, answer_all
from animedex.build.duckdb_build import build_into
from animedex.config import load_settings
from animedex.light.notes import write_note
from animedex.ontology import CQSet, get_vocab
from tests.light.test_ingest import make_note_record

pytestmark = pytest.mark.pipeline

NOTE_CQS = CQSet({"version": "t", "questions": [
    {"id": "CQ-N01", "text": "lanes", "requires": ["notes.story_engine"]},
    {"id": "CQ-N02", "text": "gaps", "requires": ["notes.gate"]},
    {"id": "CQ-N04", "text": "not tracked", "requires": ["notes.slug"]},
    {"id": "CQ-N05", "text": "coverage", "requires": ["notes.medium"]}]})


def test_the_build_counts_the_notes_and_the_questions_read_them(repo):
    for slug in ("ironvale_circuit_2021", "lantern_debt_2019", "glass_meridian_2016"):
        write_note(repo, make_note_record(slug))
    vocab = get_vocab(repo)
    hashes = build_into(repo.build, repo.canonical, vocab, repo.notes)
    assert "notes" in hashes
    con = duckdb.connect(str(repo.build_db), read_only=True)
    try:
        rows = con.execute("SELECT slug, medium, outcome, gate, story_engine FROM notes ORDER BY slug").fetchall()
        assert [r[0] for r in rows] == ["glass_meridian_2016", "ironvale_circuit_2021", "lantern_debt_2019"]
        assert rows[0][1:] == ("manga", "mixed", "trained", "ladder_climb")
        answers = answer_all(con, vocab, NOTE_CQS, load_settings(repo))
    finally:
        con.close()
    lanes = answers["CQ-N01"]
    assert lanes["columns"][:3] == ["lane", "outcome", "n"] and any(r[0] == "ladder_climb" for r in lanes["rows"])
    gaps = answers["CQ-N02"]
    assert ["trained", "memory"] not in [r[:2] for r in gaps["rows"]]          # the pair the notes hold is no gap
    assert ["innate", "lifespan"] in [r[:2] for r in gaps["rows"]]
    assert gaps["gap_ranking"]["source"] == "notes" and gaps["gap_ranking"]["n"] == 3
    assert answers["CQ-N04"]["tracked"] is False and "not tracked" in answers["CQ-N04"]["note"]
    assert answers["CQ-N05"]["rows"] == [["anime", "flop", 1], ["anime", "hit", 1], ["manga", "mixed", 1]]
    assert all(cq in QUERIES for cq in ("CQ-N01", "CQ-N02", "CQ-N03", "CQ-N04", "CQ-N05"))


def test_notes_and_quick_cards_stay_private():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    ignore = (repo_root / ".gitignore").read_text()
    assert "\nnotes/\n" in ignore and "/build/" in ignore
    from animedex.paths import Paths

    settings = load_settings(Paths(repo_root))
    mirrored = settings.model_extra["data_repo"]["paths"]
    assert "notes" in mirrored and "build/quick" in mirrored
