"""`make quick SEED="<text>" [SHOWS="a, b, c"] [N=6]` (light path, owner instruction 2026-09-27; D-053).

At most four calls, under ten minutes:
1. RESEARCH (slot `notes`, Sonnet with web, one call): with SHOWS absent, pick the 3-5 most relevant shows
   and write notes for the ones the index lacks; with SHOWS given, write notes only for the ones that lack
   them. Skipped when every note exists, and on a rerun of the same seed (its picks are kept in
   notes/_research/<key>.json).
2. GENERATE (slot `ideate_generate`, Opus): brief = seed + notes + steering rules -> N cards.
3. CHECK (slot `ideate_judge`, Codex, one call for all cards): consequence test, every steering rule,
   closest note and how close, the biggest weakness, a score. Cards that fail the consequence test
   (fewer than `ideate.h1_min_changed_dimensions` of 3) or a hard rule are dropped.
4. PRIOR ART (slot `notes`, Sonnet with web): only when a surviving card claims "never done"; a found
   counterexample downgrades the claim.
Output: build/quick/<timestamp>.md (private) with the survivors ranked by the check, each with its weakness
line and sources, plus a .json twin; the path and the total time are printed.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from animedex.budget import BudgetExceeded
from animedex.catalog.resolve import Resolved
from animedex.config import Settings
from animedex.content_guards import GuardConfig
from animedex.ideate.steering import Rule, load_rules, rule_lines
from animedex.integrity import name_leaks
from animedex.light.ingest import notes_config
from animedex.light.ingest import render_user as notes_user
from animedex.light.notes import (
    ENGINE,
    ENUMS,
    TEXT,
    _arr,
    _obj,
    index_line,
    make_note,
    note_lines,
    note_problems,
    note_schema,
    note_titles,
    read_notes,
    source_urls,
    write_note,
)
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import norm_url
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.quarantine import quarantine
from animedex.textutil import sha256_text, word_count

MAYBE = {"type": ["string", "null"]}
BOOL, INT = {"type": "boolean"}, {"type": "integer"}
SEED_KINDS = ("fight_image", "lane", "concept")
CLOSENESS = ("near", "medium", "far")
CARD_CAPS = {"logline": 30, "premise": 120, "engine": 15, "mc_edge": 25, "medium": 8, "limits": 12, "consequence": 25,
             "why_not_a_clone": 40, "never_done_claim": 20}
Resolver = Callable[[str], Resolved | None]
Numbers = Callable[[Resolved], dict[str, Any] | None]


class QuickError(ValueError):
    pass


@dataclass
class QuickResult:
    path: str = ""
    json_path: str = ""
    seconds: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)
    calls: int = 0
    research: str = ""
    picks: list[str] = field(default_factory=list)
    cards_in: int = 0
    survivors: int = 0
    dropped: list[str] = field(default_factory=list)
    notes_written: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    stopped: str | None = None

    def lines(self) -> list[str]:
        out = [f"quick: {self.survivors} of {self.cards_in} card(s) survived; research {self.research}; "
               f"{self.calls} call(s); " + ", ".join(f"{k} {v:.0f}s" for k, v in self.timings.items())
               + f"; total {self.seconds / 60:.1f} min"]
        out += [f"  {p}" for p in self.problems]
        if self.stopped:
            out.append(f"  paused: {self.stopped}. Run the same command later; finished calls are cached.")
        if self.path:
            out.append(f"cards -> {self.path} (private: build/quick/ goes only to the data repo)")
        return out


def seed_key(seed: str) -> str:
    return sha256_text(" ".join(seed.lower().split())).split(":")[-1][:12]


def quick_config(settings: Settings) -> dict[str, Any]:
    return (settings.model_extra or {}).get("quick") or {}


# ---------------------------------------------------------------- calls
def _call(client: LLMClient, pass_: str, record_id: str, system: str, user: str, schema: dict[str, Any],
          params: dict[str, Any] | None, validate: Any, paths: Paths) -> tuple[Any, str | None, str | None]:
    """(completion or None, problem, stop reason)."""
    ctx = CallContext(pass_=pass_, record_id=record_id, title_id=None, upstream=sha256_text(user))
    try:
        return client.complete_ex(system, user, schema, params, ctx=ctx, validate=validate), None, None
    except InvalidOutput as exc:
        quarantine(paths.quarantine, pass_, "quick", record_id, exc.raw, exc.errors)
        return None, f"no valid answer after one repair ({exc.errors[-1][:160]})", None
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        return None, None, str(exc)
    except ProviderError as exc:
        return None, f"the call failed ({str(exc)[:160]})", None


def _raise(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems[:25]))


def _web(settings: Settings, shows: int) -> dict[str, int]:
    cfg = notes_config(settings)
    searches, fetches = int(cfg.get("searches_per_show", 2)) * shows, int(cfg.get("fetches_per_show", 2)) * shows
    return {"max_searches": searches, "outcome_extra": 0, "max_fetches": fetches, "max_turns": searches + fetches + 2}


# ---------------------------------------------------------------- research
def research_schema() -> dict[str, Any]:
    pick = _obj({"show": TEXT, "year": {"type": ["integer", "null"]}, "in_index": BOOL, "index_slug": MAYBE, "why": TEXT})
    return _obj({"picks": _arr(pick), "notes": note_schema([])["properties"]["notes"]})


def research_problems(out: dict[str, Any], notes: dict[str, dict[str, Any]], vocab: Vocab, guards: GuardConfig,
                      lo: int, hi: int, cap: int) -> list[str]:
    problems: list[str] = []
    picks = out.get("picks") or []
    if not lo <= len(picks) <= hi:
        problems.append(f"picks: {lo} to {hi} shows")
    new_shows: list[str] = []
    for i, p in enumerate(picks):
        if p.get("in_index"):
            if p.get("index_slug") not in notes:
                problems.append(f"picks[{i}].index_slug: not in the index (set in_index false and write its note)")
        else:
            new_shows.append(str(p.get("show") or ""))
        if word_count(str(p.get("why") or "")) > 20:
            problems.append(f"picks[{i}].why: 20 words or fewer")
    problems += note_problems({"notes": out.get("notes") or []}, new_shows, vocab, guards, set(), cap)
    return problems


def _resolve_line(p: dict[str, Any]) -> str:
    return f"{p['show']} ({p['year']})" if p.get("year") else str(p["show"])


def do_research(paths: Paths, settings: Settings, vocab: Vocab, *, seed: str, shows: list[str] | None,
                notes: dict[str, dict[str, Any]], client: LLMClient, resolve: Resolver, numbers: Numbers,
                run_id: str, created_at: str | None, guards: GuardConfig, res: QuickResult) -> list[str]:
    """Returns the picks (slugs with a note). Writes notes and the seed's research record."""
    key = seed_key(seed)
    record = paths.research / f"{key}.json"
    note_prompt = read_prompt(paths.prompts / "notes.md")
    cap = int(notes_config(settings).get("premise_max_words", 25))
    if shows:  # the owner named the shows: notes only for the ones that lack them
        resolved: list[Resolved] = []
        for line in shows:
            r = resolve(line)
            if r is None:
                res.problems.append(f"show not found in the catalog: {line}")
            else:
                resolved.append(r)
        picks = [r.entry["title_id"] for r in resolved]
        missing = [r for r in resolved if r.entry["title_id"] not in notes]
        if not missing:
            res.research = "skipped (every named show has a note)"
            return picks
        titles = [r.entry["title"] for r in missing]
        limits = _web(settings, len(missing))
        client.prompt_version = note_prompt.version
        t0 = time.monotonic()
        done, problem, stop = _call(client, "NOTES", "+".join(r.entry["title_id"] for r in missing), note_prompt.body,
                                    notes_user(missing, vocab, limits), note_schema(titles), {"web": limits},
                                    lambda out: _raise(note_problems(out, titles, vocab, guards,
                                                                     {t.lower() for t in titles}, cap)), paths)
        res.timings["research"] = time.monotonic() - t0
        res.calls += 1
        if done is None:
            res.stopped = stop
            res.problems.append(f"research: {stop or problem}")
            return [p for p in picks if p in notes]
        web_urls = set((done.meta.get("web") or {}).get("urls") or [])
        by_show = {n.get("show"): n for n in done.data.get("notes") or []}
        for r in missing:
            raw = by_show.get(r.entry["title"])
            if raw is None:
                res.problems.append(f"research: no note came back for {r.entry['title']}")
                continue
            note = make_note(raw, r, _numbers(numbers, r, res), run_id=run_id, model=done.provenance_model,
                             prompt_version=note_prompt.version, vocab=vocab, cache_key=done.cache_key,
                             created_at=created_at, web_urls=web_urls)
            write_note(paths, note)
            notes[note["slug"]] = note
            res.notes_written.append(note["slug"])
        res.research = f"ran (notes for {len(res.notes_written)} named show(s))"
        return [p for p in picks if p in notes]

    if record.is_file():  # the same seed again: its picks stand
        saved = json.loads(record.read_text(encoding="utf-8"))
        picks = [p for p in saved.get("picks") or [] if p in notes]
        if picks:
            res.research = f"skipped (picks kept from {saved.get('created_at', '')[:10]}: {', '.join(picks)})"
            return picks
    cfg = quick_config(settings)
    lo, hi = int(cfg.get("picks_min", 3)), int(cfg.get("picks_max", 5))
    head = read_prompt(paths.prompts / "quick_research.md")
    system = "\n\n".join([head.body, "# The note rules", note_prompt.body])
    version = f"{head.version}+notes-{note_prompt.version}"
    client.prompt_version = version
    limits = _web(settings, hi)
    user = "\n".join([f"seed: {' '.join(seed.split())}", f"pick {lo} to {hi} shows",
                      *(index_line(n) for n in notes.values()),
                      f"limits: searches {limits['max_searches']}, fetches {limits['max_fetches']} for this whole call",
                      *(f"values {k}: " + " | ".join(vocab.enum(p)) for k, p in ENUMS.items())])
    t0 = time.monotonic()
    done, problem, stop = _call(client, "QUICK", f"research:{key}", system, user, research_schema(), {"web": limits},
                                lambda out: _raise(research_problems(out, notes, vocab, guards, lo, hi, cap)), paths)
    res.timings["research"] = time.monotonic() - t0
    res.calls += 1
    if done is None:
        res.stopped = stop
        res.problems.append(f"research: {stop or problem}")
        return []
    web_urls = set((done.meta.get("web") or {}).get("urls") or [])
    by_show = {n.get("show"): n for n in done.data.get("notes") or []}
    picks: list[str] = []
    for p in done.data.get("picks") or []:
        if p.get("in_index") and p.get("index_slug") in notes:
            picks.append(p["index_slug"])
            continue
        r = resolve(_resolve_line(p))
        raw = by_show.get(p.get("show"))
        if r is None or raw is None:
            res.problems.append(f"research: pick dropped, {'not in the catalog' if r is None else 'no note came back'}: "
                                f"{p.get('show')}")
            continue
        slug = r.entry["title_id"]
        if slug not in notes:
            note = make_note(raw, r, _numbers(numbers, r, res), run_id=run_id, model=done.provenance_model,
                             prompt_version=version, vocab=vocab, cache_key=done.cache_key, created_at=created_at,
                             web_urls=web_urls)
            write_note(paths, note)
            notes[slug] = note
            res.notes_written.append(slug)
        picks.append(slug)
    picks = list(dict.fromkeys(picks))
    atomic_write_text(record, json.dumps({"seed": seed, "key": key, "picks": picks, "run_id": run_id,
                                          "created_at": created_at or datetime.now(UTC).isoformat()},
                                         indent=2) + "\n")
    res.research = f"ran (picked {', '.join(picks)}; {len(res.notes_written)} new note(s))"
    return picks


