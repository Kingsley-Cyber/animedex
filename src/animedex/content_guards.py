"""AC-11 heuristics: no quotes, dialogue, or transcripts; no framing/blocking/editing claims in
sensory fields. Terms live in config (content_guards). Applied to model drafts (repair) and at the
canonical boundary (quarantine)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from animedex.textutil import word_count

DEFAULT_FRAMING_TERMS = (
    "close-up", "close up", "wide shot", "long shot", "medium shot", "framing", "framed", "blocking",
    "cut to", "jump cut", "editing", "edit", "camera", "angle", "tracking shot", "dolly", "zoom",
    "montage", "shot composition", "storyboard", "cinematography", "pov shot",
)
_QUOTED = re.compile(r'["“”„«»]([^"“”„«»]{1,400})["“”„«»]|‘([^‘’]{1,400})’')
# a speaker label is a name: one to four Title Case words ("Kira:", "Killua Zoldyck:", "Mr. Smith:"); a
# sentence-case label ("Iyashikei safety: ...") introduces a description, not speech (D-041)
_SPEAKER = re.compile(r"^\s*[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}:\s+(\S.*)$", re.MULTILINE)
# what makes the text after a speaker label read as speech: first/second person, an exclamation or
# question, or an opening quote mark
_SPEECH = re.compile(r"(?i)(?<![\w'])(i|i'm|i'll|i've|i'd|me|my|mine|we|we're|we'll|us|our|ours|you|you're|"
                     r"you'll|your|yours)(?![\w'])|[!?][\"'”’]?\s*$|^[\"'“‘]")

SKIP_KEYS = {
    "title", "source_ref", "run_id", "cache_key", "created_at", "model", "prompt_version", "schema_version",
    "vocab_version", "pass", "timestamp", "url", "cell_key", "grid_cell", "closest_existing", "version",
    "queries",   # web search strings we sent (quote marks are the exact-phrase operator, not copied text; D-041)
}
ID_LISTS = {
    "evidence_refs", "moment_refs", "transfer_ids", "atoms_used", "borrowed_from", "parent_ids",
    "supporting_titles", "source_transfer_ids", "supporting_episodes", "contradicting_episodes",
    "reframing_episodes", "role_tags", "modules_active", "exclude", "bridge",
}


@dataclass(frozen=True)
class GuardConfig:
    framing_terms: tuple[str, ...] = DEFAULT_FRAMING_TERMS
    min_quote_words: int = 3

    @classmethod
    def from_settings(cls, settings: Any | None) -> GuardConfig:
        cfg = (getattr(settings, "model_extra", None) or {}).get("content_guards", {}) if settings else {}
        terms = tuple(cfg.get("framing_terms") or DEFAULT_FRAMING_TERMS)
        return cls(terms, int(cfg.get("min_quote_words", 3)))


def quote_problems(text: str, min_words: int = 3) -> list[str]:
    out = []
    for m in _QUOTED.finditer(text):
        inner = m.group(1) or m.group(2) or ""
        if word_count(inner) >= min_words:
            out.append(f"looks like a quotation: {m.group(0)[:60]!r}")
    return out


def dialogue_problems(text: str) -> list[str]:
    """A speaker label followed by speech, or a script (two or more speaker-label lines). A label
    followed by a description ("Gridlock: an ability shaped by the user's circuit type") is a phrase
    style, not dialogue."""
    lines = list(_SPEAKER.finditer(text))
    return [f"looks like a dialogue line: {m.group(0).strip()[:60]!r}" for m in lines
            if len(lines) >= 2 or _SPEECH.search(m.group(1))]


def framing_problems(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [f"framing/editing claim ({t!r}) in a sensory field" for t in terms
            if re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", lowered)]


def text_fields(obj: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in SKIP_KEYS or key in ID_LISTS or key.endswith("_id") or key == "provenance":
                continue
            yield from text_fields(value, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from text_fields(item, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def record_problems(record: dict[str, Any], cfg: GuardConfig) -> list[str]:
    problems = []
    for path, text in text_fields(record):
        found = quote_problems(text, cfg.min_quote_words) + dialogue_problems(text)
        if path.startswith("sensory."):
            found += framing_problems(text, cfg.framing_terms)
        problems.extend(f"{path}: {p}" for p in found)
    return problems
