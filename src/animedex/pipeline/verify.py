"""VERIFY (05): web-check the flagged P1 fields, moment locators, and the outcome.

- Searches are capped per title (verify.max_searches_per_title + outcome_extra_searches).
- Fetched pages are transient (TransientText): sent to the model once, redacted from logs, never stored.
- A field counts as web_confirmed / web_corrected only when the model cites a page fetched for
  this call (recall is not verification); otherwise it is `unresolved`.
- Recall-vs-web conflicts (corrections) are logged; moments the pages place outside scope are dropped.
Outputs rewrite the title's candidates in place and add an outcome candidate.

Native mode (`search.backend: native`, G1a 2026-09-27): no search API. The model searches with its
CLI's own WebSearch/WebFetch tools under a hard turn limit, and a citation counts only if that
call's tool traffic retrieved the URL. Page text never reaches this process's logs or cache.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from animedex import SCHEMA_VERSION
from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.content_guards import GuardConfig, framing_problems, quote_problems
from animedex.guards import LiveRunRefused
from animedex.models import CorpusEntry
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import BLOCKED_SOURCE_NOTE, blocked_source, norm_url, url_set
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.search.base import SearchBackend, SearchCapReached
from animedex.search.web import SearchBudget
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.store.quarantine import quarantine
from animedex.store.runlog import TransientText
from animedex.textutil import word_count

FIELD_STATUS = ["confirmed", "corrected", "unresolved"]
MOMENT_STATUS = ["confirmed", "corrected", "unresolved", "not_found"]
CONFOUNDERS = ["studio", "budget_signal", "source_popularity", "platform", "release_context"]


def render_prompt(paths: Paths, *, native: bool = False) -> RenderedPrompt:
    main = read_prompt(paths.prompts / ("verify_native.md" if native else "verify_web.md"))
    return RenderedPrompt(main.body, main.version)


def native_limits(pending: Pending, settings: Settings) -> dict[str, int]:
    """The per-title search cap (05) carried over to the model's own web tools."""
    cfg = settings.verify
    searches = int(cfg.get("max_searches_per_title", 3))
    extra = int(cfg.get("outcome_extra_searches", 2)) if "core.outcome" in pending.verify else 0
    fetches = (searches + extra) * int(cfg.get("pages_per_search", 2))
    return {"max_searches": searches + extra, "outcome_extra": extra, "max_fetches": fetches,
            "max_turns": searches + extra + fetches + 2}


def output_schema(vocab: Vocab) -> dict[str, Any]:
    nullable = {"type": ["string", "null"]}
    field_item = {"type": "object", "additionalProperties": False, "properties": {
        "path": {"type": "string"}, "status": {"type": "string", "enum": FIELD_STATUS},
        "value": nullable, "source_url": nullable, "note": nullable}}
    field_item["required"] = list(field_item["properties"])
    moment_item = {"type": "object", "additionalProperties": False, "properties": {
        "moment_id": {"type": "string"}, "status": {"type": "string", "enum": MOMENT_STATUS},
        "season": {"type": ["integer", "null"]}, "episode": {"type": ["integer", "null"]},
        "source_url": nullable}}
    moment_item["required"] = list(moment_item["properties"])
    signal = {"type": "object", "additionalProperties": False, "required": ["metric", "value", "source_url"],
              "properties": {"metric": {"type": "string"}, "value": {"type": "string"}, "source_url": {"type": "string"}}}
    outcome = {"type": ["object", "null"], "additionalProperties": False,
               "required": ["label", "signals", "confounders", "failure_reason", "failure_level", "failure_evidence",
                            "failure_evidence_url"],
               "properties": {"label": {"type": "string", "enum": list(vocab.enum("core.outcome"))},
                              "signals": {"type": "array", "items": signal},
                              "confounders": {"type": "object", "additionalProperties": False, "required": CONFOUNDERS,
                                              "properties": {k: {"type": "string"} for k in CONFOUNDERS}},
                              "failure_reason": nullable,
                              "failure_level": {"type": ["string", "null"],
                                                "enum": [*vocab.enum("outcome.failure_level"), None]},
                              "failure_evidence": nullable, "failure_evidence_url": nullable}}
    return {"type": "object", "additionalProperties": False, "required": ["fields", "moments", "outcome"],
            "properties": {"fields": {"type": "array", "items": field_item},
                           "moments": {"type": "array", "items": moment_item}, "outcome": outcome}}


# ---------------------------------------------------------------- inputs
@dataclass
class Pending:
    record: dict[str, Any]
    moments: list[dict[str, Any]]
    verify: list[str]


