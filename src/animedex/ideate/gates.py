"""Deterministic IDEATE gates (05, 06), in order:

1. Clone: structural Jaccard >= structural_jaccard_reject, procedural Jaccard >= procedural_jaccard_reject,
   or (premise cosine >= premise_cosine_reject and structural >= premise_cosine_with_structural)
   -> rework once, then reject.
2. Novelty: an enum pair with zero co-occurrence under adequate coverage, or a pair of bridge
   concepts that no single title's load-bearing patterns combine -> else reject. (Zero is not novel
   when coverage is thin.)
3. Graveyard: a match with a PREMISE-level flop combination needs "why this time is different",
   else rework once, then reject. Execution-level matches are T5 evidence, not warnings (v1.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from animedex.embeddings.base import Embedder, cosine
from animedex.ideate.context import Context, jaccard, profile_set


@dataclass
class GateResult:
    structural_max: float = 0.0
    procedural_max: float = 0.0
    cosine_max: float = 0.0
    nearest: str | None = None
    novel_combo: bool = False
    novelty_basis: str = ""
    graveyard_hits: list[str] = field(default_factory=list)
    execution_matches: list[str] = field(default_factory=list)
    clone: bool = False
    failures: list[str] = field(default_factory=list)   # rework-able
    fatal: list[str] = field(default_factory=list)      # reject


def idea_struct(card: dict[str, Any]) -> set[str]:
    return profile_set(card["profile"]) | {f"bridge:{b}" for b in card.get("bridge", [])}


def title_texts(ctx: Context) -> dict[str, str]:
    out = {}
    for tid, rec in ctx.titles.items():
        core = rec.get("core") or {}
        parts = [(core.get(k) or {}).get("value") for k in ("logline_hook", "premise_engine", "core_question")]
        out[tid] = ". ".join(p for p in parts if p)
    return out


class Similarity:
    """Premise cosine against every title, with title vectors embedded once per run."""

    def __init__(self, embedder: Embedder, ctx: Context):
        self.embedder = embedder
        texts = title_texts(ctx)
        self.ids = sorted(t for t, text in texts.items() if text)
        vectors = embedder.embed([texts[t] for t in self.ids]) if self.ids else []
        self.vectors = dict(zip(self.ids, vectors, strict=True))

    def max_cosine(self, card: dict[str, Any]) -> tuple[float, str | None]:
        if not self.vectors:
            return 0.0, None
        [v] = self.embedder.embed([f"{card['logline']} {card['premise']}"])
        best = max(((cosine(v, w), t) for t, w in self.vectors.items()), default=(0.0, None))
        return round(best[0], 6), best[1]


def run_gates(card: dict[str, Any], ctx: Context, sim: Similarity, gates_cfg: dict[str, Any]) -> GateResult:
    r = GateResult()
    mine, proc = idea_struct(card), profile_set(card["profile"], ("gate", "cost_of_power", "progression",
                                                                  "visible_counter"))
    for tid in sorted(ctx.titles):
        s, p = jaccard(mine, ctx.title_struct[tid]), jaccard(proc, ctx.title_proc[tid])
        if s > r.structural_max:
            r.structural_max, r.nearest = round(s, 6), tid
        r.procedural_max = max(r.procedural_max, round(p, 6))
    r.cosine_max, _ = sim.max_cosine(card)
    s_rej = float(gates_cfg.get("structural_jaccard_reject", 0.70))
    p_rej = float(gates_cfg.get("procedural_jaccard_reject", 0.75))
    c_rej = float(gates_cfg.get("premise_cosine_reject", 0.90))
    c_with = float(gates_cfg.get("premise_cosine_with_structural", 0.55))
    if r.structural_max >= s_rej:
        r.failures.append(f"clone: structural overlap {r.structural_max:.2f} with {r.nearest} (limit {s_rej})")
    if r.procedural_max >= p_rej:
        r.failures.append(f"clone: procedural overlap {r.procedural_max:.2f} (limit {p_rej})")
    if r.cosine_max >= c_rej and r.structural_max >= c_with:
        r.failures.append(f"clone: premise similarity {r.cosine_max:.2f} with structural overlap {r.structural_max:.2f}")
    r.clone = bool(r.failures)
    # novelty
    enums = sorted(profile_set(card["profile"]))
    zero = [p for p in combinations(enums, 2) if ctx.pair_counts.get(tuple(sorted(p)), 0) == 0]
    if zero and ctx.adequate:
        r.novel_combo, r.novelty_basis = True, f"never together: {zero[0][0]} + {zero[0][1]}"
    else:
        concepts = sorted(set(card.get("bridge", [])))
        fresh = [p for p in combinations(concepts, 2) if tuple(sorted(p)) not in ctx.concept_pairs]
        if fresh and len({a['title_id'] for a in card.get('_atoms', [])}) >= 2:
            r.novel_combo, r.novelty_basis = True, f"patterns never combined in one title: {fresh[0][0]} + {fresh[0][1]}"
    if not r.novel_combo:
        r.fatal.append("novelty: no untried pair (thin coverage makes empty cells untrustworthy)")
    # graveyard (premise-level flops warn; execution-level are T5 evidence)
    for g in ctx.graveyard:
        flop = set(g["structural"]) | {f"bridge:{b}" for b in g["bridge"]}
        key = {e for e in g["structural"] if e.startswith(("power_combat.gate=", "power_combat.cost_of_power="))}
        if key and key <= mine and jaccard(mine, flop) >= 0.5:
            (r.graveyard_hits if g["warns"] else r.execution_matches).append(g["title_id"])
    if r.graveyard_hits and not (card.get("why_different") or "").strip():
        r.failures.append(f"graveyard: matches premise-level flop(s) {r.graveyard_hits}; say why this time is different")
    return r
