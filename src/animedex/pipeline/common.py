"""Shared plumbing for the analysis passes (P2, P3, CHECK, P4).

Each pass reads canonical inputs, makes one model call per title through LLMClient (one repair,
then quarantine), and writes candidates that CANONICALIZE later validates and stores. A usage
limit, an expired login, or a budget cap stops the whole run cleanly; finished titles stay cached.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from animedex import SCHEMA_VERSION
from animedex.budget import BudgetExceeded
from animedex.guards import LiveRunRefused
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, Completion, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.store.quarantine import quarantine


@dataclass
class StageResult:
    done: list[str] = field(default_factory=list)
    quarantined: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    flags: list[tuple[str, str]] = field(default_factory=list)
    stopped: str | None = None
    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def provenance(pass_: str, run_id: str, completion: Completion | None, prompt_version: str | None, vocab: Vocab,
               created_at: str | None = None) -> dict[str, Any]:
    return {"run_id": run_id, "pass": pass_, "model": completion.provenance_model if completion else None,
            "prompt_version": prompt_version, "schema_version": SCHEMA_VERSION, "vocab_version": vocab.version,
            "cache_key": completion.cache_key if completion else None,
            "created_at": created_at or datetime.now(UTC).isoformat()}


# ---------------------------------------------------------------- canonical reads
def canonical_titles(paths: Paths) -> dict[str, dict[str, Any]]:
    return {t["title_id"]: t for t in read_jsonl(paths.canonical / "titles.jsonl")}


def canonical_by_title(paths: Paths, file: str, key: str = "title_id") -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in read_jsonl(paths.canonical / file):
        out.setdefault(str(r[key]).split(".")[0] if key != "title_id" else r[key], []).append(r)
    return out


def title_of_id(record_id: str) -> str:
    return record_id.split(".")[0]


def outcomes(paths: Paths) -> dict[str, dict[str, Any]]:
    return {o["title_id"]: o for o in read_jsonl(paths.canonical / "outcomes.jsonl")}


# ---------------------------------------------------------------- candidates
def candidate_file(paths: Paths, record_type: str, title_id: str):
    return paths.candidates / record_type / f"{title_id}.jsonl"


def read_candidates(paths: Paths, record_type: str, title_id: str) -> list[dict[str, Any]]:
    f = candidate_file(paths, record_type, title_id)
    return read_jsonl(f) if f.is_file() else []


def write_candidates(paths: Paths, record_type: str, title_id: str, records: list[dict[str, Any]]) -> None:
    atomic_write_text(candidate_file(paths, record_type, title_id), dumps_jsonl(records))


# ---------------------------------------------------------------- prompt rendering
def render_profile(record: dict[str, Any], vocab: Vocab, *, verification: bool = True) -> list[str]:
    """Compact, paraphrased profile lines: `path = value [verification]` for non-null fields."""
    sc = record["scope"]
    lines = [f"Title: {record['title']} ({record['year']}); medium {record['medium']}; format {record['format']}",
             f"Scope: {sc['version']}; seasons {sc.get('seasons') or 'n/a'}; numbering {sc.get('numbering') or 'n/a'}; "
             f"out of scope: {'; '.join(sc.get('exclude') or []) or 'nothing listed'}",
             f"Modules active: {', '.join(record.get('modules_active') or []) or 'none'}"]
    for block in ["core", *(record.get("modules_active") or [])]:
        for f in vocab.block_fields(block):
            fv = (record.get(block) or {}).get(f.name) or {}
            if fv.get("value") is None:
                continue
            extra = f"; when: {fv['condition']}" if fv.get("condition") else ""
            tag = f" [{fv.get('verification')}]" if verification else ""
            lines.append(f"- {f.path} = {fv['value']}{extra}{tag}")
    return lines


def render_moments(moments: list[dict[str, Any]]) -> list[str]:
    out = []
    for m in moments:
        loc = m.get("locator") or {}
        where = f"S{loc.get('season')}E{loc.get('episode')}" if loc.get("episode") is not None else "episode unknown"
        out.append(f"- {m['moment_id']}: {m['description']} (why it hit: {m['why_it_hit']}; {where}; "
                   f"{m.get('verification')})")
    return out


def evidence_targets(record: dict[str, Any], moments: list[dict[str, Any]], vocab: Vocab) -> set[str]:
    """What an atom may cite: non-null profile field paths and the title's moment ids."""
    refs = {m["moment_id"] for m in moments}
    for block in ["core", *(record.get("modules_active") or [])]:
        for f in vocab.block_fields(block):
            if ((record.get(block) or {}).get(f.name) or {}).get("value") is not None:
                refs.add(f.path)
    return refs


# ---------------------------------------------------------------- one guarded call
@dataclass
class CallOutcome:
    completion: Completion | None = None
    stop: str | None = None


def guarded_call(result: StageResult, paths: Paths, pass_: str, record_type: str, title_id: str, client: LLMClient,
                 system: str, user: str, schema: dict[str, Any], *, upstream: str,
                 validate: Callable[..., Any] | None = None, params: dict[str, Any] | None = None,
                 record_id: str | None = None) -> CallOutcome:
    """The standard call: guard -> budget -> call -> one repair -> quarantine/failed/stop bookkeeping."""
    ctx = CallContext(pass_=pass_, record_id=record_id or title_id, title_id=title_id, upstream=upstream)
    try:
        return CallOutcome(client.complete_ex(system, user, schema, params, ctx=ctx, validate=validate))
    except InvalidOutput as exc:
        quarantine(paths.quarantine, pass_, record_type, title_id, exc.raw, exc.errors)
        result.quarantined.append((title_id, exc.errors[-1][:300]))
    except LiveRunRefused as exc:
        result.refused.append((title_id, str(exc)))
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        result.stopped = str(exc)
        return CallOutcome(stop=str(exc))
    except ProviderError as exc:
        result.failed.append((title_id, str(exc)))
    return CallOutcome()


def raise_problems(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems[:25]))


def stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
