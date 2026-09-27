"""PROFILE (v1.10 speed pass, D-048): GATHER and INTERPRET in one call, for non-gold titles.

One Opus call with web tools returns the cited facts (with the model's own ids), the reception verdicts,
the profile with its evidence links, the outcome and the cast. The API reception numbers and a print
title's adaptation signal are fetched before the call and shown to it, so the outcome can cite them.
Facts are admitted by GATHER's rules (only pages the call retrieved; MAL never); the profile is assembled
by INTERPRET's shared tail, with the speed pass's verify list (outcome and moment locators). Gold titles
never come here: they keep GATHER, INTERPRET and the full VERIFY.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from animedex import SCHEMA_VERSION
from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.content_guards import GuardConfig
from animedex.guards import LiveRunRefused
from animedex.models import CorpusEntry
from animedex.models.common import PRINT_MEDIA
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.gather import admit, gather_paths, web_limits
from animedex.pipeline.gather import output_schema as gather_schema
from animedex.pipeline.gather import render_user as gather_user
from animedex.pipeline.interpret import (
    InterpretResult,
    characters_schema,
    fact_index,
    finish_title,
    interpret_context,
    schema_with_evidence,
)
from animedex.pipeline.interpret import (
    render_system as interpret_system,
)
from animedex.pipeline.p1 import _is_length, draft_problems, normalize_draft
from animedex.pipeline.p1 import output_schema as p1_schema
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.quarantine import quarantine


def render_prompt(paths: Paths, vocab: Vocab, settings: Settings) -> RenderedPrompt:
    """profile.md, then GATHER's rules as part 1 and INTERPRET's (with the P1 prompt) as part 2."""
    head = read_prompt(paths.prompts / "profile.md")
    gather = read_prompt(paths.prompts / "gather.md")
    interp = interpret_system(paths, vocab, settings)
    system = "\n\n".join([head.body, "# Part 1: gather (the rules of the GATHER pass)", gather.body,
                          "# Part 2: interpret (the rules of the INTERPRET pass)", interp.system])
    return RenderedPrompt(system, f"{head.meta['version']}+gather-{gather.meta['version']}+{interp.version}")


def output_schema(vocab: Vocab, entry: CorpusEntry, allowed: list[str]) -> dict[str, Any]:
    gathered = gather_schema(allowed, with_ids=True)["properties"]
    return {"type": "object", "additionalProperties": False,
            "required": ["facts", "characters", "reception", "profile", "cast"],
            "properties": {**gathered, "profile": schema_with_evidence(p1_schema(vocab, entry), [], free_ids=True),
                           "cast": characters_schema(vocab, [], free_ids=True)}}


def api_lines(api: list[dict[str, Any]]) -> list[str]:
    """The API reception numbers as citable lines (A01: source score ... url)."""
    out = [f"reception_api: {len(api)} (cite these ids in outcome signals like any fact)"]
    for a in api:
        bits = [f"{a['id']}: {a.get('source')}"]
        if a.get("score") is not None:
            bits.append(f"score {a['score']}")
        if a.get("popularity") is not None:
            bits.append(f"popularity {a['popularity']}")
        if a.get("rank") is not None:
            bits.append(f"rank {a['rank']}")
        bits.append(f"({a.get('url')})")
        out.append(" ".join(bits))
    return out


def render_user(entry: CorpusEntry, allowed: list[str], vocab: Vocab, limits: dict[str, int], api: list[dict[str, Any]],
                adaptation: dict[str, Any] | None) -> str:
    lines = [gather_user(entry, allowed, vocab, limits), *api_lines(api)]
    if adaptation:
        lines.append(f"adaptation: {adaptation.get('status')} ({adaptation.get('screen_title') or 'no screen title'}; "
                     "from the catalog, already recorded: do not restate it as a fact)")
    lines.append("Give every fact an id (F1, F2, ...; character facts C1, ...; reception verdicts R1, ...) and cite "
                 "those ids, and the reception_api ids, in the profile's evidence and outcome signals. Then fill "
                 "the profile and the cast from the facts you gathered. Output one JSON object with facts, "
                 "characters, reception, profile and cast.")
    return "\n".join(lines)


def run_profile(paths: Paths, entries: list[CorpusEntry], client: LLMClient, vocab: Vocab, settings: Settings, *,
                run_id: str, reception: Any = None, adaptation: Any = None, guards: GuardConfig | None = None,
                created_at: str | None = None, params: dict[str, Any] | None = None,
                out_dir: Path | None = None) -> InterpretResult:
    """One merged call per title. `reception(entry) -> (records, notes)` and `adaptation(entry) -> dict | None`
    as in GATHER. `out_dir` + `params` (e.g. {"rerun": 2}): an agreement rerun written there, leaving the
    candidates and the gathered facts alone."""
    ctx = interpret_context(paths, vocab, settings, run_id=run_id, guards=guards, created_at=created_at, params=params,
                            out_dir=out_dir)
    ctx.prompt = render_prompt(paths, vocab, settings)
    client.prompt_version = ctx.prompt.version
    allowed, limits = gather_paths(vocab, settings), web_limits(settings)
    result = InterpretResult()
    for entry in entries:
        tid = entry.title_id
        if "gold" in entry.role_tags:
            result.skipped.append((tid, "gold titles keep GATHER, INTERPRET and the full VERIFY"))
            continue
        api: list[dict[str, Any]] = []
        notes: list[str] = []
        if reception is not None:
            records, notes = reception(entry)
            for i, rec in enumerate(records, start=1):
                api.append({"id": f"A{i:02d}", **rec.to_dict(), "api_url": rec.api_url})
        adapt = adaptation(entry) if adaptation is not None else None
        if adaptation is not None and adapt is None and entry.medium in PRINT_MEDIA:
            notes.append(f"{tid}: no adaptation signal (catalog lookup failed)")
        user = render_user(entry, allowed, vocab, limits, api, adapt)
        schema = output_schema(vocab, entry, allowed)

        def check(out: dict[str, Any], _entry: CorpusEntry = entry) -> None:
            problems = draft_problems(normalize_draft(out.get("profile") or {}, _entry, vocab), _entry, vocab,
                                      ctx.threshold, ctx.guards)
            other = [p for p in problems if not _is_length(p)]
            if other:
                raise ValueError("; ".join(other[:25]))

        cctx = CallContext(pass_="PROFILE", record_id=tid, title_id=tid,
                           upstream=upstream_hash([entry.model_dump(mode="json"),
                                                   {"paths": allowed, "limits": limits, "api": api, "adaptation": adapt}]))
        try:
            completion = client.complete_ex(ctx.prompt.system, user, schema, {**(params or {}), "web": limits}, ctx=cctx,
                                            validate=check)
        except InvalidOutput as exc:
            quarantine(paths.quarantine, "PROFILE", "title", tid, exc.raw, exc.errors)
            result.quarantined.append((tid, exc.errors[-1][:300]))
            continue
        except LiveRunRefused as exc:
            result.skipped.append((tid, str(exc)))
            continue
        except (BudgetExceeded, RateLimited, CliAuthError) as exc:  # stop the run; finished titles stay cached
            result.stopped = str(exc)
            break
        except ProviderError as exc:
            result.failed.append((tid, str(exc)))
            continue
        web = completion.meta.get("web") or {}
        kept, dropped = admit(completion.data, set(web.get("urls") or []), vocab, allowed, ctx.guards, keep_ids=True)
        if dropped:
            notes.append(f"{len(dropped)} item(s) dropped, no retry: " + "; ".join(dropped[:6]))
        gathered = {"title_id": tid, "run_id": run_id, **kept, "reception_api": api, "adaptation": adapt,
                    "searches": list(web.get("queries") or []), "notes": notes,
                    "provenance": {"run_id": run_id, "pass": "PROFILE", "model": completion.provenance_model,
                                   "prompt_version": client.prompt_version, "schema_version": SCHEMA_VERSION,
                                   "vocab_version": vocab.version, "cache_key": completion.cache_key,
                                   "created_at": ctx.created_at}}
        if out_dir is None:  # an agreement rerun leaves the facts of the first run in place
            atomic_write_text(paths.candidates / "gathered" / f"{tid}.json", json.dumps(gathered, indent=2) + "\n")
        facts = fact_index(gathered)
        if not finish_title(ctx, entry, gathered, facts, completion.data.get("profile") or {}, completion, client, result,
                            cast_data=completion.data.get("cast"), fast=True):
            break
    return result
