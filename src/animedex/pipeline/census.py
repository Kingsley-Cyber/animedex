"""CENSUS (v1.6): a wide, shallow count of which power-system combinations already exist.

- The title list comes from a real catalog (AniList: popular franchise roots, anime + donghua; or
  resolved queue lines), never from model recall.
- About 10 titles per call. Values are recall (`trust: recall`) and are only counted: they decide
  whether an empty grid cell is trustworthy and gate the borrow_system operator. They never become
  atoms, evidence, or ideation input (contract test).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from animedex.catalog.anilist import AniList, Media
from animedex.config import Settings
from animedex.ideate.context import PROFILE_PATHS
from animedex.models.ideation import BORROWED_SYSTEMS, CensusEntry
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import (
    StageResult,
    guarded_call,
    provenance,
    raise_problems,
    write_candidates,
)
from animedex.prompts import read_prompt
from animedex.providers.client import LLMClient
from animedex.store.canonical import CanonicalStore
from animedex.textutil import sha256_text, stable_json


@dataclass(frozen=True)
class CensusItem:
    census_id: str
    title: str
    year: int | None
    medium: str
    format: str
    popularity: int | None = None


def item_from_media(m: Media) -> CensusItem:
    return CensusItem(census_id=m.ref, title=m.english or m.romaji, year=m.start[0],
                      medium="donghua" if m.country == "CN" else "anime", format=m.format or "TV",
                      popularity=m.popularity)


def top_roots(cat: AniList, *, size: int, donghua: int, since: int = 1995) -> list[CensusItem]:
    """The most popular franchise roots (no prequel), anime first, then donghua."""
    out: list[CensusItem] = []
    for country, want in (("JP", size - donghua), ("CN", donghua)):
        got, page = 0, 1
        while got < want and page <= 40:
            batch = cat.popular(page, country=country, since=since)
            if not batch:
                break
            for m in batch:
                if got >= want:
                    break
                if any(r.kind == "PREQUEL" for r in m.relations) or not m.start[0]:
                    continue
                out.append(item_from_media(m))
                got += 1
            page += 1
    return out


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def output_schema(vocab: Vocab, ids: list[str]) -> dict[str, Any]:
    fields = {k: {"type": ["string", "null"], "enum": [*[v for v in vocab.enum(path) if v != "other"], None]}
              for k, path in PROFILE_PATHS.items()}
    item = _obj({"census_id": {"type": "string", "enum": ids}, "has_power_system": {"type": ["boolean", "null"]},
                 **fields, "borrowed_system": {"type": ["string", "null"], "enum": [*BORROWED_SYSTEMS, None]}})
    return _obj({"titles": {"type": "array", "items": item}})


def run_census(paths: Paths, items: list[CensusItem], client: LLMClient, vocab: Vocab, settings: Settings, *,
               run_id: str, created_at: str | None = None) -> StageResult:
    prompt = read_prompt(paths.prompts / "census.md")
    client.prompt_version = prompt.version
    done = {c["census_id"] for c in CanonicalStore(paths).read("census")}
    todo = [i for i in dict((i.census_id, i) for i in items).values() if i.census_id not in done]
    size = int((settings.model_extra or {}).get("census", {}).get("batch_size", 10))
    result = StageResult()
    result.bump("already_counted", len(items) - len(todo))
    for start in range(0, len(todo), size):
        batch = todo[start:start + size]
        ids = [b.census_id for b in batch]
        batch_id = f"{run_id}.b{start // size:03d}"
        user = "TITLES\n" + "\n".join(f"- {b.census_id}: {b.title} ({b.year}, {b.format}, {b.medium})" for b in batch)

        def check(out: dict[str, Any], _ids: list[str] = ids) -> None:
            got = sorted(t.get("census_id") for t in out.get("titles") or [])
            raise_problems([] if got == sorted(_ids) else [f"answer every title exactly once: {_ids}"])

        call = guarded_call(result, paths, "CENSUS", "census", batch_id, client, prompt.body, user,
                            output_schema(vocab, ids), upstream=sha256_text(stable_json(ids)), validate=check,
                            record_id=batch_id, about_title=False)
        if call.stop:
            break
        if call.completion is None:
            continue
        prov = provenance("CENSUS", run_id, call.completion, prompt.version, vocab, created_at)
        by_id = {b.census_id: b for b in batch}
        records = []
        for t in call.completion.data["titles"]:
            b = by_id[t["census_id"]]
            rec = {"census_id": b.census_id, "title": b.title, "year": b.year, "medium": b.medium, "format": b.format,
                   "popularity": b.popularity, "has_power_system": t.get("has_power_system"),
                   **{k: t.get(k) for k in PROFILE_PATHS}, "borrowed_system": t.get("borrowed_system"),
                   "trust": "recall", "batch_id": batch_id, "provenance": prov}
            CensusEntry.model_validate(rec)
            records.append(rec)
        write_candidates(paths, "census", batch_id.replace(".", "_"), records)
        result.done.append(batch_id)
        result.bump("titles", len(records))
        result.bump("with_power_system", sum(1 for r in records if r["has_power_system"]))
    return result
