"""Evaluation (09): coverage ledger rows, web correction rate per field (AC-13), calibration per field
(statistics as gates, item 6), and P1 enum agreement across two runs (AC-12). Pure functions over
canonical records, except `stored_drafts`, which reads the response cache."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from animedex import stats
from animedex.ontology import Vocab

VERIFIED = ("web_confirmed", "web_corrected", "gathered")  # gathered: sourced at extraction (v1.7)


ABSENT = {"value": None, "verification": "not_required"}  # a field the record's vocab predates


def active_paths(record: dict[str, Any], vocab: Vocab) -> list[str]:
    return [f.path for f in vocab.lens_fields() if f.block == "core" or f.block in record.get("modules_active", [])]


def _present(record: dict[str, Any], path: str) -> bool:
    block, _, name = path.partition(".")
    return name in (record.get(block) or {})


def _fv(record: dict[str, Any], path: str) -> dict[str, Any]:
    """A field's value dict; a field absent from an older record (vocab 1.5.0 `since`) counts as unknown."""
    block, _, name = path.partition(".")
    return record[block].get(name) or ABSENT


def coverage_row(record: dict[str, Any], vocab: Vocab) -> dict[str, Any]:
    """Coverage ledger fields for one title (04): completion, verified share, passes done. A field the
    record's vocab predates counts as not filled, so a zero on a new field is not read as covered."""
    paths = active_paths(record, vocab)
    values = [_fv(record, p) for p in paths]
    flagged = [v for v in values if v["verification"] != "not_required"]
    verified = [v for v in flagged if v["verification"] in VERIFIED]
    passes = ["P1"] + (["VERIFY"] if flagged and all(v["verification"] != "unverified" for v in flagged) else [])
    return {
        "title_id": record["title_id"],
        "passes_done": passes,
        "field_completion": round(sum(v["value"] is not None for v in values) / len(values), 4),
        "verified_share": round(len(verified) / len(flagged), 4) if flagged else 0.0,
        "modules_active": list(record.get("modules_active", [])),
    }


@dataclass
class RateRow:
    path: str
    titles: int
    flagged: int
    confirmed: int
    corrected: int
    unresolved: int

    @property
    def correction_rate(self) -> float | None:
        checked = self.confirmed + self.corrected
        return round(self.corrected / checked, 4) if checked else None


def verify_rates(titles: list[dict[str, Any]], vocab: Vocab) -> list[RateRow]:
    """Per P1 field: how often it was flagged for VERIFY and how often the web corrected it (AC-13)."""
    rows: dict[str, RateRow] = {f.path: RateRow(f.path, 0, 0, 0, 0, 0) for f in vocab.lens_fields()}
    for t in titles:
        for path in (p for p in active_paths(t, vocab) if _present(t, p)):
            v, row = _fv(t, path)["verification"], rows[path]
            row.titles += 1
            if v != "not_required":
                row.flagged += 1
            row.confirmed += v == "web_confirmed"
            row.corrected += v == "web_corrected"
            row.unresolved += v == "unresolved"
    return [r for r in rows.values() if r.titles]


def verify_rates_markdown(rows: list[RateRow], calibration: list[CalibrationRow] | None = None) -> str:
    lines = ["# Web correction rate per field (AC-13)", "",
             "| Field | Titles | Flagged | Confirmed | Corrected | Unresolved | Correction rate |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (-(r.correction_rate or 0), r.path)):
        rate = "n/a" if r.correction_rate is None else f"{r.correction_rate:.2f}"
        lines.append(f"| `{r.path}` | {r.titles} | {r.flagged} | {r.confirmed} | {r.corrected} | {r.unresolved} | {rate} |")
    if calibration is not None:
        lines += ["", *calibration_markdown(calibration)]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- calibration (statistics as gates, item 6)
CORRECT = {"web_confirmed": 1, "gathered": 1, "web_corrected": 0}  # unresolved and unchecked fields stay out


@dataclass
class CalibrationRow:
    path: str
    n: int = 0
    brier: float | None = None
    mean_conf: float | None = None
    right_share: float | None = None
    from_draft: int = 0   # confidence read from the stored P1/INTERPRET draft, before any check (D-022)
    floored: int = 0      # draft gone from the cache: the stored confidence, floored at verify.conf_threshold

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "n": self.n, "brier": self.brier, "mean_conf": self.mean_conf,
                "right_share": self.right_share, "from_draft": self.from_draft, "floored": self.floored}


def _draft_conf(draft: dict[str, Any], path: str) -> float | None:
    """The model's own confidence for a field in its stored draft (a null value is unknown: conf 0)."""
    block, _, name = path.partition(".")
    fv = (draft.get(block) or {}).get(name) if isinstance(draft.get(block), dict) else None
    if not isinstance(fv, dict) or fv.get("conf") is None:
        return None
    return 0.0 if fv.get("value") is None else float(fv["conf"])


