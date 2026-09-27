"""`make diagnose TEXT="..."`: an author's own concept, checked against the notes and steering/rules.yaml.

Two calls under `diagnose.calls_per_run`, on the same prompts as ingest and quick:
1. STRUCTURE (slot `ingest`, ingest.md `job: concept`): the concept written as a note, as it is (premise,
   engine, the six enums, MC edge, kit, and the three elements it cannot survive without).
2. CHECK (slot `check`, check.md): the consequence test against its closest note, every steering rule, the
   closest note and how close, the biggest weakness, a score.
Checks without a call: clone (the five tracked enums' overlap with each note, and the premise's similarity
to each note's premise), novelty (enum pairs no note holds; needs `diagnose.novelty_min_notes` notes),
graveyard (flop or mixed notes sharing 3 of the 5 tracked enums) and name leak. Each failure gets a line
from the fixed prescription table. Output: data/diagnose/<id>.json and .md (private). While the blind review
is pending, gold titles are masked in the output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from animedex.config import Settings
from animedex.embeddings.base import Embedder, cosine
from animedex.gold import masked_titles
from animedex.ideate.steering import load_rules
from animedex.light.notes import (
    ENGINE,
    ENUMS,
    note_problems,
    note_schema,
    note_titles,
    read_notes,
    study_fields,
    values_lines,
)
from animedex.light.quick import (
    call,
    check_problems,
    check_schema,
    check_user,
    raise_problems,
    verdict_dims,
)
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.prompts import read_prompt
from animedex.providers.client import LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.textutil import name_leaks, sha256_text, word_count

TRACKED = ("gate", "cost_of_power", "progression", "visible_counter", "fight_medium")
PAIRS = (("gate", "cost_of_power"), ("progression", "visible_counter"), ("fight_medium", "cost_of_power"))
NEAREST = 5   # notes the check sees
MASK = "[gold title]"
# failure -> what to do (a fixed table; no call)
PRESCRIPTIONS = {
    "structure": "Start from the power kit: what the power does, its limits, and what using it costs.",
    "clone": "Change the rule the nearest show depends on most, so the concept stops reading like it.",
    "novelty": "Add a second engine that pulls against the first, so the pair is one no show in the notes has tried.",
    "graveyard": "Say what the audience is promised and why that promise holds where the matched show's fell short.",
    "name_leak": "Invent your own world, places and names.",
    "consequence": "Let someone other than the hero pay, so choices, relationships and outcomes change.",
    "steering_hard": "Make the lead legibly the strongest through the medium or a cost nobody else pays, not the biggest number.",
    "steering_soft": "Revisit the rule: derive the power from the concept and build the premise out from the fight.",
}


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


def tracked_set(profile: dict[str, Any]) -> set[str]:
    return {f"{k}={profile.get(k)}" for k in TRACKED if profile.get(k) and not str(profile[k]).startswith("other")}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def similarity(concept: dict[str, Any], notes: dict[str, dict[str, Any]], embedder: Embedder | None) -> dict[str, Any]:
    """Tracked-enum overlap and premise similarity against every note."""
    mine = tracked_set(concept)
    overlap = {s: jaccard(mine, tracked_set(n)) for s, n in notes.items()}
    sims: dict[str, float] = {}
    if embedder is not None and notes:
        slugs = sorted(notes)
        vectors = embedder.embed([str(notes[s].get("premise") or "") for s in slugs])
        [v] = embedder.embed([str(concept.get("premise") or "")])
        sims = {s: cosine(v, w) for s, w in zip(slugs, vectors, strict=True)}
    return {"overlap": overlap, "cosine": sims}


def nearest(sim: dict[str, Any], k: int = NEAREST) -> list[str]:
    scores = {s: sim["overlap"][s] + sim["cosine"].get(s, 0.0) for s in sim["overlap"]}
    return sorted(scores, key=lambda s: (-scores[s], s))[:k]


def novelty_check(concept: dict[str, Any], notes: dict[str, dict[str, Any]], min_notes: int) -> Check:
    if len(notes) < min_notes:
        return Check("novelty", None, f"not run: {len(notes)} note(s), fewer than {min_notes}")
    seen = []
    for x, y in PAIRS:
        vx, vy = concept.get(x), concept.get(y)
        if not vx or not vy or str(vx).startswith("other") or str(vy).startswith("other"):
            continue
        n = sum(1 for note in notes.values() if note.get(x) == vx and note.get(y) == vy)
        if n == 0:
            return Check("novelty", True, f"no note pairs {x}={vx} with {y}={vy} ({len(notes)} notes)")
        seen.append(f"{x}={vx}+{y}={vy} in {n}")
    return Check("novelty", False, "every tracked pair appears in the notes: " + "; ".join(seen), "novelty")


def graveyard_matches(concept: dict[str, Any], notes: dict[str, dict[str, Any]]) -> list[str]:
    mine = tracked_set(concept)
    return [s for s, n in sorted(notes.items()) if (n.get("outcome") or {}).get("label") in ("flop", "mixed")
            and len(mine & tracked_set(n)) >= 3]


class Masker:
    def __init__(self, notes: dict[str, dict[str, Any]], hidden: set[str]):
        self.notes, self.hidden = notes, hidden
        self.names = sorted({s for s in hidden} | {str(notes[s].get("title")) for s in hidden if s in notes},
                            key=len, reverse=True)

    def title(self, slug: str | None) -> str:
        if not slug:
            return "none"
        return MASK if slug in self.hidden else str(self.notes.get(slug, {}).get("title", slug))

    def text(self, value: Any) -> str:
        text = str(value or "")
        for name in self.names:
            text = text.replace(name, MASK)
        return text


def run_diagnose(paths: Paths, settings: Settings, vocab: Vocab, *, text: str, clients: dict[str, LLMClient],
                 embedder: Embedder | None, run_id: str, source: str = "text", date: str | None = None,
                 created_at: str | None = None) -> DiagnoseResult:
    cfg = settings.section("diagnose")
    concept_text = text.strip()
    if not concept_text:
        raise DiagnoseError("the concept is empty")
    limit = int(cfg.get("max_concept_words", 800))
    if word_count(concept_text) > limit:
        raise DiagnoseError(f"the concept is {word_count(concept_text)} words; keep it to {limit} or fewer")
    notes = read_notes(paths)
    if not notes:
        raise DiagnoseError("no notes yet: run `make ingest LIST=<file>` first (the checks compare against notes/)")
    rules = load_rules(paths)
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    did = diagnose_id(concept_text, date)
    key = did.rsplit("_", 1)[1]
    res = DiagnoseResult(did)
    m = Masker(notes, masked_titles(paths) & set(notes))
    record: dict[str, Any] = {"diagnose_id": did, "source": source, "concept": concept_text, "rules": [r.__dict__ for r in rules],
                              "created_at": created_at or datetime.now(UTC).isoformat()}

    # 1. structure: the concept as a note
    ingest = read_prompt(paths.prompts / "ingest.md")
    ic = clients["ingest"]
    ic.prompt_version = ingest.version
    user = "\n".join(["job: concept", f"concept: {' '.join(concept_text.split())}", *values_lines(vocab)])
    done, problem, stop = call(ic, "INGEST", f"concept:{key}", ingest.body, user, note_schema(["concept"]), None,
                               lambda out: raise_problems(note_problems(out, ["concept"], vocab, set(), concept=True)), paths)
    if done is None:
        res.stopped = stop
        res.checks.append(Check("structure", None if stop else False, stop or problem or "no note", None if stop else "structure"))
        return _finish(paths, res, record, m)
    concept = study_fields(done.data["notes"][0])
    record["note"] = concept
    res.checks.append(Check("structure", True, "written as a note: " + ", ".join(f"{k} {concept[k]}" for k in ENUMS)))

    # checks without a call
    sim = similarity(concept, notes, embedder)
    near = nearest(sim)
    top_o = max(sim["overlap"], key=lambda s: (sim["overlap"][s], s))
    top_c = max(sim["cosine"], key=lambda s: (sim["cosine"][s], s)) if sim["cosine"] else None
    o, c = sim["overlap"][top_o], (sim["cosine"][top_c] if top_c else 0.0)
    record["similarity"] = {"overlap_max": round(o, 4), "overlap_nearest": top_o, "premise_max": round(c, 4),
                            "premise_nearest": top_c, "nearest": near}
    why = (f"tracked-enum overlap {o:.2f} ({m.title(top_o)}), premise similarity {c:.2f} ({m.title(top_c)})"
           + ("" if top_c else "; premise similarity not run (no embedder)"))
    clone = o >= float(cfg.get("structural_overlap_fail", 0.70)) or c >= float(cfg.get("premise_similarity_fail", 0.72))
    res.checks.append(Check("clone", not clone, why, "clone" if clone else None))
    res.checks.append(novelty_check(concept, notes, int(cfg.get("novelty_min_notes", 10))))
    graves = graveyard_matches(concept, notes)
    res.checks.append(Check("graveyard", not graves, "shares 3 of 5 tracked enums with " + ", ".join(m.title(s) for s in graves)
                            + " (rated flop or mixed)" if graves else "shares its core combination with no flop or mixed note",
                            "graveyard" if graves else None))
    leaks = name_leaks(f"{concept['premise']} {concept['mc_edge']}", note_titles(notes), set())
    res.checks.append(Check("name leak", not leaks, f"reuses existing names: {m.text(', '.join(leaks[:3]))}" if leaks
                            else "no existing title names", "name_leak" if leaks else None))

    # 2. the check, against the nearest notes
    chk = read_prompt(paths.prompts / "check.md")
    cc = clients["check"]
    cc.prompt_version = chk.version
    rule_ids = [r.id for r in rules]
    cdone, problem, stop = call(cc, "CHECK", f"concept:{key}", chk.body, check_user(rules, notes, near, {"D1": concept}),
                                check_schema(["D1"], rule_ids, near), None,
                                lambda out: raise_problems(check_problems(out, ["D1"], rule_ids)), paths)
    if cdone is None:
        res.stopped = stop
        for name in ("consequence test", *(f"rule {r.id} ({r.strength})" for r in rules)):
            res.checks.append(Check(name, None, stop or problem or "the check gave no verdict"))
    else:
        j = cdone.data["cards"][0]
        record["check"] = j
        need = int(settings.section("quick").get("consequence_min", 2))
        dims = verdict_dims(j)
        res.checks.append(Check("consequence test", dims >= need, f"{dims} of 3 dimensions differ from "
                                f"{m.title(j['closest_slug'])} (needs {need}); {m.text(j['consequence_reason'])}",
                                None if dims >= need else "consequence"))
        verdicts = {v["id"]: v for v in j.get("rules") or []}
        for r in rules:
            v = verdicts.get(r.id, {})
            ok = v.get("verdict") == "pass"
            res.checks.append(Check(f"rule {r.id} ({r.strength})", ok, m.text(v.get("reason") or "no verdict"),
                                    None if ok else ("steering_hard" if r.strength == "hard" else "steering_soft")))
    return _finish(paths, res, record, m)


def _finish(paths: Paths, res: DiagnoseResult, record: dict[str, Any], m: Masker) -> DiagnoseResult:
    record["checks"] = [{"check": c.name, "status": c.status, "why": c.why,
                         "fix": PRESCRIPTIONS[c.failure] if c.failure else None} for c in res.checks]
    base = paths.diagnose / res.diagnose_id
    atomic_write_text(base.with_suffix(".json"), json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(base.with_suffix(".md"), render_md(record, m))
    res.json_path = str(base.with_suffix(".json").relative_to(paths.root))
    res.md_path = str(base.with_suffix(".md").relative_to(paths.root))
    failed = sum(1 for c in res.checks if c.ok is False)
    res.lines = [f"diagnose {res.diagnose_id}: {failed} of {len(res.checks)} checks failed (against the notes and your rules)"]
    for c in res.checks:
        res.lines.append(f"  {c.status} {c.name}: {c.why}")
        if c.failure:
            res.lines.append(f"       fix: {PRESCRIPTIONS[c.failure]}")
    j = record.get("check")
    if j:
        res.lines.append(f"  closest: {m.title(j['closest_slug'])} ({j['closeness']}); weakness: {m.text(j['weakness'])}; "
                         f"score {j['score']}")
    if res.stopped:
        res.lines.append(f"  paused: {res.stopped}. Run the same command later; finished calls are cached.")
    res.lines.append(f"report -> {res.md_path} (private: data/diagnose/ never goes to the public repo)")
    return res


def render_md(record: dict[str, Any], m: Masker) -> str:
    lines = [f"# Diagnosis {record['diagnose_id']}", "", f"*{record['created_at'][:10]}; from {record['source']}*", "",
             "## Your concept", "", record["concept"], ""]
    note = record.get("note")
    if note:
        e, kit = note["engine"], note["power_kit"]
        lines += ["## As a note", "", f"**Premise.** {note['premise']}", "",
                  "**Engine.** " + "; ".join(f"{k}: {e.get(k)}" for k in ENGINE), "",
                  "**Profile.** " + ", ".join(f"{k} {note.get(k)}" for k in ENUMS), "",
                  f"**MC edge.** {note['mc_edge']}", "",
                  f"**Power kit.** Medium: {kit.get('medium')}. Functions: {' / '.join(kit.get('functions') or [])}. "
                  f"Tools: {' / '.join(kit.get('tools') or [])}. Limits: {kit.get('limits')}", "",
                  "**What it can't survive without.** " + " ".join(f"({i}) {el.get('element')}"
                                                                   for i, el in enumerate(note.get("elements") or [], 1)), ""]
    j = record.get("check")
    if j:
        lines += [f"**Closest note.** {m.title(j['closest_slug'])} ({j['closeness']}: {m.text(j['closeness_reason'])})", "",
                  f"**Biggest weakness.** {m.text(j['weakness'])}", "", f"**Score.** {j['score']} of 100", ""]
    lines += ["## Checks (against the notes and steering/rules.yaml)", "", "| Check | Result | Why | Fix |", "|---|---|---|---|"]
    for c in record["checks"]:
        lines.append(f"| {c['check']} | {c['status']} | {str(c['why']).replace('|', '/')} | {c['fix'] or ''} |")
    return "\n".join(lines) + "\n"
