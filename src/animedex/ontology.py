"""Controlled vocabulary, bridge concepts, competency questions, and the P1 lens (04, 01).

Domain vocabulary lives in ontology/ (10 §6); this module only loads and checks it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from animedex.paths import Paths

FieldKind = Literal["phrase", "enum", "enum_multi", "list", "group"]
PartKind = Literal["phrase", "enum"]
KINDS: tuple[str, ...] = ("phrase", "enum", "enum_multi", "list", "group")
ENUM_KINDS = ("enum", "enum_multi")
TEST_MAX_WORDS = 30  # a discrimination test is one sentence (owner ruling, grid reliability)


def version_tuple(version: str) -> tuple[int, ...]:
    """A version as a comparable tuple, e.g. (1, 5, 0); anything unparseable sorts after every real one."""
    try:
        return tuple(int(p) for p in str(version).split("."))
    except ValueError:
        return (10**6,)


@dataclass(frozen=True)
class LensPart:
    """A typed sub-field of a `list` item or a `group` value (vocab 1.5.0)."""

    name: str
    kind: PartKind
    vocab: str | None = None
    max_words: int | None = None  # phrase parts


@dataclass(frozen=True)
class LensField:
    """One P1 field: `block` is "core" or a module name; `path` is "<block>.<name>".

    Kinds (vocab 1.5.0): `phrase` and `enum` hold a string; `enum_multi` a non-empty list of enum
    values; `list` up to `max_items` small objects with typed `parts`; `group` one object with fixed
    `parts`. Every kind keeps the same conf/source/verification/epistemic envelope."""

    block: str
    name: str
    kind: FieldKind
    vocab: str | None = None
    conditional: bool = False
    max_words: int | None = None  # phrase fields only (vocab 1.4.0: per field, default lens.phrase_max_words)
    parts: tuple[LensPart, ...] = ()   # list items and group sub-fields
    max_items: int | None = None       # list fields
    since: str | None = None           # records made under an older vocab may omit the field
    differs_from: str | None = None    # optional second value: must differ from this same-block field
    outcome_in: tuple[str, ...] = ()   # only titles whose core.outcome is one of these carry a value
    needs_source: bool = False         # a value needs a cited page (source_ref)
    abstract: bool = False             # no names or medium words (premise_abstraction)

    @property
    def path(self) -> str:
        return f"{self.block}.{self.name}"

    def enum_vocabs(self) -> list[tuple[str, str]]:
        """(sub-path, vocab field) for every enum the field holds: "" for the value itself."""
        if self.kind in ENUM_KINDS and self.vocab:
            return [("", self.vocab)]
        return [(f".{p.name}", p.vocab) for p in self.parts if p.kind == "enum" and p.vocab]


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
            self.phrase_max_words = int(lens.get("phrase_max_words", 12))
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
        self.module_activation: dict[str, dict[str, Any]] = {
            m: self._activation(m, body.get("activation") or {"kind": "judgment"}) for m, body in modules.items()
        }
        self._by_path = {f.path: f for f in self.lens_fields()}
        for f in self.lens_fields():
            self._check_pairing(f)
        for name in self.fields:
            self._check_tests(name)

    @staticmethod
    def _activation(module: str, spec: dict[str, Any]) -> dict[str, Any]:
        kind = spec.get("kind")
        if kind == "judgment":
            return spec
        if kind != "rule" or not spec.get("any"):
            raise OntologyError(f"module {module}: activation must be judgment or a rule with `any` clauses")
        for clause in spec["any"]:
            ok = ("module" in clause and len(clause) == 1) or (
                clause.get("field") in ("medium", "format") and (("in" in clause) ^ ("not_in" in clause))
            )
            if not ok:
                raise OntologyError(f"module {module}: bad activation clause {clause}")
        return spec

    def _lens_field(self, block: str, name: str, spec: dict[str, Any]) -> LensField:
        path = f"{block}.{name}"
        kind = spec.get("kind")
        if kind not in KINDS:
            raise OntologyError(f"lens field {path}: kind must be {'|'.join(KINDS)}")
        vocab = spec.get("vocab")
        if kind in ENUM_KINDS and vocab not in self.fields:
            raise OntologyError(f"lens field {path}: unknown vocab field {vocab!r}")
        if kind not in ENUM_KINDS and vocab is not None:
            raise OntologyError(f"lens field {path}: only enum kinds take a vocab")
        max_words = None
        if kind == "phrase":
            max_words = self._cap(path, spec.get("max_words", self.phrase_max_words))
        elif "max_words" in spec:
            raise OntologyError(f"lens field {path}: only phrase fields take max_words")
        parts: tuple[LensPart, ...] = ()
        key = {"list": "item", "group": "fields"}.get(kind)
        if key is not None:
            body = spec.get(key)
            if not isinstance(body, dict) or not body:
                raise OntologyError(f"lens field {path}: a {kind} field needs `{key}` with its sub-fields")
            parts = tuple(self._part(f"{path}.{n}", n, sub) for n, sub in body.items())
        for other in ({"item", "fields"} - {key}):
            if other in spec:
                raise OntologyError(f"lens field {path}: only a {'list' if other == 'item' else 'group'} field takes `{other}`")
        max_items = spec.get("max_items")
        if kind == "list" and (not isinstance(max_items, int) or max_items < 1):
            raise OntologyError(f"lens field {path}: a list field needs max_items (a positive integer)")
        if kind != "list" and max_items is not None:
            raise OntologyError(f"lens field {path}: only list fields take max_items")
        since = spec.get("since")
        if since is not None and not re.fullmatch(r"\d+\.\d+\.\d+", str(since)):
            raise OntologyError(f"lens field {path}: since must be a version like 1.5.0")
        outcome_in = tuple(spec.get("outcome_in") or ())
        if outcome_in and "core.outcome" in self.fields and not set(outcome_in) <= set(self.enum("core.outcome")):
            raise OntologyError(f"lens field {path}: outcome_in must list core.outcome values")
        abstract = bool(spec.get("abstract", False))
        if abstract and kind != "phrase":
            raise OntologyError(f"lens field {path}: only phrase fields can be abstract")
        return LensField(block, name, kind, vocab, bool(spec.get("conditional", False)), max_words, parts,
                         max_items, since, spec.get("differs_from"), outcome_in, bool(spec.get("needs_source", False)),
                         abstract)

    def _cap(self, where: str, max_words: Any) -> int:
        if not isinstance(max_words, int) or max_words < 1:
            raise OntologyError(f"lens field {where}: max_words must be a positive integer")
        return max_words

    def _part(self, where: str, name: str, spec: dict[str, Any]) -> LensPart:
        kind = spec.get("kind") if isinstance(spec, dict) else None
        if kind == "phrase":
            return LensPart(name, "phrase", None, self._cap(where, spec.get("max_words", self.phrase_max_words)))
        if kind == "enum":
            if spec.get("vocab") not in self.fields:
                raise OntologyError(f"lens field {where}: unknown vocab field {spec.get('vocab')!r}")
            return LensPart(name, "enum", spec["vocab"])
        raise OntologyError(f"lens field {where}: a sub-field kind must be phrase|enum")

    def _check_pairing(self, f: LensField) -> None:
        if f.differs_from is None:
            return
        other = self._by_path.get(f"{f.block}.{f.differs_from}")
        if other is None or (other.kind, other.vocab) != (f.kind, f.vocab) or other is f:
            raise OntologyError(f"lens field {f.path}: differs_from must name another {f.block} field of the same kind")

    def _check_tests(self, name: str) -> None:
        """Discrimination tests (owner ruling, grid reliability): one sentence per listed value."""
        tests = self.fields[name].get("tests") or {}
        unknown = sorted(set(tests) - set(self.enum(name)))
        if unknown:
            raise OntologyError(f"vocab {name}: tests for values not in the enum: {unknown}")
        for value, text in tests.items():
            if not str(text).strip() or len(str(text).split()) > TEST_MAX_WORDS:
                raise OntologyError(f"vocab {name}: the test for {value} must be 1-{TEST_MAX_WORDS} words")

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

    def tests(self, field_name: str) -> dict[str, str]:
        """value -> its discrimination test (what makes it right and its nearest neighbour wrong)."""
        return dict(self.fields[field_name].get("tests") or {})

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
    kind: Literal["lens_field", "module", "vocab_field", "bridge_concept", "record_field"]
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
    vocab: Vocab, bridge: Bridge, cqs: CQSet, record_paths: set[str], record_fields: Iterable[str] = ()
) -> CoverageReport:
    """Field -> CQ table. Lens fields are covered by `requires:`; modules, vocab fields, and
    bridge concepts by their declared `cq_refs` (04 invariants). `record_fields` (v1.8: characters,
    failure patterns, P4 and idea additions) are covered by a `requires:` on the field or below it."""
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
    for name in record_fields:
        if name not in record_paths:
            errors.append(f"record field {name!r} is not a record path")
        cqs_for = {q for req, ids in requiring.items() if req == name or req.startswith(name + ".") for q in ids}
        rows.append(CoverageRow("record_field", name, sorted(cqs_for)))
    return CoverageReport(rows, sorted(set(errors)))