def load_pending(paths: Paths, title_id: str) -> Pending | None:
    title_file = paths.candidates / "title" / f"{title_id}.jsonl"
    verify_file = paths.candidates / "verify" / f"{title_id}.json"
    if not title_file.is_file() or not verify_file.is_file():
        return None
    [record] = read_jsonl(title_file)
    moments = read_jsonl(paths.candidates / "moment" / f"{title_id}.jsonl")
    verify = json.loads(verify_file.read_text(encoding="utf-8"))["verify"]
    return Pending(record, moments, verify)


def _field(record: dict[str, Any], path: str) -> dict[str, Any] | None:
    block, _, name = path.partition(".")
    return (record.get(block) or {}).get(name)


def gather_pages(entry: CorpusEntry, pending: Pending, search: SearchBackend, settings: Settings,
                 budget: SearchBudget) -> tuple[dict[str, TransientText], list[str]]:
    cfg = settings.verify
    q = cfg.get("queries", {})
    label = (cfg.get("medium_labels") or {}).get(entry.medium, entry.medium)
    fmt = {"title": entry.title, "year": entry.year, "medium_label": label}
    plan: list[tuple[str, bool]] = []
    if any(p != "core.outcome" and not p.startswith("moments.") for p in pending.verify):
        plan.append((q.get("facts", "{title} {year} {medium_label}").format(**fmt), False))
    if any(p.startswith("moments.") for p in pending.verify):
        plan.append((q.get("episodes", "{title} episode list").format(**fmt), False))
    if "core.outcome" in pending.verify:
        plan += [(t.format(**fmt), True) for t in q.get("outcome", ["{title} {year} reception"])]
    per_search = int(cfg.get("pages_per_search", 2))
    pages: dict[str, TransientText] = {}
    notes: list[str] = []
    for query, is_outcome in plan:
        try:
            budget.take(query, outcome=is_outcome)
        except SearchCapReached as exc:
            notes.append(str(exc))
            continue
        try:
            results = search.search(query)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            notes.append(f"search failed for {query!r}: {exc}")
            continue
        taken = 0
        for r in results:
            if taken >= per_search:
                break
            if r.url in pages:
                continue
            try:
                page = search.fetch(r.url)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                notes.append(f"fetch failed for {r.url}: {exc}")
                continue
            if page.text.strip():
                pages[page.url] = page
                taken += 1
    return pages, notes


def render_user(entry: CorpusEntry, pending: Pending, vocab: Vocab, pages: dict[str, TransientText]) -> str:
    lines = _brief(entry, pending, vocab) + ["", "Pages:"]
    for url, page in pages.items():
        lines += [f"=== {url}", page.text, ""]
    return "\n".join(lines)


def render_user_native(entry: CorpusEntry, pending: Pending, vocab: Vocab, limits: dict[str, int]) -> str:
    extra = f" ({limits['outcome_extra']} of them only for the outcome)" if limits["outcome_extra"] else ""
    return "\n".join(_brief(entry, pending, vocab) + [
        "", f"Limits: at most {limits['max_searches']} web searches{extra} and {limits['max_fetches']} page fetches."])


def _brief(entry: CorpusEntry, pending: Pending, vocab: Vocab) -> list[str]:
    lines = [f"Title: {entry.title} ({entry.year}); medium {entry.medium}; format {entry.format}",
             f"Scope: {entry.scope.version}; seasons {entry.scope.seasons or 'n/a'}; "
             f"numbering {entry.scope.numbering or 'n/a'}; out of scope: {'; '.join(entry.scope.exclude) or 'nothing listed'}",
             "", "Fields to check (path = recalled value):"]
    for path in pending.verify:
        if path.startswith("moments."):
            continue
        fv = _field(pending.record, path) or {}
        enum = ""
        if path in {f.path for f in vocab.lens_fields() if f.kind == "enum"}:
            enum = f"   [allowed: {' | '.join(vocab.enum(vocab.lens_field(path).vocab or path))}]"
        lines.append(f"- {path} = {fv.get('value')!r}{enum}")
    lines += ["", "Moments to locate (moment_id: description; recalled season/episode):"]
    for m in pending.moments:
        loc = m.get("locator") or {}
        lines.append(f"- {m['moment_id']}: {m['description']} (S{loc.get('season')} E{loc.get('episode')})")
    return lines


CITE_PAGES = "cite one of the provided page URLs"
CITE_NATIVE = "cite a URL your searches returned or you opened in this session"


