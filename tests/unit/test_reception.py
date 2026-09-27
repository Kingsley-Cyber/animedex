"""Reception client (controls A1/A2): MAL API v2 first, Jikan as the fallback, AniList's own numbers;
cached for 30 days, paced, only the listed fields stored, the MAL client ID never logged. The census
never imports it. Synthetic titles and a fake client ID; no network."""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from animedex.catalog.anilist import AniList
from animedex.catalog.reception import (
    CACHE_TTL_S,
    FIELDS,
    JIKAN_MIN_INTERVAL_S,
    MAL_MIN_INTERVAL_S,
    Reception,
    ReceptionClient,
    ReceptionError,
    reception_for,
)
from animedex.models import CorpusEntry

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
KEY = "fake-mal-client-id-7f3a9c"  # a fake value; the real one lives in .env only
NOW = 1_790_000_000.0
SYNOPSIS = "A synthetic synopsis that the reception client must never store anywhere at all."


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def mal_body(mal_id: int) -> dict:
    return {"id": mal_id, "title": "Ironvale Circuit", "main_picture": {"medium": "https://img.example/x.jpg"},
            "mean": 8.12, "rank": 240, "popularity": 610, "num_scoring_users": 154321}


def jikan_body(mal_id: int) -> dict:
    return {"data": {"mal_id": mal_id, "url": f"https://myanimelist.net/anime/{mal_id}/Ironvale_Circuit",
                     "title": "Ironvale Circuit", "synopsis": SYNOPSIS, "score": 8.1, "scored_by": 150000,
                     "rank": 250, "popularity": 615, "members": 400000}}


class Api:
    """Fake MAL API v2 and Jikan endpoints; keeps every request it saw."""

    def __init__(self, mal_status: int = 200, jikan_status: int = 200, mal_down: bool = False):
        self.mal_status, self.jikan_status, self.mal_down = mal_status, jikan_status, mal_down
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        mal_id = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
        if request.url.host == "api.myanimelist.net":
            if self.mal_down:
                raise httpx.ConnectError("connection refused", request=request)
            if self.mal_status != 200:
                return httpx.Response(self.mal_status, json={"error": "synthetic failure"})
            return httpx.Response(200, json=mal_body(mal_id))
        if request.url.host == "api.jikan.moe":
            if self.jikan_status != 200:
                return httpx.Response(self.jikan_status, json={"error": "synthetic failure"})
            return httpx.Response(200, json=jikan_body(mal_id))
        raise AssertionError(f"unexpected host {request.url.host}")

    @property
    def hosts(self) -> list[str]:
        return [r.url.host for r in self.seen]


def client(api, tmp_path: Path, *, key: str | None = KEY, clock=lambda: NOW) -> ReceptionClient:
    return ReceptionClient(client_id=key, transport=httpx.MockTransport(api), cache_dir=tmp_path / "reception",
                           sleep=lambda s: None, mal_interval_s=0, jikan_interval_s=0, clock=clock)


def test_mal_api_is_primary_and_carries_the_client_id_only_as_a_header(tmp_path):
    api = Api()
    rec = client(api, tmp_path).mal(101)
    assert api.hosts == ["api.myanimelist.net"]
    [req] = api.seen
    assert req.headers["X-MAL-CLIENT-ID"] == KEY and KEY not in str(req.url)
    assert req.url.path == "/v2/anime/101" and req.url.params["fields"] == "mean,num_scoring_users,rank,popularity"
    assert rec == Reception(source="mal_api", mal_id=101, anilist_id=None, score=8.12, scorers=154321, rank=240,
                            popularity=610, url="https://myanimelist.net/anime/101", fetched_at=iso(NOW))
    assert rec.api_url == "https://api.myanimelist.net/v2/anime/101?fields=mean,num_scoring_users,rank,popularity"


def test_without_a_client_id_jikan_serves_the_mal_numbers(tmp_path):
    api = Api()
    c = client(api, tmp_path, key=None)
    rec = c.mal(101)
    assert api.hosts == ["api.jikan.moe"] and not c.mal_api_enabled
    assert (rec.source, rec.score, rec.scorers, rec.rank, rec.popularity) == ("jikan", 8.1, 150000, 250, 615)
    assert rec.url == "https://myanimelist.net/anime/101"  # cited; the page itself is never fetched
    assert any("MAL_CLIENT_ID is not set" in n for n in c.notes)


