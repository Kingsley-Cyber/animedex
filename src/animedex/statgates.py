"""Stage-side plumbing for the statistics gates (owner ruling 2026-09-27, "statistics as gates").

`stats.py` holds the arithmetic. This module feeds it counts from the stages and reads the verdicts other
stages wrote; nothing here calls a model.

- Reliability (item 1): the AC-12 step writes `eval/agreement/reliability.json`
  (`{"fields": {path: {"n", "raw", "kappa", "unreliable", "pass"}}}`). A field flagged `unreliable` leaves
  the gap reports (ANALYZE) and the novelty pairs and grid-zero claims (IDEATE). No file, no exclusions.
- Adequacy (item 2): `adequacy(n)` is the rule-of-three bound 3/n over a subset and whether a zero there
  is open (3/n < 0.02, so n >= 151).
- Novelty (item 4): `pair_stats` and `key_pair` give the PMI of a pair over the rows that could show it.
- Each stage leaves its statistics in `build/stats/<stage>.json` for the read-only summary page
  (`animedex stats`), which never recomputes them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from animedex import stats
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

PMI_NOVEL = -1.0      # D-021: a novel pair co-occurs at most half as often as chance (log2 1/2)
LOW_ENTROPY = 0.5     # normalized entropy under this flags a field that barely varies
MIN_OPEN_N = next(n for n in range(1, 100_000) if stats.zero_is_open(n))  # 151: the smallest n where 3/n < 0.02


# ---------------------------------------------------------------- reliability (item 1)
def reliability_file(paths: Paths) -> Path:
    return paths.root / "eval" / "agreement" / "reliability.json"


def load_reliability(paths: Paths) -> dict[str, dict[str, Any]]:
    """Per-field verdicts of the agreement eval; {} when the file does not exist yet."""
    f = reliability_file(paths)
    if not f.is_file():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        raise ValueError(f"{f}: expected {{\"fields\": {{path: verdict}}}}")
    return {str(path): dict(v) for path, v in fields.items() if isinstance(v, dict)}


def unreliable_fields(paths: Paths) -> dict[str, dict[str, Any]]:
    """Fields the agreement eval flagged unreliable (kappa < 0.6): excluded from gaps and novelty."""
    return {path: v for path, v in sorted(load_reliability(paths).items()) if v.get("unreliable")}


def why_unreliable(path: str, verdict: dict[str, Any]) -> str:
    return f"{path} (kappa {verdict.get('kappa')}, raw agreement {verdict.get('raw')})"


# ---------------------------------------------------------------- adequacy (item 2)
def adequacy(n: int) -> dict[str, Any]:
    """The rule-of-three bound over `n` rows with zero events, and whether a zero there is open."""
    return {"n": int(n), "rule_of_three": round(stats.rule_of_three(int(n)), 4), "open": stats.zero_is_open(int(n)),
            "min_open_n": MIN_OPEN_N}


# ---------------------------------------------------------------- novelty (item 4)
def item_field(item: str) -> str:
    """The field an item belongs to: `power_combat.gate=contract` -> `power_combat.gate`; `bridge:x` -> `bridge`."""
    if item.startswith("bridge:"):
        return "bridge"
    return item.split("=", 1)[0]


def pair_stats(rows: Sequence[frozenset[str]], a: str, b: str) -> dict[str, Any]:
    """PMI of items `a` and `b` over the rows that could show both: rows with a value for both fields (enum
    items), or rows with any bridge concept (bridge items). `n` is that subset, so the pair is judged on it."""
    fa, fb = item_field(a), item_field(b)
    subset = [r for r in rows if {fa, fb} <= {item_field(i) for i in r}]
    n = len(subset)
    n_a = sum(1 for r in subset if a in r)
    n_b = sum(1 for r in subset if b in r)
    n_ab = sum(1 for r in subset if a in r and b in r)
    pmi = stats.pmi(n_ab, n_a, n_b, n)
    adequate = stats.zero_is_open(n)
    return {"pair": sorted([a, b]), "pmi": pmi, "together": n_ab, "n": n, "adequate": adequate,
            "novel": adequate and pmi <= PMI_NOVEL}


def key_pair(rows: Sequence[frozenset[str]], items: Iterable[str]) -> dict[str, Any] | None:
    """The pair a card is judged by: of its item pairs (two values of one enum field never pair), the one with
    the lowest PMI on an adequate subset; failing that, the lowest PMI overall. Ties go to the first pair."""
    ordered = sorted(set(items))
    pairs = [pair_stats(rows, a, b) for a, b in combinations(ordered, 2)
             if item_field(a) != item_field(b) or item_field(a) == "bridge"]
    if not pairs:
        return None
    return min(pairs, key=lambda p: (not p["adequate"], p["pmi"], p["pair"]))


def describe_pair(p: dict[str, Any]) -> str:
    a, b = p["pair"]
    return f"{a} + {b} (PMI {p['pmi']:+.2f}; together {p['together']} of {p['n']} rows)"


# ---------------------------------------------------------------- stage outputs for the summary page
def stage_file(paths: Paths, name: str) -> Path:
    return paths.build / "stats" / f"{name}.json"


def write_stage(paths: Paths, name: str, data: dict[str, Any]) -> Path:
    f = stage_file(paths, name)
    atomic_write_text(f, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return f


def read_stage(paths: Paths, name: str) -> dict[str, Any] | None:
    f = stage_file(paths, name)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
