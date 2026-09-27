"""Mechanical data migrations between spec versions (03: re-canonicalize, never re-extract by hand).

1.3.0: outcomes gain `failure_level`. Existing mixed/flop outcomes get the honest default
`unknown` (source `migration`); `animedex verify --outcome-only` then records a sourced level.
"""

from __future__ import annotations

from animedex.paths import Paths
from animedex.store.canonical import CanonicalStore


def migrate_1_3_0(paths: Paths, run_id: str) -> list[str]:
    store = CanonicalStore(paths)
    changed = []
    rows = []
    for o in store.read("outcome"):
        if o.get("label") in ("mixed", "flop") and not o.get("failure_level"):
            rows.append({**o, "failure_level": "unknown", "failure_evidence": None, "failure_evidence_ref": None,
                         "failure_level_source": "migration"})
            changed.append(o["title_id"])
    if rows:
        store.write("outcome", rows, run_id)
    return changed


MIGRATIONS = {"1.3.0": migrate_1_3_0}