@pytest.mark.parametrize("failure", [{"mal_status": 500}, {"mal_status": 401}, {"mal_down": True}])
def test_a_failing_mal_api_falls_back_to_jikan(tmp_path, failure):
    api = Api(**failure)
    c = client(api, tmp_path)
    rec = c.mal(101)
    assert api.hosts == ["api.myanimelist.net", "api.jikan.moe"] and rec.source == "jikan"
    assert any(n.startswith("mal 101: MAL API") and n.endswith("using Jikan") for n in c.notes)


def test_both_sources_failing_is_an_error_not_a_guess(tmp_path):
    with pytest.raises(ReceptionError, match="Jikan HTTP 503"):
        client(Api(mal_status=500, jikan_status=503), tmp_path).mal(101)
    assert not list((tmp_path / "reception").rglob("*.json"))  # nothing cached for a failure


def test_responses_are_cached_for_thirty_days(tmp_path):
    now = [NOW]
    api = Api()
    c = client(api, tmp_path, clock=lambda: now[0])
    first = c.mal(101)
    assert c.mal(101) == first and len(api.seen) == 1 and c.requests == 1
    assert client(api, tmp_path, clock=lambda: now[0]).mal(101) == first and len(api.seen) == 1  # a new process
    now[0] += CACHE_TTL_S - 60
    assert c.mal(101).fetched_at == iso(NOW) and len(api.seen) == 1  # 29 days later: still the cached record
    now[0] += 120
    assert c.mal(101).fetched_at == iso(now[0]) and len(api.seen) == 2  # a month later it refreshes


def test_only_the_listed_fields_are_stored(tmp_path):
    rec = client(Api(), tmp_path, key=None).mal(101)  # Jikan's answer also carries a title, synopsis, members...
    assert FIELDS == ("source", "mal_id", "anilist_id", "score", "scorers", "rank", "popularity", "url", "fetched_at", "kind")
    assert set(rec.to_dict()) == set(FIELDS)
    [cached] = list((tmp_path / "reception").rglob("*.json"))
    assert cached.relative_to(tmp_path / "reception").as_posix() == "jikan/101.json"
    assert set(json.loads(cached.read_text())) == set(FIELDS)
    text = cached.read_text()
    assert SYNOPSIS not in text and "Ironvale" not in text and "members" not in text


def test_the_client_id_never_reaches_records_cache_notes_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    api = Api(mal_down=True)  # the failure path writes notes and log lines
    c = client(api, tmp_path)
    records = [c.mal(101)]
    api.mal_down, api.mal_status = False, 500
    records.append(c.mal(102))
    api.mal_status = 200
    records.append(c.mal(103))
    assert [r.source for r in records] == ["jikan", "jikan", "mal_api"]
    assert c.notes and caplog.text and all(KEY not in n for n in c.notes) and KEY not in caplog.text
    assert KEY not in repr(c) and all(KEY not in json.dumps(r.to_dict()) for r in records)
    for path in (tmp_path / "reception").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(), path


def test_calls_are_paced_and_a_429_waits_for_retry_after():
    assert MAL_MIN_INTERVAL_S >= 1.0 and JIKAN_MIN_INTERVAL_S >= 1.1
    slept: list[float] = []
    jikan_calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        mal_id = int(request.url.path.rsplit("/", 1)[1])
        if request.url.host == "api.jikan.moe":
            jikan_calls[0] += 1
            if jikan_calls[0] == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
            return httpx.Response(200, json=jikan_body(mal_id))
        return httpx.Response(200, json=mal_body(mal_id))

    mal = ReceptionClient(client_id=KEY, transport=httpx.MockTransport(handler), sleep=slept.append)
    mal.mal(1)
    mal.mal(2)  # no cache: the second call waits out MAL's gap
    assert len(slept) == 1 and 0.9 < slept[0] <= MAL_MIN_INTERVAL_S
    slept.clear()
    jikan = ReceptionClient(client_id=None, transport=httpx.MockTransport(handler), sleep=slept.append)
    assert jikan.mal(3).source == "jikan" and jikan.requests == 2
    assert slept[0] == 7.0 and 1.0 < slept[1] <= JIKAN_MIN_INTERVAL_S  # Retry-After, then Jikan's own gap


