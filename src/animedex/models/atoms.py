"""Mechanism atoms (P2), proofs (P3), checks (CHECK), transfers (P4), pattern cards (M7), 04."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from animedex.models.common import (
    ATOM_ID,
    PATTERN_ID,
    TITLE_ID,
    TRANSFER_ID,
    BridgeConcept,
    Provenance,
    StrictModel,
    VocabEnum,
    check_id,
    title_of,
)
from animedex.ontology import get_vocab
from animedex.textutil import Words6, Words12, Words15, Words20, Words25, Words40

Feeling = Annotated[str, VocabEnum("feeling")]
AtomKind = Annotated[str, VocabEnum("atom_kind")]


class ElementRef(StrictModel):
    field: str | None = None
    moment_id: str | None = None


class Effect(StrictModel):
    element: Words12
    element_ref: ElementRef = Field(default_factory=ElementRef)
    feeling: Feeling
    because: Words25
    rival_because: Words25


class Engine(StrictModel):
    agent: Words6
    goal: Words15
    constraint: Words15
    strategy: Words15
    benefit: Words15
    cost: Words15
    dilemma: Words15
    dramatic_question: Words20
    feeling: Feeling


class Support(StrictModel):
    status: Annotated[str, VocabEnum("support.status")] = "profile_only"
    supporting_episodes: list[str] = Field(default_factory=list)
    contradicting_episodes: list[str] = Field(default_factory=list)
    reframing_episodes: list[str] = Field(default_factory=list)


class MechanismAtom(StrictModel):
    atom_id: str
    title_id: str
    atom_kind: AtomKind
    effect: Effect | None = None
    engine: Engine | None = None
    module: str
    epistemic: Literal["interpretive"] = "interpretive"
    conf: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(min_length=1)
    explanation: Annotated[str, VocabEnum("explanation")] = "settled"
    support: Support = Field(default_factory=Support)
    origin: Literal["p2", "promoted_from_episodes"] = "p2"
    provenance: Provenance

    @field_validator("module")
    @classmethod
    def _module(cls, value: str) -> str:
        allowed = ["core", *get_vocab().module_names]
        if value not in allowed:
            raise ValueError(f"module {value!r} not in {allowed}")
        return value

    @model_validator(mode="after")
    def _shape(self) -> MechanismAtom:
        check_id(ATOM_ID, self.atom_id, "atom_id")
        if title_of(self.atom_id) != self.title_id:
            raise ValueError("atom_id must start with its title_id")
        has = {"effect": self.effect is not None, "engine": self.engine is not None}
        if sum(has.values()) != 1 or not has.get(self.atom_kind, False):
            raise ValueError("exactly one of effect/engine must be present, matching atom_kind")
        return self


class Contrast(StrictModel):
    partner_title_id: str
    partner_role: Literal["nearest_neighbor", "flop", "cross_medium"]
    partner_has: Literal["yes", "no", "partial"]
    difference: Words25

    @field_validator("partner_title_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "partner_title_id")


class ExplanationTest(StrictModel):
    favors: Literal["because", "rival", "both", "neither"]
    via_partner: str
    note: Words25


class Ablation(StrictModel):
    if_removed: Words25
    verdict: Literal["load_bearing", "supporting", "decoration"]
    conf: float = Field(ge=0.0, le=1.0)


class ProofRecord(StrictModel):
    atom_id: str
    contrast: list[Contrast] = Field(min_length=1)
    explanation_test: ExplanationTest | None = None  # required for effect atoms (cross-record check)
    ablation: Ablation
    provenance: Provenance

    @field_validator("atom_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(ATOM_ID, value, "atom_id")


CheckReason = Literal[
    "unsupported", "overreach", "merged_claims", "off_vocab", "contradiction", "circular",
    "granularity", "scope_leak",
]


class CheckRecord(StrictModel):
    target_id: str = Field(min_length=1)
    target_type: Literal["mechanism", "proof"]
    verdict: Literal["ACCEPT", "REVISE", "REJECT", "CONTESTED", "NEEDS_ADJUDICATION"]
    reasons: list[CheckReason] = Field(default_factory=list)
    revision: dict[str, Any] | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _revision(self) -> CheckRecord:
        if self.verdict == "REVISE" and not self.revision:
            raise ValueError("REVISE must carry the corrected record")
        if self.verdict in ("REJECT", "REVISE") and not self.reasons:
            raise ValueError(f"{self.verdict} needs at least one reason")
        return self


class TransferAtom(StrictModel):
    transfer_id: str
    source_atom_id: str
    atom_kind: AtomKind
    pattern: Words25
    bridge: list[Annotated[str, BridgeConcept()]] = Field(min_length=1)
    essential_conditions: list[Words12] = Field(min_length=1)
    variable_details: list[Words12] = Field(min_length=1)
    failure_conditions: list[Words12] = Field(min_length=1)
    provenance: Provenance

    @model_validator(mode="after")
    def _ids(self) -> TransferAtom:
        check_id(TRANSFER_ID, self.transfer_id, "transfer_id")
        check_id(ATOM_ID, self.source_atom_id, "source_atom_id")
        if title_of(self.transfer_id) != title_of(self.source_atom_id):
            raise ValueError("transfer_id and source_atom_id must share a title")
        return self


class Counterexample(StrictModel):
    title_id: str
    why: Words25


class PatternCard(StrictModel):
    """Pattern card (M7). 04 requires a recorded counterexample search; see AC-40."""

    pattern_id: str
    statement: Words40
    transfer_ids: list[str] = Field(min_length=1)
    supporting_titles: list[str] = Field(min_length=1)
    counterexamples: list[Counterexample] = Field(default_factory=list)
    boundary_conditions: list[Words12] = Field(default_factory=list)
    alternative_explanations: list[Words25] = Field(default_factory=list)
    scope: Literal["title", "corpus_subset", "corpus"]
    provenance: Provenance

    @field_validator("pattern_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(PATTERN_ID, value, "pattern_id")
