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
    source_transfer_ids: list[str] = Field(default_factory=list)  # >=1 on animedex cards (IdeaCard._arm_atoms)
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


class PremortemItem(StrictModel):
    """v1.6: a way this idea could fail, drawn from a mixed/flop title's recorded failure."""

    risk: Words25
    source_title_id: str
    mitigation: Words25

    @field_validator("source_title_id")
    @classmethod
    def _src(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "source_title_id")


class RevivalRef(StrictModel):
    """v1.6: an execution-level flop whose premise this idea keeps (T5 'retold better')."""

    title_id: str
    failure_evidence_ref: str | None = None
    improvement: Words25

    @field_validator("title_id")
    @classmethod
    def _tid(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "title_id")


class Runway(StrictModel):
    """v1.6 judge question: does the engine's cost still hurt by arc 5?"""

    hurts_by_arc5: bool
    reason: Words25


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
    atoms_used: list[str] = Field(default_factory=list)  # >=1 on animedex cards (IdeaCard._arm_atoms)
    borrowed_from: list[str] = Field(default_factory=list)
    broken_rule: str = ""
    appetite: str = ""
    closest_existing: str
    why_not_a_clone: Words40
    why_different: Words40 | None = None  # required when a premise-level graveyard combination matches
    premortem: list[PremortemItem] = Field(default_factory=list)
    revival_of: RevivalRef | None = None
    runway: Runway | None = None
    gates: Gates
    taste: Taste
    status: Literal["candidate", "champion", "rejected"]
    # M5 fair baselines (controls A5, decision 1): which blind-review arm wrote the card
    arm: Literal["animedex", "baseline_loop", "baseline_single"] = "animedex"
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

    @model_validator(mode="after")
    def _arm_atoms(self) -> IdeaCard:
        """ANIMEDEX cards draw on >=1 index atom (AC-26); a baseline arm writes without the index."""
        if self.arm == "animedex" and not (self.atoms_used and self.transformation.source_transfer_ids):
            raise ValueError("an animedex card uses at least one transfer atom (atoms_used, source_transfer_ids)")
        return self


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


# ---------------------------------------------------------------- v1.6: prior art and census
class Counterexample(StrictModel):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    match_note: Words25


class PriorArtCheck(StrictModel):
    """A web check of an absence claim (T1 'never done', T4 zero occurrence, an imported/export lane)."""

    check_id: str = Field(min_length=1)
    claim_kind: Literal["T1", "T4", "lane"]
    subject_id: str = Field(min_length=1)   # idea_id, or lane:<concept>
    claim: str = Field(min_length=1)
    queries: list[str] = Field(default_factory=list)
    verdict: Literal["clear", "counterexample", "inconclusive"]
    counterexamples: list[Counterexample] = Field(default_factory=list)
    provenance: Provenance


BORROWED_SYSTEMS = ("game", "exam_or_school", "job_or_bureaucracy", "market_or_economy", "sport", "social_rating",
                    "law_or_contract", "card_or_collection", "crafting_or_cooking", "military_rank", "ritual_or_religion",
                    "none", "other")


class CensusEntry(StrictModel):
    """v1.6 census: counts only (trust: recall). Never an atom, evidence, or ideation input."""

    census_id: str = Field(pattern=r"^[a-z]+:\d+$")   # catalog:id, e.g. anilist:127401
    title: str = Field(min_length=1)
    year: int | None = None
    medium: Annotated[str, VocabEnum("medium")]
    format: str = Field(min_length=1)
    popularity: int | None = None
    has_power_system: bool | None = None
    gate: Annotated[str, VocabEnum("power_combat.gate")] | None = None
    cost_of_power: Annotated[str, VocabEnum("power_combat.cost_of_power")] | None = None
    progression: Annotated[str, VocabEnum("power_combat.progression")] | None = None
    visible_counter: Annotated[str, VocabEnum("power_combat.visible_counter")] | None = None
    fight_medium: Annotated[str, VocabEnum("power_combat.fight_medium")] | None = None
    power_is: Annotated[str, VocabEnum("relationships.power_is")] | None = None
    borrowed_system: Literal[BORROWED_SYSTEMS] | None = None  # type: ignore[valid-type]
    trust: Literal["recall"] = "recall"
    batch_id: str = Field(min_length=1)
    provenance: Provenance