# ---------------------------------------------------------------- reception_for (corpus entry -> records)
def media(mid: int, title: str, year: int, id_mal: int | None, *, score: int = 81, pop: int = 5000) -> dict:
    return {"id": mid, "idMal": id_mal, "title": {"romaji": title, "english": title, "native": None}, "synonyms": [],
            "format": "TV", "episodes": 12, "status": "FINISHED", "countryOfOrigin": "JP", "popularity": pop,
            "averageScore": score, "startDate": {"year": year, "month": 4, "day": 1},
            "endDate": {"year": year, "month": 6, "day": 1}, "studios": {"nodes": [{"name": "Studio Test"}]},
            "relations": {"edges": []}}


DB = {1: media(1, "Ironvale Circuit", 2021, 101), 2: media(2, "Glass Harbor", 2019, None, score=66, pop=900)}


def anilist(tmp_path: Path, clock=lambda: NOW) -> AniList:
    def handler(request: httpx.Request) -> httpx.Response:
        v = json.loads(request.content)["variables"]
        if "id" in v:
            return httpx.Response(200, json={"data": {"Media": DB[v["id"]]}})
        hits = [m for m in DB.values() if v.get("s", "").lower() in m["title"]["english"].lower()]
        return httpx.Response(200, json={"data": {"Page": {"media": hits}}})

    return AniList(transport=httpx.MockTransport(handler), min_interval_s=0, sleep=lambda s: None,
                   cache_dir=tmp_path / "anilist", clock=clock)


def entry(title: str = "Ironvale Circuit", year: int = 2021, ref: str | None = "anilist:1") -> CorpusEntry:
    slug = title.lower().replace(" ", "_")
    return CorpusEntry.model_validate({"title_id": f"{slug}_{year}", "title": title, "year": year, "medium": "anime",
                                       "format": "serialized", "catalog_ref": ref,
                                       "scope": {"version": "TV", "seasons": [1], "numbering": "broadcast"}})


def test_reception_for_follows_the_catalog_ref_to_the_mal_id(tmp_path):
    api = Api()
    ani, mal = reception_for(entry(), anilist=anilist(tmp_path), client=client(api, tmp_path))
    assert (ani.source, ani.anilist_id, ani.mal_id, ani.score, ani.popularity, ani.scorers, ani.rank) == (
        "anilist", 1, 101, 81.0, 5000, None, None)
    assert ani.url == "https://anilist.co/anime/1" and ani.fetched_at == iso(NOW)
    assert (mal.source, mal.mal_id, mal.anilist_id) == ("mal_api", 101, 1)
    assert [r.url.path for r in api.seen] == ["/v2/anime/101"]
    later = reception_for(entry(), anilist=anilist(tmp_path, clock=lambda: NOW + 3600), client=client(api, tmp_path))
    assert later[0].fetched_at == iso(NOW) and len(api.seen) == 1  # both served from their caches, dated as fetched


def test_reception_for_without_a_catalog_ref_resolves_the_title(tmp_path):
    records = reception_for(entry(ref=None), anilist=anilist(tmp_path), client=client(Api(), tmp_path))
    assert [(r.source, r.anilist_id, r.mal_id) for r in records] == [("anilist", 1, 101), ("mal_api", 1, 101)]


def test_reception_for_degrades_to_what_exists(tmp_path):
    api = Api()
    c = client(api, tmp_path)
    assert reception_for(entry("Harbor Lights", 2015, "tvmaze:77"), anilist=anilist(tmp_path), client=c) == []
    assert reception_for(entry("Nothing Like It", 2012, None), anilist=anilist(tmp_path), client=c) == []
    [only] = reception_for(entry("Glass Harbor", 2019, "anilist:2"), anilist=anilist(tmp_path), client=c)
    assert only.source == "anilist" and only.mal_id is None and not api.seen  # AniList lists no MAL id
    down = client(Api(mal_status=500, jikan_status=500), tmp_path)
    assert [r.source for r in reception_for(entry(), anilist=anilist(tmp_path), client=down)] == ["anilist"]
    notes = " | ".join(c.notes + down.notes)
    for needle in ("catalog tvmaze has no reception source", "not found on AniList", "lists no MAL id",
                   "no MAL numbers (Jikan HTTP 500)"):
        assert needle in notes


def test_the_census_never_fetches_reception():
    """A2: only deep-indexed titles fetch reception; the census module has no path to the client."""
    tree = ast.parse((REPO / "src" / "animedex" / "pipeline" / "census.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {node.module or ""} | {f"{node.module}.{a.name}" for a in node.names}
    assert imported and not any("reception" in name for name in imported)
    probe = "import sys, animedex.pipeline.census; print('animedex.catalog.reception' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=REPO)
    assert out.stdout.strip() == "False"  # not even through another module
