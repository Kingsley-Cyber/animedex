"""Resolve a plain title line ("Bleach (2004)", "Frieren: Beyond Journey's End") to a corpus entry
with a declared scope (01, 04).

- A version in parentheses is used as given (a 4-digit year picks that year's entry).
- Otherwise the most-watched match (AniList popularity) is chosen, and the other matches are
  listed so Kingsley can correct the choice.
- Scope: the chosen entry plus its direct TV sequels (gaps under 5 years) as seasons 1..n;
  other adaptations, films, OVAs, and later source material are excluded.
- Medium: China-origin entries are donghua; others from AniList are anime. Titles AniList does not
  know fall back to TVmaze (western animation or live action), metadata only.
- Print (v1.9, D-046): a hint in parentheses (manga, manhwa, webtoon, light novel) searches AniList's
  manga side; a line with no screen match anywhere falls back to it too. Print entries scope by volumes
  (else chapters) as `range: [1, n]`, or null while the count is unknown. Korean entries are manhwa, a
  webtoon platform among the links makes a webtoon, NOVEL is a light novel, everything else is manga.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import httpx

from animedex.catalog.anilist import AniList, CatalogError, Media

HINT = re.compile(r"^(?P<name>.+?)\s*\((?P<hint>[^)]+)\)\s*$")
SERIES = ("TV", "TV_SHORT", "ONA")
PRINT_FORMATS = ("MANGA", "NOVEL", "ONE_SHOT")
PRINT_HINTS = {"manga", "manhwa", "webtoon", "light novel", "novel", "print", "comic"}
WEBTOON_SITES = ("webtoon", "naver", "tapas", "lezhin", "tappytoon")   # webtoon-native platforms, not storefronts
TRAILING_YEAR = re.compile(r"\s*\((19|20)\d{2}\)\s*$")


@dataclass
class Resolved:
    line: str
    entry: dict[str, Any]
    how: str
    alternatives: list[str] = field(default_factory=list)
    likely: str | None = None   # hit/mixed/flop from catalog scores: a mix hint, never a label
    popularity: int = 0
    alternative_refs: set[str] = field(default_factory=set)  # other adaptations of the same story
    adaptation: dict[str, Any] | None = None   # v1.9 print entries: the screen adaptation signal


def norm(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def slug(text: str, year: int | None) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", norm(TRAILING_YEAR.sub("", text))).strip("_")[:60].rstrip("_") or "title"
    if year and base.endswith(f"_{year}"):
        base = base[: -len(f"_{year}")]
    return f"{base}_{year}" if year else base


def similarity(query: str, media: Media) -> float:
    q = norm(query)
    return max((difflib.SequenceMatcher(None, q, norm(TRAILING_YEAR.sub("", n))).ratio() for n in media.names),
               default=0.0)


def likely_label(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 78:
        return "hit"
    if score <= 62:
        return "flop"
    if 65 <= score <= 76:
        return "mixed"
    return None


def _chain(cat: AniList, first: Media, limit: int = 8, this_year: int | None = None) -> list[Media]:
    """The entry plus direct TV sequels that have aired (announced seasons are not in scope)."""
    from datetime import UTC, datetime

    this_year = this_year or datetime.now(UTC).year
    chain = [first]
    while len(chain) < limit:
        cur = chain[-1]
        prev_end = cur.end[0] or cur.start[0] or 0
        nxt = next((r for r in cur.relations if r.kind == "SEQUEL" and r.type == "ANIME" and r.format in SERIES
                    and r.start_year and prev_end and r.start_year - prev_end <= 5
                    and r.start_year <= this_year), None)
        if nxt is None or any(m.id == nxt.id for m in chain):
            break
        media = cat.media(nxt.id)
        if media.status in ("NOT_YET_RELEASED", "CANCELLED"):
            break
        chain.append(media)
    return chain


def _entry(cat: AniList, media: Media) -> dict[str, Any]:
    year = media.start[0]
    medium = "donghua" if media.country == "CN" else "anime"
    studio = media.studios[0] if media.studios else "unknown studio"
    others = sorted({f"{r.title} ({r.kind.lower().replace('_', ' ')})" for r in media.relations
                     if r.kind in ("ALTERNATIVE", "SPIN_OFF", "SIDE_STORY") and r.title})[:4]
    if media.format == "MOVIE":
        scope = {"version": f"{studio} film ({year})", "seasons": [], "numbering": None,
                 "exclude": ["other adaptations", *others]}
        fmt = "film"
    else:
        chain = _chain(cat, media)
        eps = sum(m.episodes or 0 for m in chain)
        end = chain[-1].end[0] or "ongoing"
        kind = "donghua series" if medium == "donghua" else "TV anime"
        scope = {"version": f"{studio} {kind} ({eps or '?'} eps, {year}-{end})",
                 "seasons": list(range(1, len(chain) + 1)), "numbering": "broadcast",
                 "exclude": ["films", "OVAs, specials, and recaps", "source material beyond the adaptation", *others]}
        fmt = "serialized"
    title = TRAILING_YEAR.sub("", media.english or media.romaji) or media.romaji
    return {"title_id": slug(title, year), "title": title, "year": year, "medium": medium, "format": fmt,
            "scope": scope, "role_tags": [], "catalog_ref": media.ref}


def print_medium(media: Media) -> str:
    """manga / manhwa / webtoon / light_novel for an AniList manga-side entry. A webtoon is a Korean entry
    on a webtoon-native platform; a Japanese manga licensed to Piccoma or Kakao stays a manga."""
    if media.format == "NOVEL":
        return "light_novel"
    if media.country != "KR":
        return "manga"
    links = " ".join(media.links).lower()
    return "webtoon" if any(site in links for site in WEBTOON_SITES) else "manhwa"


def adaptation_of(media: Media) -> dict[str, Any]:
    """The screen adaptation signal of a print entry, from the catalog's relations only: adapted (an
    ANIME adaptation has aired or is airing), announced (one is listed but not yet released), or none."""
    rels = [r for r in media.relations if r.kind == "ADAPTATION" and r.type == "ANIME"]
    aired = [r for r in rels if r.status in ("RELEASING", "FINISHED")]
    coming = [r for r in rels if r.status == "NOT_YET_RELEASED"]
    pick = (aired or coming or [None])[0]
    status = "adapted" if aired else "announced" if coming else "none"
    return {"status": status, "screen_title": pick.title if pick else None,
            "catalog_ref": f"anilist:{pick.id}" if pick else None,
            "source_ref": f"https://anilist.co/manga/{media.id}"}


def adaptation_for(entry: Any, cat: AniList) -> dict[str, Any] | None:
    """The adaptation signal for a print corpus entry: its catalog entry by `catalog_ref`, else by title.
    None for screen titles, and when the catalog can't be reached (GATHER notes it; nothing is guessed)."""
    from animedex.models.common import PRINT_MEDIA

    if entry.medium not in PRINT_MEDIA:
        return None
    try:
        ref = str(entry.catalog_ref or "")
        if ref.startswith("anilist:"):
            media = cat.media(int(ref.split(":", 1)[1]), "MANGA")
        else:
            found = _resolve_print(cat, entry.title, entry.year)
            if found is None:
                return None
            media = cat.media(int(found.entry["catalog_ref"].split(":", 1)[1]), "MANGA")
        return adaptation_of(media)
    except (CatalogError, ValueError):
        return None


