"""Field health (owner ruling 2026-09-27, statistics as gates, item 5): per enum field of the title profile,
how much it varies (entropy, normalized by the number of allowed values) and how much it says about the
outcome label (mutual information over the titles that have one). A field whose normalized entropy is
under 0.5 barely varies across the corpus and is flagged low-entropy. Counts from DuckDB only.
"""

from __future__ import annotations

from typing import Any

import duckdb

from animedex import stats
from animedex.analyze.cq import LABEL
from animedex.ontology import Vocab
from animedex.statgates import LOW_ENTROPY


def _nz(x: float) -> float:
    return x + 0.0  # -0.0 (a one-value field) reads as 0.0


def field_health(con: duckdb.DuckDBPyConnection, vocab: Vocab,
                 unreliable: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One row per single-value enum field, in vocab order."""
    unreliable = unreliable or {}
    labels = dict(con.execute(f"WITH {LABEL} SELECT title_id, label FROM label WHERE label IS NOT NULL").fetchall())
    values: dict[str, list[tuple[str, str]]] = {}
    for tid, path, value in con.execute("SELECT title_id, path, value FROM title_fields WHERE kind = 'enum' "
                                        "AND value IS NOT NULL ORDER BY title_id, path").fetchall():
        values.setdefault(path, []).append((tid, value))
    out = []
    for f in vocab.lens_fields():
        if f.kind != "enum":
            continue
        rows = values.get(f.path, [])
        seen = [v for _, v in rows]
        k = len(vocab.enum(f.vocab or f.path))
        with_label = [(v, labels[t]) for t, v in rows if t in labels]
        norm = _nz(stats.normalized_entropy(seen, k))
        out.append({"path": f.path, "n": len(seen), "k": k, "entropy": _nz(stats.entropy(seen)), "normalized_entropy": norm,
                    "low_entropy": bool(seen) and norm < LOW_ENTROPY, "n_with_outcome": len(with_label),
                    "mi_outcome": (None if f.path == "core.outcome" or not with_label
                                   else _nz(stats.mutual_information(with_label))),
                    "unreliable": f.path in unreliable})
    return out
