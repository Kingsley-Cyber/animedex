"""Reception data for deep-indexed titles (controls A1/A2, owner-approved 2026-09-27).

Outcome signals come from official APIs, never from scraped pages:
- MAL API v2 is primary: `GET https://api.myanimelist.net/v2/anime/{id}?fields=mean,num_scoring_users,rank,
  popularity` with the header `X-MAL-CLIENT-ID` (`MAL_CLIENT_ID` in .env). MAL stays optional: without a
  client ID, or when MAL fails, Jikan (`GET https://api.jikan.moe/v4/anime/{id}`) serves the same numbers.
- AniList supplies its own score and popularity through the existing AniList client.

A record keeps only its source, the MAL and AniList ids, score, scorers, rank, popularity, a page URL to
cite and when the numbers were fetched. Nothing else from a response is kept (Jikan also returns
synopses: never stored). Scales differ by source: MAL and Jikan give a 1-10 score, `rank` by score and
`popularity` as a rank by members (1 = most popular); AniList gives a 0-100 score and `popularity` as a
count of users, with no scorers or rank.

Every MAL and Jikan response is cached for 30 days under data/cache/reception/ (AniList responses in the
AniList client's own cache). Calls are paced (MAL 1 s, Jikan 1.1 s apart) and a 429 waits for
Retry-After. Only deep-indexed titles fetch reception (the full pipeline); the census never does
(contract test). The client ID travels only in the request header: it is never in a record, the cache,
a note or a log line.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from animedex.catalog.anilist import USER_AGENT, AniList, CatalogError, Media

if TYPE_CHECKING:
    from animedex.models import CorpusEntry
    from animedex.paths import Paths

log = logging.getLogger(__name__)

MAL_API = "https://api.myanimelist.net/v2"
MAL_FIELDS = "mean,num_scoring_users,rank,popularity"
JIKAN_API = "https://api.jikan.moe/v4"
ANILIST_API = "https://graphql.anilist.co"
MAL_PAGE = "https://myanimelist.net/{kind}/{id}"  # cited as the human page; never fetched (owner rule)
ANILIST_PAGE = "https://anilist.co/{kind}/{id}"
KINDS = ("anime", "manga")   # v1.9: MAL and AniList keep separate id spaces per kind
MAL_MIN_INTERVAL_S = 1.0
JIKAN_MIN_INTERVAL_S = 1.1
CACHE_TTL_S = 30 * 24 * 3600  # monthly refresh
RETRY_AFTER_DEFAULT_S = 30.0
RETRY_AFTER_MAX_S = 300.0
SOURCES = ("mal_api", "jikan", "anilist")
LABELS = {"mal_api": "MAL API", "jikan": "Jikan", "anilist": "AniList"}


class ReceptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reception:
    """One source's reception numbers for one title. Only these fields are ever stored."""

    source: str              # mal_api | jikan | anilist
    mal_id: int | None
    anilist_id: int | None
    score: float | None      # MAL/Jikan 1-10 mean; AniList 0-100 average
    scorers: int | None      # MAL/Jikan users who scored it; AniList: none
    rank: int | None         # MAL/Jikan rank by score; AniList: none
    popularity: int | None   # MAL/Jikan rank by members (1 = most popular); AniList: users with it listed
    url: str                 # the page to cite (MAL pages are cited, never fetched)
    fetched_at: str          # UTC ISO 8601: when the numbers left the API
    kind: str = "anime"      # v1.9: anime | manga (print titles use the manga side of both APIs)

    @property
    def api_url(self) -> str:
        """The API request the numbers came from (derived, not stored)."""
        if self.source == "mal_api":
            return f"{MAL_API}/{self.kind}/{self.mal_id}?fields={MAL_FIELDS}"
        if self.source == "jikan":
            return f"{JIKAN_API}/{self.kind}/{self.mal_id}"
        return ANILIST_API

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reception:
        return cls(**{**{k: data.get(k) for k in FIELDS}, "kind": data.get("kind") or "anime"})  # old cache: anime


FIELDS = tuple(f.name for f in dataclass_fields(Reception))


def _kind(kind: str | None) -> str:
    k = (kind or "anime").lower()
    if k not in KINDS:
        raise ValueError(f"reception kind must be anime or manga, not {kind!r}")
    return k


def _key(kind: str, mal_id: Any) -> str:
    """Cache key: anime keeps the bare id (existing cache files); manga gets its own prefix."""
    return f"{int(mal_id or 0)}" if _kind(kind) == "anime" else f"manga-{int(mal_id or 0)}"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _retry_after(resp: httpx.Response) -> float:
    try:
        wait = float(resp.headers.get("Retry-After", RETRY_AFTER_DEFAULT_S))
    except ValueError:
        wait = RETRY_AFTER_DEFAULT_S
    return min(max(wait, 0.0), RETRY_AFTER_MAX_S)


