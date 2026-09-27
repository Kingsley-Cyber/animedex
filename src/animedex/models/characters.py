"""Characters (v1.8, `characters.jsonl`): up to 4 per title, id `{title_id}.c.{nn}`, 04.

One record per cast role (protagonist, main rival, main antagonist, mentor or deuteragonist). Base
fields are nullable: null is "unknown", as on P1 fields. A power kit sits on up to 3 powered
characters per title (protagonist first); villain fields only on the main antagonist. Per-title
limits are cross-record checks (integrity). Names are allowed here, and join the name-leak list so
they never reach patterns or idea cards.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator, model_validator

from animedex.models.common import (
    CHARACTER_ID,
    Provenance,
    StrictModel,
    VocabEnum,
    check_id,
    title_of,
)
from animedex.textutil import Words6, Words15, Words20, Words25

MAX_CHARACTERS = 4            # per title (v1.8 §5)
MAX_POWER_KITS = 3            # per title, protagonist first
MAX_TURNING_POINTS = 3
KIT_FUNCTIONS = (3, 6)
MAX_KIT_TOOLS = 5
MAX_KIT_LIMITS = 5
MAX_KIT_FORMS = 5
MAX_CREATIVITY_MOVES = 3
ROLE_LIMITS = {"protagonist": 1, "main_rival": 1, "main_antagonist": 1}
SHARED_SLOT = ("mentor", "deuteragonist")   # one slot: a mentor or a deuteragonist
ANTAGONIST_ROLES = ("main_antagonist",)     # the roles that carry villain fields

MCEdge = Annotated[str, VocabEnum("power_combat.mc_edge")]
PowerKind = Annotated[str, VocabEnum("character.power_kind")]
OriginPowerLink = Annotated[str, VocabEnum("character.origin_power_link")]


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


class ConditionalTrait(StrictModel):
    """A flaw or moral line with its condition (when the flaw shows / what would make them cross it)."""

    value: Words15
    condition: Words15


class TurningPointLocator(StrictModel):
    """Where a turning point happens. Non-film titles need the episode (checked against the title)."""

    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=0)


class TurningPoint(StrictModel):
    event: Words15
    locator: TurningPointLocator


class KitTool(StrictModel):
    """A signature application of a power, naming the kit function it exploits."""

    tool: Words15
    function: Words15


class KitForm(StrictModel):
    """A named stage of the power, with what triggers it and what it costs."""

    name: Words6
    trigger: Words15
    cost: Words15


class CreativityMove(StrictModel):
    """A use beyond the power's obvious design, with the page it is documented on."""

    move: Words15
    source_ref: str

    @field_validator("source_ref")
    @classmethod
    def _url(cls, value: str) -> str:
        if not is_url(value):
            raise ValueError("a creativity move needs its source URL")
        return value


def tool_problems(functions: list[str], tools: list[KitTool]) -> list[str]:
    """Each tool must name one of the kit's functions (case-insensitive)."""
    known = {f.strip().lower() for f in functions}
    return [f"tool {t.tool!r} names {t.function!r}, which is not one of the kit's functions"
            for t in tools if t.function.strip().lower() not in known]


