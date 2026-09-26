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
from pathlib import Path

from animedex.models import RECORD_TYPES
from animedex.paths import Paths
from animedex.store.canonical import CanonicalError, CanonicalStore
from animedex.store.jsonl import JsonlError, read_jsonl
from animedex.store.quarantine import quarantine

ORDER = ["title", "moment", "outcome", "coverage", "mechanism", "proof", "check", "transfer",
         "episode", "link", "pattern", "idea", "archive"]


@dataclass
class CanonicalizeResult:
    written: dict[str, list[str]] = field(default_factory=dict)
    quarantined: list[tuple[str, str, str]] = field(default_factory=list)
    proposals: list[Path] = field(default_factory=list)
    applied_files: list[Path] = field(default_factory=list)


def canonicalize(paths: Paths, run_id: str) -> CanonicalizeResult:
    assert sorted(ORDER) == sorted(RECORD_TYPES), "ORDER must list every record type"
    store = CanonicalStore(paths)
    result = CanonicalizeResult()
    for record_type in ORDER:
        folder = paths.candidates / record_type
        files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
        if not files:
            continue
        records = []
        for f in files:
            try:
                records.extend(read_jsonl(f))
            except JsonlError as exc:
                quarantine(paths.quarantine, "CANONICALIZE", record_type, f.name, f.read_text(encoding="utf-8"), [str(exc)])
                result.quarantined.append((record_type, f.name, str(exc)))
        good, bad = store.validate_each(record_type, records, run_id)
        for rid, msg, raw in bad:
            quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, raw, [msg])
            result.quarantined.append((record_type, rid, msg))
        if good:
            try:
                wr = store.write(record_type, [clean for clean, _ in good], run_id)
            except CanonicalError as exc:
                for clean, _ in good:
                    rid = RECORD_TYPES[record_type].key(clean)
                    quarantine(paths.quarantine, "CANONICALIZE", record_type, rid, clean, [str(exc)])
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
    return result
