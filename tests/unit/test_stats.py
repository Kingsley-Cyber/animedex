"""Statistics used as gates: pure arithmetic, checked against hand-computed values."""

from __future__ import annotations

import math

import pytest

from animedex import stats

pytestmark = pytest.mark.unit


def test_gap_ranking_by_expected_count():
    joint = {("a", "p"): 40, ("b", "q"): 10}
    gaps = stats.rank_gaps(100, {"a": 60, "b": 40}, {"p": 50, "q": 50}, joint)
    assert gaps[0] == {"x": "a", "y": "q", "expected": 30.0, "real": True}  # 100 × .6 × .5
    assert gaps[1] == {"x": "b", "y": "p", "expected": 20.0, "real": True}


def test_bradley_terry_orders_and_measures_agreement():
    picks = [("A", "B")] * 3 + [("B", "C")] * 3 + [("A", "C")] * 3 + [("B", "A")]
    s = stats.bradley_terry(picks)
    assert s["A"] > s["B"] > s["C"] and math.isclose(math.prod(s.values()), 1.0, rel_tol=1e-6)
    assert stats.ranking_agreement(s, {"A": 3, "B": 2, "C": 1}) == 1.0
    assert stats.ranking_agreement(s, {"A": 1, "B": 2, "C": 3}) == 0.0