def _numbers(numbers: Numbers, r: Resolved, res: QuickResult) -> dict[str, Any] | None:
    try:
        return numbers(r)
    except Exception as exc:  # the note still stands
        res.problems.append(f"{r.entry['title_id']}: catalog numbers unavailable ({str(exc)[:100]})")
        return None


# ---------------------------------------------------------------- generate
def card_schema(picks: list[str]) -> dict[str, Any]:
    card = _obj({"logline": TEXT, "premise": TEXT, "engine": _obj({k: TEXT for k in ENGINE}), "mc_edge": TEXT,
                 "power_kit": _obj({"medium": TEXT, "functions": _arr(TEXT), "tools": _arr(TEXT), "limits": TEXT}),
                 "consequences": _obj({"choices": TEXT, "relationships": TEXT, "outcomes": TEXT}),
                 "closest_existing": {"type": "string", "enum": picks}, "why_not_a_clone": TEXT,
                 "never_done_claim": MAYBE})
    return _obj({"seed_kind": {"type": "string", "enum": list(SEED_KINDS)}, "cards": _arr(card)})


def _cap(problems: list[str], where: str, text: Any, cap: int, required: bool = True) -> None:
    n = word_count(str(text or ""))
    if n == 0 and required:
        problems.append(f"{where}: give it (1-{cap} words)")
    elif n > cap:
        problems.append(f"{where}: {n} words exceeds the {cap}-word limit")


