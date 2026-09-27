"""The paraphrase guard: no quotations and no dialogue lines in anything a model writes into notes or cards."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from animedex.textutil import word_count

MIN_QUOTE_WORDS = 3
_QUOTED = re.compile(r'["“”„«»]([^"“”„«»]{1,400})["“”„«»]|‘([^‘’]{1,400})’')
# a speaker label is a name: one to four Title Case words ("Kira:", "Killua Zoldyck:", "Mr. Smith:"); a
# sentence-case label ("Iyashikei safety: ...") introduces a description, not speech (D-041)
_SPEAKER = re.compile(r"^\s*[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}:\s+(\S.*)$", re.MULTILINE)
# what makes the text after a speaker label read as speech: first/second person, an exclamation or
# question, or an opening quote mark
_SPEECH = re.compile(r"(?i)(?<![\w'])(i|i'm|i'll|i've|i'd|me|my|mine|we|we're|we'll|us|our|ours|you|you're|"
                     r"you'll|your|yours)(?![\w'])|[!?][\"'”’]?\s*$|^[\"'“‘]")
SKIP_KEYS = {"show", "slug", "url", "sources", "provenance", "created_at", "cache_key", "model", "index_slug",
             "closest_existing", "closest_slug", "ref"}


def quote_problems(text: str, min_words: int = MIN_QUOTE_WORDS) -> list[str]:
    out = []
    for m in _QUOTED.finditer(text):
        inner = m.group(1) or m.group(2) or ""
        if word_count(inner) >= min_words:
            out.append(f"looks like a quotation: {m.group(0)[:60]!r}")
    return out


def dialogue_problems(text: str) -> list[str]:
    """A speaker label followed by speech, or a script (two or more speaker-label lines). A label followed
    by a description ("Gridlock: an ability shaped by the user's circuit type") is a phrase style."""
    lines = list(_SPEAKER.finditer(text))
    return [f"looks like a dialogue line: {m.group(0).strip()[:60]!r}" for m in lines
            if len(lines) >= 2 or _SPEECH.search(m.group(1))]


def text_fields(obj: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in SKIP_KEYS:
                continue
            yield from text_fields(value, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from text_fields(item, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def paraphrase_problems(record: dict[str, Any]) -> list[str]:
    return [f"{path}: {p}" for path, text in text_fields(record)
            for p in quote_problems(text) + dialogue_problems(text)]