def _cite(url: Any, urls: set[str], cite: str) -> str | None:
    """None when `url` is an admissible citation, else what the repair should say."""
    if blocked_source(url):
        return f"{BLOCKED_SOURCE_NOTE}; {cite}"
    return None if norm_url(url) in urls else cite


def output_problems(out: dict[str, Any], pending: Pending, vocab: Vocab, pages: dict[str, TransientText] | set[str],
                    guards: GuardConfig, *, cite: str = CITE_PAGES) -> list[str]:
    problems = []
    urls = url_set(pages)
    fields_to_check = {p for p in pending.verify if not p.startswith("moments.")}
    enum_paths = {f.path: f for f in vocab.lens_fields() if f.kind == "enum"}
    for item in out.get("fields", []):
        path, status = item.get("path"), item.get("status")
        if path not in fields_to_check:
            problems.append(f"fields: {path!r} was not asked for")
            continue
        if status in ("confirmed", "corrected") and (why := _cite(item.get("source_url"), urls, cite)):
            problems.append(f"{path}: {why}, or mark unresolved")
        if status == "corrected":
            value = item.get("value")
            if not value:
                problems.append(f"{path}: corrected needs a value")
            elif path in enum_paths:
                allowed = vocab.enum(enum_paths[path].vocab or path)
                if value not in allowed and not str(value).lower().startswith("other:"):
                    problems.append(f"{path}: {value!r} is not an allowed value")
            elif word_count(str(value)) > 12:
                problems.append(f"{path}: 12 words max")
            if value:
                problems += [f"{path}: {p}" for p in quote_problems(str(value), guards.min_quote_words)]
                if path.startswith("sensory."):
                    problems += [f"{path}: {p}" for p in framing_problems(str(value), guards.framing_terms)]
    moment_ids = {m["moment_id"] for m in pending.moments}
    for item in out.get("moments", []):
        if item.get("moment_id") not in moment_ids:
            problems.append(f"moments: unknown moment_id {item.get('moment_id')!r}")
        elif item.get("status") in ("confirmed", "corrected", "not_found") and (
                why := _cite(item.get("source_url"), urls, cite)):
            problems.append(f"{item['moment_id']}: {why}, or mark unresolved")
    oc = out.get("outcome")
    if oc:
        if not oc.get("signals"):
            problems.append("outcome needs at least one metric with its page URL")
        for s in oc.get("signals", []):
            if why := _cite(s.get("source_url"), urls, cite):
                problems.append(f"outcome signal {s.get('metric')!r}: {why}")
        reason = oc.get("failure_reason")
        if oc.get("label") in ("mixed", "flop") and not reason:
            problems.append("outcome: mixed/flop needs a failure_reason")
        if reason and word_count(reason) > 25:
            problems.append("outcome.failure_reason: 25 words max")
        level, evidence = oc.get("failure_level"), oc.get("failure_evidence")
        if oc.get("label") == "hit" and level is not None:
            problems.append("outcome: a hit carries failure_level null")
        if oc.get("label") in ("mixed", "flop"):
            if level is None:
                problems.append("outcome: mixed/flop needs failure_level (premise|execution|external|unknown)")
            elif level != "unknown":
                if not evidence:
                    problems.append(f"outcome: failure_level {level} needs failure_evidence (25 words max)")
                if why := _cite(oc.get("failure_evidence_url"), urls, cite):
                    problems.append(f"outcome.failure_evidence_url: {why}")
        if evidence:
            if word_count(evidence) > 25:
                problems.append("outcome.failure_evidence: 25 words max")
            problems += [f"outcome.failure_evidence: {p}" for p in quote_problems(str(evidence), guards.min_quote_words)]
    return problems


# ---------------------------------------------------------------- apply
class _Sources:
    """`url in sources` by normalized page identity (fetched pages or native web evidence)."""

    def __init__(self, urls: Any):
        self._urls = url_set(urls)

    def __contains__(self, url: object) -> bool:
        return norm_url(url) in self._urls