def card_problems(out: dict[str, Any], n: int, picks: list[str], titles: set[str]) -> list[str]:
    problems: list[str] = []
    cards = out.get("cards") or []
    if len(cards) != n:
        problems.append(f"cards: exactly {n} cards")
    for i, c in enumerate(cards):
        pre = f"cards[{i}]"
        _cap(problems, f"{pre}.logline", c.get("logline"), CARD_CAPS["logline"])
        _cap(problems, f"{pre}.premise", c.get("premise"), CARD_CAPS["premise"])
        for k in ENGINE:
            _cap(problems, f"{pre}.engine.{k}", (c.get("engine") or {}).get(k), CARD_CAPS["engine"])
        _cap(problems, f"{pre}.mc_edge", c.get("mc_edge"), CARD_CAPS["mc_edge"])
        kit = c.get("power_kit") or {}
        _cap(problems, f"{pre}.power_kit.medium", kit.get("medium"), CARD_CAPS["medium"])
        _cap(problems, f"{pre}.power_kit.limits", kit.get("limits"), CARD_CAPS["limits"])
        for key in ("functions", "tools"):
            if len([x for x in (kit.get(key) or []) if isinstance(x, str) and x.strip()]) != 3:
                problems.append(f"{pre}.power_kit.{key}: exactly 3 items")
        for k in ("choices", "relationships", "outcomes"):
            _cap(problems, f"{pre}.consequences.{k}", (c.get("consequences") or {}).get(k), CARD_CAPS["consequence"])
        if c.get("closest_existing") not in picks:
            problems.append(f"{pre}.closest_existing: one of {picks}")
        _cap(problems, f"{pre}.why_not_a_clone", c.get("why_not_a_clone"), CARD_CAPS["why_not_a_clone"])
        _cap(problems, f"{pre}.never_done_claim", c.get("never_done_claim"), CARD_CAPS["never_done_claim"], False)
        leaks = name_leaks(f"{c.get('logline')} {c.get('premise')}", titles, set())
        if leaks:
            problems.append(f"{pre}: uses an existing title ({', '.join(leaks[:3])}); invent your own names")
    return problems


