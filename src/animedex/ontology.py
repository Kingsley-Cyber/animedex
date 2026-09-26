"""Controlled vocabulary, bridge concepts, competency questions, and the P1 lens (04, 01).

Domain vocabulary lives in ontology/ (10 §6); this module only loads and checks it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from animedex.paths import Paths

FieldKind = Literal["phrase", "enum"]


@dataclass(frozen=True)
class LensField:
    """One P1 field: `block` is "core" or a module name; `path` is "<block>.<name>"."""

    block: str
    name: str
    kind: FieldKind
    vocab: str | None = None
    conditional: bool = False

    @property
    def path(self) -> str:
        return f"{self.block}.{self.name}"


class OntologyError(ValueError):
    """The ontology files are malformed or inconsistent."""


class Vocab:
    """vocab.json: enum fields (with alternate labels and cq_refs) plus the P1 lens."""

    def __init__(self, data: dict[str, Any]):
        try:
            self.version: str = data["version"]
            self.fields: dict[str, dict[str, Any]] = data["fields"]
            lens = data["lens"]
            core = lens["core"]["fields"]
            modules = lens["modules"]
        except KeyError as exc:
            raise OntologyError(f"vocab.json missing key: {exc}") from exc
        self.core_fields = [self._lens_field("core", n, spec) for n, spec in core.items()]
        self.modules: dict[str, list[LensField]] = {
            m: [self._lens_field(m, n, spec) for n, spec in body["fields"].items()]
            for m, body in modules.items()
        }
        self.module_cq_refs: dict[str, list[str]] = {
            m: list(body.get("cq_refs", [])) for m, body in modules.items()
        }
        self._by_path = {f.path: f for f in self.lens_fields()}

    def _lens_field(self, block: str, name: str, spec: dict[str, Any]) -> LensField:
        kind = spec.get("kind")
        if kind not in ("phrase", "enum"):
            raise OntologyError(f"lens field {block}.{name}: kind must be phrase|enum")
        vocab = spec.get("vocab")
        if kind == "enum" and vocab not in self.fields:
            raise OntologyError(f"lens field {block}.{name}: unknown vocab field {vocab!r}")
        return LensField(block, name, kind, vocab, bool(spec.get("conditional", False)))

    # enums ---------------------------------------------------------------
    def enum(self, field_name: str) -> tuple[str, ...]:
        try:
            return tuple(self.fields[field_name]["enum"])
        except KeyError as exc:
            raise OntologyError(f"unknown vocab field {field_name!r}") from exc

    def alternate_labels(self, field_name: str) -> dict[str, list[str]]:
        return dict(self.fields[field_name].get("alternate_labels", {}))

    def cq_refs(self, field_name: str) -> list[str]:
        return list(self.fields[field_name].get("cq_refs", []))

    # lens ----------------------------------------------------------------
    @property
    def module_names(self) -> list[str]:
        return list(self.modules)

    def lens_fields(self) -> list[LensField]:
        out = list(self.core_fields)
        for fields_ in self.modules.values():
            out.extend(fields_)
        return out

    def lens_field(self, path: str) -> LensField:
        try:
            return self._by_path[path]
        except KeyError as exc:
            raise OntologyError(f"unknown lens field {path!r}") from exc

    def block_fields(self, block: str) -> list[LensField]:
        return self.core_fields if block == "core" else self.modules[block]


class Bridge:
    """bridge.json: domain-neutral bridge concepts (04)."""

    def __init__(self, data: dict[str, Any]):
        try:
            self.version: str = data["version"]
            self.concepts: dict[str, dict[str, Any]] = data["concepts"]
        except KeyError as exc:
            raise OntologyError(f"bridge.json missing key: {exc}") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.concepts)


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    requires: tuple[str, ...]


class CQSet:
    """competency_questions.yaml (01)."""

    def __init__(self, data: dict[str, Any]):
        self.version = str(data.get("version", ""))
        qs = data.get("questions") or []
        self.questions = [
            Question(q["id"], q["text"], tuple(q.get("requires") or [])) for q in qs
        ]
        ids = [q.id for q in self.questions]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise OntologyError(f"duplicate CQ ids: {dupes}")

    @property
    def ids(self) -> set[str]:
        return {q.id for q in self.questions}


# ---------------------------------------------------------------- registry
_override: dict[str, Any] = {}
_cache: dict[tuple[str, str, float], Any] = {}


def _load(kind: str, path: Path) -> Any:
    key = (kind, str(path), path.stat().st_mtime)
    if key not in _cache:
        if kind == "cq":
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
        _cache[key] = {"vocab": Vocab, "bridge": Bridge, "cq": CQSet}[kind](data)
    return _cache[key]


def get_vocab(paths: Paths | None = None) -> Vocab:
    if "vocab" in _override:
        return _override["vocab"]
    return _load("vocab", (paths or Paths.discover()).vocab_file)


def get_bridge(paths: Paths | None = None) -> Bridge:
    if "bridge" in _override:
        return _override["bridge"]
    return _load("bridge", (paths or Paths.discover()).bridge_file)


def get_cqs(paths: Paths | None = None) -> CQSet:
    if "cq" in _override:
        return _override["cq"]
    return _load("cq", (paths or Paths.discover()).cq_file)


@contextmanager
def use_ontology(
    vocab: Vocab | None = None, bridge: Bridge | None = None, cqs: CQSet | None = None
) -> Iterator[None]:
    """Temporarily pin the ontology (tests)."""
    saved = dict(_override)
    try:
        for k, v in (("vocab", vocab), ("bridge", bridge), ("cq", cqs)):
            if v is not None:
                _override[k] = v
        yield
    finally:
        _override.clear()
        _override.update(saved)


# ------------------------------------------------------------ normalization
@dataclass(frozen=True)
class Normalized:
    """Result of mapping a raw enum value onto the vocab.

    `value` is a member of the enum, "other" (when the enum has it), or None.
    `proposal` carries the off-vocab phrase that must go to ontology/proposals/.
    """

    value: str | None
    proposal: str | None = None


def _snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def normalize_enum(vocab: Vocab, field_name: str, raw: Any) -> Normalized:
    if raw is None:
        return Normalized(None)
    text = str(raw).strip()
    allowed = vocab.enum(field_name)
    if text in allowed:
        return Normalized(text)
    lowered = text.lower()
    is_other = lowered.startswith("other:")
    phrase = text[len("other:") :].strip() if is_other else text
    if not is_other:
        for preferred, alts in vocab.alternate_labels(field_name).items():
            if lowered in {preferred.lower(), *(a.lower() for a in alts)}:
                return Normalized(preferred)
        snake = _snake(text)
        if snake in allowed:
            return Normalized(snake)
    fallback = "other" if "other" in allowed else None
    return Normalized(fallback, phrase or None)


# ------------------------------------------------------------ CQ coverage (AC-04)
@dataclass
class CoverageRow:
    kind: Literal["lens_field", "module", "vocab_field", "bridge_concept"]
    name: str
    cqs: list[str] = field(default_factory=list)

    @property
    def orphan(self) -> bool:
        return not self.cqs


@dataclass
class CoverageReport:
    rows: list[CoverageRow]
    errors: list[str]

    @property
    def orphans(self) -> list[CoverageRow]:
        return [r for r in self.rows if r.orphan]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.orphans

    def to_markdown(self) -> str:
        lines = [
            "# CQ coverage table",
            "",
            f"Rows: {len(self.rows)} · orphans: {len(self.orphans)} · errors: {len(self.errors)}",
            "",
            "| Kind | Name | CQs |",
            "|---|---|---|",
        ]
        for r in self.rows:
            lines.append(f"| {r.kind} | `{r.name}` | {', '.join(r.cqs) or '**ORPHAN**'} |")
        if self.errors:
            lines += ["", "## Errors", *[f"- {e}" for e in self.errors]]
        return "\n".join(lines) + "\n"


def coverage_report(
    vocab: Vocab, bridge: Bridge, cqs: CQSet, record_paths: set[str]
) -> CoverageReport:
    """Field -> CQ table. Lens fields are covered by `requires:`; modules, vocab fields, and
    bridge concepts by their declared `cq_refs` (04 invariants)."""
    errors: list[str] = []
    known = cqs.ids
    lens_paths = {f.path for f in vocab.lens_fields()}
    valid_requires = lens_paths | set(vocab.fields) | record_paths

    requiring: dict[str, list[str]] = {}
    for q in cqs.questions:
        if not q.requires:
            errors.append(f"{q.id}: empty requires")
        for req in q.requires:
            if req not in valid_requires:
                errors.append(f"{q.id}: requires unknown field {req!r}")
            requiring.setdefault(req, []).append(q.id)

    def declared(owner: str, refs: list[str]) -> list[str]:
        for ref in refs:
            if ref not in known:
                errors.append(f"{owner}: cq_ref {ref!r} is not a defined CQ")
        return sorted(set(refs))

    rows: list[CoverageRow] = []
    for f in vocab.lens_fields():
        rows.append(CoverageRow("lens_field", f.path, sorted(set(requiring.get(f.path, [])))))
    for m in vocab.module_names:
        rows.append(CoverageRow("module", m, declared(f"module {m}", vocab.module_cq_refs[m])))
    for name in vocab.fields:
        rows.append(CoverageRow("vocab_field", name, declared(f"vocab {name}", vocab.cq_refs(name))))
    for name, spec in bridge.concepts.items():
        if not str(spec.get("definition", "")).strip():
            errors.append(f"bridge {name}: missing definition")
        rows.append(
            CoverageRow("bridge_concept", name, declared(f"bridge {name}", list(spec.get("cq_refs", []))))
        )
    return CoverageReport(rows, sorted(set(errors)))