def _print_entry(media: Media) -> dict[str, Any]:
    year = media.start[0]
    medium = print_medium(media)
    units, n = ("volumes", media.volumes) if media.volumes else ("chapters", media.chapters)
    end = media.end[0] or "ongoing"
    label = {"manga": "manga", "manhwa": "manhwa", "webtoon": "webtoon", "light_novel": "light novel"}[medium]
    others = sorted({f"{r.title} ({r.kind.lower().replace('_', ' ')})" for r in media.relations
                     if r.kind in ("ALTERNATIVE", "SPIN_OFF", "SIDE_STORY", "ADAPTATION") and r.title})[:4]
    scope = {"version": f"{label} ({n or '?'} {units}, {year}-{end})", "seasons": [], "numbering": units,
             "range": [1, int(n)] if n else None,
             "exclude": ["screen adaptations", "spin-offs and side stories", "later print beyond the range", *others]}
    title = TRAILING_YEAR.sub("", media.english or media.romaji) or media.romaji
    return {"title_id": slug(title, year), "title": title, "year": year, "medium": medium, "format": "serialized",
            "scope": scope, "role_tags": [], "catalog_ref": media.ref}


def _resolve_print(cat: AniList, name: str, year: int | None, how_note: str = "") -> Resolved | None:
    try:
        found = [r for r in cat.search(name, media_type="MANGA") if r.format in PRINT_FORMATS and r.start[0]]
    except CatalogError:
        found = []
    good = [r for r in found if similarity(name, r) >= 0.6]
    if year:
        good = [r for r in good if r.start[0] == year] or [r for r in found if r.start[0] == year]
    if not good:
        return None
    ordered = sorted(good, key=lambda r: -r.popularity)
    pick = ordered[0]
    how = how_note or ("version given" if year else ("most-read match" if len(good) > 1 else "only match"))
    alternatives = [f"{r.english or r.romaji} ({r.start[0]}, {r.format})" for r in ordered[1:5]]
    return Resolved(line=name, entry=_print_entry(pick), how=how, alternatives=alternatives,
                    likely=likely_label(pick.score), popularity=pick.popularity, adaptation=adaptation_of(pick))


