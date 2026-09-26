"""Idea cards, the MAP-Elites archive (04, v1.2: status `champion`), and the coverage ledger."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from animedex.models.common import (
    IDEA_ID,
    TITLE_ID,
    BridgeConcept,
    Provenance,
    StrictModel,
    VocabEnum,
    check_id,
)
from animedex.textutil import Words25, Words30, Words40, Words120

TasteCriterion = Literal["T1", "T2", "T3", "T4", "T5"]


class IdeaEngine(StrictModel):
    goal: str = Field(min_length=1)
    constraint: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    benefit: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    dilemma: str = Field(min_length=1)
    dramatic_question: str = Field(min_length=1)


class Transformation(StrictModel):
    operator: Annotated[str, VocabEnum("transformation.operator")]
    source_transfer_ids: list[str] = Field(min_length=1)
    what_changed: Words25


class Consequences(StrictModel):
    choices: Words25
    relationships: Words25
    outcomes: Words25


class IdeaProfile(StrictModel):
    """Same enums as title profiles so overlap is computable."""

    gate: Annotated[str, VocabEnum("power_combat.gate")]
    cost_of_power: Annotated[str, VocabEnum("power_combat.cost_of_power")]
    progression: Annotated[str, VocabEnum("power_combat.progression")]
    visible_counter: Annotated[str, VocabEnum("power_combat.visible_counter")]
    fight_medium: Annotated[str, VocabEnum("power_combat.fight_medium")]
    power_is: Annotated[str, VocabEnum("relationships.power_is")]


class ConsequenceTest(StrictModel):
    choices: bool
    relationships: bool
    outcomes: bool
    h1_pass: bool


class Gates(StrictModel):
    structural_jaccard_max: float = Field(ge=0.0, le=1.0)
    procedural_jaccard_max: float = Field(ge=0.0, le=1.0)
    premise_cosine_max: float = Field(ge=-1.0, le=1.0)
    novel_combo: bool
    graveyard_hits: list[str] = Field(default_factory=list)
    failure_conditions_triggered: list[str] = Field(default_factory=list)
    consequence_test: ConsequenceTest
    coherence: Literal["pass", "fail"]


class Taste(StrictModel):
    criteria_met: list[TasteCriterion] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    hard_fail: bool = False

    @model_validator(mode="after")
    def _evidence(self) -> Taste:
        missing = [c for c in self.criteria_met if not self.evidence.get(c, "").strip()]
        if missing:
            raise ValueError(f"taste criteria {missing} lack required evidence")
        extra = sorted(set(self.evidence) - set(self.criteria_met))
        if extra:
            raise ValueError(f"evidence given for criteria not met: {extra}")
        return self


class HumanRating(StrictModel):
    """Kingsley's blind-review verdict. 'Elite' is his call, never the pipeline's."""

    rating: int = Field(ge=1, le=5)
    greenlight: bool
    criteria: list[TasteCriterion] = Field(default_factory=list)


class IdeaCard(StrictModel):
    idea_id: str
    target_domain: str = Field(min_length=1)
    logline: Words30
    premise: Words120
    theme_root: str = Field(min_length=1)
    engine: IdeaEngine
    transformation: Transformation
    consequences: Consequences
    profile: IdeaProfile
    bridge: list[Annotated[str, BridgeConcept()]] = Field(default_factory=list)
    grid_cell: str = Field(min_length=1)
    atoms_used: list[str] = Field(min_length=1)
    borrowed_from: list[str] = Field(default_factory=list)
    broken_rule: str = ""
    appetite: str = ""
    closest_existing: str
    why_not_a_clone: Words40
    gates: Gates
    taste: Taste
    status: Literal["candidate", "champion", "rejected"]
    generation: int = Field(ge=0)
    parent_ids: list[str] = Field(default_factory=list)
    human_rating: HumanRating | None = None
    provenance: Provenance

    @field_validator("idea_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(IDEA_ID, value, "idea_id")

    @field_validator("closest_existing")
    @classmethod
    def _closest(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "closest_existing")


class ArchiveRecord(StrictModel):
    """One occupied grid cell: the current champion and the idea it replaced, if any."""

    cell_key: str = Field(min_length=1)
    idea_id: str
    fitness: list[float]
    replaced_idea_id: str | None = None
    generation: int = Field(ge=0)
    provenance: Provenance


class EpisodeCounts(StrictModel):
    in_scope: int = Field(default=0, ge=0)
    indexed: int = Field(default=0, ge=0)
    unsourced: int = Field(default=0, ge=0)
    selection: dict[str, int] = Field(default_factory=dict)

    @field_validator("selection")
    @classmethod
    def _selection(cls, value: dict[str, int]) -> dict[str, int]:
        from animedex.ontology import get_vocab

        allowed = set(get_vocab().enum("episode.selection_reason"))
        unknown = sorted(set(value) - allowed)
        if unknown or any(v < 0 for v in value.values()):
            raise ValueError(f"selection keys must be {sorted(allowed)} with counts >= 0")
        return value


PassDone = Literal["P1", "VERIFY", "P2", "P3", "CHECK", "P4", "EP", "ROLLUP"]


class CoverageLedger(StrictModel):
    title_id: str
    passes_done: list[PassDone] = Field(default_factory=list)
    field_completion: float = Field(ge=0.0, le=1.0)
    verified_share: float = Field(ge=0.0, le=1.0)
    modules_active: list[str] = Field(default_factory=list)
    episodes: EpisodeCounts = Field(default_factory=EpisodeCounts)
    episode_backed_share: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: Provenance

    @field_validator("title_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "title_id")
