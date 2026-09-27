"""Study notes: the one store (notes/<slug>.json, private; mirrored to the data repo, never the public one).

The slug, scope and medium come from the AniList resolver used read-only; the outcome comes from the catalog
numbers through the existing label rule (`resolve.likely_label`), never from a model call; a print title also
carries its adaptation status. The study fields come from the ingest prompt, checked here so the client can
spend its one repair: the order of the notes, the enums (`other: ...` allowed), exactly three functions,
tools and elements, patterns with no names or medium words, two sources (Wikipedia plus one wiki, never
myanimelist.net), paraphrase only. Word counts are the prompt's guidance, not checks (2026-09-27 audit).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animedex.catalog.resolve import Resolved, likely_label
from animedex.content_guards import paraphrase_problems
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.textutil import blocked_source, name_leaks, norm_url

NOTE_VERSION = "1.0.0"
PRINT_MEDIA = ("manga", "manhwa", "webtoon", "light_novel")
ENUMS = ("gate", "cost_of_power", "progression", "visible_counter", "fight_medium", "story_engine")
ENGINE = ("goal", "constraint", "strategy", "cost", "dilemma")
MEDIUM_WORDS = re.compile(r"\b(anime|manga|manhwa|manhua|donghua|webtoon|episode|season|series|show|film|movie|cour|"
                          r"arc|studio|viewers?|audience)\b", re.I)
TEXT = {"type": "string"}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def _arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


# ---------------------------------------------------------------- schema and checks
def note_item(show: dict[str, Any]) -> dict[str, Any]:
    return _obj({"show": show, "premise": TEXT, "engine": _obj({k: TEXT for k in ENGINE}), **{k: TEXT for k in ENUMS},
                 "mc_edge": TEXT,
                 "power_kit": _obj({"medium": TEXT, "functions": _arr(TEXT), "tools": _arr(TEXT), "limits": TEXT}),
                 "villain_type": TEXT, "setting": TEXT,
                 "elements": _arr(_obj({"element": TEXT, "pattern": TEXT})), "sources": _arr(TEXT)})


def note_schema(shows: list[str]) -> dict[str, Any]:
    """One note per listed show; `show` is the exact title string the call was given."""
    return _obj({"notes": _arr(note_item({"type": "string", "enum": list(shows)}))})


def enum_ok(vocab: Vocab, key: str, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return value in vocab.enum(key) or (value.startswith("other:") and len(value) > 6)


def _given(problems: list[str], where: str, text: Any) -> None:
    if not str(text or "").strip():
        problems.append(f"{where}: give it")


def note_problems(out: dict[str, Any], shows: list[str], vocab: Vocab, titles: set[str], *,
                  concept: bool = False) -> list[str]:
    """Everything the call must get right; the client's one repair reads these lines. `concept`: the author's
    own idea (diagnose) has no sources."""
    problems: list[str] = []
    notes = out.get("notes") or []
    if [n.get("show") for n in notes] != list(shows):
        problems.append(f"one note per listed show, in the order given: {shows}")
    for i, n in enumerate(notes):
        pre = f"notes[{i}]"
        _given(problems, f"{pre}.premise", n.get("premise"))
        for k in ENGINE:
            _given(problems, f"{pre}.engine.{k}", (n.get("engine") or {}).get(k))
        for k in ENUMS:
            if not enum_ok(vocab, k, n.get(k)):
                problems.append(f"{pre}.{k}: one of {list(vocab.enum(k))} or 'other: <words>'")
        kit = n.get("power_kit") or {}
        for key in ("functions", "tools"):
            if len([x for x in (kit.get(key) or []) if isinstance(x, str) and x.strip()]) != 3:
                problems.append(f"{pre}.power_kit.{key}: exactly 3 items")
        elements = n.get("elements") or []
        if len(elements) != 3:
            problems.append(f"{pre}.elements: exactly 3 elements")
        for j, el in enumerate(elements):
            pattern = str(el.get("pattern") or "")
            _given(problems, f"{pre}.elements[{j}].pattern", pattern)
            leaks = name_leaks(pattern, titles, set())
            if leaks:
                problems.append(f"{pre}.elements[{j}].pattern: strip the names ({', '.join(leaks[:3])})")
            if MEDIUM_WORDS.search(pattern):
                problems.append(f"{pre}.elements[{j}].pattern: no medium words (anime, episode, season, show...)")
        if not concept:
            sources = [str(u) for u in (n.get("sources") or [])]
            if len(sources) != 2 or not all(u.startswith("http") for u in sources):
                problems.append(f"{pre}.sources: exactly 2 URLs (the Wikipedia page and one fan wiki page)")
            else:
                if not any("wikipedia.org" in u for u in sources):
                    problems.append(f"{pre}.sources: one of the two must be the Wikipedia page")
                if any(blocked_source(u) for u in sources):
                    problems.append(f"{pre}.sources: myanimelist.net pages are never a source")
        problems += [f"{pre}.{p}" for p in paraphrase_problems(
            {k: v for k, v in n.items() if k in ("premise", "engine", "mc_edge", "power_kit", "elements")})]
    return problems


# ---------------------------------------------------------------- the note record
def catalog_outcome(res: Resolved, numbers: dict[str, Any] | None) -> dict[str, Any]:
    """The existing label rule on the catalog score; no model call."""
    score = (numbers or {}).get("score")
    label = likely_label(score) if score is not None else res.likely
    out: dict[str, Any] = {"label": label, "anilist_score": score,
                           "popularity": (numbers or {}).get("popularity") or res.popularity or None,
                           "source": "anilist", "rule": "likely_label: hit >= 78, mixed 65-76, flop <= 62, else null"}
    if res.entry.get("medium") in PRINT_MEDIA:
        out["adaptation"] = res.adaptation
    return out


def study_fields(raw: dict[str, Any]) -> dict[str, Any]:
    kit = raw.get("power_kit") or {}
    return {"premise": raw.get("premise"), "engine": {k: (raw.get("engine") or {}).get(k) for k in ENGINE},
            **{k: raw.get(k) for k in ENUMS}, "mc_edge": raw.get("mc_edge"),
            "power_kit": {"medium": kit.get("medium"), "functions": list(kit.get("functions") or []),
                          "tools": list(kit.get("tools") or []), "limits": kit.get("limits")},
            "villain_type": raw.get("villain_type"), "setting": raw.get("setting"),
            "elements": [{"element": el.get("element"), "pattern": el.get("pattern")} for el in raw.get("elements") or []]}


def make_note(raw: dict[str, Any], res: Resolved, numbers: dict[str, Any] | None, *, run_id: str, model: str | None,
              prompt_version: str, vocab: Vocab, cache_key: str | None, created_at: str | None,
              web_urls: set[str]) -> dict[str, Any]:
    e = res.entry
    fetched = {norm_url(w) for w in web_urls}
    sources = [{"url": u, "kind": "wikipedia" if "wikipedia.org" in u else "wiki", "retrieved": norm_url(u) in fetched}
               for u in raw.get("sources") or []]
    return {"slug": e["title_id"], "title": e["title"], "year": e.get("year"), "medium": e["medium"],
            "format": e.get("format"), "scope": e.get("scope"), "catalog_ref": e.get("catalog_ref"),
            "outcome": catalog_outcome(res, numbers), **study_fields(raw), "sources": sources,
            "provenance": {"run_id": run_id, "pass": "INGEST", "model": model, "prompt_version": prompt_version,
                           "note_version": NOTE_VERSION, "vocab_version": vocab.version, "cache_key": cache_key,
                           "created_at": created_at or datetime.now(UTC).isoformat()}}


# ---------------------------------------------------------------- storage
def note_path(paths: Paths, slug: str) -> Path:
    return paths.notes / f"{slug}.json"


def write_note(paths: Paths, note: dict[str, Any]) -> Path:
    path = note_path(paths, note["slug"])
    atomic_write_text(path, json.dumps(note, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_notes(paths: Paths) -> dict[str, dict[str, Any]]:
    if not paths.notes.is_dir():
        return {}
    return {f.stem: json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(paths.notes.glob("*.json")) if not f.name.startswith("_")}


def note_titles(notes: dict[str, dict[str, Any]]) -> set[str]:
    return {str(n.get("title") or "").lower() for n in notes.values() if n.get("title")}


# ---------------------------------------------------------------- rendering for prompts
def outcome_word(note: dict[str, Any]) -> str:
    oc = note.get("outcome") or {}
    label = oc.get("label") or "outcome unknown"
    adapt = (oc.get("adaptation") or {}).get("status")
    return f"{label}; adaptation {adapt}" if adapt else str(label)


def index_line(note: dict[str, Any]) -> str:
    return (f"note {note['slug']}: {note.get('title')} ({note.get('year')}, {note.get('medium')}, "
            f"{outcome_word(note)}): {note.get('premise')}")


def note_lines(note: dict[str, Any]) -> list[str]:
    """The compact `key: value` block a prompt shows for one note."""
    e, kit = note.get("engine") or {}, note.get("power_kit") or {}
    lines = [f"=== note {note['slug']}: {note.get('title')} ({note.get('year')}, {note.get('medium')}; "
             f"{outcome_word(note)})",
             f"premise: {note.get('premise')}",
             "engine: " + "; ".join(f"{k} {e.get(k)}" for k in ENGINE),
             "profile: " + ", ".join(f"{k}={note.get(k)}" for k in ENUMS),
             f"mc_edge: {note.get('mc_edge')}",
             f"power_kit: medium {kit.get('medium')}; functions {' / '.join(kit.get('functions') or [])}; "
             f"tools {' / '.join(kit.get('tools') or [])}; limits {kit.get('limits')}",
             f"villain_type: {note.get('villain_type')}; setting: {note.get('setting')}"]
    for i, el in enumerate(note.get("elements") or [], start=1):
        lines.append(f"element {i}: {el.get('element')} | pattern: {el.get('pattern')}")
    return lines


def source_urls(note: dict[str, Any]) -> list[str]:
    return [s.get("url") for s in note.get("sources") or [] if s.get("url")]


def values_lines(vocab: Vocab) -> list[str]:
    return [f"values {k}: " + " | ".join(vocab.enum(k)) for k in ENUMS]
