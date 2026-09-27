"""Shared contract pieces (04): provenance, scope, P1 field values, vocab-backed enums."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import core_schema

from animedex.ontology import get_bridge, get_vocab
from animedex.textutil import Words15


# ---------------------------------------------------------------- base
class StrictModel(BaseModel):
    """Every contract model: unknown keys are errors; aliases and names both accepted."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_record(self) -> dict[str, Any]:
        """JSON-ready dict using wire names (e.g. `pass`)."""
        return self.model_dump(mode="json", by_alias=True)


# ---------------------------------------------------------------- vocab-backed types
class VocabEnum:
    """`Annotated[str, VocabEnum("power_combat.gate")]`: value must be in ontology/vocab.json.

    Enum members are read at validation and schema time, so no domain values live in src/.
    """

    def __init__(self, field_name: str):
        self.field_name = field_name

    def __get_pydantic_core_schema__(self, source: Any, handler: Any) -> core_schema.CoreSchema:
        field_name = self.field_name

        def check(value: str) -> str:
            allowed = get_vocab().enum(field_name)
            if value not in allowed:
                raise ValueError(f"{value!r} is not in vocab {field_name} {list(allowed)}")
            return value

        return core_schema.no_info_after_validator_function(check, handler(source))

    def __get_pydantic_json_schema__(self, schema: Any, handler: Any) -> dict[str, Any]:
        out = handler(schema)
        out["enum"] = list(get_vocab().enum(self.field_name))
        out["x-vocab"] = self.field_name
        return out


class BridgeConcept:
    """`Annotated[str, BridgeConcept()]`: value must be a concept in ontology/bridge.json."""

    def __get_pydantic_core_schema__(self, source: Any, handler: Any) -> core_schema.CoreSchema:
        def check(value: str) -> str:
            names = get_bridge().names
            if value not in names:
                raise ValueError(f"{value!r} is not a bridge concept {list(names)}")
            return value

        return core_schema.no_info_after_validator_function(check, handler(source))

    def __get_pydantic_json_schema__(self, schema: Any, handler: Any) -> dict[str, Any]:
        out = handler(schema)
        out["enum"] = list(get_bridge().names)
        return out


# ---------------------------------------------------------------- ids (04 conventions)
TITLE_ID_RE = r"[a-z0-9]+(?:_[a-z0-9]+)*_\d{4}"
TITLE_ID = re.compile(rf"^{TITLE_ID_RE}$")
MOMENT_ID = re.compile(rf"^(?P<title>{TITLE_ID_RE})\.mo\.\d{{2}}$")
ATOM_ID = re.compile(rf"^(?P<title>{TITLE_ID_RE})\.m\.\d{{3}}$")
TRANSFER_ID = re.compile(rf"^(?P<title>{TITLE_ID_RE})\.t\.\d{{3}}$")
EPISODE_ID = re.compile(rf"^(?P<title>{TITLE_ID_RE})\.s(?P<season>\d{{2,}})e(?P<episode>\d{{2,}})$")
LINK_ID = re.compile(rf"^(?P<title>{TITLE_ID_RE})\.l\.\d{{4}}$")
PATTERN_ID = re.compile(r"^pattern\.\d{3}$")
IDEA_ID = re.compile(r"^idea\.[A-Za-z0-9_-]+\.\d{3}$")


def title_of(record_id: str) -> str | None:
    """Title id embedded in a moment/atom/transfer/episode/link id."""
    for pattern in (MOMENT_ID, ATOM_ID, TRANSFER_ID, EPISODE_ID, LINK_ID):
        m = pattern.match(record_id)
        if m:
            return m.group("title")
    return None


def check_id(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"{what} {value!r} does not match {pattern.pattern}")
    return value


# ---------------------------------------------------------------- provenance (every record)
Pass = Literal[
    "P1", "VERIFY", "P2", "P3", "CHECK", "P4", "CANONICALIZE", "EP", "ROLLUP", "PATTERNS", "IDEATE", "CENSUS"
]


