"""P3 partner selection (05), deterministic over canonical P1 profiles; `corpus/titles.yaml`
`partners:` overrides win.
- nearest_neighbor: highest structural overlap (Jaccard over enum values), same medium.
- flop: a mixed/flop title sharing at least one active module.
- cross_medium: for anime titles, the nearest non-anime title. Required for anime (AC-15).
Ties break by title_id, so the choice never depends on file order.
"""

from __future__ import annotations

from typing import Any

from animedex.models import CorpusEntry
from animedex.models.common import PRINT_MEDIA
from animedex.ontology import Vocab


def enum_items(record: dict[str, Any], vocab: Vocab) -> set[str]:
    active = set(record.get("modules_active") or [])
    out = set()
    for f in vocab.lens_fields():
        if f.kind != "enum" or (f.block != "core" and f.block not in active):
            continue
        value = ((record.get(f.block) or {}).get(f.name) or {}).get("value")
        if value and not str(value).startswith("other"):
            out.add(f"{f.path}={value}")
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def outcome_label(record: dict[str, Any], outcome: dict[str, Any] | None) -> str | None:
    if outcome and outcome.get("label"):
        return str(outcome["label"])
    value = ((record.get("core") or {}).get("outcome") or {}).get("value")
    if value:
        return str(value)
    tags = set(record.get("role_tags") or [])
    return next((t for t in ("flop", "mixed", "hit") if t in tags), None)


def select_partners(record: dict[str, Any], titles: dict[str, dict[str, Any]], outcomes: dict[str, dict[str, Any]],
                    vocab: Vocab, entry: CorpusEntry | None = None) -> list[dict[str, str]]:
    tid = record["title_id"]
    pool = {t: r for t, r in titles.items() if t != tid}
    mine, mods = enum_items(record, vocab), set(record.get("modules_active") or [])
    score = {t: jaccard(mine, enum_items(r, vocab)) for t, r in pool.items()}
    order = sorted(pool, key=lambda t: (-score[t], t))
    overrides = entry.partners if entry and entry.partners else None
    chosen: list[dict[str, str]] = []

    def pick(role: str, candidates: list[str], override: str | None) -> None:
        taken = {c["title_id"] for c in chosen}
        if override and override in pool and override not in taken:
            chosen.append({"role": role, "title_id": override})
            return
        for t in candidates:
            if t not in taken:
                chosen.append({"role": role, "title_id": t})
                return

    pick("nearest_neighbor", [t for t in order if pool[t]["medium"] == record["medium"]],
         overrides.nearest_neighbor if overrides else None)
    pick("flop", [t for t in order if outcome_label(pool[t], outcomes.get(t)) in ("mixed", "flop")
                  and mods & set(pool[t].get("modules_active") or [])],
         overrides.flop if overrides else None)
    if record["medium"] == "anime":  # the screen contrast: Western or live action, never print (v1.9)
        pick("cross_medium", [t for t in order if pool[t]["medium"] not in ("anime", *PRINT_MEDIA)],
             overrides.cross_medium if overrides else None)
    elif record["medium"] in PRINT_MEDIA:  # a print title's contrast is any screen title
        pick("cross_medium", [t for t in order if pool[t]["medium"] not in PRINT_MEDIA],
             overrides.cross_medium if overrides else None)
    return chosen
