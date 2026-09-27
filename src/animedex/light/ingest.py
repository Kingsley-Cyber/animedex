"""`make ingest LIST=<file>`: one Sonnet call with web per three shows writes notes/<slug>.json for each show
that has none. Shows resolve through the catalog (read-only); the outcome is the catalog's numbers under the
existing label rule. A failed answer (after the client's one repair) is quarantined and every show of that
call is reported with the reason; a plan limit pauses the run and the rerun continues from the cache.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from animedex.budget import BudgetExceeded
from animedex.catalog.resolve import Resolved
from animedex.config import Settings
from animedex.light.notes import (
    PRINT_MEDIA,
    make_note,
    note_path,
    note_problems,
    note_schema,
    values_lines,
    write_note,
)
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.prompts import PromptFile, read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.cache import upstream_hash
from animedex.store.quarantine import quarantine

Resolver = Callable[[str], Resolved | None]
Numbers = Callable[[Resolved], dict[str, Any] | None]


@dataclass
class IngestResult:
    written: list[str] = field(default_factory=list)          # slugs
    skipped: list[str] = field(default_factory=list)          # slugs with a note already
    failed: list[tuple[str, str]] = field(default_factory=list)   # (line or slug, reason)
    calls: int = 0
    call_seconds: list[float] = field(default_factory=list)
    stopped: str | None = None
    seconds: float = 0.0

    def lines(self) -> list[str]:
        per_show = (sum(self.call_seconds) / len(self.written)) if self.written else 0.0
        out = [f"ingest: {len(self.written)} note(s) written, {len(self.skipped)} skipped (note exists), "
               f"{len(self.failed)} failed; {self.calls} call(s); {self.seconds / 60:.1f} min total, "
               f"{per_show:.0f} s of call time per written note"]
        out += [f"  failed {who}: {why[:220]}" for who, why in self.failed]
        if self.stopped:
            out.append(f"  paused: {self.stopped}. Run the same command later; finished calls are cached.")
        return out


def read_list(path: Path) -> list[str]:
    """One show per line; blank lines and # comments are skipped."""
    return [s for s in (raw.strip() for raw in path.read_text(encoding="utf-8").splitlines())
            if s and not s.startswith("#")]


def web_limits(settings: Settings, shows: int) -> dict[str, int]:
    cfg = settings.section("notes")
    searches = int(cfg.get("searches_per_show", 2)) * shows
    fetches = int(cfg.get("fetches_per_show", 2)) * shows
    return {"max_searches": searches, "outcome_extra": 0, "max_fetches": fetches, "max_turns": searches + fetches + 2}


def show_lines(entries: list[Resolved]) -> list[str]:
    lines = []
    for i, res in enumerate(entries, start=1):
        e = res.entry
        ref = str(e.get("catalog_ref") or "")
        kind = "manga" if e.get("medium") in PRINT_MEDIA else "anime"
        url = f"https://anilist.co/{kind}/{ref.split(':')[-1]}" if ref.startswith("anilist:") else ref
        lines.append(f"show {i}: {e['title']} ({e.get('year')}, {e.get('medium')}); scope: "
                     f"{(e.get('scope') or {}).get('version')}; catalog: {url}")
    return lines


def render_user(entries: list[Resolved], vocab: Vocab, limits: dict[str, int]) -> str:
    return "\n".join(["job: shows", *show_lines(entries),
                      f"limits: searches {limits['max_searches']}, fetches {limits['max_fetches']} for this whole call",
                      *values_lines(vocab)])


def resolve_lines(paths: Paths, lines: list[str], resolve: Resolver, result: IngestResult) -> list[Resolved]:
    """Lines -> resolved shows without a note; unresolved lines and existing notes are reported."""
    todo: list[Resolved] = []
    seen: set[str] = set()
    for line in lines:
        try:
            res = resolve(line)
        except Exception as exc:  # a catalog outage is a reason, not a crash
            result.failed.append((line, f"catalog lookup failed: {str(exc)[:160]}"))
            continue
        if res is None:
            result.failed.append((line, "not found in the catalog"))
            continue
        slug = res.entry["title_id"]
        if slug in seen:
            continue
        seen.add(slug)
        if note_path(paths, slug).is_file():
            result.skipped.append(slug)
            continue
        todo.append(res)
    return todo


def run_ingest(paths: Paths, settings: Settings, vocab: Vocab, lines: list[str], *, client: LLMClient,
               resolve: Resolver, numbers: Numbers, run_id: str, created_at: str | None = None,
               prompt: PromptFile | None = None, echo: Callable[[str], None] = lambda s: None) -> IngestResult:
    started = time.monotonic()
    prompt = prompt or read_prompt(paths.prompts / "ingest.md")
    client.prompt_version = prompt.version
    result = IngestResult()
    todo = resolve_lines(paths, lines, resolve, result)
    per_call = max(1, int(settings.section("notes").get("shows_per_call", 3)))
    for i in range(0, len(todo), per_call):
        group = todo[i:i + per_call]
        shows = [r.entry["title"] for r in group]
        slugs = [r.entry["title_id"] for r in group]
        label = "+".join(slugs)
        limits = web_limits(settings, len(group))
        titles = {str(r.entry["title"]).lower() for r in group}
        echo(f"notes: {', '.join(shows)}")

        def check(out: dict[str, Any], _shows: list[str] = shows, _titles: set[str] = titles) -> None:
            problems = note_problems(out, _shows, vocab, _titles)
            if problems:
                raise ValueError("; ".join(problems[:25]))

        ctx = CallContext(pass_="INGEST", record_id=label,
                          upstream=upstream_hash([{"entries": [r.entry for r in group], "limits": limits}]))
        t0 = time.monotonic()
        try:
            done = client.complete_ex(prompt.body, render_user(group, vocab, limits), note_schema(shows),
                                      {"web": limits}, ctx=ctx, validate=check)
        except InvalidOutput as exc:
            quarantine(paths.quarantine, "INGEST", "note", label, exc.raw, exc.errors)
            result.failed += [(s, f"no valid note after one repair ({exc.errors[-1][:160]})") for s in slugs]
            result.calls += 1
            result.call_seconds.append(time.monotonic() - t0)
            continue
        except (BudgetExceeded, RateLimited, CliAuthError) as exc:
            result.stopped = str(exc)
            result.failed += [(r.entry["title_id"], "not run: the run paused") for r in todo[i:]]
            break
        except ProviderError as exc:
            result.failed += [(s, f"the call failed ({str(exc)[:160]})") for s in slugs]
            result.calls += 1
            result.call_seconds.append(time.monotonic() - t0)
            continue
        result.calls += 1
        result.call_seconds.append(time.monotonic() - t0)
        web_urls = set((done.meta.get("web") or {}).get("urls") or [])
        by_show = {n.get("show"): n for n in done.data.get("notes") or []}
        for res in group:
            raw = by_show.get(res.entry["title"])
            if raw is None:
                result.failed.append((res.entry["title_id"], "the answer held no note for this show"))
                continue
            try:
                nums = numbers(res)
            except Exception as exc:  # the note still stands; the outcome falls back to the resolver's hint
                nums = None
                echo(f"  {res.entry['title_id']}: catalog numbers unavailable ({str(exc)[:120]})")
            write_note(paths, make_note(raw, res, nums, run_id=run_id, model=done.provenance_model,
                                        prompt_version=prompt.version, vocab=vocab, cache_key=done.cache_key,
                                        created_at=created_at, web_urls=web_urls))
            result.written.append(res.entry["title_id"])
    result.seconds = time.monotonic() - started
    return result
