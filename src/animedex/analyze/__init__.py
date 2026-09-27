"""ANALYZE (05): coverage report, gap cells with coverage-adequacy flags, imported/export lanes, the
graveyard index, and saved answers for every competency question.

Outputs (all under build/, rebuilt from canonical data):
- cq_answers/<CQ-ID>.json + hashes.json: regression answers (AC-21, AC-24);
- graveyard.json: mixed/flop titles with their structural + load-bearing combination, failure
  level and reason; only premise-level failures warn (v1.3, AC-23);
- reports/analysis.md: a human summary. Gold titles stay counts-only while the blind is pending.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import duckdb

from animedex.analyze.cq import answer_all, save_answers
from animedex.build.duckdb_build import build
from animedex.config import Settings
from animedex.eligibility import eligible_atom_ids
from animedex.gold import masked_titles
from animedex.guards import load_corpus
from animedex.ontology import get_cqs, get_vocab
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore

STRUCTURAL = ("power_combat.gate", "power_combat.cost_of_power", "power_combat.progression",
              "power_combat.visible_counter", "power_combat.fight_medium", "relationships.power_is")


def structural_set(record: dict[str, Any]) -> list[str]:
    out = []
    for path in STRUCTURAL:
        block, name = path.split(".")
        value = ((record.get(block) or {}).get(name) or {}).get("value")
        if value and not str(value).startswith("other"):
            out.append(f"{path}={value}")
    return sorted(out)


def graveyard_index(state: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Mixed/flop titles and what their failure was made of. `warns` only for premise-level failures."""
    eligible = eligible_atom_ids(state)
    concepts: dict[str, set[str]] = {}
    for t in state.get("transfer", []):
        if t["source_atom_id"] in eligible:
            concepts.setdefault(t["source_atom_id"].split(".")[0], set()).update(t["bridge"])
    outcomes = {o["title_id"]: o for o in state.get("outcome", [])}
    rows = []
    for title in sorted(state.get("title", []), key=lambda r: r["title_id"]):
        o = outcomes.get(title["title_id"]) or {}
        label = o.get("label") or ((title.get("core") or {}).get("outcome") or {}).get("value")
        if label not in ("mixed", "flop"):
            continue
        level = o.get("failure_level") or "unknown"
        rows.append({"title_id": title["title_id"], "label": label, "failure_level": level,
                     "failure_reason": o.get("failure_reason"), "structural": structural_set(title),
                     "bridge": sorted(concepts.get(title["title_id"], set())), "warns": level == "premise",
                     "t5_evidence": level == "execution"})
    return rows


@dataclass
class AnalyzeResult:
    answered: int = 0
    graveyard: int = 0
    empty_cells: int = 0
    zeros_are: str = ""
    lanes: dict[str, int] = field(default_factory=dict)


def _md(answers: dict[str, dict[str, Any]], graveyard: list[dict[str, Any]], hidden: set[str],
        coverage: list[dict[str, Any]]) -> str:
    g01, g07 = answers["CQ-G01"], answers["CQ-G07"]
    need = g07.get("min_needed", 5)
    lines = ["# ANIMEDEX analysis", "",
             "Built from canonical data. Gold titles stay counts-only until Kingsley says "
             "\"annotations done\" or \"annotations waived\".", "", "## Coverage by module", "",
             "| Module | Titles with it (completion ≥ threshold) | Needed for a trustworthy zero |", "|---|---|---|"]
    lines += [f"| {m} | {n} | {need} |" for m, n in g07["rows"]]
    lines += ["", "## Titles", "", "| Title | Passes done | Field completion |", "|---|---|---|"]
    for c in sorted(coverage, key=lambda c: c["title_id"]):
        lines.append(f"| {c['title_id']} | {', '.join(c.get('passes_done', []))} | {c['field_completion']:.2f} |")
    lines += ["", f"## Gap cells: power gate × cost of power ({len(g01['rows'])} empty; zeros are "
                  f"**{g01.get('zeros_are')}**)", ""]
    lines += [f"- {gate} × {cost}" for gate, cost in g01["rows"][:40]] or ["- none"]
    lines += ["", "## Graveyard (mixed and flop titles)", "",
              "| Title | Label | Failure level | Warns | Reason |", "|---|---|---|---|---|"]
    for g in graveyard:
        if g["title_id"] in hidden:
            lines.append(f"| {g['title_id']} | (gold: hidden) | (hidden) | (hidden) | (hidden) |")
        else:
            lines.append(f"| {g['title_id']} | {g['label']} | {g['failure_level']} | {'yes' if g['warns'] else 'no'} | "
                         f"{g['failure_reason'] or ''} |")
    for cq, title in (("CQ-G05", "Imported lanes (≥2 non-anime titles, 0 anime)"),
                      ("CQ-G06", "Export lanes (anime, never Western)")):
        lines += ["", f"## {title}", ""]
        lines += [f"- {r[0]} ({r[1]} vs {r[2]})" for r in answers[cq]["rows"]] or ["- none yet"]
    lines += ["", f"## Competency questions: {len(answers)} answered (build/cq_answers/)", ""]
    return "\n".join(lines) + "\n"


def run_analyze(paths: Paths, settings: Settings) -> AnalyzeResult:
    vocab, cqs = get_vocab(paths), get_cqs(paths)
    build(paths)
    con = duckdb.connect(str(paths.build_db), read_only=True)
    try:
        answers = answer_all(con, vocab, cqs, settings)
    finally:
        con.close()
    save_answers(answers, paths.build / "cq_answers")
    state = CanonicalStore(paths).state()
    graveyard = graveyard_index(state)
    atomic_write_text(paths.build / "graveyard.json", json.dumps(graveyard, indent=2, sort_keys=True) + "\n")
    corpus = load_corpus(paths)
    hidden = masked_titles(paths, {t for t, e in corpus.items() if "gold" in e.role_tags})
    atomic_write_text(paths.reports / "analysis.md", _md(answers, graveyard, hidden, state.get("coverage", [])))
    return AnalyzeResult(answered=len(answers), graveyard=len(graveyard), empty_cells=len(answers["CQ-G01"]["rows"]),
                         zeros_are=str(answers["CQ-G01"].get("zeros_are")),
                         lanes={"imported": len(answers["CQ-G05"]["rows"]), "export": len(answers["CQ-G06"]["rows"])})


def verify_cq_determinism(paths: Paths, settings: Settings) -> tuple[bool, dict[str, tuple[str, str]]]:
    """AC-24: CQ answers from an independent clean build must hash the same."""
    import shutil
    import tempfile
    from pathlib import Path

    from animedex.build.duckdb_build import build_into

    run_analyze(paths, settings)
    first = json.loads((paths.build / "cq_answers" / "hashes.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="animedex-cq-"))
    try:
        vocab = get_vocab(paths)
        build_into(tmp, paths.canonical, vocab)
        con = duckdb.connect(str(tmp / "animedex.duckdb"), read_only=True)
        try:
            second = save_answers(answer_all(con, vocab, get_cqs(paths), settings), tmp / "cq_answers")
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    diffs = {k: (first.get(k, ""), second.get(k, "")) for k in sorted(set(first) | set(second))
             if first.get(k) != second.get(k)}
    return not diffs, diffs

