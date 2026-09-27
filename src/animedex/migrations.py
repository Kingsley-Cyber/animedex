"""Mechanical data migrations between spec versions (03: re-canonicalize, never re-extract by hand).

1.3.0: outcomes gain `failure_level`. Existing mixed/flop outcomes get the honest default
`unknown` (source `migration`); `animedex verify --outcome-only` then records a sourced level.
"""

from __future__ import annotations

from animedex.paths import Paths
from animedex.store.canonical import CanonicalStore


def _default(o: dict) -> dict | None:
    if o.get("label") in ("mixed", "flop") and not o.get("failure_level"):
        return {**o, "failure_level": "unknown", "failure_evidence": None, "failure_evidence_ref": None,
                "failure_level_source": "migration"}
    return None


def migrate_1_3_0(paths: Paths, run_id: str) -> list[str]:
    """Canonical outcomes and outcome candidates still waiting to be canonicalized."""
    from animedex.store.atomic import atomic_write_text
    from animedex.store.jsonl import dumps_jsonl, read_jsonl

    store = CanonicalStore(paths)
    changed = []
    rows = [r for r in (_default(o) for o in store.read("outcome")) if r]
    if rows:
        store.write("outcome", rows, run_id)
        changed += [r["title_id"] for r in rows]
    folder = paths.candidates / "outcome"
    for f in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        records = read_jsonl(f)
        fixed = [(_default(o) or o) for o in records]
        if fixed != records:
            atomic_write_text(f, dumps_jsonl(fixed))
            changed += [o["title_id"] for o, n in zip(records, fixed, strict=True) if o is not n]
    return sorted(set(changed))


MIGRATIONS = {"1.3.0": migrate_1_3_0}
