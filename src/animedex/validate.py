"""`make validate`: ontology coverage (AC-04), schemas current, config/corpus parse, and every
canonical record valid with references resolving (04 invariants)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from animedex.config import live_problems, load_settings
from animedex.content_guards import GuardConfig, record_problems
from animedex.guards import load_corpus
from animedex.integrity import integrity_errors
from animedex.models import RECORD_TYPES, record_paths
from animedex.ontology import coverage_report, get_bridge, get_cqs, get_vocab
from animedex.paths import Paths
from animedex.schemas import stale_schemas
from animedex.store.atomic import atomic_write_text, stale_temp_files
from animedex.store.jsonl import JsonlError, dumps_jsonl, read_jsonl
from animedex.store.proposals import pending_proposals


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_repo(paths: Paths) -> ValidationReport:
    report = ValidationReport()
    vocab, bridge, cqs = get_vocab(paths), get_bridge(paths), get_cqs(paths)

    cov = coverage_report(vocab, bridge, cqs, record_paths())
    atomic_write_text(paths.reports / "cq_coverage.md", cov.to_markdown())
    report.errors.extend(f"ontology: {e}" for e in cov.errors)
    report.errors.extend(f"ontology: orphan {r.kind} {r.name} (no competency question)" for r in cov.orphans)
    report.notes.append(f"CQ coverage: {len(cov.rows)} rows, {len(cov.orphans)} orphans -> build/reports/cq_coverage.md")

    report.errors.extend(f"schemas/{name} is stale; run `make schemas`" for name in stale_schemas(paths))

    try:
        settings = load_settings(paths)
        pending = live_problems(settings, {})
        if pending:
            report.warnings.append(f"config: {len(pending)} item(s) block live runs (offline work is fine); see `animedex smoke`")
    except (ValidationError, OSError, ValueError) as exc:
        report.errors.append(f"config/settings.yaml: {exc}")

    try:
        corpus = load_corpus(paths)
        report.notes.append(f"corpus: {len(corpus)} title(s)")
    except (ValidationError, ValueError) as exc:
        report.errors.append(f"corpus/titles.yaml: {exc}")

    try:
        guards = GuardConfig.from_settings(load_settings(paths))
    except (ValidationError, OSError, ValueError):
        guards = GuardConfig()
    state: dict[str, list[dict]] = {}
    for name, rt in RECORD_TYPES.items():
        path = paths.canonical / rt.file
        try:
            records = read_jsonl(path)
        except JsonlError as exc:
            report.errors.append(f"canonical {exc}")
            state[name] = []
            continue
        keys = [rt.key(r) if isinstance(r, dict) else "?" for r in records]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            report.errors.append(f"{rt.file}: duplicate ids {dupes[:5]}")
        if keys != sorted(keys):
            report.errors.append(f"{rt.file}: records are not sorted by id")
        model = rt.model
        clean = []
        for record, key in zip(records, keys, strict=True):
            for problem in record_problems(record, guards):
                report.errors.append(f"{rt.file} {key}: {problem}")
            try:
                clean.append(model.model_validate(record).to_record())
            except ValidationError as exc:
                report.errors.append(f"{rt.file} {key}: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}")
        if records and len(clean) == len(records) and path.read_text(encoding="utf-8") != dumps_jsonl(clean):
            report.warnings.append(f"{rt.file}: not in canonical form (was it edited by hand? re-run CANONICALIZE)")
        state[name] = records
    report.errors.extend(f"integrity: {e}" for e in integrity_errors(state, vocab))

    for tmp in stale_temp_files(paths.canonical):
        report.warnings.append(f"stale temp file from an interrupted write: {tmp.name} (safe to delete)")
    proposals = pending_proposals(paths.proposals)
    if proposals:
        report.notes.append(f"{len(proposals)} ontology proposal(s) pending review (G3)")
    return report
