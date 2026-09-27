"""Small text helpers: word counts, stable JSON, hashes, URL comparison, and the name-leak check."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def word_count(text: str) -> int:
    return len(text.split())


def stable_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 kept."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_url(url: Any) -> str:
    """Compare citations by the page, not its spelling: no fragment, no trailing slash, host lowercased."""
    text = str(url or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, parts.query, ""))


# Owner rule 2026-09-27: never scrape MyAnimeList pages; a page from there is never a source.
BLOCKED_SOURCE_HOSTS = ("myanimelist.net",)


def blocked_source(url: Any) -> bool:
    host = urlsplit(norm_url(url)).hostname or ""
    return any(host == h or host.endswith("." + h) for h in BLOCKED_SOURCE_HOSTS)


_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _base(token: str) -> str:
    """A token without its possessive or hyphenated tail: "Earth's" -> Earth, "League-style" -> League."""
    return token.split("'")[0].split("-")[0]


def name_leaks(text: str, titles: set[str], tokens: set[str]) -> list[str]:
    """Existing titles (lowercased) and name tokens that a text reuses."""
    hits = [t for t in titles if t and t in text.lower()]
    words = set(_WORD.findall(text))
    words |= {_base(w) for w in words}
    hits += sorted(tokens & words)
    return sorted(set(hits))
