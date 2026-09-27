"""Pydantic models = data contracts (04). `RECORD_TYPES` maps each canonical file to its model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from animedex.models.atoms import CheckRecord, MechanismAtom, PatternCard, ProofRecord, TransferAtom
from animedex.models.common import FieldValue, Provenance, Scope, StrictModel
from animedex.models.evidence import Episode, Link, Moment, Outcome
from animedex.models.ideation import ArchiveRecord, CoverageLedger, IdeaCard
from animedex.models.title import CorpusEntry, TitleProfileBase, title_profile_model


@dataclass(frozen=True)
class RecordType:
    name: str
    file: str
    _model: Callable[[], type[StrictModel]]
    key: Callable[[dict[str, Any]], str]

    @property
    def model(self) -> type[StrictModel]:
        return self._model()


def _field(name: str) -> Callable[[dict[str, Any]], str]:
    return lambda r: str(r[name])


def _check_key(r: dict[str, Any]) -> str:
    """One record per verdict: an atom and its proof share a target_id, so the type is part of the key."""
    prov = r.get("provenance") or {}
    return f"{r['target_id']}|{r['target_type']}|{prov.get('run_id', '')}|{prov.get('created_at', '')}"


RECORD_TYPES: dict[str, RecordType] = {
    rt.name: rt
    for rt in (
        RecordType("title", "titles.jsonl", title_profile_model, _field("title_id")),
        RecordType("moment", "moments.jsonl", lambda: Moment, _field("moment_id")),
        RecordType("outcome", "outcomes.jsonl", lambda: Outcome, _field("title_id")),
        RecordType("mechanism", "mechanisms.jsonl", lambda: MechanismAtom, _field("atom_id")),
        RecordType("proof", "proofs.jsonl", lambda: ProofRecord, _field("atom_id")),
        RecordType("check", "checks.jsonl", lambda: CheckRecord, _check_key),
        RecordType("transfer", "transfers.jsonl", lambda: TransferAtom, _field("transfer_id")),
        RecordType("episode", "episodes.jsonl", lambda: Episode, _field("episode_id")),
        RecordType("link", "links.jsonl", lambda: Link, _field("link_id")),
        RecordType("pattern", "patterns.jsonl", lambda: PatternCard, _field("pattern_id")),
        RecordType("coverage", "coverage.jsonl", lambda: CoverageLedger, _field("title_id")),
        RecordType("idea", "ideas.jsonl", lambda: IdeaCard, _field("idea_id")),
        RecordType("archive", "archive.jsonl", lambda: ArchiveRecord, _field("cell_key")),
    )
}


def _walk(schema: dict[str, Any], defs: dict[str, Any], prefix: str, out: set[str]) -> None:
    if "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            _walk(sub, defs, prefix, out)
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        _walk(schema["items"], defs, prefix, out)
    for name, sub in (schema.get("properties") or {}).items():
        path = f"{prefix}.{name}"
        out.add(path)
        _walk(sub, defs, path, out)


def record_paths() -> set[str]:
    """Every addressable field path, as `<record>.<dotted.path>` (used to check CQ `requires:`)."""
    out: set[str] = set()
    for rt in RECORD_TYPES.values():
        schema = rt.model.model_json_schema(by_alias=True)
        _walk(schema, schema.get("$defs", {}), rt.name, out)
    return out


__all__ = [
    "RECORD_TYPES",
    "ArchiveRecord",
    "CheckRecord",
    "CorpusEntry",
    "CoverageLedger",
    "Episode",
    "FieldValue",
    "IdeaCard",
    "Link",
    "MechanismAtom",
    "Moment",
    "Outcome",
    "PatternCard",
    "ProofRecord",
    "Provenance",
    "RecordType",
    "Scope",
    "StrictModel",
    "TitleProfileBase",
    "TransferAtom",
    "record_paths",
    "title_profile_model",
]
