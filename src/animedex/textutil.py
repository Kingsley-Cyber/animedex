"""Text limits (04: phrases <= 12 words, sentences <= 25, summaries <= 60) and stable JSON."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any

from pydantic import AfterValidator


def word_count(text: str) -> int:
    return len(text.split())


def _max_words(limit: int):
    def check(value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        n = word_count(value)
        if n > limit:
            raise ValueError(f"{n} words exceeds the {limit}-word limit")
        return value

    return check


def words(limit: int) -> Any:
    """A non-blank string capped at `limit` words."""
    return Annotated[str, AfterValidator(_max_words(limit))]


Words6 = words(6)
Words12 = words(12)
Words15 = words(15)
Words20 = words(20)
Words25 = words(25)
Words30 = words(30)
Words40 = words(40)
Words60 = words(60)
Words120 = words(120)


# Medium-specific words (04: transfer patterns, and premise abstractions from vocab 1.5.0, never use them)
MEDIUM_WORDS = ("anime", "manga", "manhua", "manhwa", "donghua", "cartoon", "cartoons", "episode", "episodes",
                "season", "seasons", "show", "shows", "film", "films", "movie", "movies", "cour", "cours", "ova",
                "webtoon", "studio", "chapter", "chapters", "volume", "volumes", "light novel", "light novels")
_MEDIUM = re.compile(r"(?<![a-z])(" + "|".join(MEDIUM_WORDS) + r")(?![a-z])", re.I)


def medium_words(text: str) -> list[str]:
    """The medium-specific words a domain-neutral text uses, lowercased and sorted."""
    return sorted({m.lower() for m in _MEDIUM.findall(text)})


def stable_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 kept."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
