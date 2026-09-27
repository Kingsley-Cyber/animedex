"""IDEATE model calls: generate (one card), judge (a batch), prior art (a batch of absence claims).

Each builds a strict JSON schema (valid for claude and codex structured output) and validates the
answer so LLMClient can spend its one repair. The generate call's input is the M5 call brief
(`ideate/brief.py`): atoms arrive under opaque aliases (A1, A2...) and the card maps them back to
real transfer ids.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from animedex.ideate.context import PROFILE_PATHS, Context
from animedex.integrity import name_leaks
from animedex.models import IdeaCard
from animedex.ontology import Vocab
from animedex.pipeline.common import BLOCKED_SOURCE_NOTE, blocked_source, norm_url
from animedex.textutil import word_count

OPERATORS = {
    "reverse_incentive": "What was rewarded becomes costly, or vice versa.",
    "redistribute_knowledge": "Change who knows the secret, or when.",
    "transfer_cost": "The cost lands on someone else.",
    "change_rule": "Alter one world or power rule.",
    "combine_mechanisms": "Join two engines whose consequences interfere.",
    "import_lane": "Bring a pattern from another medium where it is absent.",
    "revive_execution_flop": "Keep an execution-level flop's premise; replace the part that failed with a proven "
                             "engine from the patterns given.",
    "borrow_system": "Borrow a system audiences already know that no title uses as a power system, break one of its "
                     "rules, aim it at an unserved appetite, and make progress visible.",
}
ENGINE = ("goal", "constraint", "strategy", "benefit", "cost", "dilemma", "dramatic_question")
CRITERIA = ["T1", "T2", "T3", "T4", "T5"]


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


TEXT, MAYBE = {"type": "string"}, {"type": ["string", "null"]}


# ---------------------------------------------------------------- generate
PLACEHOLDER_TITLE = "placeholder_2000"  # stands in for a baseline card's closest title until the clone gate measures it


def generate_schema(vocab: Vocab, aliases: list[str], title_ids: list[str] | None, flop_ids: list[str]) -> dict[str, Any]:
    """`aliases`: the brief's atom aliases (A1...); none for baseline 1. `title_ids` None (baseline 1, which
    sees no titles) makes `closest_existing` free text; the clone gate then measures the nearest title."""
    profile = _obj({k: {"type": "string", "enum": [v for v in vocab.enum(path)]} for k, path in PROFILE_PATHS.items()})
    props: dict[str, Any] = {"logline": TEXT, "premise": TEXT, "engine": _obj({k: TEXT for k in ENGINE}),
                             "what_changed": TEXT}
    if aliases:
        props["source_transfer_ids"] = {"type": "array", "items": {"type": "string", "enum": aliases}}
    props.update({
        "consequences": _obj({"choices": TEXT, "relationships": TEXT, "outcomes": TEXT}), "profile": profile,
        "broken_rule": TEXT, "appetite": TEXT,
        "closest_existing": {"type": "string", "enum": title_ids} if title_ids is not None else TEXT,
        "why_not_a_clone": TEXT, "why_different": MAYBE, "revival_improvement": MAYBE,
    })
    if flop_ids:
        props["premortem"] = {"type": "array", "items": _obj({"risk": TEXT, "source_title_id": {"type": "string",
                              "enum": flop_ids}, "mitigation": TEXT})}
    return _obj(props)


def card_from(out: dict[str, Any], *, idea_id: str, atoms: list[dict[str, Any]], operator: str, theme: str,
              grid_cell: str, generation: int, prov: dict[str, Any], revival: dict[str, Any] | None,
              aliases: dict[str, str] | None = None, arm: str = "animedex",
              closest: str | None = None) -> dict[str, Any]:
    """The model's answer as a full IdeaCard draft (gates, taste, status are filled later). Aliases in
    `source_transfer_ids` map back to real transfer ids; `closest` overrides `closest_existing`."""
    named = list(out.get("source_transfer_ids") or [])
    source_ids = [(aliases or {}).get(a, a) for a in named] if aliases is not None else named
    card = {
        "idea_id": idea_id, "target_domain": "anime", "logline": out.get("logline"), "premise": out.get("premise"),
        "theme_root": theme, "engine": {k: (out.get("engine") or {}).get(k) for k in ENGINE},
        "transformation": {"operator": operator, "source_transfer_ids": source_ids,
                           "what_changed": out.get("what_changed")},
        "consequences": {k: (out.get("consequences") or {}).get(k) for k in ("choices", "relationships", "outcomes")},
        "profile": dict(out.get("profile") or {}), "bridge": sorted({b for a in atoms for b in a["bridge"]}),
        "grid_cell": grid_cell, "atoms_used": [a["transfer_id"] for a in atoms],
        "borrowed_from": sorted({a["title_id"] for a in atoms}), "broken_rule": out.get("broken_rule") or "",
        "appetite": out.get("appetite") or "", "closest_existing": closest or out.get("closest_existing"),
        "why_not_a_clone": out.get("why_not_a_clone"), "why_different": out.get("why_different") or None,
        "premortem": list(out.get("premortem") or []),
        "revival_of": ({"title_id": revival["title_id"], "failure_evidence_ref": revival.get("failure_evidence_ref"),
                        "improvement": out.get("revival_improvement")} if revival else None),
        "runway": None,
        "gates": {"structural_jaccard_max": 0.0, "procedural_jaccard_max": 0.0, "premise_cosine_max": 0.0,
                  "novel_combo": False, "graveyard_hits": [], "failure_conditions_triggered": [],
                  "consequence_test": {"choices": False, "relationships": False, "outcomes": False, "h1_pass": False},
                  "coherence": "fail"},
        "taste": {"criteria_met": [], "evidence": {}, "hard_fail": False}, "status": "candidate", "arm": arm,
        "generation": generation, "parent_ids": [], "human_rating": None, "provenance": prov,
    }
    return card


def generate_problems(out: dict[str, Any], ctx: Context, atoms: list[dict[str, Any]], operator: str,
                      grid_cell: str, prov: dict[str, Any], *, aliases: dict[str, str] | None = None,
                      flop_ids: list[str] | None = None, arm: str = "animedex") -> list[str]:
    """`aliases`: the brief's alias map (the model lists aliases, never real ids); `flop_ids`: the
    graveyard rows the brief showed (the pre-mortem's only possible sources)."""
    problems: list[str] = []
    given = sorted(aliases) if aliases is not None else sorted(a["transfer_id"] for a in atoms)
    if sorted(out.get("source_transfer_ids") or []) != given:
        problems.append(f"source_transfer_ids must list every given pattern: {given}")
    leaks = name_leaks(f"{out.get('logline', '')} {out.get('premise', '')}", *ctx.names)
    if leaks:
        problems.append(f"logline/premise reuse existing names {leaks[:3]}; invent original ones")
    shown = flop_ids if flop_ids is not None else [g["title_id"] for g in ctx.graveyard]
    if shown and not 2 <= len(out.get("premortem") or []) <= 3:
        problems.append("give 2-3 premortem items")
    if operator == "revive_execution_flop" and not (out.get("revival_improvement") or "").strip():
        problems.append("revival_improvement: name the improvement mapped to the flop's recorded weakness")
    revival = {"title_id": PLACEHOLDER_TITLE} if operator == "revive_execution_flop" else None
    draft = card_from(out, idea_id="idea.run_check.001", atoms=atoms, operator=operator, theme="theme",
                      grid_cell=grid_cell, generation=0, prov=prov, revival=revival, aliases=aliases, arm=arm,
                      closest=PLACEHOLDER_TITLE if arm != "animedex" else None)
    try:
        IdeaCard.model_validate(draft)
    except ValidationError as exc:
        problems += [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()[:6]]
    return problems


# ---------------------------------------------------------------- judge
WHY_DIFFERENT = ["pass", "fail", "not_applicable"]


def judge_schema(refs: list[str], conditions: list[str]) -> dict[str, Any]:
    cond = {"type": "array", "items": ({"type": "string", "enum": conditions} if conditions else TEXT)}
    item = _obj({"ref": {"type": "string", "enum": refs},
                 **{f"{d}_differs": {"type": "boolean"} for d in ("choices", "relationships", "outcomes")},
                 **{f"{d}_reason": TEXT for d in ("choices", "relationships", "outcomes")},
                 "failure_conditions_triggered": cond, "coherence": {"type": "string", "enum": ["pass", "fail"]},
                 "coherence_reason": TEXT, "runway_hurts_by_arc5": {"type": "boolean"}, "runway_reason": TEXT,
                 # M5 ruling: on a premise-level graveyard match, why_different is judged, not just present
                 "why_different_verdict": {"type": "string", "enum": WHY_DIFFERENT}, "why_different_reason": TEXT,
                 "taste": {"type": "array", "items": _obj({"criterion": {"type": "string", "enum": CRITERIA},
                                                           "evidence": TEXT})}})
    return _obj({"cards": {"type": "array", "items": item}})


def graveyard_match_lines(card: dict[str, Any], matches: list[dict[str, Any]]) -> list[str]:
    """What the judge weighs why_different against: each matched premise-level flop's recorded failure."""
    if not matches:
        return ["graveyard match: none (answer why_different not_applicable)"]
    lines = [f"graveyard match {g['title_id']}: {g['label']}; recorded failure ({g['failure_level']}): "
             f"{g.get('failure_reason') or 'not stated'}" for g in matches]
    return [*lines, f"why_different: {card.get('why_different') or '(blank)'}"]


def judge_card_text(ref: str, card: dict[str, Any], ctx: Context, atoms: list[dict[str, Any]], facts: list[str],
                    matches: list[dict[str, Any]] | None = None) -> str:
    near = ctx.titles.get(card["closest_existing"]) or {}
    core = near.get("core") or {}
    near_lines = [f"{k}: {(core.get(k) or {}).get('value')}" for k in ("logline_hook", "premise_engine", "primary_feeling")]
    near_lines += [f"{p}: {((near.get(p.split('.')[0]) or {}).get(p.split('.')[1]) or {}).get('value')}"
                   for p in PROFILE_PATHS.values()]
    e, c = card["engine"], card["consequences"]
    return "\n".join([
        f"=== CARD {ref}", f"logline: {card['logline']}", f"premise: {card['premise']}",
        f"theme: {card['theme_root']}", f"operator: {card['transformation']['operator']}; what changed: "
        f"{card['transformation']['what_changed']}",
        "engine: " + "; ".join(f"{k} {e[k]}" for k in ENGINE),
        f"consequences: choices {c['choices']}; relationships {c['relationships']}; outcomes {c['outcomes']}",
        "profile: " + ", ".join(f"{k}={v}" for k, v in card["profile"].items()),
        "patterns used: " + (" | ".join(a["pattern"] for a in atoms) or "none"),
        "failure conditions of these patterns: " + ("; ".join(f for a in atoms for f in a["failure_conditions"])
                                                    or "none"),
        f"closest existing: {card['closest_existing']} ({near.get('medium', '?')}): " + "; ".join(near_lines),
        *graveyard_match_lines(card, list(matches or [])),
        "supplied facts: " + ("; ".join(facts) or "none"),
    ])


def judge_problems(out: dict[str, Any], refs: list[str], matched: list[str] | tuple[str, ...] = ()) -> list[str]:
    """`matched`: refs whose card matches a premise-level flop; each needs a pass or fail on why_different."""
    problems: list[str] = []
    got = [c.get("ref") for c in out.get("cards") or []]
    if sorted(got) != sorted(refs):
        problems.append(f"judge every card exactly once: {refs}")
    for i, c in enumerate(out.get("cards") or []):
        # "cards[i].key: N words exceeds the 25-word limit" names the text by its path, so the client's
        # length repair can shorten just that text (D-030)
        for key in ("choices_reason", "relationships_reason", "outcomes_reason", "coherence_reason", "runway_reason",
                    "why_different_reason"):
            if (n := word_count(str(c.get(key) or ""))) > 25:
                problems.append(f"cards[{i}].{key}: {n} words exceeds the 25-word limit")
        if c.get("ref") in matched:
            if c.get("why_different_verdict") not in ("pass", "fail"):
                problems.append(f"{c.get('ref')}: it matches a premise-level flop; judge why_different pass or fail")
            elif not str(c.get("why_different_reason") or "").strip():
                problems.append(f"{c.get('ref')}.why_different_reason: give the reason (1-25 words)")
        for j, t in enumerate(c.get("taste") or []):
            if (n := word_count(str(t.get("evidence") or ""))) > 25:
                problems.append(f"cards[{i}].taste[{j}].evidence: {n} words exceeds the 25-word limit")
            elif not str(t.get("evidence") or "").strip():
                problems.append(f"{c.get('ref')}.taste {t.get('criterion')}: evidence of 1-25 words")
    return problems


# ---------------------------------------------------------------- prior art (v1.6)
def prior_art_schema(refs: list[str]) -> dict[str, Any]:
    ce = _obj({"title": TEXT, "url": TEXT, "match_note": TEXT})
    item = _obj({"ref": {"type": "string", "enum": refs}, "verdict": {"type": "string", "enum": [
        "clear", "counterexample", "inconclusive"]}, "counterexamples": {"type": "array", "items": ce}})
    return _obj({"checks": {"type": "array", "items": item}})


def prior_art_problems(out: dict[str, Any], refs: list[str], urls: set[str]) -> list[str]:
    problems: list[str] = []
    got = [c.get("ref") for c in out.get("checks") or []]
    if sorted(got) != sorted(refs):
        problems.append(f"check every claim exactly once: {refs}")
    for c in out.get("checks") or []:
        if c.get("verdict") == "counterexample" and not c.get("counterexamples"):
            problems.append(f"{c.get('ref')}: a counterexample verdict needs the title and page")
        for x in c.get("counterexamples") or []:
            if blocked_source(x.get("url")):
                problems.append(f"{c.get('ref')}: {BLOCKED_SOURCE_NOTE}; cite another page")
            elif norm_url(x.get("url")) not in urls:
                problems.append(f"{c.get('ref')}: cite a URL your searches returned or you opened in this session")
            if word_count(str(x.get("match_note") or "")) > 25:
                problems.append(f"{c.get('ref')}: match_note 25 words max")
    return problems
