"""Search backends (config `search.backend`) + page fetch + per-title search budget (05 VERIFY).

Fetched pages come back as TransientText: they are passed to the model once and never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import httpx

from animedex.config import Settings, is_placeholder
from animedex.search.base import MockSearch, SearchBackend, SearchCapReached, SearchResult
from animedex.store.runlog import TransientText

USER_AGENT = "animedex/0.1 (research; +https://github.com/Kingsley-Cyber/animedex)"
MAX_PAGE_CHARS = 6000


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str, limit: int = MAX_PAGE_CHARS) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text[:limit]


class _HttpBackend:
    name = "http"

    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout_s: float = 30.0):
        self._client = httpx.Client(timeout=timeout_s, follow_redirects=True, transport=transport,
                                    headers={"User-Agent": USER_AGENT})

    def fetch(self, url: str) -> TransientText:
        resp = self._client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        text = html_to_text(resp.text) if "html" in ctype or resp.text.lstrip().startswith("<") else resp.text[:MAX_PAGE_CHARS]
        return TransientText(str(resp.url), text)


class BraveSearch(_HttpBackend):
    name = "brave"

    def __init__(self, api_key: str, count: int = 5, **kw: Any):
        super().__init__(**kw)
        self.api_key, self.count = api_key, count

    def search(self, query: str) -> list[SearchResult]:
        resp = self._client.get("https://api.search.brave.com/res/v1/web/search",
                                params={"q": query, "count": self.count},
                                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
        resp.raise_for_status()
        rows = (resp.json().get("web") or {}).get("results") or []
        return [SearchResult(r["url"], r.get("title", ""), r.get("description", "")) for r in rows if r.get("url")]


class TavilySearch(_HttpBackend):
    name = "tavily"

    def __init__(self, api_key: str, count: int = 5, **kw: Any):
        super().__init__(**kw)
        self.api_key, self.count = api_key, count

    def search(self, query: str) -> list[SearchResult]:
        resp = self._client.post("https://api.tavily.com/search", json={"query": query, "max_results": self.count},
                                 headers={"Authorization": f"Bearer {self.api_key}"})
        resp.raise_for_status()
        rows = resp.json().get("results") or []
        return [SearchResult(r["url"], r.get("title", ""), r.get("content", "")) for r in rows if r.get("url")]


class SearxngSearch(_HttpBackend):
    name = "searxng"

    def __init__(self, base_url: str, count: int = 5, **kw: Any):
        super().__init__(**kw)
        self.base_url, self.count = base_url.rstrip("/"), count

    def search(self, query: str) -> list[SearchResult]:
        resp = self._client.get(f"{self.base_url}/search", params={"q": query, "format": "json"})
        resp.raise_for_status()
        rows = (resp.json().get("results") or [])[: self.count]
        return [SearchResult(r["url"], r.get("title", ""), r.get("content", "")) for r in rows if r.get("url")]


class SearchConfigError(RuntimeError):
    pass


def build_search(settings: Settings, env: dict[str, str], *, transport: httpx.BaseTransport | None = None
                 ) -> SearchBackend | None:
    """None means `native`: VERIFY's model searches with its own CLI web tools (G1a 2026-09-27)."""
    backend = str(settings.search.get("backend", ""))
    if is_placeholder(backend) or not backend:
        raise SearchConfigError("search.backend is not set (G1a)")
    if backend == "native":
        return None
    key = env.get(str(settings.search.get("api_key_env", "SEARCH_API_KEY")), "")
    if backend == "mock":
        return MockSearch()
    if backend in ("brave", "tavily"):
        if not key:
            raise SearchConfigError(f"search backend {backend} needs SEARCH_API_KEY in .env")
        cls = BraveSearch if backend == "brave" else TavilySearch
        return cls(key, transport=transport)
    if backend == "searxng":
        base = settings.search.get("base_url")
        if not base:
            raise SearchConfigError("search.base_url is required for searxng")
        return SearxngSearch(str(base), transport=transport)
    raise SearchConfigError(f"unknown search backend {backend!r} (native | brave | tavily | searxng)")


@dataclass
class SearchBudget:
    """VERIFY caps per title: `max_searches` for fields and locators, plus `outcome_extra` for outcomes."""

    max_searches: int
    outcome_extra: int
    used: int = 0
    used_outcome: int = 0
    log: list[str] = field(default_factory=list)

    def take(self, query: str, outcome: bool = False) -> None:
        if outcome and self.used_outcome < self.outcome_extra:
            self.used_outcome += 1
        elif self.used < self.max_searches:
            self.used += 1
        else:
            raise SearchCapReached(f"search cap reached before {query!r}")
        self.log.append(query)
