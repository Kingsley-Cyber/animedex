"""`make diagnose TEXT="..."` on the light path (owner instruction 2026-09-27, item 4; D-054).

The notes index is the comparison set and steering/rules.yaml gives the constraints. Three calls under
`diagnose.calls_per_run`: structure (slot `ideate_generate`, `diagnose_structure.md`), the judge (slot
`ideate_judge`, `diagnose_judge.md`: the consequence test against the closest note, coherence, runway,
why_different on a graveyard match, every steering rule) and the ablation pass (`diagnose_ablation.md`).
Checks, one line each with a prescription for a failure: structure, clone (the five tracked enums and the
premise's similarity to the notes; set_structure and power_is are not tracked), novelty (enum pairs no note
holds), graveyard (flop or mixed notes sharing three of the five tracked enums), name leak, H1, coherence,
runway, why different, each steering rule (a hard rule fails the concept, a soft one warns), ablation.
Output: data/diagnose/<id>.json and .md (private).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from animedex.config import Settings
from animedex.embeddings.base import Embedder
from animedex.gold import masked_titles
from animedex.guards import load_corpus
from animedex.ideate.diagnose import (
    PRESCRIPTIONS,
    Check,
    DiagnoseError,
    DiagnoseResult,
    _call,
    ablation_check,
    ablation_parts,
    ablation_problems,
    ablation_schema,
    ablation_user,
    card_draft,
    diagnose_id,
    render_md,
    structure_problems,
    structure_schema,
)
from animedex.ideate.llm import ENGINE, OPERATORS, TEXT, _obj
from animedex.ideate.report import Masker
from animedex.ideate.steering import Rule, load_rules, rule_lines
from animedex.integrity import name_leaks
from animedex.light.notes import note_lines, note_titles, read_notes
from animedex.models.diagnose import DiagnoseCard
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import provenance, raise_problems
from animedex.prompts import read_prompt
from animedex.providers.client import LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.textutil import word_count

TRACKED = ("gate", "cost_of_power", "progression", "visible_counter", "fight_medium")
NOT_TRACKED = ("set_structure", "power_is")
PAIRS = (("gate", "cost_of_power"), ("progression", "visible_counter"), ("fight_medium", "cost_of_power"))
MIN_NOTES_FOR_NOVELTY = 10
LIGHT_PRESCRIPTIONS = {
    **PRESCRIPTIONS,
    "steering_hard": ("rung", "MC", "Make the lead legibly the strongest through the medium or a cost nobody else pays, "
                                    "not the biggest number."),
    "steering_soft": ("rung", "kit", "Derive the affinity from a domain of meaning bound to a host, and build the premise "
                                     "out from the fight."),
}


def prescription(failure: str) -> str:
    kind, target, advice = LIGHT_PRESCRIPTIONS[failure]
    if kind == "operator":
        return f"operator {target} ({OPERATORS[target].rstrip('.').lower()}): {advice}"
    return f"ladder rung '{target}': {advice}"


# ---------------------------------------------------------------- the notes as the comparison set
def tracked_set(profile: dict[str, Any]) -> set[str]:
    return {f"{k}={profile.get(k)}" for k in TRACKED if profile.get(k) and not str(profile[k]).startswith("other")}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def clone_numbers(card: dict[str, Any], notes: dict[str, dict[str, Any]], embedder: Embedder | None
                  ) -> dict[str, Any]:
    mine = tracked_set(card["profile"])
    struct = max(((jaccard(mine, tracked_set(n)), slug) for slug, n in notes.items()), default=(0.0, None))
    cos: tuple[float, str | None] = (0.0, None)
    if embedder is not None and notes:
        slugs = sorted(notes)
        vectors = embedder.embed([f"{notes[s].get('title')}: {notes[s].get('premise')}" for s in slugs])
        [mine_v] = embedder.embed([f"{card['logline']} {card['premise']}"])
        cos = max(((_cosine(mine_v, v), s) for s, v in zip(slugs, vectors, strict=True)), default=(0.0, None))
    return {"structural_jaccard_max": round(struct[0], 4), "nearest": struct[1],
            "premise_cosine_max": round(cos[0], 4), "nearest_premise": cos[1]}


def clone_check(numbers: dict[str, Any], gates_cfg: dict[str, Any], m: Masker) -> Check:
    struct, cos = numbers["structural_jaccard_max"], numbers["premise_cosine_max"]
    why = (f"tracked-enum overlap {struct:.2f} (nearest {m.title(numbers['nearest']) or 'none'}), premise similarity "
           f"{cos:.2f} (nearest {m.title(numbers['nearest_premise']) or 'none'}); {', '.join(NOT_TRACKED)}: not tracked "
           "in the notes")
    if struct >= float(gates_cfg.get("structural_jaccard_reject", 0.70)):
        return Check("clone", False, why, "clone_structural")
    if cos >= float(gates_cfg.get("premise_cosine_reject", 0.72)) or (
            cos >= float(gates_cfg.get("premise_cosine_with_structural", 0.55)) and struct >= 0.5):
        return Check("clone", False, why, "clone_premise")
    return Check("clone", True, why)


def novelty_check(card: dict[str, Any], notes: dict[str, dict[str, Any]]) -> Check:
    if len(notes) < MIN_NOTES_FOR_NOVELTY:
        return Check("novelty", None, f"not tracked: {len(notes)} note(s), fewer than {MIN_NOTES_FOR_NOVELTY}")
    p = card["profile"]
    seen: list[str] = []
    for x, y in PAIRS:
        vx, vy = p.get(x), p.get(y)
        if not vx or not vy or str(vx).startswith("other") or str(vy).startswith("other"):
            continue
        n = sum(1 for note in notes.values() if note.get(x) == vx and note.get(y) == vy)
        if n == 0:
            return Check("novelty", True, f"no note pairs {x}={vx} with {y}={vy} ({len(notes)} notes)")
        seen.append(f"{x}={vx}+{y}={vy} in {n}")
    return Check("novelty", False, "every tracked pair appears in the notes: " + "; ".join(seen), "novelty")


def graveyard_matches(card: dict[str, Any], notes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    mine = tracked_set(card["profile"])
    out = []
    for slug, n in sorted(notes.items()):
        label = (n.get("outcome") or {}).get("label")
        if label in ("flop", "mixed") and len(mine & tracked_set(n)) >= 3:
            out.append({"title_id": slug, "label": label, "shared": len(mine & tracked_set(n))})
    return out


# ---------------------------------------------------------------- the judge
def judge_schema(rule_ids: list[str]) -> dict[str, Any]:
    rule = _obj({"id": {"type": "string", "enum": rule_ids}, "verdict": {"type": "string", "enum": ["pass", "fail"]},
                 "reason": TEXT})
    item = _obj({"ref": {"type": "string", "enum": ["D1"]},
                 **{f"{d}_differs": {"type": "boolean"} for d in ("choices", "relationships", "outcomes")},
                 **{f"{d}_reason": TEXT for d in ("choices", "relationships", "outcomes")},
                 "coherence": {"type": "string", "enum": ["pass", "fail"]}, "coherence_reason": TEXT,
                 "runway_hurts_by_arc5": {"type": "boolean"}, "runway_reason": TEXT,
                 "why_different_verdict": {"type": "string", "enum": ["pass", "fail", "not_applicable"]},
                 "why_different_reason": TEXT, "rules": {"type": "array", "items": rule}})
    return _obj({"cards": {"type": "array", "items": item}})


def judge_problems(out: dict[str, Any], rule_ids: list[str], matched: bool) -> list[str]:
    problems: list[str] = []
    cards = out.get("cards") or []
    if [c.get("ref") for c in cards] != ["D1"]:
        problems.append("judge the one card, ref D1, exactly once")
    for c in cards:
        for key in ("choices_reason", "relationships_reason", "outcomes_reason", "coherence_reason", "runway_reason",
                    "why_different_reason"):
            if (n := word_count(str(c.get(key) or ""))) > 25:
                problems.append(f"cards[0].{key}: {n} words exceeds the 25-word limit")
        if sorted(r.get("id") for r in c.get("rules") or []) != sorted(rule_ids):
            problems.append(f"cards[0].rules: one verdict per rule: {rule_ids}")
        for r in c.get("rules") or []:
            if not 1 <= word_count(str(r.get("reason") or "")) <= 20:
                problems.append(f"cards[0].rules.{r.get('id')}.reason: 1-20 words")
        if matched and c.get("why_different_verdict") not in ("pass", "fail"):
            problems.append("cards[0]: the card matches a flop or mixed note; judge why_different pass or fail")
    return problems


def judge_user(card: dict[str, Any], rules: list[Rule], near: dict[str, Any] | None,
               matches: list[dict[str, Any]], notes: dict[str, dict[str, Any]]) -> str:
    lines = list(rule_lines(rules) or ["rules: none"])
    lines += note_lines(near) if near else ["closest note: none"]
    if matches:
        lines += [f"graveyard match {g['title_id']}: {g['label']} ({notes[g['title_id']].get('title')}); recorded "
                  f"failure: not tracked in the notes, judge on the outcome; shares {g['shared']} of 5 tracked fields"
                  for g in matches]
        lines.append(f"why_different: {card.get('why_different') or '(blank)'}")
    else:
        lines.append("graveyard match: none (answer why_different not_applicable)")
    e, q = card["engine"], card["consequences"]
    lines += ["=== CARD D1", f"logline: {card['logline']}", f"premise: {card['premise']}", f"theme: {card['theme_root']}",
              "engine: " + "; ".join(f"{k} {e[k]}" for k in ENGINE), f"what changed: {card['what_changed']}",
              f"consequences: choices {q['choices']}; relationships {q['relationships']}; outcomes {q['outcomes']}",
              "profile: " + ", ".join(f"{k}={v}" for k, v in card["profile"].items())]
    return "\n".join(lines)


# ---------------------------------------------------------------- the run
def run_diagnose_light(paths: Paths, settings: Settings, vocab: Vocab, *, text: str, clients: dict[str, LLMClient],
                       embedder: Embedder | None, run_id: str, source: str = "text", date: str | None = None,
                       created_at: str | None = None) -> DiagnoseResult:
    cfg = (settings.model_extra or {}).get("diagnose") or {}
    concept = text.strip()
    if not concept:
        raise DiagnoseError("the concept is empty")
    limit = int(cfg.get("max_concept_words", 800))
    if word_count(concept) > limit:
        raise DiagnoseError(f"the concept is {word_count(concept)} words; keep it to {limit} or fewer")
    notes = read_notes(paths)
    if not notes:
        raise DiagnoseError("no notes yet: run `make ingest LIST=<file>` first (the checks compare against notes/)")
    rules = load_rules(paths)
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    did = diagnose_id(concept, date)
    key = did.rsplit("_", 1)[1]
    res = DiagnoseResult(did)
    gold = {t for t, e in load_corpus(paths).items() if "gold" in e.role_tags}
    hidden = masked_titles(paths, gold) & set(notes)
    m = Masker({s: {"title": n.get("title")} for s, n in notes.items()}, hidden)
    visible = [s for s in sorted(notes) if s not in hidden] or sorted(notes)
    flops = [s for s in visible if (notes[s].get("outcome") or {}).get("label") in ("flop", "mixed")]

    structure = read_prompt(paths.prompts / "diagnose_structure.md")
    gen = clients["ideate_generate"]
    gen.prompt_version = structure.version
    prov = provenance("IDEATE", run_id, None, structure.version, vocab, created_at)
    user = "\n".join([f"concept: {' '.join(concept.split())}",
                      *(f"title {s}: {notes[s].get('medium')}; {notes[s].get('premise')}" for s in visible),
                      *(f"flop {s}: {(notes[s].get('outcome') or {}).get('label')}; recorded failure: not tracked"
                        for s in flops)])
    done, problem, stop = _call(gen, f"diagnose:{key}", structure.body, user, structure_schema(vocab, visible),
                                lambda out: raise_problems(structure_problems(out, did, prov)), paths)
    record: dict[str, Any] = {"diagnose_id": did, "source": source, "created_at": created_at or
                              datetime.now(UTC).isoformat(), "concept": concept, "path": "light",
                              "rules": [r.__dict__ for r in rules]}
    if done is None:
        res.stopped = stop
        res.checks.append(Check("structure", None if stop else False, stop or problem or "no card",
                                None if stop else "structure"))
        return _finish(paths, res, record, None, m)
    card = DiagnoseCard.model_validate(card_draft(done.data, did, provenance("IDEATE", run_id, done, structure.version,
                                                                              vocab, created_at))).to_record()
    record["card"] = card
    res.checks.append(Check("structure", True, f"structured into a card; closest note: {m.title(card['closest_existing'])}"))

    numbers = clone_numbers(card, notes, embedder)
    record["gates"] = numbers
    res.checks.append(clone_check(numbers, settings.gates, m))
    res.checks.append(novelty_check(card, notes))
    matches = graveyard_matches(card, notes)
    record["gates"]["graveyard_hits"] = [g["title_id"] for g in matches]
    if not matches:
        res.checks.append(Check("graveyard", True, "shares no core combination with a flop or mixed note"))
    elif not card.get("why_different"):
        res.checks.append(Check("graveyard", False, "shares its core combination with " +
                                ", ".join(m.title(g["title_id"]) for g in matches) + " and says nothing about why this "
                                "time is different", "graveyard"))
    else:
        res.checks.append(Check("graveyard", True, "shares its core combination with " +
                                ", ".join(m.title(g["title_id"]) for g in matches) + "; why_different is given (judged below)"))
    leaks = name_leaks(f"{card['logline']} {card['premise']}", note_titles(notes), set())
    res.checks.append(Check("name leak", False, f"reuses existing names: {m.text(', '.join(leaks[:3]))}", "name_leak")
                      if leaks else Check("name leak", True, "no existing title names"))

    judge = read_prompt(paths.prompts / "diagnose_judge.md")
    jc = clients["ideate_judge"]
    jc.prompt_version = judge.version
    rule_ids = [r.id for r in rules]
    near = notes.get(card["closest_existing"])
    jdone, problem, stop = _call(jc, f"diagnose:{key}:judge", judge.body, judge_user(card, rules, near, matches, notes),
                                 judge_schema(rule_ids), lambda out: raise_problems(judge_problems(out, rule_ids, bool(matches))),
                                 paths)
    if stop:
        res.stopped = stop
    h1_min = int(settings.ideate.get("h1_min_changed_dimensions", 2))
    hide_near = card["closest_existing"] in hidden
    if jdone is None:
        why = stop or problem or "the judge gave no verdict"
        for name in ("H1 consequence test", "coherence", "runway", *(["why different"] if matches else []),
                     *(f"rule {r.id} ({r.strength})" for r in rules)):
            res.checks.append(Check(name, None, why))
    else:
        j = jdone.data["cards"][0]
        record["judge"] = j
        dims = [d for d in ("choices", "relationships", "outcomes") if j[f"{d}_differs"]]
        reasons = ("(reasons withheld: the closest note is a gold title while the blind is pending)" if hide_near else
                   "; ".join(f"{d}: {j[f'{d}_reason']}" for d in ("choices", "relationships", "outcomes")))
        res.checks.append(Check("H1 consequence test", len(dims) >= h1_min,
                                f"{len(dims)} of 3 consequence dimensions differ from "
                                f"{m.title(card['closest_existing'])} (needs {h1_min}); {m.text(reasons)}",
                                None if len(dims) >= h1_min else "h1"))
        res.checks.append(Check("coherence", j["coherence"] == "pass", m.text(j["coherence_reason"]),
                                None if j["coherence"] == "pass" else "coherence"))
        res.checks.append(Check("runway", bool(j["runway_hurts_by_arc5"]), m.text(j["runway_reason"]),
                                None if j["runway_hurts_by_arc5"] else "runway"))
        if matches:
            ok = j["why_different_verdict"] == "pass"
            res.checks.append(Check("why different", ok, m.text(j["why_different_reason"]), None if ok else "why_different"))
        verdicts = {r["id"]: r for r in j.get("rules") or []}
        for r in rules:
            v = verdicts.get(r.id, {})
            ok = v.get("verdict") == "pass"
            res.checks.append(Check(f"rule {r.id} ({r.strength})", ok, m.text(v.get("reason") or "no verdict"),
                                    None if ok else ("steering_hard" if r.strength == "hard" else "steering_soft")))

    abl = read_prompt(paths.prompts / "diagnose_ablation.md")
    parts = ablation_parts(card)
    part_ids = list(parts)
    if not res.stopped:
        jc.prompt_version = abl.version
        adone, problem, stop = _call(jc, f"diagnose:{key}:ablation", abl.body, ablation_user(card, parts),
                                     ablation_schema(part_ids), lambda out: raise_problems(ablation_problems(out, part_ids)),
                                     paths)
        if stop:
            res.stopped = stop
        if adone is None:
            res.checks.append(Check("ablation", None, stop or problem or "no answer"))
        else:
            record["ablation"] = sorted(adone.data["parts"], key=lambda p: part_ids.index(p["part"]))
            res.checks.append(ablation_check(record["ablation"]))
    else:
        res.checks.append(Check("ablation", None, res.stopped))
    return _finish(paths, res, record, card, m)


def _finish(paths: Paths, res: DiagnoseResult, record: dict[str, Any], card: dict[str, Any] | None,
            m: Masker) -> DiagnoseResult:
    record["checks"] = [{"check": c.name, "status": c.status, "why": c.why,
                         "prescription": prescription(c.failure) if c.failure else None} for c in res.checks]
    base = paths.root / "data" / "diagnose" / res.diagnose_id
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    atomic_write_text(json_path, json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(md_path, render_md(record, card, res, m).replace("## Checks", "## Checks (against the notes index "
                                                                                    "and steering/rules.yaml)", 1))
    res.json_path = str(json_path.relative_to(paths.root))
    res.md_path = str(md_path.relative_to(paths.root))
    failed = sum(1 for c in res.checks if c.ok is False)
    res.lines = [f"diagnose {res.diagnose_id}: {failed} of {len(res.checks)} checks failed (light path: notes + steering)"]
    for c in res.checks:
        res.lines.append(f"  {c.status} {c.name}: {c.why}")
        if c.failure:
            res.lines.append(f"       fix: {prescription(c.failure)}")
    if res.stopped:
        res.lines.append(f"  paused: {res.stopped}. Run the same command later; finished calls are cached.")
    res.lines.append(f"card and report -> {res.md_path} (private: data/diagnose/ never goes to the public repo)")
    return res


__all__ = ["LIGHT_PRESCRIPTIONS", "NOT_TRACKED", "PAIRS", "TRACKED", "clone_check", "clone_numbers", "graveyard_matches",
           "judge_problems", "judge_schema", "novelty_check", "prescription", "run_diagnose_light", "tracked_set"]
