"""Reproducible Metropolis-Hastings retrieval over the private notes index."""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from typing import Any


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[\w']+", value.casefold()))


def _note_text(note: dict[str, Any]) -> str:
    engine = note.get("engine") or {}
    elements = note.get("elements") or []
    return " ".join([str(note.get("premise") or ""),
                     *(str(value) for value in engine.values()),
                     *(str(item.get("pattern") or "") for item in elements if isinstance(item, dict))])


def retrieve_premises(gap: dict[str, Any], notes: dict[str, dict[str, Any]], *, count: int,
                      seed: str) -> dict[str, Any]:
    """Sample notes with a symmetric uniform proposal and a text-overlap target.

    The chain makes one corpus-sized sweep per requested premise. The target's
    positive smoothing term keeps every note reachable, including zero-overlap
    counterexamples. This is retrieval, not evidence that a genre gap is real.
    """
    if count < 1 or not notes:
        raise ValueError("premise retrieval needs notes and a positive requested count")
    slugs = sorted(notes)
    query = _terms(" ".join(str(gap.get(key) or "") for key in
                            ("anomaly", "expected_pattern", "observation")))
    weights = {slug: 1 + len(query & _terms(_note_text(notes[slug]))) for slug in slugs}
    rng = random.Random(int.from_bytes(hashlib.sha256(seed.encode()).digest(), "big"))
    state = rng.choice(slugs)
    chain: list[dict[str, Any]] = [{"state": state, "weight": weights[state]}]
    visits: Counter[str] = Counter({state: 1})
    for _ in range(len(slugs) * min(count, len(slugs))):
        proposal = rng.choice(slugs)
        accepted = rng.random() < min(1.0, weights[proposal] / weights[state])
        if accepted:
            state = proposal
        visits[state] += 1
        chain.append({"proposal": proposal, "accepted": accepted,
                      "state": state, "weight": weights[state]})
    selected = sorted((slug for slug in slugs if visits[slug]),
                      key=lambda slug: (-visits[slug], -weights[slug], slug))[:count]
    return {"method": "metropolis_hastings", "target": "1 + query token overlap with note story fields",
            "proposal": "uniform over indexed notes", "weights": weights,
            "chain": chain, "selected_note_ids": selected}
