"""`animedex diagnose` (owner ruling 2026-09-27, M5; reuses the M5 gates and judge).

Kingsley's own concept, as text, goes through:
1. one structuring call (slot `ideate_generate`, `prompts/diagnose_structure.md`) that turns it into
   a card: logline, premise, theme, engine (7 parts), twist, consequences, profile (6 enums), closest
   existing title, broken rule, appetite, why different. Stored in data/diagnose/<id>.json (private);
2. every gate exactly as on generated cards: clone, novelty, graveyard, name leak;
3. the judge (same prompt and call shape as IDEATE, one card): H1, coherence, runway, why_different
   on a premise-level graveyard match, taste with its evidence rule;
4. an ablation pass (slot `ideate_judge`, `prompts/diagnose_ablation.md`): for each part of the
   concept, is it load-bearing, supporting or decoration, with a reason of 20 words or fewer.
Output: data/diagnose/<id>.md plus printed lines, one per check (PASS / FAIL / SKIP and why), and
for each failure a prescription from the fixed table below: one of the 8 operators or a rung of the
concept ladder. Three calls under the per-run cap `diagnose.calls_per_run` (6: each call may spend its
one repair). No reworks and no rebuild (`amplify` stays after blind review #1).

Gold blind: while it is pending, the structuring call sees no gold title (its closest title comes
from the rest of the corpus), gold names are masked, and a judge reason written against a gold title
is withheld.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.embeddings.base import Embedder
from animedex.gold import masked_titles
from animedex.guards import load_corpus
from animedex.ideate.brief import flop_line, title_line
from animedex.ideate.context import PROFILE_PATHS, Context, build_context
from animedex.ideate.gates import GateResult, Similarity, run_gates
from animedex.ideate.llm import (
    ENGINE,
    MAYBE,
    OPERATORS,
    TEXT,
    _obj,
    judge_card_text,
    judge_problems,
    judge_schema,
)
from animedex.ideate.report import Masker
from animedex.ideate.run import graveyard_matches, judge_facts
from animedex.integrity import name_leaks
from animedex.models.diagnose import DiagnoseCard
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import provenance, raise_problems
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.quarantine import quarantine
from animedex.textutil import sha256_text, word_count

# The concept ladder (CHANGE_PLAN_ideation_modes §5), in climbing order.
LADDER = ("kit", "set", "MC", "villain and thematic argument", "world", "engine and escalation",
          "promise and hooks", "pilot hook", "three key frames", "storyboard")

# Failure type -> (kind, operator or ladder rung, what to do). Fixed in code; documented in 05 DIAGNOSE.
PRESCRIPTIONS: dict[str, tuple[str, str, str]] = {
    "structure": ("rung", "kit", "Start from the power kit: what the power does, its limits, and what using it costs."),
    "clone_structural": ("operator", "change_rule", "Change the rule the nearest title depends on most."),
    "clone_procedural": ("rung", "kit", "Rebuild the kit: a different gate, cost, progression or visible counter."),
    "clone_premise": ("operator", "redistribute_knowledge",
                      "Move the secret so the premise stops reading like the nearest title."),
    "novelty": ("operator", "combine_mechanisms",
                "Add a second engine that pulls against the first, so the pair is one no title has tried."),
    "graveyard": ("rung", "promise and hooks",
                  "Say what the audience is promised and why that promise holds where the matched flop's broke."),
    "why_different": ("rung", "promise and hooks",
                      "Answer the matched flop's recorded failure with a concrete change to the promise."),
    "name_leak": ("rung", "world", "Invent your own world, places and names."),
    "h1": ("operator", "transfer_cost",
           "Let someone other than the hero pay, so choices, relationships and outcomes change."),
    "coherence": ("rung", "villain and thematic argument",
                  "Tie the mechanic to the theme through an opponent whose argument the power answers."),
    "runway": ("rung", "engine and escalation", "Make the cost scale with the power so it still hurts by arc 5."),
    "ablation_twist": ("operator", "change_rule", "Make the twist a rule the story cannot work without."),
    "ablation_flat": ("operator", "reverse_incentive",
                      "Make what the hero wins also cost them, so the parts start carrying weight."),
}
VERDICTS = ("load_bearing", "supporting", "decoration")
PROFILE_PARTS = {"gate": "how the power is gained", "cost_of_power": "what using the power costs",
                 "progression": "how the power grows", "visible_counter": "how progress is shown",
                 "fight_medium": "what fights are fought with", "power_is": "whose power it is"}
HIDDEN = "(reason withheld: written against a gold title while the blind is pending)"


class DiagnoseError(ValueError):
    pass


@dataclass
class Check:
    name: str
    ok: bool | None          # None: not run (SKIP)
    why: str
    failure: str | None = None

    @property
    def status(self) -> str:
        return "SKIP" if self.ok is None else ("PASS" if self.ok else "FAIL")


@dataclass
class DiagnoseResult:
    diagnose_id: str
    checks: list[Check] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    json_path: str = ""
    md_path: str = ""
    stopped: str | None = None


def diagnose_id(text: str, date: str) -> str:
    return f"diag_{date.replace('-', '')}_{sha256_text(' '.join(text.split())).split(':')[1][:8]}"


def prescription(failure: str) -> str:
    kind, target, advice = PRESCRIPTIONS[failure]
    if kind == "operator":
        return f"operator {target} ({OPERATORS[target].rstrip('.').lower()}): {advice}"
    return f"ladder rung '{target}': {advice}"


# ---------------------------------------------------------------- structuring
def structure_schema(vocab: Vocab, title_ids: list[str]) -> dict[str, Any]:
    profile = _obj({k: {"type": "string", "enum": list(vocab.enum(path))} for k, path in PROFILE_PATHS.items()})
    return _obj({"logline": TEXT, "premise": TEXT, "theme_root": TEXT, "engine": _obj({k: TEXT for k in ENGINE}),
                 "what_changed": TEXT, "consequences": _obj({"choices": TEXT, "relationships": TEXT, "outcomes": TEXT}),
                 "profile": profile, "closest_existing": {"type": "string", "enum": title_ids},
                 "why_not_a_clone": TEXT, "broken_rule": TEXT, "appetite": TEXT, "why_different": MAYBE})


def structure_user(text: str, ctx: Context, title_ids: list[str], flops: list[dict[str, Any]]) -> str:
    return "\n".join([f"concept: {' '.join(text.split())}", *(title_line(ctx, t) for t in title_ids),
                      *map(flop_line, flops)])


def card_draft(out: dict[str, Any], did: str, prov: dict[str, Any]) -> dict[str, Any]:
    return {"diagnose_id": did, "logline": out.get("logline"), "premise": out.get("premise"),
            "theme_root": out.get("theme_root"), "engine": {k: (out.get("engine") or {}).get(k) for k in ENGINE},
            "what_changed": out.get("what_changed"),
            "consequences": {k: (out.get("consequences") or {}).get(k) for k in ("choices", "relationships", "outcomes")},
            "profile": dict(out.get("profile") or {}), "closest_existing": out.get("closest_existing"),
            "why_not_a_clone": out.get("why_not_a_clone"), "broken_rule": out.get("broken_rule") or "",
            "appetite": out.get("appetite") or "", "why_different": out.get("why_different") or None,
            "provenance": prov}


def structure_problems(out: dict[str, Any], did: str, prov: dict[str, Any]) -> list[str]:
    try:
        DiagnoseCard.model_validate(card_draft(out, did, prov))
    except ValidationError as exc:
        return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()[:6]]
    return []


# ---------------------------------------------------------------- ablation
def ablation_parts(card: dict[str, Any]) -> dict[str, str]:
    """part id -> the text the ablation judge sees."""
    parts = {f"engine.{k}": card["engine"][k] for k in ENGINE}
    parts["what_changed"] = f"the twist: {card['what_changed']}"
    if card.get("broken_rule"):
        parts["broken_rule"] = f"the rule it breaks: {card['broken_rule']}"
    for k, meaning in PROFILE_PARTS.items():
        parts[f"profile.{k}"] = f"{meaning}: {card['profile'][k]}"
    return parts


def ablation_schema(part_ids: list[str]) -> dict[str, Any]:
    item = _obj({"part": {"type": "string", "enum": part_ids}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                 "reason": TEXT})
    return _obj({"parts": {"type": "array", "items": item}})


def ablation_user(card: dict[str, Any], parts: dict[str, str]) -> str:
    return "\n".join([f"logline: {card['logline']}", f"premise: {card['premise']}",
                      *(f"part {pid}: {text}" for pid, text in parts.items())])


def ablation_problems(out: dict[str, Any], part_ids: list[str]) -> list[str]:
    got = [p.get("part") for p in out.get("parts") or []]
    problems = [] if sorted(got) == sorted(part_ids) else [f"answer every part exactly once: {part_ids}"]
    for p in out.get("parts") or []:
        if not 1 <= word_count(str(p.get("reason") or "")) <= 20:
            problems.append(f"{p.get('part')}.reason: 1-20 words")
    return problems


def ablation_check(parts: list[dict[str, Any]]) -> Check:
    by = {v: sorted(p["part"] for p in parts if p["verdict"] == v) for v in VERDICTS}
    summary = f"load-bearing: {', '.join(by['load_bearing']) or 'none'}; decoration: {', '.join(by['decoration']) or 'none'}"
    if "what_changed" in by["decoration"]:
        return Check("ablation", False, f"the twist is decoration (the concept works the same without it); {summary}",
                     "ablation_twist")
    if not by["load_bearing"]:
        return Check("ablation", False, f"no part is load-bearing; {summary}", "ablation_flat")
    return Check("ablation", True, summary)


# ---------------------------------------------------------------- the run
def _call(client: LLMClient, record_id: str, system: str, user: str, schema: dict[str, Any], validate: Any,
          paths: Paths) -> tuple[Any, str | None, str | None]:
    """(completion or None, problem, stop reason)."""
    ctx = CallContext(pass_="IDEATE", record_id=record_id, title_id=None, upstream=sha256_text(user))
    try:
        return client.complete_ex(system, user, schema, None, ctx=ctx, validate=validate), None, None
    except InvalidOutput as exc:
        quarantine(paths.quarantine, "IDEATE", "diagnose", record_id, exc.raw, exc.errors)
        return None, f"no valid answer after one repair ({exc.errors[-1][:160]})", None
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        return None, None, str(exc)
    except ProviderError as exc:
        return None, f"the call failed ({str(exc)[:160]})", None


def _clone_check(g: GateResult, m: Masker) -> Check:
    clone = [f for f in g.failures if f.startswith("clone:")]
    numbers = (f"structural overlap {g.structural_max:.2f} (nearest {m.title(g.nearest) or 'none'}), procedural "
               f"{g.procedural_max:.2f}, premise similarity {g.cosine_max:.2f}")
    if not clone:
        return Check("clone", True, numbers)
    kind = ("clone_structural" if "structural overlap" in clone[0] else
            "clone_procedural" if "procedural overlap" in clone[0] else "clone_premise")
    return Check("clone", False, m.text(clone[0].removeprefix("clone: ")), kind)


def run_diagnose(paths: Paths, settings: Settings, vocab: Vocab, *, text: str, clients: dict[str, LLMClient],
                 embedder: Embedder, run_id: str, source: str = "text", date: str | None = None,
                 created_at: str | None = None) -> DiagnoseResult:
    cfg = (settings.model_extra or {}).get("diagnose") or {}
    concept = text.strip()
    if not concept:
        raise DiagnoseError("the concept is empty")
    limit = int(cfg.get("max_concept_words", 800))
    if word_count(concept) > limit:
        raise DiagnoseError(f"the concept is {word_count(concept)} words; keep it to {limit} or fewer")
    ctx = build_context(paths, settings, vocab)
    if not ctx.titles:
        raise DiagnoseError("no indexed titles yet: the gates and the judge compare against the corpus")
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    did = diagnose_id(concept, date)
    key = did.rsplit("_", 1)[1]
    res = DiagnoseResult(did)
    gold = {t for t, e in load_corpus(paths).items() if "gold" in e.role_tags}
    hidden = masked_titles(paths, gold)
    m = Masker(ctx.titles, hidden)
    visible = [t for t in sorted(ctx.titles) if t not in hidden] or sorted(ctx.titles)
    flops = [g for g in ctx.graveyard if g["title_id"] not in hidden]

    structure = read_prompt(paths.prompts / "diagnose_structure.md")
    gen = clients["ideate_generate"]
    gen.prompt_version = structure.version
    prov = provenance("IDEATE", run_id, None, structure.version, vocab, created_at)
    done, problem, stop = _call(gen, f"diagnose:{key}", structure.body, structure_user(concept, ctx, visible, flops),
                                structure_schema(vocab, visible),
                                lambda out: raise_problems(structure_problems(out, did, prov)), paths)
    record: dict[str, Any] = {"diagnose_id": did, "source": source, "created_at": created_at or
                              datetime.now(UTC).isoformat(), "concept": concept}
    if done is None:
        res.stopped = stop
        res.checks.append(Check("structure", None if stop else False, stop or problem or "no card",
                                None if stop else "structure"))
        return _finish(paths, res, record, None, m)
    card = DiagnoseCard.model_validate(card_draft(done.data, did, provenance("IDEATE", run_id, done, structure.version,
                                                                              vocab, created_at))).to_record()
    record["card"] = card
    res.checks.append(Check("structure", True, f"structured into a card; closest existing title: "
                                               f"{m.title(card['closest_existing'])}"))

    # gates, exactly as on generated cards
    gate_card = {"logline": card["logline"], "premise": card["premise"], "profile": card["profile"], "bridge": [],
                 "_atoms": [], "why_different": card["why_different"]}
    g = run_gates(gate_card, ctx, Similarity(embedder, ctx), settings.gates)
    record["gates"] = {"structural_jaccard_max": g.structural_max, "nearest": g.nearest,
                       "procedural_jaccard_max": g.procedural_max, "premise_cosine_max": g.cosine_max,
                       "novel_combo": g.novel_combo, "novelty_basis": g.novelty_basis,
                       "graveyard_hits": g.graveyard_hits, "failures": g.failures, "fatal": g.fatal}
    res.checks.append(_clone_check(g, m))
    res.checks.append(Check("novelty", True, g.novelty_basis) if g.novel_combo else
                      Check("novelty", False, g.fatal[0].removeprefix("novelty: "), "novelty"))
    matches = graveyard_matches(ctx, g)
    blank = [f for f in g.failures if f.startswith("graveyard:")]
    if not matches:
        res.checks.append(Check("graveyard", True, "matches no premise-level flop combination"))
    elif blank:
        res.checks.append(Check("graveyard", False, m.text(blank[0].removeprefix("graveyard: ")), "graveyard"))
    else:
        res.checks.append(Check("graveyard", True, "matches premise-level flop(s) "
                                f"{', '.join(m.title(x['title_id']) for x in matches)}; why_different is given "
                                "(judged below)"))
    leaks = name_leaks(f"{card['logline']} {card['premise']}", *ctx.names)
    res.checks.append(Check("name leak", False, f"reuses existing names: {m.text(', '.join(leaks[:3]))}", "name_leak")
                      if leaks else Check("name leak", True, "no existing title or character names"))

    # the judge: same prompt and call shape as IDEATE, one card
    judge = read_prompt(paths.prompts / "ideate_judge.md")
    jc = clients["ideate_judge"]
    jc.prompt_version = judge.version
    judge_card = {**card, "transformation": {"operator": "user_concept", "what_changed": card["what_changed"]},
                  "bridge": []}
    ref = "D1"
    matched = [ref] if matches else []
    user = judge_card_text(ref, judge_card, ctx, [], judge_facts(ctx, g, judge_card), matches)
    jdone, problem, stop = _call(jc, f"diagnose:{key}:judge", judge.body, user, judge_schema([ref], []),
                                 lambda out: raise_problems(judge_problems(out, [ref], matched)), paths)
    if stop:
        res.stopped = stop
    h1_min = int(settings.ideate.get("h1_min_changed_dimensions", 2))
    if jdone is None:
        why = stop or problem or "the judge gave no verdict"
        for name in ("H1 consequence test", "coherence", "runway", *(["why different"] if matches else [])):
            res.checks.append(Check(name, None, why))
    else:
        j = jdone.data["cards"][0]
        record["judge"] = j
        hide_near = card["closest_existing"] in hidden
        dims = [d for d in ("choices", "relationships", "outcomes") if j[f"{d}_differs"]]
        reasons = HIDDEN if hide_near else "; ".join(f"{d}: {j[f'{d}_reason']}" for d in
                                                     ("choices", "relationships", "outcomes"))
        res.checks.append(Check("H1 consequence test", len(dims) >= h1_min,
                                f"{len(dims)} of 3 consequence dimensions differ from "
                                f"{m.title(card['closest_existing'])} (needs {h1_min}); {m.text(reasons)}",
                                None if len(dims) >= h1_min else "h1"))
        res.checks.append(Check("coherence", j["coherence"] == "pass",
                                HIDDEN if hide_near else m.text(j["coherence_reason"]),
                                None if j["coherence"] == "pass" else "coherence"))
        res.checks.append(Check("runway", bool(j["runway_hurts_by_arc5"]),
                                HIDDEN if hide_near else m.text(j["runway_reason"]),
                                None if j["runway_hurts_by_arc5"] else "runway"))
        if matches:
            hide_flop = any(x["title_id"] in hidden for x in matches)
            ok = j["why_different_verdict"] == "pass"
            res.checks.append(Check("why different", ok, HIDDEN if hide_flop else m.text(j["why_different_reason"]),
                                    None if ok else "why_different"))
        record["taste_claimed"] = [t["criterion"] for t in j.get("taste") or []]

    # ablation: which parts carry the concept
    abl = read_prompt(paths.prompts / "diagnose_ablation.md")
    parts = ablation_parts(card)
    part_ids = list(parts)
    if not res.stopped:
        jc.prompt_version = abl.version
        adone, problem, stop = _call(jc, f"diagnose:{key}:ablation", abl.body, ablation_user(card, parts),
                                     ablation_schema(part_ids),
                                     lambda out: raise_problems(ablation_problems(out, part_ids)), paths)
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
    atomic_write_text(md_path, render_md(record, card, res, m))
    res.json_path = str(json_path.relative_to(paths.root))
    res.md_path = str(md_path.relative_to(paths.root))
    failed = sum(1 for c in res.checks if c.ok is False)
    res.lines = [f"diagnose {res.diagnose_id}: {failed} of {len(res.checks)} checks failed"]
    for c in res.checks:
        res.lines.append(f"  {c.status} {c.name}: {c.why}")
        if c.failure:
            res.lines.append(f"       fix: {prescription(c.failure)}")
    if res.stopped:
        res.lines.append(f"  paused: {res.stopped}. Run the same command later; finished calls are cached.")
    res.lines.append(f"card and report -> {res.md_path} (private: data/diagnose/ never goes to the public repo)")
    return res


def render_md(record: dict[str, Any], card: dict[str, Any] | None, res: DiagnoseResult, m: Masker) -> str:
    lines = [f"# Diagnosis {res.diagnose_id}", "", f"*{record['created_at'][:10]}; from {record['source']}*", "",
             "## Your concept", "", record["concept"], ""]
    if card:
        e, q = card["engine"], card["consequences"]
        hide = card["closest_existing"] in m.hidden
        lines += ["## As a card", "", f"**Logline.** {m.text(card['logline'])}", "",
                  f"**Premise.** {m.text(card['premise'])}", "", f"**Theme.** {m.text(card['theme_root'])}", "",
                  f"**Engine.** Wants {m.text(e['goal'])}, but {m.text(e['constraint'])}. Chooses "
                  f"{m.text(e['strategy'])}; gains {m.text(e['benefit'])}, pays {m.text(e['cost'])}. Dilemma: "
                  f"{m.text(e['dilemma'])} *{m.text(e['dramatic_question'])}*", "",
                  f"**Twist.** {m.text(card['what_changed'])} Closest existing: {m.title(card['closest_existing'])}. "
                  + (HIDDEN if hide else m.text(card["why_not_a_clone"])), "",
                  "**Profile.** " + ", ".join(f"{k} {v}" for k, v in card["profile"].items()), ""]
        if not hide:
            lines += [f"**How it plays differently.** Choices: {m.text(q['choices'])} Relationships: "
                      f"{m.text(q['relationships'])} Outcomes: {m.text(q['outcomes'])}", ""]
    lines += ["## Checks", "", "| Check | Result | Why | Prescription |", "|---|---|---|---|"]
    for c in record["checks"]:
        why = str(c["why"]).replace("|", "/")
        lines.append(f"| {c['check']} | {c['status']} | {why} | {c['prescription'] or ''} |")
    if record.get("ablation"):
        lines += ["", "## Which parts carry it (ablation)", "", "| Part | Verdict | If removed |", "|---|---|---|"]
        lines += [f"| {p['part']} | {p['verdict'].replace('_', '-')} | {m.text(p['reason'])} |"
                  for p in record["ablation"]]
    if record.get("taste_claimed"):
        lines += ["", "Taste criteria the judge saw (unverified here: no prior-art web check runs in diagnose): "
                  + ", ".join(record["taste_claimed"]) + "."]
    lines += ["", "Prescriptions come from a fixed table (05 DIAGNOSE): one of the 8 operators or a rung of the "
              "concept ladder (kit, set, MC, villain and thematic argument, world, engine and escalation, promise "
              "and hooks, pilot hook, three key frames, storyboard)."]
    return "\n".join(lines) + "\n"


__all__ = ["LADDER", "PRESCRIPTIONS", "Check", "DiagnoseError", "DiagnoseResult", "diagnose_id", "prescription",
           "run_diagnose"]
