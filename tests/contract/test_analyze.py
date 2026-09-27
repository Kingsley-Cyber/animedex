"""M4 ANALYZE: every CQ has a query and a saved answer (AC-21); gap zeros carry a coverage flag
(AC-22); the graveyard attaches failure_reason + failure_level and warns on premise failures
only (AC-23, v1.3); CQ answers are identical after a clean rebuild (AC-24); gold stays masked."""

from __future__ import annotations

import json

import pytest
import yaml
from typer.testing import CliRunner

from animedex.analyze import graveyard_index, run_analyze, verify_cq_determinism
from animedex.analyze.cq import QUERIES
from animedex.cli import app
from animedex.config import load_settings
from animedex.ontology import get_cqs
from tests.conftest import synthetic_state, write_state

pytestmark = pytest.mark.contract


def test_every_cq_has_a_query_and_a_saved_answer(repo):
    assert set(QUERIES) == get_cqs().ids  # AC-21: no question without a query, no orphan query
    write_state(repo, synthetic_state())
    result = run_analyze(repo, load_settings(repo))
    saved = {p.stem for p in (repo.build / "cq_answers").glob("CQ-*.json")}
    assert saved == get_cqs().ids and result.answered == len(saved)


def test_queries_run_on_an_empty_corpus(repo):
    result = run_analyze(repo, load_settings(repo))
    g01 = json.loads((repo.build / "cq_answers" / "CQ-G01.json").read_text())
    assert result.answered == len(get_cqs().ids)
    assert g01["zeros_are"] == "insufficient coverage" and g01["rows"]  # every cell empty, none trusted


def test_gap_zeros_carry_the_coverage_flag(repo):
    from tests.conftest import prov

    state = synthetic_state()
    state["coverage"] = [{"title_id": "ironvale_circuit_2021", "passes_done": ["P1", "VERIFY"], "field_completion": 0.9,
                          "verified_share": 0.5, "modules_active": ["power_combat", "sensory", "anime_production",
                                                                    "series_engine"],
                          "episodes": {"in_scope": 0, "indexed": 0, "unsourced": 0, "selection": {}},
                          "episode_backed_share": 0.0, "provenance": prov("CANONICALIZE", model=None)}]
    write_state(repo, state)
    run_analyze(repo, load_settings(repo))
    g01 = json.loads((repo.build / "cq_answers" / "CQ-G01.json").read_text())
    assert g01["coverage"]["adequate"] is False and g01["zeros_are"] == "insufficient coverage"  # AC-22
    g07 = json.loads((repo.build / "cq_answers" / "CQ-G07.json").read_text())
    assert dict(map(tuple, g07["rows"]))["power_combat"] == 1


def test_graveyard_warns_on_premise_failures_only():
    state = synthetic_state()
    rows = graveyard_index(state)
    [flop] = [r for r in rows if r["title_id"] == "glass_meridian_2016"]
    assert (flop["failure_level"], flop["warns"], flop["t5_evidence"]) == ("execution", False, True)  # AC-23
    assert flop["failure_reason"]
    state["outcome"][0]["failure_level"] = "premise"
    [flop] = [r for r in graveyard_index(state) if r["title_id"] == "glass_meridian_2016"]
    assert flop["warns"] is True and flop["t5_evidence"] is False


def test_cq_answers_are_deterministic(repo):
    write_state(repo, synthetic_state())
    ok, diffs = verify_cq_determinism(repo, load_settings(repo))
    assert ok and diffs == {}  # AC-24
    result = CliRunner().invoke(app, ["build", "--verify-determinism"])
    assert result.exit_code == 0 and "identical hashes and CQ answers" in result.output


def test_make_build_includes_the_cq_step(repo):
    write_state(repo, synthetic_state())
    result = CliRunner().invoke(app, ["build"])
    assert result.exit_code == 0 and "CQ answers" in result.output
    assert (repo.build / "cq_answers" / "hashes.json").is_file()


def test_report_masks_gold_titles_while_the_blind_is_pending(repo):
    state = synthetic_state()
    write_state(repo, state)
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope")}
              | {"role_tags": ["gold", "flop"] if t["title_id"] == "glass_meridian_2016" else t["role_tags"]}
              for t in state["title"]]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    (repo.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "pending", "runs_without_annotations": True}))
    run_analyze(repo, load_settings(repo))
    report = (repo.reports / "analysis.md").read_text()
    assert "glass_meridian_2016 | (gold: hidden)" in report and "Execution problems" not in report
    (repo.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "waived", "runs_without_annotations": True}))
    run_analyze(repo, load_settings(repo))
    assert "Execution problems" in (repo.reports / "analysis.md").read_text()