@dataclass
class VerifyTitleResult:
    title_id: str
    statuses: dict[str, str] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    dropped_moments: list[str] = field(default_factory=list)
    outcome: bool = False
    searches: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def apply(pending: Pending, out: dict[str, Any], pages: dict[str, TransientText] | set[str], *, prov: dict[str, Any],
          threshold: float) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, VerifyTitleResult]:
    record = json.loads(json.dumps(pending.record))
    res = VerifyTitleResult(record["title_id"])
    pages = _Sources(pages)
    by_path = {i["path"]: i for i in out.get("fields", [])}
    for path in pending.verify:
        if path.startswith("moments."):
            continue
        fv = _field(record, path)
        if fv is None:
            continue
        item = by_path.get(path)
        status = item["status"] if item and (item["status"] == "unresolved" or item.get("source_url") in pages) else "unresolved"
        if status == "confirmed":
            fv.update(source="web", verification="web_confirmed", source_ref=item["source_url"], conf=max(fv["conf"], threshold))
        elif status == "corrected":
            res.conflicts.append({"path": path, "recall": fv["value"], "web": item["value"], "source_ref": item["source_url"]})
            fv.update(value=item["value"], source="web", verification="web_corrected", source_ref=item["source_url"],
                      conf=max(fv["conf"], threshold))
        else:
            fv.update(verification="unresolved")
        res.statuses[path] = status
    by_moment = {i["moment_id"]: i for i in out.get("moments", [])}
    moments = []
    for m in pending.moments:
        m = json.loads(json.dumps(m))
        item = by_moment.get(m["moment_id"])
        status = item["status"] if item and (item["status"] == "unresolved" or item.get("source_url") in pages) else "unresolved"
        if status == "not_found":
            res.dropped_moments.append(m["moment_id"])
            continue
        if status == "confirmed":
            m.update(verification="web_confirmed", source_ref=item["source_url"])
        elif status == "corrected":
            m["locator"].update(season=item.get("season"), episode=item.get("episode"))
            m.update(verification="web_corrected", source_ref=item["source_url"])
        else:
            m["verification"] = "unresolved"
        res.statuses[f"moments.{m['moment_id']}.locator"] = status
        moments.append(m)
    outcome = None
    oc = out.get("outcome")
    if oc and all(s["source_url"] in pages for s in oc.get("signals", [])) and oc.get("signals"):
        level = oc.get("failure_level") if oc["label"] != "hit" else None
        sourced = level not in (None, "unknown") and oc.get("failure_evidence_url") in pages
        if level not in (None, "unknown") and not sourced:
            level = "unknown"  # an unsourced level is not evidence
        outcome = {"title_id": record["title_id"], "label": oc["label"],
                   "signals": [{"metric": s["metric"], "value": s["value"], "source_ref": s["source_url"]} for s in oc["signals"]],
                   "confounders": {k: (oc.get("confounders") or {}).get(k, "") for k in CONFOUNDERS},
                   "failure_reason": oc.get("failure_reason"),
                   "failure_level": level,
                   "failure_evidence": oc.get("failure_evidence") if sourced else None,
                   "failure_evidence_ref": oc.get("failure_evidence_url") if sourced else None,
                   "failure_level_source": "verify" if level is not None else None,
                   "provenance": prov}
        res.outcome = True
    return record, moments, outcome, res


# ---------------------------------------------------------------- stage
@dataclass
class VerifyResult:
    titles: list[VerifyTitleResult] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    quarantined: list[tuple[str, str]] = field(default_factory=list)
    stopped: str | None = None


def canonical_pending(paths: Paths, title_id: str) -> Pending | None:
    """Outcome-only re-verify (v1.3 boundary): the canonical profile, with only the outcome to check."""
    record = next((t for t in read_jsonl(paths.canonical / "titles.jsonl") if t["title_id"] == title_id), None)
    return None if record is None else Pending(record, [], ["core.outcome"])


