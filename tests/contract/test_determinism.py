"""AC-07: `rm -rf build && make build` produces identical DuckDB table hashes."""

from __future__ import annotations

import json
import shutil

import pytest
from typer.testing import CliRunner

from animedex.build.duckdb_build import TABLES, VIEWS, build, build_into, verify_determinism
from animedex.cli import app
from animedex.ontology import get_vocab
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from tests.conftest import synthetic_state, write_state

pytestmark = pytest.mark.contract


def test_clean_rebuild_identical_hashes(repo):
    write_state(repo, synthetic_state())
    first = build(repo)
    shutil.rmtree(repo.build)
    second = build(repo)
    assert first == second
    assert set(first) == {t.name for t in TABLES} | {n for n, _ in VIEWS}


def test_verify_determinism_and_cli(repo):
    write_state(repo, synthetic_state())
    ok, diffs = verify_determinism(repo)
    assert ok and diffs == {}
    result = CliRunner().invoke(app, ["build", "--verify-determinism"])
    assert result.exit_code == 0 and "identical hashes" in result.output


def test_provenance_timestamps_do_not_reach_derived_tables(repo, tmp_path):
    write_state(repo, synthetic_state())
    before = build_into(tmp_path / "a", repo.canonical, get_vocab())
    for path in repo.canonical.glob("*.jsonl"):
        records = read_jsonl(path)
        for r in records:
            r["provenance"]["created_at"] = "2031-01-01T00:00:00+00:00"
            r["provenance"]["run_id"] = "run_later"
        path.write_text(dumps_jsonl(records))
    assert build_into(tmp_path / "b", repo.canonical, get_vocab()) == before


def test_content_change_changes_hashes(repo, tmp_path):
    write_state(repo, synthetic_state())
    before = build_into(tmp_path / "a", repo.canonical, get_vocab())
    path = repo.canonical / "moments.jsonl"
    records = read_jsonl(path)
    records[0]["why_it_hit"] = "A different synthetic reason."
    path.write_text(dumps_jsonl(records))
    after = build_into(tmp_path / "b", repo.canonical, get_vocab())
    assert after["moments"] != before["moments"] and after["titles"] == before["titles"]


def test_views_answer_on_synthetic_data(repo):
    import duckdb

    write_state(repo, synthetic_state())
    build(repo)
    con = duckdb.connect(str(repo.build_db), read_only=True)
    try:
        assert con.execute("SELECT atom_id FROM v_load_bearing").fetchall() == [("ironvale_circuit_2021.m.001",)]
        assert con.execute("SELECT count(*) FROM v_incidence").fetchone()[0] > 0
        assert con.execute("SELECT label FROM v_outcomes WHERE title_id = 'glass_meridian_2016'").fetchone() == ("flop",)
    finally:
        con.close()
    hashes = json.loads(repo.build_hashes.read_text())
    assert all(v.startswith("sha256:") for v in hashes.values())