class ReceptionClient:
    """MAL's numbers by MAL id (MAL API v2, else Jikan), cached and paced; AniList's from a `Media`.
    `notes` collects what fell back or failed, in plain words (never the client ID)."""

    def __init__(self, *, client_id: str | None = None, transport: httpx.BaseTransport | None = None,
                 cache_dir: Path | None = None, ttl_s: float = CACHE_TTL_S, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, mal_interval_s: float = MAL_MIN_INTERVAL_S,
                 jikan_interval_s: float = JIKAN_MIN_INTERVAL_S):
        self._client_id = (client_id or "").strip() or None
        self._http = httpx.Client(timeout=30.0, transport=transport,
                                  headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.cache_dir, self.ttl_s, self._clock, self._sleep = cache_dir, ttl_s, clock, sleep
        self._interval = {"mal_api": mal_interval_s, "jikan": jikan_interval_s}
        self._last: dict[str, float] = {}
        self.requests = 0  # network requests made (cache hits are free)
        self.notes: list[str] = []
        self._said_no_key = False

    @classmethod
    def from_env(cls, paths: Paths, env: dict[str, str], **kw: Any) -> ReceptionClient:
        """`MAL_CLIENT_ID` from .env or the environment (`animedex.config.environment`); optional."""
        return cls(client_id=env.get("MAL_CLIENT_ID"), cache_dir=paths.cache / "reception", **kw)

    @property
    def mal_api_enabled(self) -> bool:
        return self._client_id is not None

    def __repr__(self) -> str:
        return f"ReceptionClient(mal_api={'on' if self._client_id else 'off'}, cache_dir={self.cache_dir})"

    def note(self, text: str) -> None:
        self.notes.append(text)
        log.warning("reception: %s", text)

    # ------------------------------------------------------------ cache
    def _cache_file(self, source: str, key: str | int) -> Path | None:
        return None if self.cache_dir is None else self.cache_dir / source / f"{key}.json"

    def _cached(self, source: str, key: str | int) -> Reception | None:
        path = self._cache_file(source, key)
        if path is None or not path.is_file():
            return None
        try:
            rec = Reception.from_dict(json.loads(path.read_text(encoding="utf-8")))
            age = self._clock() - datetime.fromisoformat(rec.fetched_at).timestamp()
        except (ValueError, TypeError, KeyError):
            return None  # unreadable: fetch again
        return rec if age < self.ttl_s else None

    def _store(self, rec: Reception) -> Reception:
        path = self._cache_file(rec.source, _key(rec.kind, rec.mal_id))
        if path is not None:
            from animedex.store.atomic import atomic_write_text

            atomic_write_text(path, json.dumps(rec.to_dict(), sort_keys=True) + "\n")
        return rec

    # ------------------------------------------------------------ network
    def _get(self, source: str, url: str, *, params: dict[str, str] | None = None,
             headers: dict[str, str] | None = None) -> dict[str, Any]:
        label = LABELS[source]
        for _ in range(4):
            last = self._last.get(source)
            if last is not None:
                wait = self._interval[source] - (time.monotonic() - last)
                if wait > 0:
                    self._sleep(wait)
            self._last[source] = time.monotonic()
            self.requests += 1
            try:
                resp = self._http.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:  # the message names the error type only, never the request
                raise ReceptionError(f"{label} unreachable ({type(exc).__name__})") from None
            if resp.status_code == 429:
                self._sleep(_retry_after(resp))
                continue
            if resp.status_code >= 400:
                raise ReceptionError(f"{label} HTTP {resp.status_code}")
            try:
                body = resp.json()
            except ValueError:
                raise ReceptionError(f"{label} answered without JSON") from None
            if not isinstance(body, dict):
                raise ReceptionError(f"{label} answered with an unexpected shape")
            return body
        raise ReceptionError(f"{label} still rate-limited after retries")

    def _fetch_mal(self, mal_id: int, kind: str = "anime") -> Reception:
        kind = _kind(kind)
        body = self._get("mal_api", f"{MAL_API}/{kind}/{mal_id}", params={"fields": MAL_FIELDS},
                         headers={"X-MAL-CLIENT-ID": self._client_id or ""})
        return Reception(source="mal_api", mal_id=mal_id, anilist_id=None, score=_num(body.get("mean")),
                         scorers=_int(body.get("num_scoring_users")), rank=_int(body.get("rank")),
                         popularity=_int(body.get("popularity")), url=MAL_PAGE.format(kind=kind, id=mal_id),
                         fetched_at=_iso(self._clock()), kind=kind)

    def _fetch_jikan(self, mal_id: int, kind: str = "anime") -> Reception:
        kind = _kind(kind)
        data = self._get("jikan", f"{JIKAN_API}/{kind}/{mal_id}").get("data")
        if not isinstance(data, dict):
            raise ReceptionError("Jikan answered without data")
        return Reception(source="jikan", mal_id=mal_id, anilist_id=None, score=_num(data.get("score")),
                         scorers=_int(data.get("scored_by")), rank=_int(data.get("rank")),
                         popularity=_int(data.get("popularity")), url=MAL_PAGE.format(kind=kind, id=mal_id),
                         fetched_at=_iso(self._clock()), kind=kind)

    # ------------------------------------------------------------ lookups
    def mal(self, mal_id: int, kind: str = "anime") -> Reception:
        """MAL's numbers for one MAL id (anime or, v1.9, manga): a cached record (≤ 30 days), else MAL API
        v2 when a client ID is set, else Jikan. Raises ReceptionError when neither answers."""
        kind = _kind(kind)
        for source in ("mal_api", "jikan"):
            if (rec := self._cached(source, _key(kind, mal_id))) is not None:
                return rec
        if self._client_id:
            try:
                return self._store(self._fetch_mal(mal_id, kind))
            except ReceptionError as exc:
                self.note(f"mal {mal_id}: {exc}; using Jikan")
        elif not self._said_no_key:
            self._said_no_key = True
            self.note("MAL_CLIENT_ID is not set; MAL numbers come from Jikan")
        return self._store(self._fetch_jikan(mal_id, kind))

    def from_anilist(self, media: Media, *, fetched_at: float | None = None) -> Reception:
        """AniList's own numbers from a catalog `Media` (fetched_at: when AniList served it)."""
        kind = "manga" if media.kind == "MANGA" else "anime"
        return Reception(source="anilist", mal_id=media.id_mal, anilist_id=media.id,
                         score=_num(media.score), scorers=None, rank=None, popularity=_int(media.popularity),
                         url=ANILIST_PAGE.format(kind=kind, id=media.id),
                         fetched_at=_iso(self._clock() if fetched_at is None else fetched_at), kind=kind)


def _media_for(entry: CorpusEntry, anilist: AniList, client: ReceptionClient) -> Media | None:
    """The entry's AniList media: its `catalog_ref` (anilist:ID) when present, else the resolver."""
    from animedex.catalog.resolve import resolve
    from animedex.models.common import PRINT_MEDIA

    media_type = "MANGA" if entry.medium in PRINT_MEDIA else "ANIME"   # v1.9: the print side of AniList
    ref = entry.catalog_ref or ""
    try:
        if ref.startswith("anilist:"):
            return anilist.media(int(ref.split(":", 1)[1]), media_type)
        if ref:  # another catalog (TVmaze: western animation, live action) has no AniList or MAL entry
            client.note(f"{entry.title_id}: catalog {ref.split(':', 1)[0]} has no reception source")
            return None
        found = resolve(anilist, f"{entry.title} ({'manga' if media_type == 'MANGA' else entry.year})")
        found_ref = str((found.entry if found else {}).get("catalog_ref") or "")
        if not found_ref.startswith("anilist:"):
            client.note(f"{entry.title_id}: not found on AniList; no reception numbers")
            return None
        return anilist.media(int(found_ref.split(":", 1)[1]), media_type)
    except (CatalogError, ValueError) as exc:
        client.note(f"{entry.title_id}: AniList lookup failed ({exc})")
        return None


def reception_for(entry: CorpusEntry, *, anilist: AniList, client: ReceptionClient) -> list[Reception]:
    """Reception records for one deep-indexed corpus entry: AniList's numbers, then MAL's (MAL API v2,
    else Jikan), both carrying both ids. Titles AniList doesn't know get none. Failures become notes
    on `client`, never errors: MAL stays optional in the label rule. Give `anilist` its cache
    (`AniList(cache_dir=paths.cache / "anilist")`) so AniList is asked at most monthly too."""
    media = _media_for(entry, anilist, client)
    if media is None:
        return []
    records = [client.from_anilist(media, fetched_at=anilist.fetched_at)]
    if media.id_mal is None:
        client.note(f"{entry.title_id}: AniList lists no MAL id; AniList numbers only")
        return records
    try:
        records.append(replace(client.mal(media.id_mal, "manga" if media.kind == "MANGA" else "anime"),
                               anilist_id=media.id))
    except ReceptionError as exc:
        client.note(f"{entry.title_id}: no MAL numbers ({exc}); AniList numbers only")
    return records
