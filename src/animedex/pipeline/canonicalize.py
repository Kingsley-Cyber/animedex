"""CANONICALIZE (05): data/candidates/<record_type>/*.jsonl -> data/canonical/<file>.jsonl.

Per-title transactions (owner ruling 2026-09-27): every title-scoped candidate file is named after its
title, so a title's records (profile, moments, characters, outcome, atoms, proofs, checks, transfers,
episodes, links) are validated together and land together or not at all. A title with an invalid record, or
one whose records break referential integrity, is held: its bad records are quarantined with reasons,
its candidate files stay pending (a fix plus a rerun applies them), and every other title is written.
Global record types (patterns, ideas, archive, prior art, census) keep one transaction per type.
Applied candidate files move to candidates/<type>/applied/<run_id>/ so a rerun cannot revert later
canonical updates (e.g. ROLLUP).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animedex import SCHEMA_VERSION
from animedex.evaluation import coverage_row
from animedex.integrity import integrity_errors
from animedex.models import RECORD_TYPES
from animedex.paths import Paths
from animedex.store.canonical import CanonicalError, CanonicalStore
from animedex.store.jsonl import JsonlError, read_jsonl
from animedex.store.quarantine import quarantine

ORDER = ["title", "moment", "character", "outcome", "coverage", "mechanism", "proof", "check", "transfer",
         "episode", "link", "pattern", "idea", "archive", "prior_art", "census"]
GLOBAL_TYPES = ("pattern", "idea", "archive", "prior_art", "census")  # not scoped to one title
HELD_UNTIL_CHECKED = ("mechanism", "proof")
M3_TYPES = ("mechanism", "proof", "check", "transfer")


@dataclass
class CanonicalizeResult:
    written: dict[str, list[str]] = field(default_factory=dict)
    quarantined: list[tuple[str, str, str]] = field(default_factory=list)
    proposals: list[Path] = field(default_factory=list)
    applied_files: list[Path] = field(default_factory=list)
    held: list[Path] = field(default_factory=list)                 # files left pending (awaiting CHECK)
    held_titles: dict[str, str] = field(default_factory=dict)      # title -> why its records were held


def _candidate_files(paths: Paths, record_type: str, checked: set[str], result: CanonicalizeResult) -> list[Path]:
    folder = paths.candidates / record_type
    files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    if record_type in HELD_UNTIL_CHECKED:  # M3: atoms and proofs land only with their CHECK verdicts
        result.held.extend(f for f in files if f.stem not in checked)
        files = [f for f in files if f.stem in checked]
    return files


def _read(paths: Paths, record_type: str, f: Path, result: CanonicalizeResult) -> list[dict[str, Any]] | None:
    try:
        return read_jsonl(f)
    except JsonlError as exc:
        quarantine(paths.quarantine, "CANONICALIZE", record_type, f.name, f.read_text(encoding="utf-8"), [str(exc)])
        result.quarantined.append((record_type, f.name, str(exc)))
        return None


def _apply_files(files: list[Path], run_id: str, result: CanonicalizeResult) -> None:
    for f in files:
        target = f.parent / "applied" / run_id / f.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), target)
        result.applied_files.append(target)


def canonicalize(paths: Paths, run_id: str) -> CanonicalizeResult:
    assert sorted(ORDER) == sorted(RECORD_TYPES), "ORDER must list every record type"
    store = CanonicalStore(paths)
    result = CanonicalizeResult()
    checked = {f.stem for f in (paths.candidates / "check").glob("*.jsonl")}

    # ---- title-scoped types: one transaction per title
    groups: dict[str, dict[str, list[tuple[Path, list[dict[str, Any]]]]]] = {}
    for record_type in ORDER:
        if record_type in GLOBAL_TYPES:
            continue
        for f in _candidate_files(paths, record_type, checked, result):
            records = _read(paths, record_type, f, result)
            if records is not None:
                groups.setdefault(f.stem, {}).setdefault(record_type, []).append((f, records))
    state = store.state()
    base_errors = set(integrity_errors(state, store.vocab))
    accepted: dict[str, list[dict[str, Any]]] = {}
    for title in sorted(groups):
        bad: list[tuple[str, str, str, dict[str, Any]]] = []
        clean: dict[str, list[dict[str, Any]]] = {}
        for record_type, parts in groups[title].items():
            raws = [r for _, records in parts for r in records]
            good, invalid = store.validate_each(record_type, raws, run_id)
            bad += [(record_type, rid, msg, raw) for rid, msg, raw in invalid]
            clean[record_type] = [c for c, _ in good]
        if not bad:
            trial = {k: list(v) for k, v in state.items()}
            for record_type, recs in clean.items():
                key = RECORD_TYPES[record_type].key
                merged = {key(r): r for r in trial[record_type]}
                merged.update({key(r): r for r in recs})
                trial[record_type] = [merged[k] for k in sorted(merged)]
            new = [e for e in integrity_errors(trial, store.vocab) if e not in base_errors]
            if not new:
                state = trial
                for record_type, parts in groups[title].items():
                    accepted.setdefault(record_type, []).extend(r for _, records in parts for r in records)
                continue
            bad = [(rt, RECORD_TYPES[rt].key(raw), "integrity: " + "; ".join(new[:3]), raw)
                   for rt, parts in groups[title].items() for _, records in parts for raw in records]
        for record_type, rid, msg, raw in bad:  # the whole title waits; its files stay pending
            quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, raw, [msg])
            result.quarantined.append((record_type, rid, msg))
        result.held_titles[title] = bad[0][2][:200]
    for record_type in ORDER:
        if record_type in accepted:
            wr = store.write(record_type, accepted[record_type], run_id)
            result.written[record_type] = wr.written
            result.proposals.extend(wr.proposals)
    _apply_files([f for title in sorted(groups) if title not in result.held_titles
                  for parts in groups[title].values() for f, _ in parts], run_id, result)

    # ---- global types: one transaction per type
    for record_type in GLOBAL_TYPES:
        files = _candidate_files(paths, record_type, checked, result)
        records = [r for f in files for r in (_read(paths, record_type, f, result) or [])]
        if not files:
            continue
        good_raw = []
        known_ideas = {i["idea_id"] for i in store.read("idea")} if record_type == "archive" else set()
        for raw in records:  # pass raw (not normalized) records on, so the store writes their proposals
            if record_type == "archive" and raw.get("idea_id") not in known_ideas:
                # its idea was quarantined or never written: drop this row alone, never the whole archive (D-041)
                rid = RECORD_TYPES[record_type].key(raw)
                msg = f"archive row for {raw.get('idea_id')}: that idea is not in the canonical ideas"
                quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, raw, [msg])
                result.quarantined.append((record_type, rid, msg))
                continue
            _, bad_one = store.validate_each(record_type, [raw], run_id)
            for rid, msg, _raw in bad_one:
                quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, raw, [msg])
                result.quarantined.append((record_type, rid, msg))
            if not bad_one:
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
        _apply_files(files, run_id, result)

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
