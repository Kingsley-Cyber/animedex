"""GATHER (v1.7, gather-first P1): documented facts about one title, each with its source URL.

One call per title on the cheapest subscription model with its own web tools (Wikipedia first, then
the show's wiki). It collects facts for the documented lens fields listed in config (`gather.paths`,
kept only where the vocab has the field), character facts (up to 4 roles), and one critic or
reference reception verdict. Reception numbers come from the APIs, not the model: AniList, then
MAL's official API (Jikan as fallback), cached monthly (catalog/reception.py).

Evidence rules, as in VERIFY (owner rules 2026-09-27): a fact counts only when its URL is one the
call itself retrieved and is not a blocked source (myanimelist.net pages); anything else is dropped
and counted, never retried. Facts the model can't place inside the scope are kept, marked
`unplaced`, and never settle a field. Page text is never stored: only paraphrased values and URLs.
Output: `data/candidates/gathered/<title_id>.json`, the input INTERPRET works from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from animedex import SCHEMA_VERSION
from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.content_guards import GuardConfig, dialogue_problems, quote_problems
from animedex.guards import LiveRunRefused
from animedex.models import CorpusEntry
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import blocked_source, norm_url, url_set
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.quarantine import quarantine
from animedex.textutil import word_count

ROLES = ("protagonist", "main_rival", "main_antagonist", "mentor", "deuteragonist")
CHARACTER_FIELDS = ("origin", "abilities", "forms", "turning_point", "allegiance", "ending")
NOTE_WORDS = 25  # character facts and reception verdicts


@dataclass
class GatherTitleResult:
    title_id: str
    kept: int = 0
    unplaced: int = 0
    dropped: list[str] = field(default_factory=list)
    reception: list[str] = field(default_factory=list)  # sources that answered
    notes: list[str] = field(default_factory=list)


@dataclass
class GatherResult:
    titles: list[GatherTitleResult] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    quarantined: list[tuple[str, str]] = field(default_factory=list)
    stopped: str | None = None


def gather_paths(vocab: Vocab, settings: Settings) -> list[str]:
    """The documented lens fields GATHER may fill: config list ∩ the vocab's lens."""
    have = {f.path for f in vocab.lens_fields()}
    return [p for p in (settings.model_extra or {}).get("gather", {}).get("paths", []) if p in have]


def web_limits(settings: Settings) -> dict[str, int]:
    cfg = (settings.model_extra or {}).get("gather", {})
    searches, fetches = int(cfg.get("max_searches", 4)), int(cfg.get("max_fetches", 8))
    return {"max_searches": searches, "outcome_extra": 0, "max_fetches": fetches, "max_turns": searches + fetches + 2}