def resolve(cat: AniList, line: str, *, tvmaze: TvMaze | None = None) -> Resolved | None:
    m = HINT.match(line.strip())
    name, hint = (m["name"].strip(), m["hint"].strip()) if m else (line.strip(), None)
    year = int(hint) if hint and hint.isdigit() and len(hint) == 4 else None
    if hint and norm(hint) in PRINT_HINTS:  # v1.9: the owner asked for the print version
        found_print = _resolve_print(cat, name, None, how_note=f"print version given ({norm(hint)})")
        if found_print is not None:
            found_print.line = line
        return found_print
    try:
        found = [r for r in cat.search(name) if r.format in (*SERIES, "MOVIE") and r.start[0]]
    except CatalogError:
        found = []
    good = [r for r in found if similarity(name, r) >= 0.6]
    if year:
        good = [r for r in good if r.start[0] == year] or [r for r in found if r.start[0] == year]
    elif hint:
        words = set(norm(hint).split())
        good = [r for r in good if words <= set(" ".join(norm(n) for n in r.names).split())] or good
    if not good:
        screen = tvmaze.resolve(line) if tvmaze else None
        if screen is not None:
            return screen
        found_print = _resolve_print(cat, name, year, how_note="no screen version found: the print original")
        if found_print is not None:
            found_print.line = line
        return found_print
    series_first = sorted(good, key=lambda r: (r.format == "MOVIE", -r.popularity))
    pick = series_first[0]
    how = "version given" if hint else ("most-watched match" if len(good) > 1 else "only match")
    alternatives = [f"{r.english or r.romaji} ({r.start[0]}, {r.format})" for r in series_first[1:5]]
    return Resolved(line=line, entry=_entry(cat, pick), how=how, alternatives=alternatives,
                    likely=likely_label(pick.score), popularity=pick.popularity,
                    alternative_refs={f"anilist:{r.id}" for r in pick.relations if r.kind == "ALTERNATIVE"})


class TvMaze:
    """Fallback for non-anime series (metadata only). Films are not covered."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url="https://api.tvmaze.com", timeout=30.0, transport=transport,
                                  headers={"User-Agent": "animedex/0.1 (personal research tool)"})

    def resolve(self, line: str) -> Resolved | None:
        m = HINT.match(line.strip())
        name, hint = (m["name"].strip(), m["hint"].strip()) if m else (line.strip(), None)
        resp = self._http.get("/search/shows", params={"q": name})
        if resp.status_code != 200:
            return None
        shows = [s["show"] for s in resp.json() if s.get("show", {}).get("premiered")]
        if hint and hint.isdigit():
            shows = [s for s in shows if s["premiered"].startswith(hint)] or shows
        if not shows:
            return None
        show = shows[0]
        year = int(show["premiered"][:4])
        seasons = [s for s in self._http.get(f"/shows/{show['id']}/seasons").json() if s.get("premiereDate")]
        medium = "western_animation" if show.get("type") == "Animation" else "live_action"  # adult: set by hand
        channel = (show.get("network") or show.get("webChannel") or {}).get("name", "unknown channel")
        scope = {"version": f"{channel} series ({len(seasons) or 1} season(s), {year}-"
                            f"{(show.get('ended') or 'ongoing')[:4]})",
                 "seasons": list(range(1, (len(seasons) or 1) + 1)), "numbering": "broadcast",
                 "exclude": ["spin-offs", "films", "source material"]}
        entry = {"title_id": slug(show["name"], year), "title": show["name"], "year": year, "medium": medium,
                 "format": "serialized", "scope": scope, "role_tags": [], "catalog_ref": f"tvmaze:{show['id']}"}
        return Resolved(line=line, entry=entry, how="version given" if hint else "best TVmaze match",
                        alternatives=[f"{s['name']} ({s['premiered'][:4]})" for s in shows[1:4]],
                        likely=None, popularity=int(show.get("weight") or 0))