def calibration(titles: list[dict[str, Any]], vocab: Vocab, drafts: dict[str, dict[str, Any]] | None = None
                ) -> list[CalibrationRow]:
    """Per field: the Brier score of the extraction's confidence against verified correctness (web_confirmed or
    gathered = right, web_corrected = wrong; unresolved left out). VERIFY and INTERPRET's gathered step raise a
    checked field's stored confidence to at least `verify.conf_threshold`, so the confidence comes from the
    stored draft in `drafts` (title_id -> the P1/INTERPRET answer) when there is one (D-022)."""
    drafts = drafts or {}
    pairs: dict[str, list[tuple[float, int]]] = {}
    rows: dict[str, CalibrationRow] = {}
    for t in sorted(titles, key=lambda t: t["title_id"]):
        draft = drafts.get(t["title_id"]) or {}
        for path in (p for p in active_paths(t, vocab) if _present(t, p)):
            fv = _fv(t, path)
            right = CORRECT.get(fv["verification"])
            if right is None:
                continue
            row = rows.setdefault(path, CalibrationRow(path))
            conf = _draft_conf(draft, path)
            if conf is None:
                conf, row.floored = float(fv["conf"]), row.floored + 1
            else:
                row.from_draft += 1
            pairs.setdefault(path, []).append((conf, right))
    for path, row in rows.items():
        got = pairs[path]
        row.n, row.brier = len(got), stats.brier(got)
        row.mean_conf = round(sum(c for c, _ in got) / len(got), 4)
        row.right_share = round(sum(y for _, y in got) / len(got), 4)
    return sorted(rows.values(), key=lambda r: r.path)


def calibration_overall(rows: list[CalibrationRow]) -> dict[str, Any]:
    """One Brier score over every checked field, with how many confidences were floored."""
    total = sum(r.n for r in rows)
    return {"checked": total, "floored": sum(r.floored for r in rows),
            "brier": round(sum((r.brier or 0.0) * r.n for r in rows) / total, 4) if total else None}


def calibration_markdown(rows: list[CalibrationRow]) -> list[str]:
    lines = ["## Calibration: Brier score of confidence against verified correctness, per field", "",
             "Right = web_confirmed or gathered; wrong = web_corrected; unresolved fields are left out. 0 is perfect, "
             "and a constant 0.5 scores 0.25. The confidence is the extraction model's own, read from its stored "
             "draft; VERIFY and INTERPRET raise a checked field's stored confidence to at least the verify threshold, "
             "so where the draft is gone from the cache the stored (floored) value stands in and is counted.", ""]
    if not rows:
        return lines + ["No verified fields yet."]
    lines += ["| Field | Checked | Brier | Mean confidence | Share right | Floored |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (-(r.brier or 0.0), r.path)):
        lines.append(f"| `{r.path}` | {r.n} | {r.brier:.3f} | {r.mean_conf:.2f} | {r.right_share:.2f} | {r.floored} |")
    o = calibration_overall(rows)
    lines += ["", f"Overall: Brier {o['brier']:.3f} over {o['checked']} checked field(s); {o['floored']} confidence(s) "
              "floored (no stored draft)."]
    return lines


def stored_drafts(cache_root: Path, titles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each title's P1 or INTERPRET answer, read from the response cache through the record's provenance
    cache key (no call is made). A title whose draft is gone is left out."""
    from animedex.store.cache import ResponseCache

    cache = ResponseCache(cache_root)
    out: dict[str, dict[str, Any]] = {}
    for t in titles:
        key = str((t.get("provenance") or {}).get("cache_key") or "")
        if not key:
            continue
        for pass_ in ("INTERPRET", "P1"):
            hit = cache.get(pass_, key)
            if hit and isinstance(hit.get("json"), dict):
                out[t["title_id"]] = hit["json"]
                break
    return out


def p1_agreement(run_a: list[dict[str, Any]], run_b: list[dict[str, Any]], vocab: Vocab) -> dict[str, Any]:
    """Enum-field agreement between two P1 runs over the titles both runs profiled (AC-12)."""
    a, b = {t["title_id"]: t for t in run_a}, {t["title_id"]: t for t in run_b}
    enum_paths = [f.path for f in vocab.lens_fields() if f.kind == "enum"]
    per_field: dict[str, list[int]] = {p: [0, 0] for p in enum_paths}
    per_title: dict[str, list[int]] = {}
    for tid in sorted(set(a) & set(b)):
        shared = [p for p in enum_paths if p in set(active_paths(a[tid], vocab)) & set(active_paths(b[tid], vocab))
                  and _present(a[tid], p) and _present(b[tid], p)]
        per_title[tid] = [0, 0]
        for p in shared:
            same = int(_fv(a[tid], p)["value"] == _fv(b[tid], p)["value"])
            per_field[p][0] += same
            per_field[p][1] += 1
            per_title[tid][0] += same
            per_title[tid][1] += 1
    total_same = sum(v[0] for v in per_field.values())
    total = sum(v[1] for v in per_field.values())
    return {
        "titles": sorted(per_title),
        "overall": round(total_same / total, 4) if total else None,
        "comparisons": total,
        "per_field": {p: round(s / n, 4) for p, (s, n) in per_field.items() if n},
        "per_title": {t: round(s / n, 4) for t, (s, n) in per_title.items() if n},
    }


def latest_per_title(run_files: list[Any], ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """AC-12 second runs may cover the gold titles one at a time: the newest record per title wins
    (run ids sort by time). Returns the records and the runs they came from."""
    from animedex.store.jsonl import read_jsonl

    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for f in sorted(run_files, key=lambda p: p.parent.name):
        for t in read_jsonl(f):
            if t["title_id"] in ids:
                latest[t["title_id"]] = (f.parent.name, t)
    return [t for _, t in latest.values()], sorted({r for r, _ in latest.values()})

