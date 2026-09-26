"""Moments, outcomes, episodes (M6), and links (M6), 04."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from animedex.models.common import (
    EPISODE_ID,
    LINK_ID,
    MOMENT_ID,
    TITLE_ID,
    Provenance,
    StrictModel,
    Verification,
    VocabEnum,
    check_id,
)
from animedex.textutil import Words12, Words25, Words60


class MomentLocator(StrictModel):
    season: int | None = None
    episode: int | None = None
    timestamp: str | None = None
    episode_id: str | None = None


class Moment(StrictModel):
    moment_id: str
    title_id: str
    description: Words25
    locator: MomentLocator = Field(default_factory=MomentLocator)
    moment_type: Annotated[str, VocabEnum("moment_type")]
    why_it_hit: Words25
    conf: float = Field(ge=0.0, le=1.0)
    verification: Verification
    source_ref: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _ids(self) -> Moment:
        check_id(MOMENT_ID, self.moment_id, "moment_id")
        if not self.moment_id.startswith(self.title_id + "."):
            raise ValueError("moment_id must start with its title_id")
        if self.verification in ("web_confirmed", "web_corrected") and not self.source_ref:
            raise ValueError("a web-verified moment needs a source_ref")
        return self


class Signal(StrictModel):
    metric: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)


class Confounders(StrictModel):
    studio: str = ""
    budget_signal: str = ""
    source_popularity: str = ""
    platform: str = ""
    release_context: str = ""


class Outcome(StrictModel):
    """External-metric outcome record (VERIFY)."""

    title_id: str
    label: Annotated[str, VocabEnum("core.outcome")]
    signals: list[Signal] = Field(default_factory=list)
    confounders: Confounders = Field(default_factory=Confounders)
    failure_reason: Words25 | None = None
    provenance: Provenance

    @field_validator("title_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "title_id")


# ---------------------------------------------------------------- episodes (M6)
class EpisodeLocator(StrictModel):
    season: int = Field(ge=0)
    episode: int = Field(ge=0)
    episode_title: str = ""
    numbering: Annotated[str, VocabEnum("scope.numbering")]


EngineAdvance = Literal["goal", "constraint", "strategy", "benefit", "cost", "dilemma"]


class EngineBeat(StrictModel):
    engine_atom_id: str
    advances: EngineAdvance
    note: Words25


class Decision(StrictModel):
    agent: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    choice: str = Field(min_length=1)
    rejected: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    actual: str = Field(min_length=1)


class InfoShift(StrictModel):
    audience_learns: str = ""
    characters_learn: str = ""
    gap_change: Annotated[str, VocabEnum("info_shift.gap_change")]


class Payoff(StrictModel):
    payoff: Words12
    setup_episode_id: str | None = None


class AtomSupport(StrictModel):
    atom_id: str
    relation: Literal["supports", "contradicts", "reframes"]
    note: Words25


class ProposedAtom(StrictModel):
    atom_kind: Annotated[str, VocabEnum("atom_kind")]
    draft: Words25


class Episode(StrictModel):
    """Episode evidence record (M6). Never created from recall: source must be a fetched URL."""

    episode_id: str
    title_id: str
    locator: EpisodeLocator
    selection_reason: Annotated[str, VocabEnum("episode.selection_reason")]
    summary: Words60
    function: Annotated[str, VocabEnum("episode.function")]
    end_hook: Annotated[str, VocabEnum("episode.end_hook")]
    engine_beat: EngineBeat | None = None
    decisions: list[Decision] = Field(default_factory=list)
    info_shift: InfoShift
    setups: list[Words12] = Field(default_factory=list)
    payoffs: list[Payoff] = Field(default_factory=list)
    moment_refs: list[str] = Field(default_factory=list)
    atom_support: list[AtomSupport] = Field(default_factory=list)
    proposed_atoms: list[ProposedAtom] = Field(default_factory=list)
    source: Literal["web"]
    source_ref: str = Field(min_length=1)
    verification: Literal["web_confirmed", "unresolved"]
    provenance: Provenance

    @model_validator(mode="after")
    def _ids(self) -> Episode:
        m = EPISODE_ID.match(self.episode_id)
        if not m:
            raise ValueError(f"episode_id {self.episode_id!r} does not match {EPISODE_ID.pattern}")
        if m.group("title") != self.title_id:
            raise ValueError("episode_id must start with its title_id")
        if (int(m.group("season")), int(m.group("episode"))) != (self.locator.season, self.locator.episode):
            raise ValueError("episode_id season/episode must match the locator")
        if not self.source_ref.startswith(("http://", "https://")):
            raise ValueError("episode source_ref must be the fetched URL")
        return self


class Link(StrictModel):
    link_id: str
    title_id: str
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    type: Annotated[str, VocabEnum("link.type")]
    evidence: Words25
    provenance: Provenance

    @model_validator(mode="after")
    def _ids(self) -> Link:
        check_id(LINK_ID, self.link_id, "link_id")
        if not self.link_id.startswith(self.title_id + "."):
            raise ValueError("link_id must start with its title_id")
        return self