class Provenance(StrictModel):
    run_id: str = Field(min_length=1)
    pass_: Pass = Field(alias="pass")
    model: str | None = None
    prompt_version: str | None = None
    schema_version: str = Field(min_length=1)
    vocab_version: str = Field(min_length=1)
    cache_key: str | None = None
    created_at: str

    @field_validator("created_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("cache_key")
    @classmethod
    def _key(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("sha256:"):
            raise ValueError("cache_key must start with 'sha256:'")
        return value


# ---------------------------------------------------------------- scope (corpus entry + title)
class Scope(StrictModel):
    version: str = Field(min_length=1)
    seasons: list[int] = Field(default_factory=list)
    numbering: Any = None  # validated against vocab below; null only for films
    exclude: list[str] = Field(default_factory=list)

    @field_validator("numbering")
    @classmethod
    def _numbering(cls, value: Any) -> Any:
        if value is None:
            return None
        allowed = get_vocab().enum("scope.numbering")
        if value not in allowed:
            raise ValueError(f"{value!r} is not in vocab scope.numbering {list(allowed)}")
        return value

    @field_validator("seasons")
    @classmethod
    def _seasons(cls, value: list[int]) -> list[int]:
        if any(s < 0 for s in value) or len(set(value)) != len(value):
            raise ValueError("seasons must be distinct non-negative integers")
        return value

    def check_for_format(self, fmt: str) -> None:
        """Films may use seasons [] and numbering null; every other format needs both (v1.2 D2)."""
        if fmt == "film":
            return
        if not self.seasons:
            raise ValueError("scope.seasons must list at least one season for non-film titles")
        if self.numbering is None:
            raise ValueError("scope.numbering is required for non-film titles")


RoleTag = Literal["gold", "hit", "mixed", "flop", "contrast"]


# ---------------------------------------------------------------- P1 field value
Source = Literal["recall", "web", "episodes"]
Verification = Literal[
    "not_required", "unverified", "web_confirmed", "web_corrected", "derived_from_episodes", "unresolved"
]
Epistemic = Literal["observed", "derived", "interpretive", "external_metric"]


class FieldValue(StrictModel):
    """Shape of every P1 field (04). Subclassed per lens field for enum/phrase rules."""

    value: str | None = None
    condition: Words15 | None = None
    conf: float = Field(ge=0.0, le=1.0)
    uncertainty_reason: Words15 | None = None
    source: Source
    verification: Verification
    source_ref: str | None = None
    epistemic: Epistemic

    # set on per-field subclasses (dunder names: pydantic leaves them alone)
    __field_path__: ClassVar[str] = ""
    __enum__: ClassVar[tuple[str, ...] | None] = None
    __conditional__: ClassVar[bool] = False
    __max_words__: ClassVar[int] = 15  # phrase fields; the vocab sets it per field (1.4.0)

    @model_validator(mode="after")
    def _rules(self) -> FieldValue:
        cls = type(self)
        if self.value is None:
            if self.conf != 0.0:
                raise ValueError("unknown value (null) must carry conf 0")
        elif cls.__enum__ is not None:
            if self.value not in cls.__enum__:
                raise ValueError(f"{self.value!r} is not in vocab for {cls.__field_path__} {list(cls.__enum__)}")
        else:
            words, cap = len(self.value.split()), cls.__max_words__
            if not self.value.strip() or words > cap:
                raise ValueError(f"phrase value must be 1-{cap} words (got {words})")
        if self.condition is not None and not cls.__conditional__:
            raise ValueError(f"{cls.__field_path__ or 'field'} does not take a condition")
        if self.verification in ("web_confirmed", "web_corrected"):
            if self.source != "web" or not self.source_ref:
                raise ValueError("web verification needs source='web' and a source_ref (recall is not verification)")
        if self.verification == "derived_from_episodes" and self.source != "episodes":
            raise ValueError("derived_from_episodes needs source='episodes'")
        return self


def field_value_type(
    path: str, enum: tuple[str, ...] | None, conditional: bool, vocab_name: str | None = None,
    max_words: int | None = None,
) -> type[FieldValue]:
    """Per-lens-field FieldValue subclass carrying its enum, condition rule and word cap."""
    name = "FV_" + re.sub(r"[^A-Za-z0-9]", "_", path)
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "__field_path__": path,
        "__enum__": enum,
        "__conditional__": conditional,
    }
    if max_words is not None:
        attrs["__max_words__"] = max_words
    if enum is not None:
        attrs["__annotations__"] = {"value": Any}
        attrs["value"] = Field(
            default=None, json_schema_extra={"enum": [*enum, None], "x-vocab": vocab_name or path}
        )
    return type(name, (FieldValue,), attrs)
