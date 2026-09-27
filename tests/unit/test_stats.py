"""Statistics used as gates: pure arithmetic, checked against hand-computed values."""

from __future__ import annotations

import math

import pytest

from animedex import stats

pytestmark = pytest.mark.unit


def test_kappa_matches_a_hand_computed_table():
    # 10 items: 7 agree; rater A: 6 x, 4 y; rater B: 5 x, 5 y -> p_o .7, p_e .6*.5+.4*.5 = .5 -> kappa .4
    pairs = [("x", "x")] * 4 + [("y", "y")] * 3 + [("x", "y")] * 2 + [("y", "x")] * 1
    assert stats.cohen_kappa(pairs) == 0.4
    assert stats.cohen_kappa([("a", "a")] * 5) is None  # one category: undefined
    r = stats.reliability(pairs, grid=True)
    assert (r["raw"], r["kappa"], r["unreliable"], r["pass"]) == (0.7, 0.4, True, False)
    assert stats.reliability([("a", "a"), ("b", "b"), ("a", "a"), ("b", "b")], grid=True)["pass"] is True


def test_rule_of_three_and_open_zeros():
    assert stats.rule_of_three(150) == 0.02 and not stats.zero_is_open(150) and stats.zero_is_open(151)
    assert not stats.zero_is_open(14)  # the 14-title corpus alone can't call a zero open


def test_gap_ranking_by_expected_count():
    joint = {("a", "p"): 40, ("b", "q"): 10}
    gaps = stats.rank_gaps(100, {"a": 60, "b": 40}, {"p": 50, "q": 50}, joint)
    assert gaps[0] == {"x": "a", "y": "q", "expected": 30.0, "real": True}  # 100 × .6 × .5
    assert gaps[1] == {"x": "b", "y": "p", "expected": 20.0, "real": True}


def test_pmi_is_negative_for_rare_pairs_and_finite_for_unseen():
    assert stats.pmi(25, 50, 50, 100) == pytest.approx(0.0, abs=0.02)  # independent
    assert stats.pmi(0, 50, 50, 100) < -4 and math.isfinite(stats.pmi(0, 50, 50, 100))
    assert stats.pmi(45, 50, 50, 100) > 0.8


def test_entropy_and_mutual_information():
    assert stats.entropy(["a", "b"]) == 1.0 and stats.entropy(["a"] * 4) == 0.0
    assert stats.normalized_entropy(["a", "a", "a", "b"], 4) == round(0.8113 / 2, 4)
    assert stats.mutual_information([("x", "hit"), ("y", "flop")] * 5) == 1.0
    assert stats.mutual_information([("x", "hit"), ("x", "flop")]) == 0.0


def test_brier_score():
    assert stats.brier([(0.9, 1), (0.8, 0)]) == round((0.01 + 0.64) / 2, 4)
    assert stats.brier([]) is None


def test_bradley_terry_orders_and_measures_agreement():
    picks = [("A", "B")] * 3 + [("B", "C")] * 3 + [("A", "C")] * 3 + [("B", "A")]
    s = stats.bradley_terry(picks)
    assert s["A"] > s["B"] > s["C"] and math.isclose(math.prod(s.values()), 1.0, rel_tol=1e-6)
    assert stats.ranking_agreement(s, {"A": 3, "B": 2, "C": 1}) == 1.0
    assert stats.ranking_agreement(s, {"A": 1, "B": 2, "C": 3}) == 0.0


def test_backtest_binomial_and_sample_size():
    assert stats.mcnemar(5, 0) == round(1 / 32, 6)  # all 5 discordant titles favour the index
    assert stats.mcnemar(3, 2) > 0.05
    need = stats.sample_size_needed(3, 1, 10)
    assert need is not None and need > 10 and stats.mcnemar(round(0.3 * need), round(0.1 * need)) < 0.05
    assert stats.sample_size_needed(1, 3, 10) is None
