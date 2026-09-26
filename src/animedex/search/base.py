"""Web source adapter interface (03): search(query) -> results, fetch(url) -> text.

Fetched text is transient: it is returned as a TransientText so run logs can redact it and it is
never written to disk. The concrete backend is chosen in config (search.backend) at G1a and is
implemented with VERIFY (M2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from animedex.store.runlog import TransientText


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str


class SearchBackend(Protocol):
    name: str

    def search(self, query: str) -> list[SearchResult]: ...

    def fetch(self, url: str) -> TransientText: ...


class SearchCapReached(RuntimeError):
    pass


class MockSearch:
    """Fixture-backed search: `results[query]` and `pages[url]`. Counts calls for cap tests."""

    def __init__(self, results: dict[str, list[SearchResult]] | None = None, pages: dict[str, str] | None = None):
        self.name = "mock"
        self.results = dict(results or {})
        self.pages = dict(pages or {})
        self.search_calls = 0
        self.fetch_calls = 0

    def search(self, query: str) -> list[SearchResult]:
        self.search_calls += 1
        return list(self.results.get(query, []))

    def fetch(self, url: str) -> TransientText:
        self.fetch_calls += 1
        if url not in self.pages:
            raise KeyError(f"mock: no page for {url}")
        return TransientText(url, self.pages[url])
