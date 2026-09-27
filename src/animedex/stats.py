"""Statistics over counts: deterministic, no models.

- Gap ranking (`make analyze`): an empty pair's expected count under independence, n x p(x) x p(y); expected
  >= 3 with none observed is a real gap.
- Taste (`make review`): Bradley-Terry strengths from pairwise picks, and another ranking's agreement with them.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence

REAL_GAP_EXPECTED = 3.0      # empty cells with expected >= 3 are real gaps


def expected_count(n: int, count_x: int, count_y: int) -> float:
    """Expected co-occurrences under independence: n × p(x) × p(y)."""
    return n * (count_x / n) * (count_y / n) if n else 0.0

def rank_gaps(n: int, marginals_x: dict[str, int], marginals_y: dict[str, int], joint: dict[tuple[str, str], int]
              ) -> list[dict[str, object]]:
    """Every empty (x, y) cell with its expected count, highest first; `real` when expected >= 3."""
    out = []
    for x, cx in marginals_x.items():
        for y, cy in marginals_y.items():
            if joint.get((x, y), 0) == 0:
                e = expected_count(n, cx, cy)
                out.append({"x": x, "y": y, "expected": round(e, 3), "real": e >= REAL_GAP_EXPECTED})
    return sorted(out, key=lambda r: (-float(r["expected"]), r["x"], r["y"]))

def bradley_terry(picks: Sequence[tuple[Hashable, Hashable]], *, iters: int = 200, prior: float = 0.5
                  ) -> dict[Hashable, float]:
    """Strengths from (winner, loser) picks by the MM algorithm, with `prior` pseudo-wins and losses
    against an average opponent so every item stays finite. Normalized to a geometric mean of 1."""
    items = sorted({i for p in picks for i in p}, key=str)
    if not items:
        return {}
    wins = Counter(w for w, _ in picks)
    games: Counter[tuple[Hashable, Hashable]] = Counter()
    for w, loser in picks:
        games[(w, loser)] += 1
        games[(loser, w)] += 1
    s = {i: 1.0 for i in items}
    for _ in range(iters):
        new = {}
        for i in items:
            denom = sum(g / (s[i] + s[j]) for (a, j), g in games.items() if a == i) + 2 * prior / (s[i] + 1.0)
            new[i] = (wins[i] + prior) / denom
        g = math.exp(sum(math.log(v) for v in new.values()) / len(new))
        s = {i: v / g for i, v in new.items()}
    return {i: round(v, 6) for i, v in s.items()}

def ranking_agreement(reference: dict[Hashable, float], other: dict[Hashable, float]) -> float | None:
    """Share of item pairs that `other` orders the same way as `reference` (ties in either are skipped)."""
    common = sorted(set(reference) & set(other), key=str)
    agree = total = 0
    for i, a in enumerate(common):
        for b in common[i + 1:]:
            dr, do = reference[a] - reference[b], other[a] - other[b]
            if dr == 0 or do == 0:
                continue
            total += 1
            agree += (dr > 0) == (do > 0)
    return round(agree / total, 4) if total else None
