"""The notes, counted in place: DuckDB reads notes/*.json directly (no build step, nothing copied).

`make analyze` answers the competency questions (ontology/competency_questions.yaml) and ranks each empty
enum pair by the count expected under independence; what the notes do not record is listed as not
tracked. `make export` writes spreadsheets: build/exports/notes.csv and build/exports/cards.csv.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from animedex import stats
from animedex.light.notes import PRINT_MEDIA
from animedex.ontology import CQSet, Vocab
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

# column -> (JSON path, SQL type)
COLUMNS: dict[str, tuple[str, str]] = {
    "slug": ("$.slug", "VARCHAR"), "title": ("$.title", "VARCHAR"), "year": ("$.year", "INTEGER"),
    "medium": ("$.medium", "VARCHAR"), "format": ("$.format", "VARCHAR"),
    "outcome": ("$.outcome.label", "VARCHAR"), "anilist_score": ("$.outcome.anilist_score", "INTEGER"),
    "popularity": ("$.outcome.popularity", "INTEGER"), "adaptation": ("$.outcome.adaptation.status", "VARCHAR"),
    **{k: (f"$.{k}", "VARCHAR") for k in ("gate", "cost_of_power", "progression", "visible_counter", "fight_medium",
                                          "story_engine", "premise", "mc_edge", "villain_type", "setting")},
    **{f"engine_{k}": (f"$.engine.{k}", "VARCHAR") for k in ("goal", "constraint", "strategy", "cost", "dilemma")},
    "power_medium": ("$.power_kit.medium", "VARCHAR"), "power_limits": ("$.power_kit.limits", "VARCHAR"),
}
NOT_TRACKED = ("set_structure", "power_is", "subset mechanics", "characters", "moments and episodes", "atoms and proofs")
GAPS = {"CQ-N02": ("gate", "cost_of_power"), "CQ-N03": ("progression", "visible_counter")}


def _gap_sql(x: str, y: str) -> str:
    return (f"WITH a AS (SELECT unnest(?::VARCHAR[]) AS {x}), b AS (SELECT unnest(?::VARCHAR[]) AS {y}), "
            f"p AS (SELECT {x}, {y}, COUNT(*) AS n FROM notes GROUP BY 1, 2) "
            f"SELECT a.{x}, b.{y} FROM a CROSS JOIN b LEFT JOIN p ON p.{x} = a.{x} AND p.{y} = b.{y} "
            f"WHERE p.n IS NULL ORDER BY 1, 2")


QUERIES: dict[str, str] = {
    "CQ-N01": "SELECT COALESCE(story_engine, 'unknown') AS lane, COALESCE(outcome, 'unknown') AS outcome, COUNT(*) AS n, "
              "string_agg(slug, ', ' ORDER BY slug) AS notes FROM notes GROUP BY 1, 2 ORDER BY 1, 2",
    "CQ-N02": _gap_sql(*GAPS["CQ-N02"]),
    "CQ-N03": _gap_sql(*GAPS["CQ-N03"]),
    "CQ-N05": "SELECT medium, COALESCE(outcome, 'unknown') AS outcome, COUNT(*) AS n FROM notes GROUP BY 1, 2 ORDER BY 1, 2",
    "CQ-P01": "SELECT COALESCE(story_engine, 'unknown') AS lane, medium, title, year, popularity FROM notes "
              f"WHERE medium IN ({', '.join(repr(m) for m in PRINT_MEDIA)}) AND adaptation = 'none' "
              "ORDER BY lane, popularity DESC NULLS LAST, title",
}


def connect(paths: Paths) -> duckdb.DuckDBPyConnection:
    """An in-memory database whose `notes` view reads notes/*.json at query time."""
    con = duckdb.connect()
    cols = ", ".join(f"TRY_CAST(json->>'{p}' AS {t}) AS {c}" for c, (p, t) in COLUMNS.items())
    files = sorted(f for f in paths.notes.glob("*.json")) if paths.notes.is_dir() else []
    if files:
        glob = str(paths.notes / "*.json").replace("'", "''")
        con.execute(f"CREATE VIEW notes AS SELECT {cols} FROM read_json_objects('{glob}', format = 'auto')")
    else:
        con.execute(f"CREATE TABLE notes ({', '.join(f'{c} {t}' for c, (_, t) in COLUMNS.items())})")
    return con


def _values(vocab: Vocab, name: str) -> list[str]:
    return [v for v in vocab.enum(name) if v != "other"]


def gap_ranking(con: duckdb.DuckDBPyConnection, x: str, y: str, vocab: Vocab, empty: list[list[Any]]) -> dict[str, Any]:
    rows = con.execute(f"SELECT slug, {x}, {y} FROM notes WHERE {x} IS NOT NULL AND {y} IS NOT NULL "
                       f"AND {x} NOT LIKE 'other%' AND {y} NOT LIKE 'other%'").fetchall()
    xs, ys, joint = Counter(r[1] for r in rows), Counter(r[2] for r in rows), Counter((r[1], r[2]) for r in rows)
    ranked = stats.rank_gaps(len(rows), {v: xs.get(v, 0) for v in _values(vocab, x)},
                             {v: ys.get(v, 0) for v in _values(vocab, y)}, dict(joint))
    listed = {(r[0], r[1]) for r in empty}
    ranked = [g for g in ranked if (g["x"], g["y"]) in listed]
    return {"x": x, "y": y, "n": len(rows),
            "real_gaps": [[g["x"], g["y"], g["expected"]] for g in ranked if g["real"]],
            "unsurprising": [[g["x"], g["y"], g["expected"]] for g in ranked if not g["real"]]}


def answer_all(con: duckdb.DuckDBPyConnection, vocab: Vocab, cqs: CQSet) -> dict[str, dict[str, Any]]:
    answers = {}
    for q in cqs.questions:
        sql = QUERIES[q.id]
        params = [_values(vocab, GAPS[q.id][0]), _values(vocab, GAPS[q.id][1])] if q.id in GAPS else []
        cur = con.execute(sql, params)
        answer: dict[str, Any] = {"id": q.id, "text": q.text, "columns": [d[0] for d in cur.description],
                                  "rows": [list(r) for r in cur.fetchall()]}
        if q.id in GAPS:
            answer["gap_ranking"] = gap_ranking(con, *GAPS[q.id], vocab, answer["rows"])
        answers[q.id] = answer
    return answers


def analysis_md(answers: dict[str, dict[str, Any]], n_notes: int) -> str:
    lines = ["# Notes index: lanes and gaps", "", f"Counts over {n_notes} note(s) in notes/, read in place.", ""]
    for a in answers.values():
        lines += [f"## {a['id']}: {a['text']}", ""]
        g = a.get("gap_ranking")
        if g:
            lines.append(f"{len(a['rows'])} empty pair(s) over {g['n']} note(s) with both fields. A real gap is expected 3 "
                         "or more times and never seen.")
            lines += ["", "Real gaps: " + (", ".join(f"{x} x {y} (expected {e:.1f})" for x, y, e in g["real_gaps"]) or "none"),
                      "", "Most expected of the rest: " + (", ".join(f"{x} x {y} ({e:.1f})"
                                                                     for x, y, e in g["unsurprising"][:8]) or "none"), ""]
            continue
        if not a["rows"]:
            lines += ["(no rows)", ""]
            continue
        lines += ["| " + " | ".join(a["columns"]) + " |", "|" + "---|" * len(a["columns"])]
        lines += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in a["rows"]]
        lines.append("")
    lines += ["## Not tracked", "", "The notes do not record: " + ", ".join(NOT_TRACKED) + ". Questions about them "
              "report \"not tracked\" (the heavy path at the tag heavy-final holds them for the gold titles).", ""]
    return "\n".join(lines)


def analyze(paths: Paths, vocab: Vocab, cqs: CQSet) -> tuple[dict[str, dict[str, Any]], Path]:
    con = connect(paths)
    try:
        answers = answer_all(con, vocab, cqs)
        n = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        con.close()
    out = paths.reports / "analysis.md"
    atomic_write_text(out, analysis_md(answers, n))
    atomic_write_text(paths.reports / "cq_answers.json", json.dumps(answers, indent=2, ensure_ascii=False) + "\n")
    return answers, out


# ---------------------------------------------------------------- spreadsheets
def _csv(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def notes_csv(paths: Paths) -> str:
    notes = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(paths.notes.glob("*.json"))] \
        if paths.notes.is_dir() else []
    header = [*COLUMNS, "power_functions", "power_tools", *(f"element_{i}" for i in (1, 2, 3)),
              *(f"pattern_{i}" for i in (1, 2, 3)), "source_1", "source_2"]
    rows = []
    for n in notes:
        def get(path: str, n: dict[str, Any] = n) -> Any:
            cur: Any = n
            for part in path.removeprefix("$.").split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            return cur
        kit, els = n.get("power_kit") or {}, (n.get("elements") or []) + [{}] * 3
        srcs = [s.get("url") for s in n.get("sources") or []] + [None, None]
        rows.append([get(p) for p, _ in COLUMNS.values()] + [" / ".join(kit.get("functions") or []),
                    " / ".join(kit.get("tools") or [])] + [els[i].get("element") for i in range(3)]
                    + [els[i].get("pattern") for i in range(3)] + srcs[:2])
    return _csv(header, rows)


def cards_csv(paths: Paths) -> str:
    header = ["file", "created_at", "seed", "seed_kind", "status", "rank", "ref", "logline", "premise", "mc_edge",
              "power_medium", "closest", "closeness", "score", "consequence_dims", "rules", "weakness",
              "never_done_claim", "prior_art"]
    rows = []
    for f in sorted(paths.quick.glob("*.json")) if paths.quick.is_dir() else []:
        r = json.loads(f.read_text(encoding="utf-8"))
        survivors = r.get("survivors") or []
        for ref, c in (r.get("cards") or {}).items():
            k = (r.get("checks") or {}).get(ref, {})
            rows.append([f.name, r.get("created_at"), r.get("seed"), r.get("seed_kind"),
                         "survived" if ref in survivors else "dropped",
                         survivors.index(ref) + 1 if ref in survivors else None, ref, c.get("logline"), c.get("premise"),
                         c.get("mc_edge"), (c.get("power_kit") or {}).get("medium"),
                         k.get("closest_slug") or c.get("closest_existing"), k.get("closeness"), k.get("score"),
                         k.get("dims"), "; ".join(f"{x['id']} {x['verdict']}" for x in k.get("rules") or []),
                         k.get("weakness"), c.get("never_done_claim"), c.get("prior_art")])
    return _csv(header, rows)


def export(paths: Paths) -> list[Path]:
    out = []
    for name, text in (("notes.csv", notes_csv(paths)), ("cards.csv", cards_csv(paths))):
        atomic_write_text(paths.exports / name, text)
        out.append(paths.exports / name)
    return out