def generate_user(seed: str, rules: list[Rule], n: int, notes: dict[str, dict[str, Any]], picks: list[str]) -> str:
    lines = [f"seed: {' '.join(seed.split())}", *(rule_lines(rules) or ["rules: none"]), f"cards: {n}"]
    for slug in picks:
        lines += note_lines(notes[slug])
    return "\n".join(lines)


# ---------------------------------------------------------------- check
def check_schema(refs: list[str], rule_ids: list[str], picks: list[str]) -> dict[str, Any]:
    rule = _obj({"id": {"type": "string", "enum": rule_ids}, "verdict": {"type": "string", "enum": ["pass", "fail"]},
                 "reason": TEXT})
    item = _obj({"ref": {"type": "string", "enum": refs},
                 **{f"{d}_differs": BOOL for d in ("choices", "relationships", "outcomes")},
                 "consequence_reason": TEXT, "rules": _arr(rule),
                 "closest_slug": {"type": "string", "enum": picks}, "closeness": {"type": "string", "enum": list(CLOSENESS)},
                 "closeness_reason": TEXT, "weakness": TEXT, "score": INT})
    return _obj({"cards": _arr(item)})


def check_problems(out: dict[str, Any], refs: list[str], rule_ids: list[str]) -> list[str]:
    problems: list[str] = []
    cards = out.get("cards") or []
    if sorted(c.get("ref") for c in cards) != sorted(refs):
        problems.append(f"check every card exactly once: {refs}")
    for i, c in enumerate(cards):
        pre = f"cards[{i}]"
        if sorted(r.get("id") for r in c.get("rules") or []) != sorted(rule_ids):
            problems.append(f"{pre}.rules: one verdict per rule: {rule_ids}")
        for r in c.get("rules") or []:
            _cap(problems, f"{pre}.rules.{r.get('id')}.reason", r.get("reason"), 20)
        _cap(problems, f"{pre}.consequence_reason", c.get("consequence_reason"), 25)
        _cap(problems, f"{pre}.closeness_reason", c.get("closeness_reason"), 20)
        _cap(problems, f"{pre}.weakness", c.get("weakness"), 25)
        if not isinstance(c.get("score"), int) or not 0 <= c["score"] <= 100:
            problems.append(f"{pre}.score: an integer from 0 to 100")
    return problems


