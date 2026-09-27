"""Catalog numbers for a resolved show: AniList's score and popularity, read-only."""

from __future__ import annotations

from typing import Any

from animedex.catalog.anilist import AniList
from animedex.catalog.resolve import Resolved
from animedex.light.notes import PRINT_MEDIA


def catalog_numbers(cat: AniList, res: Resolved) -> dict[str, Any] | None:
    ref = str(res.entry.get("catalog_ref") or "")
    if not ref.startswith("anilist:"):
        return None
    media = cat.media(int(ref.split(":")[-1]), "MANGA" if res.entry.get("medium") in PRINT_MEDIA else "ANIME")
    return {"score": media.score, "popularity": media.popularity}
