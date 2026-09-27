"""ANALYZE (05): coverage report, gap cells with coverage-adequacy flags, imported/export lanes, the
graveyard index, and saved answers for every competency question.

Outputs (all under build/, rebuilt from canonical data):
- cq_answers/<CQ-ID>.json + hashes.json: regression answers (AC-21, AC-24);
- graveyard.json: mixed/flop titles with their structural + load-bearing combination, failure
  level and reason; only premise-level failures warn (v1.3, AC-23);
- reports/analysis.md: a human summary. Gold titles stay counts-only while the blind is pending;
- stats/analysis.json: the statistics the summary page (`animedex stats`) reads.

Statistics as gates (owner ruling 2026-09-27): zeros are open only by the rule of three (3/n < 0.02);
the grid-gap questions rank their empty cells by expected count (real gaps: expected >= 3, none
observed); fields the agreement eval flagged unreliable (`eval/agreement/reliability.json`) leave the
gap reports; field health (entropy, normalized entropy, mutual information with the outcome) is reported
per enum field, with low-entropy fields flagged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import duckdb

from animedex.analyze.cq import (
    GAP_RANK,
    ZERO_DIMS,
    adequacy,
    answer_all,
    census_adequacy,
    save_answers,
)
from animedex.build.duckdb_build import build
from animedex.config import Settings
from animedex.eligibility import eligible_atom_ids
from animedex.gold import masked_titles
from animedex.guards import load_corpus
from animedex.ontology import get_cqs, get_vocab
from animedex.paths import Paths
from animedex.statgates import (
    MIN_OPEN_N,
    reliability_file,
    unreliable_fields,
    why_unreliable,
    write_stage,
)
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
    real_gaps: int = 0
    low_entropy: list[str] = field(default_factory=list)
    unreliable: list[str] = field(default_factory=list)
    lanes: dict[str, int] = field(default_factory=dict)


GAP_TITLES = {"CQ-G01": "power gate × cost of power", "CQ-G04": "progression × fight medium",
              "CQ-G10": "power gate × cost of power, census", "CQ-G17": "set structure × subset mechanic"}
UNSURPRISING_SHOWN = 12


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _coverage_md(stats_: dict[str, Any]) -> list[str]:
    lines = ["## Coverage by module", "",
             f"A zero is open only when the rule-of-three bound 3/n is below 0.02, so n must be at least {MIN_OPEN_N} "
             "(titles with the module and good field completion, or census rows with a power system).", "",
             "| Module | Titles with it (completion ≥ threshold) | Rule-of-three bound 3/n | Zeros open |",
             "|---|---|---|---|"]
    for m, cov in stats_["modules"].items():
        if m == "core":
            continue
        lines.append(f"| {m} | {cov['n_adequate_titles']} | {cov['rule_of_three']:.3f} | {_yes(cov['adequate'])} |")
    c = stats_["census"]
    lines.append(f"| census (rows with a power system) | {c['n_powered_census_rows']} | {c['rule_of_three']:.3f} | "
                 f"{_yes(c['adequate'])} |")
    return lines


def _gap_md(cq_id: str, answer: dict[str, Any]) -> list[str]:
    lines = [f"## Gap cells: {GAP_TITLES[cq_id]} ({len(answer['rows'])} empty; zeros are "
             f"**{answer.get('zeros_are', 'not flagged')}**)", ""]
    if answer.get("excluded_fields"):
        return lines + ["Excluded from the gap reports: unreliable field "
                        + "; ".join(answer["excluded_fields"]) + " (agreement eval, kappa below 0.6).", ""]
    g = answer.get("gap_ranking") or {}
    x, y = g.get("x", "x").split(".")[-1], g.get("y", "y").split(".")[-1]
    lines += [f"Ranked by the count expected under independence, n × p(x) × p(y), over the {g.get('n', 0)} "
              f"{'census rows' if g.get('source') == 'census' else 'titles'} with both fields. A real gap is expected "
              "3 or more times and never seen; the rest are unsurprising.", "",
              "### Real gaps", ""]
    if g.get("real_gaps"):
        lines += [f"| {x} | {y} | Expected |", "|---|---|---|"]
        lines += [f"| {a} | {b} | {e:.1f} |" for a, b, e in g["real_gaps"]]
    else:
        lines.append("- none")
    rest = g.get("unsurprising") or []
    shown = ", ".join(f"{a} × {b} ({e:.1f})" for a, b, e in rest[:UNSURPRISING_SHOWN])
    lines += ["", f"Unsurprising (expected under 3): {len(rest)} cell(s)" + (f"; highest first: {shown}" if shown else ""),
              ""]
    return lines


def _health_md(health: list[dict[str, Any]]) -> list[str]:
    lines = ["## Field health", "",
             "Entropy per enum field (bits; normalized by the number of allowed values, so 0 never varies and 1 is "
             "uniform), and mutual information with the outcome label over the titles that have one. Normalized "
             "entropy under 0.5 is flagged low.", "",
             "| Field | Titles | Entropy | Normalized | Low entropy | MI with outcome | Reliability |",
             "|---|---|---|---|---|---|---|"]
    for h in health:
        if not h["n"]:
            continue
        mi = ("n/a" if h["mi_outcome"] is None else
              f"{h['mi_outcome']:.3f} ({h['n_with_outcome']} title{'' if h['n_with_outcome'] == 1 else 's'})")
        lines.append(f"| `{h['path']}` | {h['n']} | {h['entropy']:.3f} | {h['normalized_entropy']:.3f} | "
                     f"{'LOW' if h['low_entropy'] else ''} | {mi} | {'unreliable' if h['unreliable'] else ''} |")
    empty = sum(1 for h in health if not h["n"])
    if empty:
        lines += ["", f"{empty} enum field(s) have no values yet."]
    return lines


def _reliability_md(unreliable: dict[str, dict[str, Any]], have_file: bool) -> list[str]:
    lines = ["## Reliability", ""]
    if not have_file:
        return lines + ["No reliability report yet (`eval/agreement/reliability.json`): no field is excluded.", ""]
    if not unreliable:
        return lines + ["No field is flagged unreliable (kappa below 0.6).", ""]
    return lines + ["Flagged unreliable and excluded from the gap reports and from ideation's novelty pairs:", "",
                    *[f"- {why_unreliable(p, v)}" for p, v in unreliable.items()], ""]


def _md(answers: dict[str, dict[str, Any]], graveyard: list[dict[str, Any]], hidden: set[str],
        coverage: list[dict[str, Any]], stats_: dict[str, Any] | None = None) -> str:
    stats_ = stats_ or {}
    lines = ["# ANIMEDEX analysis", "",
             "Built from canonical data. Gold titles stay counts-only until Kingsley says "
             "\"annotations done\" or \"annotations waived\".", ""]
    if stats_.get("adequacy"):
        lines += _coverage_md(stats_["adequacy"])
    lines += ["", "## Titles", "", "| Title | Passes done | Field completion |", "|---|---|---|"]
    for c in sorted(coverage, key=lambda c: c["title_id"]):
        lines.append(f"| {c['title_id']} | {', '.join(c.get('passes_done', []))} | {c['field_completion']:.2f} |")
    lines.append("")
    lines += _reliability_md(stats_.get("unreliable") or {}, bool(stats_.get("reliability_file")))
    for cq_id in GAP_RANK:
        if cq_id in answers:
            lines += _gap_md(cq_id, answers[cq_id])
    lines += _health_md(stats_.get("field_health") or [])
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
    from animedex.analyze.health import field_health

    vocab, cqs = get_vocab(paths), get_cqs(paths)
    unreliable = unreliable_fields(paths)
    build(paths)
    con = duckdb.connect(str(paths.build_db), read_only=True)
    try:
        answers = answer_all(con, vocab, cqs, settings, unreliable)
        health = field_health(con, vocab, unreliable)
        modules = adequacy(con, settings, ["core", *vocab.module_names])
        census = census_adequacy(con)
    finally:
        con.close()
    save_answers(answers, paths.build / "cq_answers")
    state = CanonicalStore(paths).state()
    graveyard = graveyard_index(state)
    atomic_write_text(paths.build / "graveyard.json", json.dumps(graveyard, indent=2, sort_keys=True) + "\n")
    corpus = load_corpus(paths)
    hidden = masked_titles(paths, {t for t, e in corpus.items() if "gold" in e.role_tags})
    stats_ = {"adequacy": {"modules": modules, "census": census}, "unreliable": unreliable,
              "reliability_file": reliability_file(paths).is_file(), "field_health": health,
              "zeros_are": {cq: answers[cq].get("zeros_are") for cq in ZERO_DIMS if cq in answers},
              "gaps": {cq: answers[cq].get("gap_ranking") or {"excluded": answers[cq].get("excluded_fields", [])}
                       for cq in GAP_RANK if cq in answers}}
    atomic_write_text(paths.reports / "analysis.md", _md(answers, graveyard, hidden, state.get("coverage", []), stats_))
    write_stage(paths, "analysis", stats_)
    g01 = answers["CQ-G01"]
    return AnalyzeResult(answered=len(answers), graveyard=len(graveyard), empty_cells=len(g01["rows"]),
                         zeros_are=str(g01.get("zeros_are")),
                         real_gaps=len((g01.get("gap_ranking") or {}).get("real_gaps") or []),
                         low_entropy=[h["path"] for h in health if h["low_entropy"]], unreliable=list(unreliable),
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
            second = save_answers(answer_all(con, vocab, get_cqs(paths), settings, unreliable_fields(paths)),
                                  tmp / "cq_answers")
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    diffs = {k: (first.get(k, ""), second.get(k, "")) for k in sorted(set(first) | set(second))
             if first.get(k) != second.get(k)}
    return not diffs, diffs