class PowerKit(StrictModel):
    """What a powered character can do (v1.8 §5). `stat_block` kits generate drama through
    `drama_source`; every other kit through creativity (level, backed by sourced moves)."""

    power_kind: PowerKind
    medium: Words6 | None = None
    functions: list[Words15] = Field(default_factory=list, max_length=KIT_FUNCTIONS[1])
    tools: list[KitTool] = Field(default_factory=list, max_length=MAX_KIT_TOOLS)
    limits: list[Words15] = Field(default_factory=list, max_length=MAX_KIT_LIMITS)
    forms: list[KitForm] = Field(default_factory=list, max_length=MAX_KIT_FORMS)
    creativity_level: Annotated[str, VocabEnum("character.creativity_level")] | None = None
    creativity_moves: list[CreativityMove] = Field(default_factory=list, max_length=MAX_CREATIVITY_MOVES)
    drama_source: Annotated[str, VocabEnum("character.drama_source")] | None = None
    evolution: Words20 | None = None

    @model_validator(mode="after")
    def _kit(self) -> PowerKit:
        if self.power_kind == "none":
            if self.functions or self.tools or self.forms or self.creativity_moves or self.creativity_level \
                    or self.drama_source:
                raise ValueError("a kit of kind none has no functions, tools, forms, creativity or drama_source")
            return self
        lo, hi = KIT_FUNCTIONS
        if not lo <= len(self.functions) <= hi:
            raise ValueError(f"a power kit lists {lo}-{hi} core functions (got {len(self.functions)})")
        problems = tool_problems(self.functions, self.tools)
        if problems:
            raise ValueError("; ".join(problems))
        if self.power_kind == "stat_block":
            if self.creativity_level is not None or self.creativity_moves:
                raise ValueError("a stat_block kit takes drama_source instead of creativity")
            if self.drama_source is None:
                raise ValueError("a stat_block kit needs a drama_source")
        else:
            if self.drama_source is not None:
                raise ValueError("drama_source is only for stat_block kits")
            if self.creativity_level in ("inventive", "transcendent") and not self.creativity_moves:
                raise ValueError(f"creativity_level {self.creativity_level} needs at least one sourced creativity move")
        return self


class VillainFields(StrictModel):
    """Antagonist roles only (v1.8 §5)."""

    villain_type: Annotated[str, VocabEnum("character.villain_type")]
    villain_reveal: Annotated[str, VocabEnum("character.villain_reveal")]
    relation_to_mc: Annotated[str, VocabEnum("character.relation_to_mc")]


class CharacterRecord(StrictModel):
    """One cast member of a title (v1.8 §5). Base fields must be written out; null means unknown."""

    character_id: str
    title_id: str
    name: Words6
    role: Annotated[str, VocabEnum("character.role")]
    origin: Words25 | None
    wound: Words15 | None             # the formative loss or event
    want: Words15 | None
    need: Words15 | None
    flaw: ConditionalTrait | None
    moral_line: ConditionalTrait | None
    relationship_to_power: MCEdge | None
    origin_power_link: OriginPowerLink | None
    arc_type: Annotated[str, VocabEnum("character.arc_type")] | None
    backstory_reveal: Annotated[str, VocabEnum("character.backstory_reveal")] | None
    turning_points: list[TurningPoint] = Field(default_factory=list, max_length=MAX_TURNING_POINTS)
    power_kit: PowerKit | None = None
    villain: VillainFields | None = None
    source_refs: list[str] = Field(default_factory=list)   # pages the documented facts came from
    provenance: Provenance

    @model_validator(mode="after")
    def _shape(self) -> CharacterRecord:
        check_id(CHARACTER_ID, self.character_id, "character_id")
        if title_of(self.character_id) != self.title_id:
            raise ValueError("character_id must start with its title_id")
        if self.villain is not None and self.role not in ANTAGONIST_ROLES:
            raise ValueError(f"villain fields are only for {'/'.join(ANTAGONIST_ROLES)} (role is {self.role})")
        if self.villain is None and self.role in ANTAGONIST_ROLES:
            raise ValueError(f"a {self.role} needs villain fields (villain_type, villain_reveal, relation_to_mc)")
        bad = [u for u in self.source_refs if not is_url(u)]
        if bad:
            raise ValueError(f"source_refs must be URLs: {bad[:3]}")
        return self


def cq_fields() -> list[str]:
    """The character fields every competency-question set must reference (the orphan check)."""
    skip = {"character_id", "title_id", "name", "source_refs", "provenance"}
    out = [n for n in CharacterRecord.model_fields if n not in skip]
    out += [f"power_kit.{n}" for n in PowerKit.model_fields]
    out += [f"villain.{n}" for n in VillainFields.model_fields]
    return out
