"""Title profile (P1, `titles.jsonl`) and corpus entry (`corpus/titles.yaml`), 04.

The core block and module blocks are built from the lens in ontology/vocab.json, so module
definitions stay out of src/ (10 §6). A lens field added in a later vocab (`since`) may be absent
from a record made under an older one; it is omitted, not null-filled (vocab 1.5.0).
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from pydantic import Field, create_model, field_validator, model_serializer, model_validator

from animedex.models.common import (
    TITLE_ID,
    FieldValue,
    Provenance,
    RoleTag,
    Scope,
    StrictModel,
    VocabEnum,
    check_id,
    field_value_type,
)
from animedex.ontology import LensField, Vocab, get_vocab, version_tuple
from animedex.textutil import medium_words

Medium = Annotated[str, VocabEnum("medium")]
Format = Annotated[str, VocabEnum("format")]


class PartnerOverrides(StrictModel):
    nearest_neighbor: str | None = None
    flop: str | None = None
    cross_medium: str | None = None


class CorpusEntry(StrictModel):
    """One title in corpus/titles.yaml (01): medium, format, scope, role tags, partner overrides."""

    title_id: str
    title: str = Field(min_length=1)
    year: int = Field(ge=1900, le=2100)
    medium: Medium
    format: Format
    scope: Scope
    role_tags: list[RoleTag] = Field(default_factory=list)
    partners: PartnerOverrides | None = None
    # v1.3: Kingsley's call on premise vs. execution failure wins over VERIFY's
    failure_level_override: Annotated[str, VocabEnum("outcome.failure_level")] | None = None
    # catalog entry the title was resolved to, e.g. "anilist:127401" (backfill, census)
    catalog_ref: str | None = None

    @field_validator("title_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "title_id")

    @model_validator(mode="after")
    def _scope_rules(self) -> CorpusEntry:
        if not self.title_id.endswith(f"_{self.year}"):
            raise ValueError("title_id must end with the first-airing year (slug + year)")
        self.scope.check_for_format(self.format)
        return self


class TitleProfileBase(StrictModel):
    """Fields shared by every title profile; lens blocks are added per vocab version."""

    title_id: str
    title: str = Field(min_length=1)
    year: int = Field(ge=1900, le=2100)
    medium: Medium
    format: Format
    scope: Scope
    role_tags: list[RoleTag] = Field(default_factory=list)
    modules_active: list[str] = Field(default_factory=list)
    provenance: Provenance

    __module_names__: ClassVar[tuple[str, ...]] = ()

    @field_validator("title_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "title_id")

    @model_validator(mode="after")
    def _modules(self) -> TitleProfileBase:
        known = tuple(type(self).__module_names__)
        active = self.modules_active
        if len(set(active)) != len(active):
            raise ValueError("modules_active has duplicates")
        unknown = [m for m in active if m not in known]
        if unknown:
            raise ValueError(f"unknown modules {unknown}; lens modules are {list(known)}")
        for m in known:
            present = getattr(self, m) is not None
            if present and m not in active:
                raise ValueError(f"module {m} is present but not in modules_active (omit inactive modules)")
            if m in active and not present:
                raise ValueError(f"module {m} is active but missing")
        self.scope.check_for_format(self.format)
        return self

    @model_serializer(mode="wrap")
    def _omit_inactive(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for m in type(self).__module_names__:
            if data.get(m) is None:
                data.pop(m, None)
        return data

    @model_validator(mode="after")
    def _lens_rules(self) -> TitleProfileBase:
        """Cross-field rules from the lens (vocab 1.5.0): fields a record's vocab version requires are
        present; a secondary value differs from its primary; outcome-bound fields only on those outcomes;
        abstract phrases carry no medium words."""
        version = version_tuple(self.provenance.vocab_version)
        outcome_fv = getattr(self.core, "outcome", None)
        outcome = outcome_fv.value if isinstance(outcome_fv, FieldValue) else None
        for block in ["core", *self.modules_active]:
            body = getattr(self, block)
            for name, f in type(body).__lens__.items():
                fv = getattr(body, name)
                if fv is None:
                    if f.since and version >= version_tuple(f.since):
                        raise ValueError(f"{f.path} is missing (a lens field since vocab {f.since})")
                    continue
                if fv.value is None:
                    continue
                if f.differs_from:
                    primary = getattr(body, f.differs_from)
                    if primary is None or primary.value is None:
                        raise ValueError(f"{f.path} needs {block}.{f.differs_from} (a secondary needs its primary)")
                    if primary.value == fv.value:
                        raise ValueError(f"{f.path} must differ from {block}.{f.differs_from}")
                if f.outcome_in and outcome not in f.outcome_in:
                    raise ValueError(f"{f.path} is only for {'/'.join(f.outcome_in)} titles (core.outcome is {outcome})")
                if f.abstract and (found := medium_words(fv.value)):
                    raise ValueError(f"{f.path} uses medium words {found}")
        return self


class LensBlock(StrictModel):
    """The core block or a module block. A field the record's vocab predates stays absent (omitted)."""

    __lens__: ClassVar[dict[str, LensField]] = {}

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for name, f in type(self).__lens__.items():
            if f.since and name in data and data[name] is None:
                data.pop(name)
        return data


def _block_model(vocab: Vocab, block: str) -> type[LensBlock]:
    fields: dict[str, Any] = {}
    for f in vocab.block_fields(block):
        fv = field_value_type(f, vocab)
        fields[f.name] = (fv | None, None) if f.since else (fv, ...)
    name = "Core" if block == "core" else "".join(p.title() for p in block.split("_"))
    model = create_model(f"{name}Block", __base__=LensBlock, **fields)
    model.__lens__ = {f.name: f for f in vocab.block_fields(block)}
    return model


_title_models: dict[tuple[int, str], type[TitleProfileBase]] = {}


def title_profile_model(vocab: Vocab | None = None) -> type[TitleProfileBase]:
    """TitleProfile class for the given (default: current) vocab; cached per vocab object."""
    vocab = vocab or get_vocab()
    key = (id(vocab), vocab.version)
    if key not in _title_models:
        fields: dict[str, Any] = {"core": (_block_model(vocab, "core"), ...)}
        for m in vocab.module_names:
            fields[m] = (_block_model(vocab, m) | None, None)
        model = create_model("TitleProfile", __base__=TitleProfileBase, **fields)
        model.__module_names__ = tuple(vocab.module_names)
        _title_models[key] = model
    return _title_models[key]
