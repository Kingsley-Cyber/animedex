"""IDEATE model calls: generate (one card), judge (a batch), prior art (a batch of absence claims).

Each builds a strict JSON schema (valid for claude and codex structured output), renders the user
prompt from canonical context, and validates the answer so LLMClient can spend its one repair.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from animedex.ideate.context import PROFILE_PATHS, Context
from animedex.integrity import name_leaks
from animedex.models import IdeaCard
from animedex.ontology import Vocab
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
def generate_schema(vocab: Vocab, transfer_ids: list[str], title_ids: list[str], flop_ids: list[str]) -> dict[str, Any]:
    profile = _obj({k: {"type": "string", "enum": [v for v in vocab.enum(path)]} for k, path in PROFILE_PATHS.items()})
    props: dict[str, Any] = {
        "logline": TEXT, "premise": TEXT, "engine": _obj({k: TEXT for k in ENGINE}), "what_changed": TEXT,
        "source_transfer_ids": {"type": "array", "items": {"type": "string", "enum": transfer_ids}},
        "consequences": _obj({"choices": TEXT, "relationships": TEXT, "outcomes": TEXT}), "profile": profile,
        "broken_rule": TEXT, "appetite": TEXT, "closest_existing": {"type": "string", "enum": title_ids},
        "why_not_a_clone": TEXT, "why_different": MAYBE, "revival_improvement": MAYBE,
    }
    if flop_ids:
        props["premortem"] = {"type": "array", "items": _obj({"risk": TEXT, "source_title_id": {"type": "string",
                              "enum": flop_ids}, "mitigation": TEXT})}
    return _obj(props)


def _pattern_line(t: dict[str, Any]) -> str:
    return (f"- {t['transfer_id']}: {t['pattern']} | bridge: {', '.join(t['bridge'])} | essential: "
            f"{'; '.join(t['essential_conditions'])} | variable: {'; '.join(t['variable_details'])} | "
            f"failure: {'; '.join(t['failure_conditions'])}")


def generate_user(ctx: Context, *, theme: str, operator: str, target: dict[str, str], atoms: list[dict[str, Any]],
                  revival: dict[str, Any] | None = None, borrowed: str | None = None,
                  rework: list[str] | None = None) -> str:
    lines = [f"THEME ROOT: {theme}", f"OPERATOR: {operator}: {OPERATORS[operator]}",
             "TARGET PROFILE: " + ", ".join(f"{k}={v}" for k, v in target.items()), "", "PATTERNS (use every one):",
             *map(_pattern_line, atoms)]
    if revival:
        lines += ["", f"FLOP TO REVIVE: {revival['title_id']} (execution-level failure). Recorded failure: "
                      f"{revival.get('failure_reason') or 'not stated'}"]
    if borrowed:
        lines += ["", f"BORROWED SYSTEM: {borrowed} (no census title uses it as a power system)"]
    lines += ["", "CORPUS TITLES (closest_existing must be one of these ids):"]
    for tid in sorted(ctx.titles):
        hook = ((ctx.titles[tid].get("core") or {}).get("logline_hook") or {}).get("value") or ""
        lines.append(f"- {tid}: {ctx.titles[tid]['title']} ({ctx.titles[tid]['medium']}): {hook}")
    flops = [g for g in ctx.graveyard]
    if flops:
        lines += ["", "MIXED AND FLOP TITLES (premortem sources):"]
        lines += [f"- {g['title_id']}: {g['label']}; failure ({g['failure_level']}): {g['failure_reason'] or 'not stated'}"
                  for g in flops]
    if rework:
        lines += ["", "REWORK: the previous version failed these checks; fix them:", *[f"- {r}" for r in rework]]
    return "\n".join(lines)


def card_from(out: dict[str, Any], *, idea_id: str, atoms: list[dict[str, Any]], operator: str, theme: str,
              grid_cell: str, generation: int, prov: dict[str, Any], revival: dict[str, Any] | None) -> dict[str, Any]:
    """The model's answer as a full IdeaCard draft (gates, taste, status are filled later)."""
    card = {
        "idea_id": idea_id, "target_domain": "anime", "logline": out.get("logline"), "premise": out.get("premise"),
        "theme_root": theme, "engine": {k: (out.get("engine") or {}).get(k) for k in ENGINE},
        "transformation": {"operator": operator, "source_transfer_ids": list(out.get("source_transfer_ids") or []),
                           "what_changed": out.get("what_changed")},
        "consequences": {k: (out.get("consequences") or {}).get(k) for k in ("choices", "relationships", "outcomes")},
        "profile": dict(out.get("profile") or {}), "bridge": sorted({b for a in atoms for b in a["bridge"]}),
        "grid_cell": grid_cell, "atoms_used": [a["transfer_id"] for a in atoms],
        "borrowed_from": sorted({a["title_id"] for a in atoms}), "broken_rule": out.get("broken_rule") or "",
        "appetite": out.get("appetite") or "", "closest_existing": out.get("closest_existing"),
        "why_not_a_clone": out.get("why_not_a_clone"), "why_different": out.get("why_different") or None,
        "premortem": list(out.get("premortem") or []),
        "revival_of": ({"title_id": revival["title_id"], "failure_evidence_ref": revival.get("failure_evidence_ref"),
                        "improvement": out.get("revival_improvement")} if revival else None),
        "runway": None,
        "gates": {"structural_jaccard_max": 0.0, "procedural_jaccard_max": 0.0, "premise_cosine_max": 0.0,
                  "novel_combo": False, "graveyard_hits": [], "failure_conditions_triggered": [],
                  "consequence_test": {"choices": False, "relationships": False, "outcomes": False, "h1_pass": False},
                  "coherence": "fail"},
        "taste": {"criteria_met": [], "evidence": {}, "hard_fail": False}, "status": "candidate",
        "generation": generation, "parent_ids": [], "human_rating": None, "provenance": prov,
    }
    return card


