"""CANONICALIZE (05): data/candidates/<record_type>/*.jsonl -> data/canonical/<file>.jsonl.

Per record type: validate + normalize each candidate; invalid ones go to quarantine with reasons;
valid ones are written all-or-nothing (integrity checked against the whole canonical state).
Applied candidate files move to candidates/<type>/applied/<run_id>/ so a rerun cannot revert
later canonical updates (e.g. ROLLUP). Near-duplicate atom dedupe and the coverage-ledger update
arrive with the passes that produce atoms and P1 profiles (M2/M3).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from animedex import SCHEMA_VERSION
from animedex.evaluation import coverage_row
from animedex.models import RECORD_TYPES
from animedex.paths import Paths
from animedex.store.canonical import CanonicalError, CanonicalStore
from animedex.store.jsonl import JsonlError, read_jsonl
from animedex.store.quarantine import quarantine

ORDER = ["title", "moment", "outcome", "coverage", "mechanism", "proof", "check", "transfer",
         "episode", "link", "pattern", "idea", "archive", "prior_art", "census"]
HELD_UNTIL_CHECKED = ("mechanism", "proof")
M3_TYPES = ("mechanism", "proof", "check", "transfer")


@dataclass
class CanonicalizeResult:
    written: dict[str, list[str]] = field(default_factory=dict)
    quarantined: list[tuple[str, str, str]] = field(default_factory=list)
    proposals: list[Path] = field(default_factory=list)
    applied_files: list[Path] = field(default_factory=list)
    held: list[Path] = field(default_factory=list)


def canonicalize(paths: Paths, run_id: str) -> CanonicalizeResult:
    assert sorted(ORDER) == sorted(RECORD_TYPES), "ORDER must list every record type"
    store = CanonicalStore(paths)
    result = CanonicalizeResult()
    checked = {f.stem for f in (paths.candidates / "check").glob("*.jsonl")}
    for record_type in ORDER:
        folder = paths.candidates / record_type
        files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
        if record_type in HELD_UNTIL_CHECKED:  # M3: atoms and proofs land only with their CHECK verdicts
            held = [f for f in files if f.stem not in checked]
            result.held.extend(held)
            files = [f for f in files if f.stem in checked]
        if not files:
            continue
        records = []
        for f in files:
            try:
                records.extend(read_jsonl(f))
            except JsonlError as exc:
                quarantine(paths.quarantine, "CANONICALIZE", record_type, f.name, f.read_text(encoding="utf-8"), [str(exc)])
                result.quarantined.append((record_type, f.name, str(exc)))
        good_raw = []
        for raw in records:  # pass raw (not normalized) records on, so the store writes their proposals
            _, bad = store.validate_each(record_type, [raw], run_id)
            for rid, msg, _raw in bad:
                quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, raw, [msg])
                result.quarantined.append((record_type, rid, msg))
            if not bad:
                good_raw.append(raw)
        if good_raw:
            try:
                wr = store.write(record_type, good_raw, run_id)
            except CanonicalError as exc:
                for raw in good_raw:
                    rid = RECORD_TYPES[record_type].key(raw)
                    quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, raw, [str(exc)])
                    result.quarantined.append((record_type, rid, "integrity"))
                continue
            result.written[record_type] = wr.written
            result.proposals.extend(wr.proposals)
        applied = folder / "applied" / run_id
        applied.mkdir(parents=True, exist_ok=True)
        for f in files:
            target = applied / f.name
            shutil.move(str(f), target)
            result.applied_files.append(target)
    touched = set(result.written.get("title", []))
    for record_type in M3_TYPES:
        for key in result.written.get(record_type, []):
            touched.add(key.split(".")[0].split("|")[0])
    if touched:
        update_coverage(store, sorted(touched), run_id, result)
    return result


def m3_passes(state: dict[str, list[dict]], title_id: str) -> list[str]:
    """P2/P3/CHECK/P4 are done for a title when every atom has what the next pass needs."""
    from animedex.eligibility import eligible_atom_ids

    atoms = [m["atom_id"] for m in state.get("mechanism", []) if m["title_id"] == title_id]
    if not atoms:
        return []
    passes = ["P2"]
    proved = {p["atom_id"] for p in state.get("proof", [])}
    checked = {c["target_id"] for c in state.get("check", []) if c["target_type"] == "mechanism"}
    if all(a in proved for a in atoms):
        passes.append("P3")
    if all(a in checked for a in atoms):
        passes.append("CHECK")
        eligible = [a for a in atoms if a in eligible_atom_ids(state)]
        transferred = {t["source_atom_id"] for t in state.get("transfer", [])}
        if all(a in transferred for a in eligible):
            passes.append("P4")
    return passes


def update_coverage(store: CanonicalStore, title_ids: list[str], run_id: str, result: CanonicalizeResult) -> None:
    """05 CANONICALIZE: refresh the coverage ledger for titles written in this run."""
    state = store.state()
    titles = {t["title_id"]: t for t in state.get("title", [])}
    existing = {c["title_id"]: c for c in store.read("coverage")}
    prov = {"run_id": run_id, "pass": "CANONICALIZE", "model": None, "prompt_version": None,
            "schema_version": SCHEMA_VERSION, "vocab_version": store.vocab.version, "cache_key": None,
            "created_at": datetime.now(UTC).isoformat()}
    rows = []
    for tid in sorted(set(title_ids)):
        if tid not in titles:
            continue
        row = coverage_row(titles[tid], store.vocab)
        row["passes_done"] = [*row["passes_done"], *m3_passes(state, tid)]
        old = existing.get(tid, {})
        row["episodes"] = old.get("episodes", {"in_scope": 0, "indexed": 0, "unsourced": 0, "selection": {}})
        row["episode_backed_share"] = old.get("episode_backed_share", 0.0)
        row["provenance"] = prov
        rows.append(row)
    wr = store.write("coverage", rows, run_id)
    result.written["coverage"] = wr.written
