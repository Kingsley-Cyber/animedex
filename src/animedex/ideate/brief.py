"""The M5 call brief (owner ruling 2026-09-27, "before M5" item 4; CHANGE_PLAN_ideation_modes §4).

Each generate call gets a small assembled brief instead of every title and every flop:
- the theme root, the operator and the target cell;
- the plan's atoms under opaque aliases A1, A2... (no source title, no transfer id); the card maps
  the aliases back to the real transfer ids;
- the nearest `ideate.brief_titles` (10) titles to the target, by the clone gate's structural
  Jaccard between the target profile + the atoms' bridge concepts and each title's structural set
  (ties by id). `closest_existing` may still be any corpus id;
- the graveyard rows in the target region: mixed/flop titles whose structural set overlaps the
  target set, most overlap first, up to `ideate.brief_graveyard_max`. When none overlaps, the first
  two rows by id stand in (marked `graveyard_region: fallback` in the call meta), so the pre-mortem
  still has sources (AC-46);
- the cell's counts (corpus titles, census rows; counts only, AC-44) and whether zeros are
  trusted, the lane concepts among the atoms' bridges, and the prior-art verdicts already recorded
  for earlier cards in the cell;
- every steering rule (the same lines every arm gets) and, on a retry, the rework notes.

Lines are compact `key: value` text, not Markdown. The brief is capped at `ideate.brief_max_words`
(600): optional lines are trimmed first (farthest titles, then extra flops, prior art, lanes, the
last flop); a brief whose required lines alone pass the cap is refused before any call. Its size
(words and an estimated token count, chars / 4) goes into the run log's call meta.

`index=False` is baseline 1 (controls decision 1): the same loop with an empty brief. It keeps the
theme, operator, target, steering rules and rework notes (title ids redacted) and drops every piece
of index material: atoms, titles, flops, cell counts, lanes, prior art.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from animedex.config import Settings
from animedex.ideate.context import Context, cell_key, jaccard, profile_set
from animedex.ideate.llm import OPERATORS
from animedex.ideate.steering import Rule, rule_lines
from animedex.textutil import word_count

FALLBACK_FLOPS = 2


class BriefOverCap(ValueError):
    """The required lines alone exceed `ideate.brief_max_words`: no call is made."""


@dataclass
class Brief:
    text: str
    aliases: dict[str, str] = field(default_factory=dict)   # "A1" -> transfer_id
    title_ids: list[str] = field(default_factory=list)      # titles shown
    flop_ids: list[str] = field(default_factory=list)       # graveyard rows shown (pre-mortem sources)
    meta: dict[str, Any] = field(default_factory=dict)      # logged with the call

    def transfer_ids(self, aliases: list[str]) -> list[str]:
        return [self.aliases[a] for a in aliases if a in self.aliases]


def est_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def target_set(target: dict[str, str], atoms: list[dict[str, Any]]) -> set[str]:
    return profile_set(target) | {f"bridge:{b}" for a in atoms for b in a["bridge"]}


def nearest_titles(ctx: Context, tset: set[str], n: int) -> list[str]:
    ranked = sorted(ctx.titles, key=lambda t: (-jaccard(tset, ctx.title_struct.get(t, set())), t))
    return ranked[:n]


def region_graveyard(ctx: Context, tset: set[str], n: int) -> tuple[list[dict[str, Any]], str]:
    scored = [(jaccard(tset, set(g["structural"]) | {f"bridge:{b}" for b in g["bridge"]}), g) for g in ctx.graveyard]
    region = [g for s, g in sorted(scored, key=lambda x: (-x[0], x[1]["title_id"])) if s > 0][:n]
    if region:
        return region, "overlap"
    if not ctx.graveyard:
        return [], "none"
    return sorted(ctx.graveyard, key=lambda g: g["title_id"])[:min(n, FALLBACK_FLOPS)], "fallback"


def _atom_line(alias: str, t: dict[str, Any]) -> str:
    return (f"atom {alias}: {t['pattern']} | bridge: {', '.join(t['bridge'])} | essential: "
            f"{'; '.join(t['essential_conditions'])} | variable: {'; '.join(t['variable_details'])} | "
            f"failure: {'; '.join(t['failure_conditions'])}")


def title_line(ctx: Context, tid: str) -> str:
    rec = ctx.titles[tid]
    hook = ((rec.get("core") or {}).get("logline_hook") or {}).get("value") or "no logline recorded"
    return f"title {tid}: {rec['medium']}; {hook}"


def flop_line(g: dict[str, Any]) -> str:
    return f"flop {g['title_id']}: {g['label']}; failure ({g['failure_level']}): {g['failure_reason'] or 'not stated'}"


def _cell_line(ctx: Context, key: str) -> str:
    trusted = ctx.adequate and ctx.census_zeros_trusted
    return (f"cell: corpus titles {ctx.cell_titles.get(key, 0)}; census titles {ctx.cell_census.get(key, 0)}; "
            f"zeros {'trusted' if trusted else 'untrusted'} (census powered rows {ctx.powered_census} of "
            f"{ctx.census_novelty_min_rows} needed)")


def _lane_line(ctx: Context, atoms: list[dict[str, Any]]) -> str:
    concepts = sorted({b for a in atoms for b in a["bridge"]})
    imported = [c for c in concepts if c in ctx.lanes["imported"]]
    export = [c for c in concepts if c in ctx.lanes["export"]]
    return f"lanes: imported {', '.join(imported) or 'none'}; export {', '.join(export) or 'none'}"


def _prior_art_lines(ctx: Context, key: str, limit: int = 3) -> list[str]:
    out = []
    for pa in (ctx.prior_art_by_cell.get(key) or [])[-limit:]:
        seen = "; ".join(f"{x['title']} ({x['match_note']})" for x in (pa.get("counterexamples") or [])[:2])
        out.append(f"prior_art: {pa['claim_kind']} {pa['verdict']}" + (f"; done before: {seen}" if seen else ""))
    return out


def redact_titles(text: str, ctx: Context) -> str:
    """Baseline 1's rework notes carry no title ids (an empty brief stays empty)."""
    ids = sorted(set(ctx.titles) | {g["title_id"] for g in ctx.graveyard}, key=len, reverse=True)
    if not ids:
        return text
    return re.sub("|".join(re.escape(i) for i in ids), "an existing title", text)