def card_text(ref: str, c: dict[str, Any]) -> list[str]:
    e, kit, q = c["engine"], c["power_kit"], c["consequences"]
    return [f"=== CARD {ref}", f"logline: {c['logline']}", f"premise: {c['premise']}",
            "engine: " + "; ".join(f"{k} {e.get(k)}" for k in ENGINE), f"mc_edge: {c['mc_edge']}",
            f"power_kit: medium {kit.get('medium')}; functions {' / '.join(kit.get('functions') or [])}; "
            f"tools {' / '.join(kit.get('tools') or [])}; limits {kit.get('limits')}",
            f"consequences: choices {q.get('choices')}; relationships {q.get('relationships')}; outcomes {q.get('outcomes')}",
            f"closest note (the card's own claim): {c['closest_existing']}; why not a clone: {c['why_not_a_clone']}",
            f"never done claim: {c.get('never_done_claim') or 'none'}"]


def check_user(rules: list[Rule], notes: dict[str, dict[str, Any]], picks: list[str], cards: dict[str, dict[str, Any]]) -> str:
    lines = list(rule_lines(rules) or ["rules: none"])
    for slug in picks:
        lines += note_lines(notes[slug])
    for ref, c in cards.items():
        lines += card_text(ref, c)
    return "\n".join(lines)


# ---------------------------------------------------------------- prior art
def prior_art_schema(refs: list[str]) -> dict[str, Any]:
    item = _obj({"ref": {"type": "string", "enum": refs}, "found": BOOL, "counterexample": MAYBE, "url": MAYBE,
                 "note": TEXT})
    return _obj({"claims": _arr(item)})


