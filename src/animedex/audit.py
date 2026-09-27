"""`make audit` and `make audit-report` (controls A7; owner rulings 2026-09-27).

audit: samples `size` (10) random load-bearing-eligible atoms, seeded by the date, each with its
evidence trail: the atom's text, every evidence ref resolved to the profile field, moment or episode
it names (with its verification and source URL), and the CHECK verdict history. Written to
eval/audit/audit_<date>.yaml (git-ignored; backed up to the private data repo) with a blank `mark:`
per atom for Kingsley: true | plausible | wrong. An existing sheet is never overwritten: it may hold
marks. Owner guard: while eval/gold/BLIND.yaml is pending, gold titles are never sampled (partner
titles are).

audit-report: reads every sheet and writes build/reports/audit.md with
- the wrong rate per audit date (wrong / marked), so it can be followed over time;
- the extractor-critic disagreement per P2 run: the share of checked atoms whose first CHECK verdict
  was not ACCEPT, grouped by the P2 run that extracted them. Atoms CHECK rejected live in
  quarantine, so they are counted from there. Counts only, with no atom text.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from animedex.eligibility import eligible_atom_ids
from animedex.gold import masked_titles
from animedex.guards import load_corpus
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore

MARKS = ("true", "plausible", "wrong")
MARK_HINT = "mark:   # true | plausible | wrong"


class AuditError(ValueError):
    pass


@dataclass
class AuditResult:
    path: str
    sampled: int
    eligible: int
    gold_excluded: int


def audit_dir(paths: Paths) -> Path:
    return paths.root / "eval" / "audit"


def atom_text(a: dict[str, Any]) -> str:
    if a["atom_kind"] == "effect":
        e = a["effect"]
        return f"{e['element']} -> {e['feeling']}, because {e['because']} (rival: {e['rival_because']})"
    g = a["engine"]
    return (f"{g['agent']} wants {g['goal']} but {g['constraint']}; chooses {g['strategy']}; gets {g['benefit']} "
            f"and pays {g['cost']}; dilemma: {g['dilemma']}; question: {g['dramatic_question']}")


def _refs(a: dict[str, Any]) -> list[str]:
    refs = list(a.get("evidence_refs") or [])
    element = ((a.get("effect") or {}).get("element_ref") or {})
    for extra in (element.get("field"), element.get("moment_id")):
        if extra and extra not in refs:
            refs.append(extra)
    return refs


def resolve_ref(ref: str, title: dict[str, Any] | None, moments: dict[str, dict[str, Any]],
                episodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if ref in moments:
        m = moments[ref]
        return {"ref": ref, "kind": "moment", "text": m["description"], "why_it_hit": m["why_it_hit"],
                "verification": m["verification"], "source": m.get("source_ref")}
    if ref in episodes:
        e = episodes[ref]
        return {"ref": ref, "kind": "episode", "text": e["summary"], "verification": e["verification"],
                "source": e.get("source_ref")}
    if title and "." in ref:
        block, name = ref.split(".", 1)
        fv = (title.get(block) or {}).get(name)
        if isinstance(fv, dict):
            out = {"ref": ref, "kind": "field", "value": fv.get("value"), "verification": fv.get("verification"),
                   "source": fv.get("source_ref")}
            if fv.get("condition"):
                out["condition"] = fv["condition"]
            return out
    return {"ref": ref, "kind": "unresolved"}


def check_history(checks: list[dict[str, Any]], atom_id: str) -> list[dict[str, Any]]:
    mine = [c for c in checks if c["target_id"] == atom_id]
    mine.sort(key=lambda c: (c["provenance"].get("run_id", ""), c["provenance"].get("created_at", ""),
                             c["target_type"]))
    return [{"target": c["target_type"], "verdict": c["verdict"], "reasons": list(c.get("reasons") or []),
             "run_id": c["provenance"].get("run_id")} for c in mine]


def run_audit(paths: Paths, *, date: str | None = None, size: int = 10) -> AuditResult:
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    path = audit_dir(paths) / f"audit_{date}.yaml"
    rel = path.relative_to(paths.root)
    if path.exists():
        raise AuditError(f"{rel} already exists; it may hold your marks, so it is never overwritten")
    state = CanonicalStore(paths).state()
    gold = {t for t, e in load_corpus(paths).items() if "gold" in e.role_tags}
    hidden = masked_titles(paths, gold)  # owner guard: no gold title while the blind is pending
    eligible = sorted(eligible_atom_ids(state))
    allowed = [a for a in eligible if a.split(".")[0] not in hidden]
    if not allowed:
        raise AuditError(f"no eligible atoms to audit ({len(eligible)} eligible, all on gold titles while the "
                         "blind is pending)" if eligible else "no eligible atoms yet: run P2-P4 and CHECK first")
    picked = sorted(random.Random(f"audit:{date}").sample(allowed, min(size, len(allowed))))
    atoms = {m["atom_id"]: m for m in state.get("mechanism", [])}
    titles = {t["title_id"]: t for t in state.get("title", [])}
    moments = {m["moment_id"]: m for m in state.get("moment", [])}
    episodes = {e["episode_id"]: e for e in state.get("episode", [])}
    entries = []
    for aid in picked:
        a = atoms[aid]
        entries.append({"atom_id": aid, "title_id": a["title_id"], "kind": a["atom_kind"], "module": a["module"],
                        "p2_run": a["provenance"].get("run_id"), "text": atom_text(a),
                        "evidence": [resolve_ref(r, titles.get(a["title_id"]), moments, episodes) for r in _refs(a)],
                        "checks": check_history(state.get("check", []), aid), "mark": None})
    head = [f"# Audit {date}: {len(picked)} load-bearing-eligible atoms with their evidence trails.",
            "# For each atom, set mark to true (the evidence supports it), plausible (it might, the evidence is thin)",
            "# or wrong (the evidence does not support it). Then run `make audit-report`.",
            f"# Sampled from {len(allowed)} eligible atom(s)"
            + (f"; {len(eligible) - len(allowed)} on gold titles skipped while the blind is pending." if hidden else ".")]
    body = yaml.safe_dump({"date": date, "atoms": entries}, sort_keys=False, allow_unicode=True, width=110)
    body = body.replace("mark: null", MARK_HINT)
    atomic_write_text(path, "\n".join(head) + "\n" + body)
    return AuditResult(str(rel), len(picked), len(eligible), len(eligible) - len(allowed))


# ---------------------------------------------------------------- the report
def _mark(value: Any) -> str:
    if value is True:
        return "true"
    if value is None or (isinstance(value, str) and not value.strip()):
        return "blank"
    text = str(value).strip().lower()
    return text if text in MARKS else "invalid"


def sheet_rows(paths: Paths) -> list[dict[str, Any]]:
    rows = []
    for f in sorted(audit_dir(paths).glob("audit_*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        marks = Counter(_mark(a.get("mark")) for a in data.get("atoms") or [])
        marked = sum(marks[m] for m in MARKS)
        rows.append({"date": str(data.get("date") or f.stem.removeprefix("audit_")), "atoms": sum(marks.values()),
                     "marked": marked, **{m: marks[m] for m in MARKS}, "invalid": marks["invalid"],
                     "wrong_rate": round(marks["wrong"] / marked, 3) if marked else None})
    return rows


def disagreement_by_run(paths: Paths) -> dict[str, dict[str, int]]:
    """P2 run id -> atoms checked, first verdict not ACCEPT, rejected (from quarantine)."""
    state = CanonicalStore(paths).state()
    atoms = {m["atom_id"]: m for m in state.get("mechanism", [])}
    first: dict[str, dict[str, Any]] = {}
    for c in sorted((c for c in state.get("check", []) if c["target_type"] == "mechanism"),
                    key=lambda c: (c["provenance"].get("run_id", ""), c["provenance"].get("created_at", ""))):
        first.setdefault(c["target_id"], c)
    runs: dict[str, Counter] = {}
    for aid, c in first.items():
        run = str(((atoms.get(aid) or {}).get("provenance") or {}).get("run_id") or "unknown")
        tally = runs.setdefault(run, Counter())
        tally["checked"] += 1
        tally["disagreed"] += int(c["verdict"] != "ACCEPT")
    rejected = paths.quarantine / "CHECK" / "mechanism"
    for f in sorted(rejected.glob("*.json")) if rejected.is_dir() else []:
        entry = json.loads(f.read_text(encoding="utf-8"))
        rec = entry.get("record") or {}
        aid = rec.get("atom_id") or entry.get("record_id")
        if aid in first:
            continue
        tally = runs.setdefault(str((rec.get("provenance") or {}).get("run_id") or "unknown"), Counter())
        tally["checked"] += 1
        tally["disagreed"] += 1
        tally["rejected"] += 1
    return {run: {k: int(t[k]) for k in ("checked", "disagreed", "rejected")} for run, t in sorted(runs.items())}


def render_report(rows: list[dict[str, Any]], runs: dict[str, dict[str, int]]) -> str:
    lines = ["# Audit report", "",
             "Built from `eval/audit/audit_*.yaml` (your marks) and canonical CHECK records. Counts only.", "",
             "## Wrong rate over time", ""]
    if rows:
        lines += ["| Audit date | Atoms | Marked | True | Plausible | Wrong | Wrong rate |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            rate = f"{r['wrong_rate']:.0%}" if r["wrong_rate"] is not None else "not marked yet"
            lines.append(f"| {r['date']} | {r['atoms']} | {r['marked']} | {r['true']} | {r['plausible']} | "
                         f"{r['wrong']} | {rate} |")
        invalid = sum(r["invalid"] for r in rows)
        if invalid:
            lines += ["", f"{invalid} mark(s) are not true, plausible or wrong; they are left out of the rates."]
    else:
        lines.append("No audit sheets yet. Run `make audit`, then mark each atom.")
    lines += ["", "## Extractor-critic disagreement per P2 run", "",
              "The share of atoms whose first CHECK verdict was not ACCEPT, by the P2 run that extracted them.", ""]
    if runs:
        lines += ["| P2 run | Atoms checked | First verdict not ACCEPT | Rejected | Disagreement |", "|---|---|---|---|---|"]
        for run, t in runs.items():
            rate = f"{t['disagreed'] / t['checked']:.0%}" if t["checked"] else "n/a"
            lines.append(f"| {run} | {t['checked']} | {t['disagreed']} | {t['rejected']} | {rate} |")
    else:
        lines.append("No checked atoms yet.")
    return "\n".join(lines) + "\n"


def write_audit_report(paths: Paths) -> tuple[Path, list[dict[str, Any]], dict[str, dict[str, int]]]:
    rows, runs = sheet_rows(paths), disagreement_by_run(paths)
    out = paths.reports / "audit.md"
    atomic_write_text(out, render_report(rows, runs))
    return out, rows, runs
