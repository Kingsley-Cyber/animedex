"""The novelty gate's key pair (owner ruling 2026-09-27, statistics as gates, item 4): PMI replaced "unseen pair".

An idea card's `gates.pmi_key_pair` records the pair the gate judged it by: two profile values (`enum`) or two
bridge concepts (`bridge`), their PMI in bits over the `n` rows that could show both (add-half smoothed, D-015),
how often they were seen `together`, whether that subset is adequate by the rule of three (3/n < 0.02), and
whether the pair is `novel` (adequate and PMI <= -1.0, D-021).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from animedex.models.common import StrictModel


class KeyPairPMI(StrictModel):
    basis: Literal["enum", "bridge"]
    pair: list[str] = Field(min_length=2, max_length=2)
    pmi: float
    together: int = Field(ge=0)
    n: int = Field(ge=0)
    adequate: bool
    novel: bool
