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
    # D-041, live M5: a sentence-case label is a description even when the text says "your"
    "Iyashikei safety: cozy club comedies never kill main characters, and sacrifice gives your death meaning.",
])
def test_a_label_and_a_description_is_not_dialogue(text):
    assert not dialogue_problems(text)


def test_urls_are_not_read_as_quotations():
    """A URL is never read as quoted text; a quoted line in a text field is."""
    from animedex.content_guards import paraphrase_problems

    rec = {"claim": "an original story where memory is the price", "url": 'https://e.org/"only she remembers"'}
    assert paraphrase_problems(rec) == []
    assert paraphrase_problems({"claim": 'she said "only she remembers the night" once'})
