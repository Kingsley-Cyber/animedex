"""Canonical JSONL store (03): the source of truth. Written only by CANONICALIZE and ROLLUP.

Every write is all-or-nothing: normalize enums -> validate every record -> check referential
integrity against the whole canonical state -> atomic write -> queue off-vocab proposals.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from animedex.config import load_settings
from animedex.content_guards import GuardConfig, record_problems
from animedex.integrity import integrity_errors
from animedex.models import RECORD_TYPES, StrictModel
from animedex.ontology import Vocab, get_vocab, normalize_enum
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.store.proposals import Proposal, write_proposal


class CanonicalError(ValueError):
    pass


class InvalidRecords(CanonicalError):
    """Raised before anything is written (AC-02)."""

    def __init__(self, record_type: str, errors: list[tuple[str, str]]):
        self.record_type = record_type
        self.errors = errors
        lines = "\n".join(f"  {rid}: {msg}" for rid, msg in errors[:20])
        super().__init__(f"{len(errors)} invalid {record_type} record(s); nothing written:\n{lines}")


class IntegrityError(CanonicalError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("referential integrity failed; nothing written:\n  " + "\n  ".join(errors[:20]))


# ---------------------------------------------------------------- enum normalization
def _vocab_paths(schema: dict[str, Any], defs: dict[str, Any], prefix: tuple[str, ...], out: list) -> None:
    if "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    if "x-vocab" in schema:
        out.append((prefix, schema["x-vocab"]))
        return
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            _vocab_paths(sub, defs, prefix, out)
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        _vocab_paths(schema["items"], defs, prefix + ("[]",), out)
    for name, sub in (schema.get("properties") or {}).items():
        _vocab_paths(sub, defs, prefix + (name,), out)


def vocab_paths(model: type[StrictModel]) -> list[tuple[tuple[str, ...], str]]:
    schema = model.model_json_schema(by_alias=True)
    out: list[tuple[tuple[str, ...], str]] = []
    _vocab_paths(schema, schema.get("$defs", {}), (), out)
    return sorted(set(out))


def _visit(obj: Any, path: tuple[str, ...], fn: Callable[[dict[str, Any], str, tuple[str, ...]], None],
           trail: tuple[str, ...] = ()) -> None:
    if not path:
        return
    head, rest = path[0], path[1:]
    if head == "[]":
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                _visit(item, rest, fn, trail + (str(i),))
        return
    if not isinstance(obj, dict) or head not in obj:
        return
    if rest:
        _visit(obj[head], rest, fn, trail + (head,))
    else:
        fn(obj, head, trail + (head,))


def _first_words(text: str, n: int) -> str:
    return " ".join(text.split()[:n])


def normalize_record(
    record_type: str, record: dict[str, Any], vocab: Vocab, run_id: str | None = None
) -> tuple[dict[str, Any], list[Proposal]]:
    """Map alternate labels to preferred values; route off-vocab values to proposals.

    Enum with `other`: store `other`. P1 field whose enum lacks `other`: store value null,
    conf 0, and an uncertainty_reason, so no off-vocab value enters canonical data (P-04).
    Other records keep the raw value and fail validation (quarantine upstream).
    """
    rt = RECORD_TYPES[record_type]
    out = copy.deepcopy(record)
    proposals: list[Proposal] = []
    try:
        record_id = rt.key(out)
    except (KeyError, TypeError):
        record_id = "?"

    for path, vocab_field in vocab_paths(rt.model):
        is_p1_value = record_type == "title" and len(path) == 3 and path[-1] == "value"

        def fix(container: dict[str, Any], key: str, trail: tuple[str, ...], _vf: str = vocab_field,
                _p1: bool = is_p1_value) -> None:
            raw = container[key]
            if raw is None:
                return
            norm = normalize_enum(vocab, _vf, raw)
            if norm.proposal is None:
                if norm.value is not None:
                    container[key] = norm.value
                return
            proposals.append(Proposal(_vf, norm.proposal, record_type, str(record_id), ".".join(trail), run_id))
            if norm.value is not None:
                container[key] = norm.value
            elif _p1:
                container[key] = None
                container["conf"] = 0.0
                container["uncertainty_reason"] = _first_words(f"off-vocab proposal: {norm.proposal}", 12)

        _visit(out, path, fix)
    return out, proposals


# ---------------------------------------------------------------- store
@dataclass
class WriteResult:
    record_type: str
    written: list[str] = field(default_factory=list)
    proposals: list[Path] = field(default_factory=list)


class CanonicalStore:
    def __init__(self, paths: Paths | None = None, vocab: Vocab | None = None):
        self.paths = paths or Paths.discover()
        self._vocab = vocab
        self._guards: GuardConfig | None = None

    @property
    def vocab(self) -> Vocab:
        return self._vocab or get_vocab(self.paths)

    @property
    def guards(self) -> GuardConfig:
        if self._guards is None:
            try:
                self._guards = GuardConfig.from_settings(load_settings(self.paths))
            except (OSError, ValueError):
                self._guards = GuardConfig()
        return self._guards

    def file(self, record_type: str) -> Path:
        return self.paths.canonical / RECORD_TYPES[record_type].file

    def read(self, record_type: str) -> list[dict[str, Any]]:
        return read_jsonl(self.file(record_type))

    def state(self) -> dict[str, list[dict[str, Any]]]:
        return {name: self.read(name) for name in RECORD_TYPES}

    def validate_each(
        self, record_type: str, records: Iterable[dict[str, Any]], run_id: str | None = None
    ) -> tuple[list[tuple[dict[str, Any], list[Proposal]]], list[tuple[str, str, dict[str, Any]]]]:
        """Split records into (valid normalized records + their proposals) and (id, error, raw)."""
        rt = RECORD_TYPES[record_type]
        model = rt.model
        good, bad = [], []
        for raw in records:
            try:
                norm, props = normalize_record(record_type, raw, self.vocab, run_id)
                clean = model.model_validate(norm).to_record()
                problems = record_problems(clean, self.guards)
                if problems:
                    raise ValueError("content guard: " + "; ".join(problems[:5]))
                good.append((clean, props))
            except (ValidationError, KeyError, TypeError, ValueError) as exc:
                try:
                    rid = rt.key(raw)
                except Exception:  # noqa: BLE001 - id itself may be missing
                    rid = "<no id>"
                bad.append((rid, str(exc), raw))
        return good, bad

    def write(self, record_type: str, records: list[dict[str, Any]], run_id: str | None = None) -> WriteResult:
        rt = RECORD_TYPES[record_type]
        good, bad = self.validate_each(record_type, records, run_id)
        if bad:
            raise InvalidRecords(record_type, [(rid, msg) for rid, msg, _ in bad])

        merged = {rt.key(r): r for r in self.read(record_type)}
        for clean, _ in good:
            merged[rt.key(clean)] = clean
        new_records = [merged[k] for k in sorted(merged)]

        state = self.state()
        state[record_type] = new_records
        errors = integrity_errors(state, self.vocab)
        if errors:
            raise IntegrityError(errors)

        atomic_write_text(self.file(record_type), dumps_jsonl(new_records))
        result = WriteResult(record_type, [rt.key(c) for c, _ in good])
        for _, props in good:
            for p in props:
                result.proposals.append(write_proposal(self.paths.proposals, p))
        return result
