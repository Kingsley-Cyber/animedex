"""AniList catalog client (v1.6; backfill). Metadata only: ids, titles, format, dates, episodes,
popularity, country, studios, relations. Descriptions and reviews are never requested or stored.

AniList's public GraphQL API needs a User-Agent and allows about 90 requests a minute (less when
degraded), so calls are paced and a 429 waits for Retry-After. Terms: free for non-commercial use
(v1.6 decision 2: switch to Wikidata if ideas will be sold).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

ENDPOINT = "https://graphql.anilist.co"
USER_AGENT = "animedex/0.1 (personal research tool)"
_MEDIA = """id idMal title { romaji english native } synonyms format episodes status countryOfOrigin popularity
averageScore startDate { year month day } endDate { year month day } studios(isMain: true) { nodes { name } }
relations { edges { relationType node { id type format episodes title { romaji english }
startDate { year month } endDate { year month } } } }"""


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class Relation:
    kind: str
    id: int
    type: str
    format: str | None
    title: str
    start_year: int | None
    end_year: int | None
    episodes: int | None


@dataclass(frozen=True)
class Media:
    id: int
    title: str
    romaji: str
    english: str | None
    synonyms: tuple[str, ...]
    format: str | None
    episodes: int | None
    status: str | None
    country: str | None
    popularity: int
    score: int | None
    start: tuple[int | None, int | None]
    end: tuple[int | None, int | None]
    studios: tuple[str, ...]
    relations: tuple[Relation, ...] = field(default_factory=tuple)

    @property
    def ref(self) -> str:
        return f"anilist:{self.id}"

    @property
    def names(self) -> list[str]:
        return [n for n in (self.english, self.romaji, *self.synonyms) if n]


def _media(d: dict[str, Any]) -> Media:
    t = d.get("title") or {}
    rels = []
    for e in (d.get("relations") or {}).get("edges") or []:
        n = e.get("node") or {}
        nt = n.get("title") or {}
        rels.append(Relation(kind=e.get("relationType") or "", id=int(n.get("id") or 0), type=n.get("type") or "",
                             format=n.get("format"), title=nt.get("english") or nt.get("romaji") or "",
                             start_year=(n.get("startDate") or {}).get("year"),
                             end_year=(n.get("endDate") or {}).get("year"), episodes=n.get("episodes")))
    sd, ed = d.get("startDate") or {}, d.get("endDate") or {}
    return Media(id=int(d["id"]), title=t.get("english") or t.get("romaji") or "", romaji=t.get("romaji") or "",
                 english=t.get("english"), synonyms=tuple(d.get("synonyms") or ()), format=d.get("format"),
                 episodes=d.get("episodes"), status=d.get("status"), country=d.get("countryOfOrigin"),
                 popularity=int(d.get("popularity") or 0), score=d.get("averageScore"),
                 start=(sd.get("year"), sd.get("month")), end=(ed.get("year"), ed.get("month")),
                 studios=tuple(n["name"] for n in ((d.get("studios") or {}).get("nodes") or [])), relations=tuple(rels))


class AniList:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, min_interval_s: float = 0.8,
                 sleep: Callable[[float], None] = time.sleep):
        self._http = httpx.Client(timeout=30.0, transport=transport,
                                  headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                                           "Accept": "application/json"})
        self.min_interval_s, self._sleep, self._last = min_interval_s, sleep, 0.0

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        for _ in range(4):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            resp = self._http.post(ENDPOINT, json={"query": query, "variables": variables})
            if resp.status_code == 429:
                self._sleep(float(resp.headers.get("Retry-After", "30")))
                continue
            if resp.status_code >= 400:
                raise CatalogError(f"AniList HTTP {resp.status_code}")
            body = resp.json()
            if body.get("errors"):
                raise CatalogError(f"AniList: {body['errors'][0].get('message', 'error')}")
            return body["data"]
        raise CatalogError("AniList: still rate-limited after retries")

    def search(self, text: str, per_page: int = 10) -> list[Media]:
        q = ("query ($s: String, $n: Int) { Page(perPage: $n) { media(search: $s, type: ANIME, "
             f"sort: [SEARCH_MATCH, POPULARITY_DESC]) {{ {_MEDIA} }} }} }}")
        return [_media(m) for m in self._post(q, {"s": text, "n": per_page})["Page"]["media"]]

    def media(self, media_id: int) -> Media:
        q = f"query ($id: Int) {{ Media(id: $id, type: ANIME) {{ {_MEDIA} }} }}"
        return _media(self._post(q, {"id": media_id})["Media"])

    def popular(self, page: int, *, country: str, per_page: int = 50, since: int = 1995,
                formats: tuple[str, ...] = ("TV", "TV_SHORT", "ONA", "MOVIE")) -> list[Media]:
        q = ("query ($p: Int, $n: Int, $c: CountryCode, $d: FuzzyDateInt, $f: [MediaFormat]) { Page(page: $p, "
             "perPage: $n) { media(type: ANIME, sort: POPULARITY_DESC, countryOfOrigin: $c, startDate_greater: $d, "
             f"format_in: $f) {{ {_MEDIA} }} }} }}")
        data = self._post(q, {"p": page, "n": per_page, "c": country, "d": since * 10000, "f": list(formats)})
        return [_media(m) for m in data["Page"]["media"]]