def generate_problems(out: dict[str, Any], ctx: Context, atoms: list[dict[str, Any]], operator: str,
                      grid_cell: str, prov: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    given = sorted(a["transfer_id"] for a in atoms)
    if sorted(out.get("source_transfer_ids") or []) != given:
        problems.append(f"source_transfer_ids must list every given pattern: {given}")
    leaks = name_leaks(f"{out.get('logline', '')} {out.get('premise', '')}", *ctx.names)
    if leaks:
        problems.append(f"logline/premise reuse existing names {leaks[:3]}; invent original ones")
    if ctx.graveyard and not 2 <= len(out.get("premortem") or []) <= 3:
        problems.append("give 2-3 premortem items")
    if operator == "revive_execution_flop" and not (out.get("revival_improvement") or "").strip():
        problems.append("revival_improvement: name the improvement mapped to the flop's recorded weakness")
    revival = {"title_id": "placeholder_2000"} if operator == "revive_execution_flop" else None
    draft = card_from(out, idea_id="idea.run_check.001", atoms=atoms, operator=operator, theme="theme",
                      grid_cell=grid_cell, generation=0, prov=prov, revival=revival)
    try:
        IdeaCard.model_validate(draft)
    except ValidationError as exc:
        problems += [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()[:6]]
    return problems


# ---------------------------------------------------------------- judge
def judge_schema(refs: list[str], conditions: list[str]) -> dict[str, Any]:
    cond = {"type": "array", "items": ({"type": "string", "enum": conditions} if conditions else TEXT)}
    item = _obj({"ref": {"type": "string", "enum": refs},
                 **{f"{d}_differs": {"type": "boolean"} for d in ("choices", "relationships", "outcomes")},
                 **{f"{d}_reason": TEXT for d in ("choices", "relationships", "outcomes")},
                 "failure_conditions_triggered": cond, "coherence": {"type": "string", "enum": ["pass", "fail"]},
                 "coherence_reason": TEXT, "runway_hurts_by_arc5": {"type": "boolean"}, "runway_reason": TEXT,
                 "taste": {"type": "array", "items": _obj({"criterion": {"type": "string", "enum": CRITERIA},
                                                           "evidence": TEXT})}})
    return _obj({"cards": {"type": "array", "items": item}})


def judge_card_text(ref: str, card: dict[str, Any], ctx: Context, atoms: list[dict[str, Any]], facts: list[str]) -> str:
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
        "patterns used: " + " | ".join(a["pattern"] for a in atoms),
        "failure conditions of these patterns: " + "; ".join(f for a in atoms for f in a["failure_conditions"]),
        f"closest existing: {card['closest_existing']} ({near.get('medium', '?')}): " + "; ".join(near_lines),
        "supplied facts: " + ("; ".join(facts) or "none"),
    ])


def judge_problems(out: dict[str, Any], refs: list[str]) -> list[str]:
    problems: list[str] = []
    got = [c.get("ref") for c in out.get("cards") or []]
    if sorted(got) != sorted(refs):
        problems.append(f"judge every card exactly once: {refs}")
    for c in out.get("cards") or []:
        for key in ("choices_reason", "relationships_reason", "outcomes_reason", "coherence_reason", "runway_reason"):
            if word_count(str(c.get(key) or "")) > 25:
                problems.append(f"{c.get('ref')}.{key}: 25 words max")
        for t in c.get("taste") or []:
            if word_count(str(t.get("evidence") or "")) > 25 or not str(t.get("evidence") or "").strip():
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
            if x.get("url") not in urls:
                problems.append(f"{c.get('ref')}: cite a URL your searches returned or you opened in this session")
            if word_count(str(x.get("match_note") or "")) > 25:
                problems.append(f"{c.get('ref')}: match_note 25 words max")
    return problems