def output_schema(paths_: list[str]) -> dict[str, Any]:
    fact = {"type": "object", "additionalProperties": False,
            "required": ["path", "value", "season", "episode", "source_url", "scope"],
            "properties": {"path": {"type": "string", "enum": paths_ or ["none"]}, "value": {"type": "string"},
                           "season": {"type": ["integer", "null"]}, "episode": {"type": ["integer", "null"]},
                           "source_url": {"type": "string"}, "scope": {"type": "string", "enum": ["in_scope", "unplaced"]}}}
    cfact = {"type": "object", "additionalProperties": False,
             "required": ["field", "value", "season", "episode", "source_url", "scope"],
             "properties": {"field": {"type": "string", "enum": list(CHARACTER_FIELDS)}, "value": {"type": "string"},
                            "season": {"type": ["integer", "null"]}, "episode": {"type": ["integer", "null"]},
                            "source_url": {"type": "string"},
                            "scope": {"type": "string", "enum": ["in_scope", "unplaced"]}}}
    character = {"type": "object", "additionalProperties": False, "required": ["role", "name", "facts"],
                 "properties": {"role": {"type": "string", "enum": list(ROLES)}, "name": {"type": "string"},
                                "facts": {"type": "array", "items": cfact}}}
    verdict = {"type": "object", "additionalProperties": False, "required": ["kind", "verdict", "source_url"],
               "properties": {"kind": {"type": "string", "enum": ["critic_review", "reception_section"]},
                              "verdict": {"type": "string"}, "source_url": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["facts", "characters", "reception"],
            "properties": {"facts": {"type": "array", "items": fact},
                           "characters": {"type": "array", "items": character, "maxItems": 4},
                           "reception": {"type": "array", "items": verdict, "maxItems": 2}}}


def render_user(entry: CorpusEntry, paths_: list[str], vocab: Vocab, limits: dict[str, int]) -> str:
    """Compact key: value lines (v1.7): the title, its scope, the fields and their word limits."""
    scope = entry.scope
    lines = [f"title: {entry.title} ({entry.year})", f"medium: {entry.medium}", f"format: {entry.format}",
             f"scope_version: {scope.version}", f"scope_seasons: {scope.seasons or 'n/a'}",
             f"scope_numbering: {scope.numbering or 'n/a'}", f"out_of_scope: {'; '.join(scope.exclude) or 'nothing listed'}",
             f"limits: at most {limits['max_searches']} web searches and {limits['max_fetches']} page fetches"]
    for p in paths_:
        f = vocab.lens_field(p)
        kind = f"one of: {', '.join(vocab.enum(f.vocab or p))}" if f.kind == "enum" else f"max {f.max_words} words"
        lines.append(f"field: {p} ({kind})")
    lines.append(f"character_fields: {', '.join(CHARACTER_FIELDS)} (max {NOTE_WORDS} words each)")
    return "\n".join(lines)


def _clean(value: str, cap: int, guards: GuardConfig) -> str | None:
    """Why a value can't be kept, or None."""
    if not value.strip():
        return "empty"
    if word_count(value) > cap:
        return f"over {cap} words"
    problems = quote_problems(value, guards.min_quote_words) + dialogue_problems(value)
    return problems[0] if problems else None


def admit(out: dict[str, Any], urls: set[str], vocab: Vocab, allowed: list[str], guards: GuardConfig
          ) -> tuple[dict[str, Any], list[str]]:
    """Keep what the evidence supports; drop the rest with a reason (owner rule: no retries)."""
    dropped: list[str] = []
    ok_urls = url_set(urls)

    def cited(url: Any, what: str) -> bool:
        if blocked_source(url):
            dropped.append(f"{what}: myanimelist.net pages are not an allowed source")
            return False
        if norm_url(url) not in ok_urls:
            dropped.append(f"{what}: cites a page this call never retrieved")
            return False
        return True

    facts, n = [], 0
    for f in out.get("facts") or []:
        what = f"fact {f.get('path')}"
        if f.get("path") not in allowed:
            dropped.append(f"{what}: not a gatherable field")
            continue
        lf = vocab.lens_field(f["path"])
        value = str(f.get("value") or "")
        if lf.kind == "enum" and value not in vocab.enum(lf.vocab or f["path"]) and not value.lower().startswith("other:"):
            dropped.append(f"{what}: {value!r} is not an allowed value")
            continue
        cap = lf.max_words if lf.kind == "phrase" else NOTE_WORDS  # a list/group/multi fact is one paraphrased line
        if lf.kind != "enum" and (why := _clean(value, cap or 15, guards)):
            dropped.append(f"{what}: {why}")
            continue
        if not cited(f.get("source_url"), what):
            continue
        n += 1
        facts.append({"id": f"F{n:02d}", **{k: f.get(k) for k in ("path", "value", "season", "episode", "source_url", "scope")}})
    characters, c = [], 0
    for ch in (out.get("characters") or [])[:4]:
        kept = []
        for cf in ch.get("facts") or []:
            what = f"character {ch.get('role')} {cf.get('field')}"
            if (why := _clean(str(cf.get("value") or ""), NOTE_WORDS, guards)):
                dropped.append(f"{what}: {why}")
                continue
            if not cited(cf.get("source_url"), what):
                continue
            c += 1
            kept.append({"id": f"C{c:02d}", **{k: cf.get(k) for k in ("field", "value", "season", "episode", "source_url", "scope")}})
        if kept:
            characters.append({"role": ch.get("role"), "name": str(ch.get("name") or "")[:60], "facts": kept})
    reception, r = [], 0
    for v in out.get("reception") or []:
        what = "reception verdict"
        if (why := _clean(str(v.get("verdict") or ""), NOTE_WORDS, guards)) or not cited(v.get("source_url"), what):
            if why:
                dropped.append(f"{what}: {why}")
            continue
        r += 1
        reception.append({"id": f"R{r:02d}", **{k: v.get(k) for k in ("kind", "verdict", "source_url")}})
    return {"facts": facts, "characters": characters, "reception": reception}, dropped


def run_gather(paths: Paths, entries: list[CorpusEntry], client: LLMClient, vocab: Vocab, settings: Settings, *,
               run_id: str, reception: Any = None, guards: GuardConfig | None = None,
               created_at: str | None = None) -> GatherResult:
    """`reception(entry) -> (records, notes)` supplies the API reception numbers (None: skip)."""
    guards = guards or GuardConfig.from_settings(settings)
    prompt = read_prompt(paths.prompts / "gather.md")
    client.prompt_version = str(prompt.meta["version"])
    allowed = gather_paths(vocab, settings)
    schema, limits = output_schema(allowed), web_limits(settings)
    result = GatherResult()
    for entry in entries:
        tid = entry.title_id
        res = GatherTitleResult(tid)
        user = render_user(entry, allowed, vocab, limits)
        ctx = CallContext(pass_="GATHER", record_id=tid, title_id=tid,
                          upstream=upstream_hash([entry.model_dump(mode="json"), {"paths": allowed, "limits": limits}]))
        try:
            completion = client.complete_ex(prompt.body, user, schema, {"web": limits}, ctx=ctx, validate=None)
        except InvalidOutput as exc:
            quarantine(paths.quarantine, "GATHER", "title", tid, exc.raw, exc.errors)
            result.quarantined.append((tid, exc.errors[-1][:300]))
            continue
        except LiveRunRefused as exc:
            result.skipped.append((tid, str(exc)))
            continue
        except (BudgetExceeded, RateLimited, CliAuthError) as exc:  # stop the run; finished titles stay cached
            result.stopped = str(exc)
            break
        except ProviderError as exc:
            result.skipped.append((tid, str(exc)))
            continue
        web = completion.meta.get("web") or {}
        kept, dropped = admit(completion.data, set(web.get("urls") or []), vocab, allowed, guards)
        api: list[dict[str, Any]] = []
        if reception is not None:
            records, notes = reception(entry)
            res.notes += list(notes)
            for i, rec in enumerate(records, start=1):
                api.append({"id": f"A{i:02d}", **rec.to_dict(), "api_url": rec.api_url})
            res.reception = [a["source"] for a in api]
        res.kept = len(kept["facts"]) + sum(len(c["facts"]) for c in kept["characters"]) + len(kept["reception"])
        res.unplaced = sum(1 for f in kept["facts"] if f["scope"] == "unplaced")
        res.dropped = dropped
        if dropped:
            res.notes.append(f"{len(dropped)} item(s) dropped, no retry: " + "; ".join(dropped[:6]))
        record = {"title_id": tid, "run_id": run_id, **kept, "reception_api": api,
                  "searches": list(web.get("queries") or []), "notes": res.notes,
                  "provenance": {"run_id": run_id, "pass": "GATHER", "model": completion.provenance_model,
                                 "prompt_version": client.prompt_version, "schema_version": SCHEMA_VERSION,
                                 "vocab_version": vocab.version, "cache_key": completion.cache_key,
                                 "created_at": created_at or datetime.now(UTC).isoformat()}}
        atomic_write_text(paths.candidates / "gathered" / f"{tid}.json", json.dumps(record, indent=2) + "\n")
        result.titles.append(res)
    return result


def load_gathered(paths: Paths, title_id: str) -> dict[str, Any] | None:
    f = paths.candidates / "gathered" / f"{title_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
