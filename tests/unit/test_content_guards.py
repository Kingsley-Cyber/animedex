"""AC-11 dialogue heuristic: speaker lines are dialogue; a label and a description are not.
Every text here is synthetic (09)."""

from __future__ import annotations

import pytest

from animedex.content_guards import dialogue_problems

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("text", [
    "Marisol: this grid answers to me now",           # first person
    "Kaito: never again!",                             # an exclamation
    "Rhea: are they coming back?",                     # a question
    "Oren: \u201cthe tide turns tonight\u201d",       # a quote mark
    "Ana: the grid holds\nBo: the city falls",         # a script: two speaker lines
])
def test_speaker_lines_are_dialogue(text):
    assert dialogue_problems(text)


@pytest.mark.parametrize("text", [
    "Gridlock: a personal ability shaped by the user's circuit type and imagination",
    "Card duel mechanics: decks, mana, turn limits, and ranked ladders",
    "Echo Theft: steals others' skills and their memories",
    "focus on the user's wallet",                      # 'us'/'user' are not the pronoun 'us'
])
def test_a_label_and_a_description_is_not_dialogue(text):
    assert not dialogue_problems(text)
