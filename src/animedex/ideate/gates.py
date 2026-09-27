"""Deterministic IDEATE gates (05, 06), in order:

1. Clone: structural Jaccard >= structural_jaccard_reject, procedural Jaccard >= procedural_jaccard_reject,
   or (premise cosine >= premise_cosine_reject and structural >= premise_cosine_with_structural)
   -> rework once, then reject.
2. Novelty (statistics as gates, item 4: PMI replaced "unseen pair"): the card's key pair is the pair
   of its profile values (enum) or of its bridge concepts (atoms from 2+ titles) with the lowest PMI on
   an adequate subset. It is novel when it co-occurs at most half as often as chance (PMI <= -1.0,
   D-021) over more than 150 rows that could show it (rule of three, 3/n < 0.02) -> else reject.
   Enum rows are the corpus titles plus, once the census holds `ideate.census_novelty_min_rows` (200)
   powered rows, the census rows (owner ruling 2026-09-27); bridge rows are the corpus titles. Fields
   the agreement eval flagged unreliable never form a pair. The key pair and its PMI are recorded
   on the card (`gates.pmi_key_pair`).
3. Graveyard: a match with a PREMISE-level flop combination needs "why this time is different",
   else rework once, then reject. Execution-level matches are T5 evidence, not warnings (v1.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from animedex.embeddings.base import Embedder, cosine
from animedex.ideate.context import Context, jaccard, profile_set
from animedex.statgates import describe_pair, key_pair


@dataclass
class GateResult:
    structural_max: float = 0.0
    procedural_max: float = 0.0
    cosine_max: float = 0.0
    nearest: str | None = None          # highest structural Jaccard (ties: lowest id)
    cosine_nearest: str | None = None   # highest premise cosine
    novel_combo: bool = False
    novelty_basis: str = ""
    pmi_key_pair: dict[str, Any] | None = None   # the pair novelty judged (basis, pair, PMI, n, adequate, novel)
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
    r.cosine_max, r.cosine_nearest = sim.max_cosine(card)
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
    novelty(card, ctx, r)  # PMI of the key pair on an adequate subset (statistics as gates, item 4)
    # graveyard (premise-level flops warn; execution-level are T5 evidence)
    for g in ctx.graveyard:
        flop = set(g["structural"]) | {f"bridge:{b}" for b in g["bridge"]}
        key = {e for e in g["structural"] if e.startswith(("power_combat.gate=", "power_combat.cost_of_power="))}
        if key and key <= mine and jaccard(mine, flop) >= 0.5:
            (r.graveyard_hits if g["warns"] else r.execution_matches).append(g["title_id"])
    if r.graveyard_hits and not (card.get("why_different") or "").strip():
        r.failures.append(f"graveyard: matches premise-level flop(s) {r.graveyard_hits}; say why this time is different")
    return r


def novelty(card: dict[str, Any], ctx: Context, r: GateResult) -> None:
    """Statistics as gates, item 4: the card's key pair must co-occur at most half as often as chance
    (PMI <= -1.0) over an adequate subset (rule of three). Unreliable fields never form a pair."""
    enums = [e for e in profile_set(card["profile"]) if e.split("=", 1)[0] not in ctx.unreliable]
    two_titles = len({a["title_id"] for a in card.get("_atoms", [])}) >= 2
    keys = {"enum": key_pair(ctx.enum_rows(), enums),
            "bridge": key_pair(ctx.concept_rows(), [f"bridge:{b}" for b in card.get("bridge", [])]) if two_titles
            else None}
    measured = [(basis, k) for basis, k in keys.items() if k]
    novel = [(basis, k) for basis, k in measured if k["novel"]]
    if novel:
        basis, k = novel[0]
        r.novel_combo, r.pmi_key_pair = True, {"basis": basis, **k}
        what = "profile values" if basis == "enum" else "patterns from 2+ titles"
        r.novelty_basis = f"{what} rarer together than chance: {describe_pair(k)}"
        return
    if measured:
        basis, k = min(measured, key=lambda bk: (not bk[1]["adequate"], bk[1]["pmi"]))
        r.pmi_key_pair = {"basis": basis, **k}
        found = f"key pair {describe_pair(k)}"
    else:
        found = "no pair to measure"
    why = [found, "a novel pair needs PMI <= -1 over more than 150 rows (rule of three)"]
    if not ctx.census_zeros_trusted:
        why.append(f"census-backed pairs need {ctx.census_novelty_min_rows} powered census rows "
                   f"(have {ctx.powered_census})")
    if not two_titles:
        why.append("bridge pairs need atoms from 2+ titles")
    r.fatal.append("novelty: no pair rarer than chance on an adequate sample (" + "; ".join(why) + ")")
