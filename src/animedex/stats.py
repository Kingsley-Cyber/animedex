"""Statistics used as gates (owner request 2026-09-27): pure arithmetic over counts, deterministic, no models.

Each function replaces a check inside its existing stage (agreement eval, adequacy, gap report, novelty
gate, VERIFY report, review import, backtest); `animedex stats` only summarizes them read-only.

- Reliability: Cohen's kappa per enum field next to raw agreement.
- Adequacy: a zero is "open" only when the rule-of-three bound 3/n is below 0.02.
- Gap ranking: expected count under independence, n × p(x) × p(y).
- Novelty: pointwise mutual information of a key pair (add-half smoothing, so unseen pairs stay finite).
- Field health: entropy per field and mutual information with outcome.
- Calibration: Brier score of confidence against verified correctness.
- Taste: Bradley–Terry strengths from pairwise picks, and agreement of another ranking with them.
- Backtest: exact binomial (McNemar) p-value on the titles where only one condition was right, and the
  sample size the observed split would need to reach significance.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Iterable, Sequence

KAPPA_GRID_MIN = 0.80        # grid fields need at least this (owner rule)
KAPPA_UNRELIABLE = 0.60      # below this a field is unreliable and excluded from gaps
OPEN_BOUND = 0.02            # a zero is "open" only when 3/n < 0.02, i.e. n > 150
REAL_GAP_EXPECTED = 3.0      # empty cells with expected >= 3 are real gaps
ALPHA = 0.05


# ---------------------------------------------------------------- reliability
def cohen_kappa(pairs: Sequence[tuple[Hashable, Hashable]]) -> float | None:
    """Kappa for two ratings of the same items. None when chance agreement is 1 (both runs used one
    single category): kappa is undefined there, and raw agreement says all there is to say."""
    n = len(pairs)
    if not n:
        return None
    p_o = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    p_e = sum(ca[k] * cb[k] for k in ca) / (n * n)
    if p_e >= 1.0:
        return None
    return round((p_o - p_e) / (1 - p_e), 4)


def reliability(pairs: Sequence[tuple[Hashable, Hashable]], *, grid: bool) -> dict[str, object]:
    """Raw agreement, kappa, and the verdict: grid fields need kappa >= 0.8 (and raw >= 0.8); any field
    under 0.6 is unreliable. An undefined kappa (one category) is reported, never a pass by itself."""
    n = len(pairs)
    raw = round(sum(a == b for a, b in pairs) / n, 4) if n else None
    k = cohen_kappa(pairs)
    unreliable = k is not None and k < KAPPA_UNRELIABLE
    if grid:
        ok = raw is not None and raw >= KAPPA_GRID_MIN and (k is None or k >= KAPPA_GRID_MIN)
    else:
        ok = not unreliable
    return {"n": n, "raw": raw, "kappa": k, "unreliable": unreliable, "pass": ok,
            "note": "kappa undefined: both runs used one category" if n and k is None else ""}


# ---------------------------------------------------------------- adequacy and gaps
def rule_of_three(n: int) -> float:
    """95% upper bound on a rate after n trials with zero events."""
    return 3.0 / n if n > 0 else 1.0


def zero_is_open(n: int) -> bool:
    """A zero count is evidence of an open cell only when 3/n < 0.02 (n > 150)."""
    return rule_of_three(n) < OPEN_BOUND


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


# ---------------------------------------------------------------- novelty
def pmi(n_xy: int, n_x: int, n_y: int, n: int) -> float:
    """Pointwise mutual information in bits, add-half smoothed: log2(p(x,y) / (p(x) p(y))). Negative
    means the pair co-occurs less than chance; an unseen pair in a large sample is strongly negative."""
    if n <= 0:
        return 0.0
    d = n + 1.0
    return round(math.log2(((n_xy + 0.5) / d) / (((n_x + 0.5) / d) * ((n_y + 0.5) / d))), 4)


# ---------------------------------------------------------------- field health
def entropy(values: Iterable[Hashable]) -> float:
    counts = Counter(values)
    n = sum(counts.values())
    return round(-sum(c / n * math.log2(c / n) for c in counts.values()), 4) if n else 0.0


def normalized_entropy(values: Sequence[Hashable], k: int) -> float:
    """Entropy over log2(k) for a field with k possible values: 0 = always the same, 1 = uniform."""
    return round(entropy(values) / math.log2(k), 4) if k > 1 and values else 0.0


def mutual_information(pairs: Sequence[tuple[Hashable, Hashable]]) -> float:
    """I(X; Y) in bits from paired observations (e.g. a field's value and the outcome label)."""
    n = len(pairs)
    if not n:
        return 0.0
    joint, px, py = Counter(pairs), Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    return round(sum(c / n * math.log2((c / n) / ((px[a] / n) * (py[b] / n))) for (a, b), c in joint.items()), 4)


# ---------------------------------------------------------------- calibration
def brier(pairs: Sequence[tuple[float, int]]) -> float | None:
    """Mean squared gap between stated confidence and verified correctness (1 right, 0 wrong)."""
    return round(sum((c - y) ** 2 for c, y in pairs) / len(pairs), 4) if pairs else None


# ---------------------------------------------------------------- taste
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


# ---------------------------------------------------------------- backtest
def binomial_tail(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)) if n else 1.0


def mcnemar(only_a: int, only_b: int) -> float:
    """One-sided exact McNemar p-value that condition A beats B, from the discordant items only."""
    return round(binomial_tail(only_a, only_a + only_b), 6) if only_a + only_b else 1.0


def sample_size_needed(only_a: int, only_b: int, n: int, *, alpha: float = ALPHA, limit: int = 2000) -> int | None:
    """Items needed for the observed discordant split to reach p < alpha, scaling the same proportions;
    None when A doesn't lead or the limit is reached."""
    if n <= 0 or only_a <= only_b:
        return None
    ra, rb = only_a / n, only_b / n
    for m in range(n, limit + 1):
        a, b = round(ra * m), round(rb * m)
        if a + b and mcnemar(a, b) < alpha:
            return m
    return None
