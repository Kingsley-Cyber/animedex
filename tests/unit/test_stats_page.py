"""`animedex stats`: a read-only page that collects each stage's statistics and recomputes nothing."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from animedex.cli import app

pytestmark = pytest.mark.unit


def test_an_empty_repo_names_the_command_behind_each_missing_section(repo):
    result = CliRunner().invoke(app, ["stats"])
    assert result.exit_code == 0 and "0 of 6 section(s) with data" in result.output
    page = (repo.reports / "stats.md").read_text()
    for command in ("make eval", "make analyze", "make ideas", "make review-report", "make backtest"):
        assert f"Run `{command}`" in page


def test_the_page_collects_every_stage_output(repo):
    from animedex.analyze import run_analyze
    from animedex.backtest import BacktestResult, score, write_report
    from animedex.config import load_settings
    from animedex.ideate.review import taste_summary
    from animedex.store.canonical import CanonicalStore
    from tests.unit.test_review_page import _review

    _review(repo, {"C01": 5, "C02": 2, "C03": 3, "C04": 4})  # canonical state, packet, ratings, key, panel file
    key = {"basis": "enum", "pair": ["power_combat.fight_medium=energy", "power_combat.visible_counter=numeric_level"],
           "pmi": -2.3041, "together": 0, "n": 202, "adequate": True, "novel": True}
    store = CanonicalStore(repo)
    ideas = store.read("idea")
    ideas[0]["gates"]["pmi_key_pair"] = key  # the champion, as the novelty gate recorded it
    store.write("idea", ideas)
    f = repo.root / "eval" / "agreement" / "reliability.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"fields": {
        "power_combat.gate": {"n": 14, "raw": 0.93, "kappa": 0.88, "unreliable": False, "pass": True},
        "power_combat.progression": {"n": 14, "raw": 0.64, "kappa": 0.41, "unreliable": True, "pass": False}}}))
    run_analyze(repo, load_settings(repo))
    assert CliRunner().invoke(app, ["eval"]).exit_code == 0  # calibration (no checked fields yet)
    taste_summary(repo)
    res = BacktestResult(titles=3, gathered=3, interpreted=3,
                         predictions={"a_2020": {"label": "hit", "blank": "flop", "index": "hit"},
                                      "b_2021": {"label": "flop", "blank": "flop", "index": "flop"}})
    res.summary = score(res.predictions)
    write_report(repo, res)
    result = CliRunner().invoke(app, ["stats"])
    assert result.exit_code == 0 and "6 of 6 section(s) with data" in result.output
    page = (repo.reports / "stats.md").read_text()
    assert "| `power_combat.progression` | 14 | 0.64 | 0.41 | unreliable |" in page
    assert "| census rows with a power system | 0 | 1.000 | no |" in page
    assert "- CQ-G04: excluded (unreliable: power_combat.progression (kappa 0.41, raw agreement 0.64))" in page
    assert "- CQ-G01 (gate × cost_of_power" in page and "low-entropy" in page
    assert "| idea.run_test_001.001 | power_combat.fight_medium=energy + power_combat.visible_counter=numeric_level " \
           "| -2.30 | 0 | 202 |" in page
    assert "Overall: Brier n/a over 0 checked field(s)" in page
    assert "Arm strengths: animedex" in page and "Judge agreement with the ranking: 0.67" in page
    assert "2 title(s) scored: accuracy 0.50 blank, 1.00 with the index (+0.50)" in page
