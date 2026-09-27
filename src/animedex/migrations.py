"""Mechanical data migrations between spec versions (03: re-canonicalize, never re-extract by hand).

1.3.0: outcomes gain `failure_level`. Existing mixed/flop outcomes get the honest default
`unknown` (source `migration`); `animedex verify --outcome-only` then records a sourced level.

1.5.1: resolved enum proposals (D-031). A proposal the lead accepted (a new listed value) or merged (into
an existing value) carries its `resolution`; every title example whose value is still plain `other` at the
example's path takes it. A later run's answer is never overwritten, and a list that already holds the value
just loses its `other`. The decisions live in the proposal files (model output: git-ignored, backed up in
the private data repo), so this code names no title.
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


RESOLVED = ("accepted", "merged")


def resolved_proposals(root) -> list[dict]:
    import json

    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") in RESOLVED and data.get("resolution"):
            out.append(data)
    return out


def _resolve(value, index: int | None, to: str):
    """The value with its `other` at `index` (or the single value) replaced by `to`; None when unchanged."""
    if index is None:
        return to if value == "other" else None
    if not isinstance(value, list) or index >= len(value) or value[index] != "other":
        return None
    return [v for i, v in enumerate(value) if i != index] if to in value else [*value[:index], to, *value[index + 1:]]


def migrate_1_5_1(paths: Paths, run_id: str) -> list[str]:
    """Resolved enum proposals onto canonical titles still holding `other` where the proposal came from."""
    store = CanonicalStore(paths)
    titles = {t["title_id"]: t for t in store.read("title")}
    steps = []
    for prop in resolved_proposals(paths.proposals):
        for ex in prop.get("examples", []):
            rest = str(ex.get("path", "")).removeprefix(f"{prop['field']}.value")
            if ex.get("record_type") == "title" and (not rest or rest.lstrip(".").isdigit()):
                steps.append((ex["record_id"], prop["field"], int(rest.lstrip(".")) if rest else None,
                              prop["resolution"]))
    # per field, later list positions first, so dropping an entry never shifts one still to be resolved
    steps.sort(key=lambda s: (s[0], s[1], -(s[2] if s[2] is not None else -1), s[3]))
    changed: set[str] = set()
    for record_id, field, index, to in steps:
        block, name = field.split(".", 1)
        fv = ((titles.get(record_id) or {}).get(block) or {}).get(name)
        new = _resolve(fv.get("value"), index, to) if isinstance(fv, dict) else None
        if new is not None:
            fv["value"] = new
            changed.add(record_id)
    if changed:
        store.write("title", [titles[t] for t in sorted(changed)], run_id)
    return sorted(changed)


MIGRATIONS = {"1.3.0": migrate_1_3_0, "1.5.1": migrate_1_5_1}