def run_verify(paths: Paths, entries: list[CorpusEntry], client: LLMClient, search: SearchBackend | None,
               vocab: Vocab, settings: Settings, *, run_id: str, guards: GuardConfig | None = None,
               created_at: str | None = None, outcome_only: bool = False) -> VerifyResult:
    """`search=None` is native mode: the model's own web tools do the searching. `outcome_only`
    re-checks just the outcome of canonical titles (v1.3 `failure_level`) and writes only outcomes."""
    guards = guards or GuardConfig.from_settings(settings)
    native = search is None
    prompt = render_prompt(paths, native=native)
    client.prompt_version = prompt.version
    schema = output_schema(vocab)
    threshold = float(settings.verify.get("conf_threshold", 0.7))
    result = VerifyResult()
    for entry in entries:
        tid = entry.title_id
        pending = canonical_pending(paths, tid) if outcome_only else load_pending(paths, tid)
        if pending is None:
            result.skipped.append((tid, "no canonical profile" if outcome_only else
                                   "no P1 candidate; run `animedex p1` first"))
            continue
        budget = SearchBudget(int(settings.verify.get("max_searches_per_title", 3)),
                              int(settings.verify.get("outcome_extra_searches", 2)))
        try:
            if client.provider.live and client.title_guard:
                client.title_guard(tid)  # blind guard before any web or model traffic for this title
            pages, notes = ({}, []) if native else gather_pages(entry, pending, search, settings, budget)
        except LiveRunRefused as exc:
            result.skipped.append((tid, str(exc)))
            continue
        out: dict[str, Any] = {"fields": [], "moments": [], "outcome": None}
        completion = None
        sources: dict[str, TransientText] | set[str] = pages
        if native and (pending.verify or pending.moments):
            limits = native_limits(pending, settings)
            if outcome_only:  # the outcome's own extra searches are the whole budget
                extra = int(settings.verify.get("outcome_extra_searches", 2))
                fetches = extra * int(settings.verify.get("pages_per_search", 2))
                limits = {"max_searches": extra, "outcome_extra": extra, "max_fetches": fetches,
                          "max_turns": extra + fetches + 2}
            ctx = CallContext(pass_="VERIFY", record_id=tid, title_id=tid,
                              upstream=upstream_hash([pending.record, *pending.moments, {"verify": pending.verify},
                                                      {"search": "native", "limits": limits}]))

            def check_native(data: dict[str, Any], meta: dict[str, Any], _p: Pending = pending) -> None:
                urls = set(((meta or {}).get("web") or {}).get("urls") or [])
                problems = output_problems(data, _p, vocab, urls, guards, cite=CITE_NATIVE)
                if problems:
                    raise ValueError("; ".join(problems[:25]))

            call = (prompt.system, render_user_native(entry, pending, vocab, limits), {"web": limits}, check_native)
        elif pages:
            ctx = CallContext(pass_="VERIFY", record_id=tid, title_id=tid,
                              upstream=upstream_hash([pending.record, *pending.moments, {"verify": pending.verify},
                                                      {"pages": sorted((u, p.placeholder) for u, p in pages.items())}]),
                              transients=tuple(pages.values()))

            def check(data: dict[str, Any], _p: Pending = pending, _pages: dict = pages) -> None:
                problems = output_problems(data, _p, vocab, _pages, guards)
                if problems:
                    raise ValueError("; ".join(problems[:25]))

            call = (prompt.system, render_user(entry, pending, vocab, pages), None, check)
        else:
            call = None
        if call is not None:
            system, user, params, validate = call
            try:
                completion = client.complete_ex(system, user, schema, params, ctx=ctx, validate=validate)
                out = completion.data
                if native:
                    web = completion.meta.get("web") or {}
                    sources = set(web.get("urls") or [])
                    budget.log = list(web.get("queries") or [])
                    if int(web.get("searches") or 0) > limits["max_searches"]:
                        notes.append(f"search cap exceeded: {web['searches']} searches > {limits['max_searches']}")
            except InvalidOutput as exc:
                quarantine(paths.quarantine, "VERIFY", "title", tid, exc.raw, exc.errors)
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
        prov = {"run_id": run_id, "pass": "VERIFY", "model": completion.provenance_model if completion else None,
                "prompt_version": prompt.version, "schema_version": SCHEMA_VERSION, "vocab_version": vocab.version,
                "cache_key": completion.cache_key if completion else None,
                "created_at": created_at or datetime.now(UTC).isoformat()}
        record, moments, outcome, res = apply(pending, out, sources, prov=prov, threshold=threshold)
        if outcome and entry.failure_level_override and outcome["label"] != "hit":
            outcome.update(failure_level=entry.failure_level_override, failure_level_source="owner")
            notes.append(f"failure_level set by owner override: {entry.failure_level_override}")
        res.searches, res.notes = budget.log, notes
        if not outcome_only:
            atomic_write_text(paths.candidates / "title" / f"{tid}.jsonl", dumps_jsonl([record]))
            atomic_write_text(paths.candidates / "moment" / f"{tid}.jsonl", dumps_jsonl(moments))
        if outcome:
            atomic_write_text(paths.candidates / "outcome" / f"{tid}.jsonl", dumps_jsonl([outcome]))
        summary = {"title_id": tid, "run_id": run_id, "statuses": res.statuses, "conflicts": res.conflicts,
                   "dropped_moments": res.dropped_moments, "outcome": res.outcome, "searches": res.searches,
                   "notes": res.notes, "sources": sorted(sources)}
        name = f"{tid}.outcome.result.json" if outcome_only else f"{tid}.result.json"
        atomic_write_text(paths.candidates / "verify" / name, json.dumps(summary, indent=2) + "\n")
        result.titles.append(res)
    return result
