"""`animedex diagnose` card (owner ruling 2026-09-27, M5): Kingsley's own concept, structured.

Stored only under data/diagnose/ (private, git-ignored, backed up to the private data repo). It is
never a canonical record, never in the archive and never in a blind packet, so it is not one of the
04 record types. It reuses the idea card's engine, consequences and profile shapes, so every gate
and the judge read it exactly as they read a generated card.
"""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from animedex.models.common import TITLE_ID, Provenance, StrictModel, check_id
from animedex.models.ideation import Consequences, IdeaEngine, IdeaProfile
from animedex.textutil import Words25, Words30, Words40, Words120

DIAGNOSE_ID = re.compile(r"^diag_\d{8}_[0-9a-f]{8}$")


class DiagnoseCard(StrictModel):
    diagnose_id: str
    logline: Words30
    premise: Words120
    theme_root: str = Field(min_length=1)
    engine: IdeaEngine
    what_changed: Words25
    consequences: Consequences
    profile: IdeaProfile
    closest_existing: str
    why_not_a_clone: Words40
    broken_rule: str = ""
    appetite: str = ""
    why_different: Words40 | None = None
    provenance: Provenance

    @field_validator("diagnose_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return check_id(DIAGNOSE_ID, value, "diagnose_id")

    @field_validator("closest_existing")
    @classmethod
    def _closest(cls, value: str) -> str:
        return check_id(TITLE_ID, value, "closest_existing")