def prior_art_problems(out: dict[str, Any], refs: list[str], urls: set[str]) -> list[str]:
    problems: list[str] = []
    claims = out.get("claims") or []
    if sorted(c.get("ref") for c in claims) != sorted(refs):
        problems.append(f"answer every claim exactly once: {refs}")
    known = {norm_url(u) for u in urls}
    for i, c in enumerate(claims):
        _cap(problems, f"claims[{i}].note", c.get("note"), 25)
        if c.get("found"):
            if not c.get("counterexample") or not c.get("url"):
                problems.append(f"claims[{i}]: found needs the counterexample's title and page URL")
            elif norm_url(c["url"]) not in known:
                problems.append(f"claims[{i}].url: cite a page this call searched or opened, or answer found false")
    return problems


# ---------------------------------------------------------------- the run
def run_quick(paths: Paths, settings: Settings, vocab: Vocab, *, seed: str, shows: list[str] | None, n: int,
              clients: dict[str, LLMClient], resolve: Resolver, numbers: Numbers, run_id: str,
              created_at: str | None = None, guards: GuardConfig | None = None,
              echo: Callable[[str], None] = lambda s: None) -> QuickResult:
    started = time.monotonic()
    seed = " ".join(seed.split())
    if not seed:
        raise QuickError("the seed is empty")
    guards = guards or GuardConfig.from_settings(settings)
    rules = load_rules(paths)
    hard = [r.id for r in rules if r.strength == "hard"]
    notes = read_notes(paths)
    res = QuickResult()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    record: dict[str, Any] = {"seed": seed, "run_id": run_id, "created_at": created_at or datetime.now(UTC).isoformat(),
                              "rules": [r.__dict__ for r in rules]}

    # 1. research
    echo("quick: research")
    picks = do_research(paths, settings, vocab, seed=seed, shows=shows, notes=notes, client=clients["notes"],
                        resolve=resolve, numbers=numbers, run_id=run_id, created_at=created_at, guards=guards, res=res)
    res.picks = picks
    record["picks"] = picks
    if res.stopped or not picks:
        if not picks and not res.stopped:
            res.problems.append("no notes to measure against: name shows with SHOWS=... or run make ingest")
        return _finish(paths, res, record, [], {}, stamp, started)

    # 2. generate
    echo(f"quick: generate {n} card(s) against {', '.join(picks)}")
    gen_prompt = read_prompt(paths.prompts / "quick_generate.md")
    gen = clients["ideate_generate"]
    gen.prompt_version = gen_prompt.version
    titles = note_titles({s: notes[s] for s in picks})
    t0 = time.monotonic()
    done, problem, stop = _call(gen, "QUICK", f"generate:{seed_key(seed)}:{stamp}", gen_prompt.body,
                                generate_user(seed, rules, n, notes, picks), card_schema(picks),
                                None, lambda out: _raise(card_problems(out, n, picks, titles)), paths)
    res.timings["generate"] = time.monotonic() - t0
    res.calls += 1
    if done is None:
        res.stopped = stop
        res.problems.append(f"generate: {stop or problem}")
        return _finish(paths, res, record, [], {}, stamp, started)
    record["seed_kind"] = done.data["seed_kind"]
    cards = {f"C{i}": c for i, c in enumerate(done.data["cards"], start=1)}
    res.cards_in = len(cards)

    # 3. check
    echo("quick: check")
    chk_prompt = read_prompt(paths.prompts / "quick_check.md")
    judge = clients["ideate_judge"]
    judge.prompt_version = chk_prompt.version
    refs, rule_ids = list(cards), [r.id for r in rules]
    t0 = time.monotonic()
    cdone, problem, stop = _call(judge, "QUICK", f"check:{seed_key(seed)}:{stamp}", chk_prompt.body,
                                 check_user(rules, notes, picks, cards), check_schema(refs, rule_ids, picks),
                                 None, lambda out: _raise(check_problems(out, refs, rule_ids)), paths)
    res.timings["check"] = time.monotonic() - t0
    res.calls += 1
    if cdone is None:
        res.stopped = stop
        res.problems.append(f"check: {stop or problem}")
        return _finish(paths, res, record, [], cards, stamp, started)
    h1_min = int(settings.ideate.get("h1_min_changed_dimensions", 2))
    checks = {c["ref"]: c for c in cdone.data["cards"]}
    survivors: list[str] = []
    for ref in refs:
        c = checks[ref]
        dims = sum(1 for d in ("choices", "relationships", "outcomes") if c[f"{d}_differs"])
        failed_hard = [r["id"] for r in c["rules"] if r["id"] in hard and r["verdict"] == "fail"]
        c["dims"] = dims
        if dims < h1_min:
            res.dropped.append(f"{ref}: consequence test {dims} of 3 ({c['consequence_reason']})")
        elif failed_hard:
            why = "; ".join(f"{r['id']}: {r['reason']}" for r in c["rules"] if r["id"] in failed_hard)
            res.dropped.append(f"{ref}: hard rule failed ({why})")
        else:
            survivors.append(ref)
    survivors.sort(key=lambda r: (-int(checks[r]["score"]), r))
    res.survivors = len(survivors)
    record["checks"] = checks

    # 4. prior art, only for surviving "never done" claims
    claims = [r for r in survivors if cards[r].get("never_done_claim")]
    if claims:
        echo(f"quick: prior art for {len(claims)} claim(s)")
        pa_prompt = read_prompt(paths.prompts / "quick_prior_art.md")
        pa = clients["notes"]
        pa.prompt_version = pa_prompt.version
        limits = _web(settings, len(claims))
        user = "\n".join([f"limits: searches {limits['max_searches']}, fetches {limits['max_fetches']} for this whole call",
                          *(f"claim {r}: {cards[r]['never_done_claim']} | logline: {cards[r]['logline']}" for r in claims)])
        t0 = time.monotonic()
        pdone, problem, stop = _call(pa, "QUICK", f"prior_art:{seed_key(seed)}:{stamp}", pa_prompt.body, user,
                                     prior_art_schema(claims), {"web": limits}, None, paths)
        res.timings["prior_art"] = time.monotonic() - t0
        res.calls += 1
        if pdone is None:
            res.stopped = stop
            res.problems.append(f"prior art: {stop or problem}")
            for r in claims:
                cards[r]["prior_art"] = f"not checked ({stop or problem})"
        else:
            urls = set((pdone.meta.get("web") or {}).get("urls") or [])
            probs = prior_art_problems(pdone.data, claims, urls)
            if probs:  # an uncited counterexample is no counterexample (no second repair; cards keep their claim)
                res.problems.append("prior art: " + "; ".join(probs[:3]))
            for c in pdone.data["claims"]:
                card = cards[c["ref"]]
                cited = c.get("url") and norm_url(c["url"]) in {norm_url(u) for u in urls}
                if c.get("found") and c.get("counterexample") and cited:
                    card["prior_art"] = f"downgraded: {c['counterexample']} already does this ({c['url']})"
                    card["prior_art_url"] = c["url"]
                else:
                    card["prior_art"] = f"claim stands: no counterexample found ({c.get('note') or 'searched'})"
    return _finish(paths, res, record, survivors, cards, stamp, started)