def build_brief(ctx: Context, settings: Settings, *, theme: str, operator: str, target: dict[str, str],
                atoms: list[dict[str, Any]], revival: dict[str, Any] | None = None, borrowed: str | None = None,
                rules: list[Rule] | tuple[Rule, ...] = (), rework: list[str] | None = None,
                index: bool = True) -> Brief:
    cfg = settings.ideate
    cap = int(cfg.get("brief_max_words", 600))
    dims = list(cfg.get("grid_dims") or [])
    head = [f"theme: {theme}", f"operator: {operator}: {OPERATORS[operator]}",
            "target: " + ", ".join(f"{k}={v}" for k, v in target.items())]
    aliases: dict[str, str] = {}
    titles: list[str] = []
    flops: list[dict[str, Any]] = []
    prior: list[str] = []
    lanes: list[str] = []
    region = "none"
    if index:
        aliases = {f"A{i}": a["transfer_id"] for i, a in enumerate(atoms, start=1)}
        head += [_atom_line(alias, a) for alias, a in zip(aliases, atoms, strict=True)]
        if revival:
            head.append(f"revive: {revival['title_id']} (execution-level failure); recorded failure: "
                        f"{revival.get('failure_reason') or 'not stated'}")
        if borrowed:
            head.append(f"borrowed_system: {borrowed} (no census title uses it as a power system)")
        key = cell_key(target, dims)
        head.append(_cell_line(ctx, key))
        tset = target_set(target, atoms)
        titles = nearest_titles(ctx, tset, int(cfg.get("brief_titles", 10)))
        flops, region = region_graveyard(ctx, tset, int(cfg.get("brief_graveyard_max", 5)))
        prior = _prior_art_lines(ctx, key)
        lanes = [_lane_line(ctx, atoms)] if atoms else []
    else:
        head.append("patterns: none given")
        rework = [redact_titles(r, ctx) for r in rework or []]
    tail = [*rule_lines(list(rules)), *[f"rework: {r}" for r in rework or []]]

    def render() -> str:
        return "\n".join([*head, *lanes, *prior, *(title_line(ctx, t) for t in titles), *map(flop_line, flops),
                          *tail])

    trimmed = 0
    text = render()
    while word_count(text) > cap:
        if titles:
            titles.pop()
        elif len(flops) > 1:
            flops.pop()
        elif prior:
            prior.pop()
        elif lanes:
            lanes.pop()
        elif flops:
            flops.pop()
        else:
            raise BriefOverCap(f"brief: the required lines alone are {word_count(text)} words (cap {cap})")
        trimmed += 1
        text = render()
    meta = {"words": word_count(text), "est_tokens": est_tokens(text), "cap_words": cap, "index": index,
            "atoms": len(aliases), "titles": len(titles), "flops": len(flops), "graveyard_region": region,
            "rules": len(rules), "trimmed_lines": trimmed}
    return Brief(text=text, aliases=aliases, title_ids=list(titles), flop_ids=[g["title_id"] for g in flops],
                 meta=meta)
