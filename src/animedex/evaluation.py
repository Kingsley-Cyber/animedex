"""Evaluation (09): coverage ledger rows, web correction rate per field (AC-13), and P1 enum
agreement across two runs (AC-12). Pure functions over canonical records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from animedex.ontology import Vocab

VERIFIED = ("web_confirmed", "web_corrected")


def active_paths(record: dict[str, Any], vocab: Vocab) -> list[str]:
    return [f.path for f in vocab.lens_fields() if f.block == "core" or f.block in record.get("modules_active", [])]


def _fv(record: dict[str, Any], path: str) -> dict[str, Any]:
    block, _, name = path.partition(".")
    return record[block][name]


def coverage_row(record: dict[str, Any], vocab: Vocab) -> dict[str, Any]:
    """Coverage ledger fields for one title (04): completion, verified share, passes done."""
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
        for path in active_paths(t, vocab):
            v, row = _fv(t, path)["verification"], rows[path]
            row.titles += 1
            if v != "not_required":
                row.flagged += 1
            row.confirmed += v == "web_confirmed"
            row.corrected += v == "web_corrected"
            row.unresolved += v == "unresolved"
    return [r for r in rows.values() if r.titles]


def verify_rates_markdown(rows: list[RateRow]) -> str:
    lines = ["# Web correction rate per field (AC-13)", "",
             "| Field | Titles | Flagged | Confirmed | Corrected | Unresolved | Correction rate |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (-(r.correction_rate or 0), r.path)):
        rate = "n/a" if r.correction_rate is None else f"{r.correction_rate:.2f}"
        lines.append(f"| `{r.path}` | {r.titles} | {r.flagged} | {r.confirmed} | {r.corrected} | {r.unresolved} | {rate} |")
    return "\n".join(lines) + "\n"


def p1_agreement(run_a: list[dict[str, Any]], run_b: list[dict[str, Any]], vocab: Vocab) -> dict[str, Any]:
    """Enum-field agreement between two P1 runs over the titles both runs profiled (AC-12)."""
    a, b = {t["title_id"]: t for t in run_a}, {t["title_id"]: t for t in run_b}
    enum_paths = [f.path for f in vocab.lens_fields() if f.kind == "enum"]
    per_field: dict[str, list[int]] = {p: [0, 0] for p in enum_paths}
    per_title: dict[str, list[int]] = {}
    for tid in sorted(set(a) & set(b)):
        shared = [p for p in enum_paths if p in set(active_paths(a[tid], vocab)) & set(active_paths(b[tid], vocab))]
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