def _finish(paths: Paths, res: QuickResult, record: dict[str, Any], survivors: list[str], cards: dict[str, dict[str, Any]],
            stamp: str, started: float) -> QuickResult:
    res.seconds = time.monotonic() - started
    record.update({"cards": cards, "survivors": survivors, "dropped": res.dropped, "timings": res.timings,
                   "calls": res.calls, "research": res.research, "problems": res.problems, "stopped": res.stopped,
                   "seconds": round(res.seconds, 1)})
    notes = read_notes(paths)
    base = paths.quick / stamp
    atomic_write_text(base.with_suffix(".json"), json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(base.with_suffix(".md"), render_md(record, notes, res))
    res.path, res.json_path = str(base.with_suffix(".md").relative_to(paths.root)), str(base.with_suffix(".json").relative_to(paths.root))
    return res


def render_md(record: dict[str, Any], notes: dict[str, dict[str, Any]], res: QuickResult) -> str:
    cards, checks = record.get("cards") or {}, record.get("checks") or {}
    picks = record.get("picks") or []
    lines = [f"# Quick cards {record.get('created_at', '')[:19]}", "", f"**Seed.** {record['seed']}"
             + (f" (read as: {record['seed_kind'].replace('_', ' ')})" if record.get("seed_kind") else ""), "",
             "**Measured against.** " + (", ".join(f"{s} ({notes[s]['title']})" if s in notes else s for s in picks) or "nothing"),
             "", f"**Research.** {res.research or 'not run'}", "",
             f"**Run.** {res.calls} call(s); " + ", ".join(f"{k} {v:.0f}s" for k, v in res.timings.items())
             + f"; total {res.seconds / 60:.1f} min", ""]
    if res.problems:
        lines += ["**Notes on this run.** " + " ".join(res.problems), ""]
    for rank, ref in enumerate(record.get("survivors") or [], start=1):
        c, k = cards[ref], checks.get(ref, {})
        e, kit, q = c["engine"], c["power_kit"], c["consequences"]
        near = k.get("closest_slug") or c["closest_existing"]
        lines += [f"## {rank}. {c['logline']}", "",
                  f"*Score {k.get('score')}; closest {notes.get(near, {}).get('title', near)} ({k.get('closeness')}: "
                  f"{k.get('closeness_reason')})*", "",
                  f"**Premise.** {c['premise']}", "",
                  f"**Engine.** Wants {e.get('goal')}, but {e.get('constraint')}. Chooses {e.get('strategy')}; pays "
                  f"{e.get('cost')}. Dilemma: {e.get('dilemma')}", "",
                  f"**MC edge.** {c['mc_edge']}", "",
                  f"**Power kit.** Medium: {kit.get('medium')}. Functions: {' / '.join(kit.get('functions') or [])}. "
                  f"Tools: {' / '.join(kit.get('tools') or [])}. Limits: {kit.get('limits')}", "",
                  f"**Consequences.** Choices: {q.get('choices')} Relationships: {q.get('relationships')} "
                  f"Outcomes: {q.get('outcomes')}", "",
                  f"**Why not a clone.** {c['why_not_a_clone']}", "",
                  f"**Check.** {k.get('dims')} of 3 consequence dimensions differ ({k.get('consequence_reason')}). Rules: "
                  + "; ".join(f"{r['id']} {r['verdict']} ({r['reason']})" for r in k.get("rules") or []), "",
                  f"**Weakness.** {k.get('weakness')}", ""]
        if c.get("never_done_claim"):
            lines += [f"**Never done?** Claim: {c['never_done_claim']}. {c.get('prior_art', 'not checked')}", ""]
        srcs = source_urls(notes.get(near, {})) + ([c["prior_art_url"]] if c.get("prior_art_url") else [])
        lines += ["**Sources.** " + (", ".join(srcs) or "none recorded"), ""]
    if res.dropped:
        lines += ["## Dropped by the check", ""] + [f"- {d}" for d in res.dropped] + [""]
    if not cards and not res.dropped:
        lines += ["No cards were written.", ""]
    return "\n".join(lines)


def parse_shows(text: str | None) -> list[str] | None:
    if not text or not text.strip():
        return None
    return [s.strip() for s in re.split(r"[,;\n]", text) if s.strip()]


__all__ = ["QuickError", "QuickResult", "card_problems", "check_problems", "parse_shows", "prior_art_problems",
           "research_problems", "run_quick", "seed_key"]
