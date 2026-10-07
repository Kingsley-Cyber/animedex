"""`make quick SEED="<text>" [SHOWS="a, b, c"] [N=6]`: at most four calls, under ten minutes.

1. RESEARCH (slot `ingest`, prompt ingest.md, one call with web): with SHOWS absent, `job: seed` picks the 3-5
   most relevant shows and writes notes for the ones the index lacks; with SHOWS given, `job: shows` writes
   notes only for the ones that lack them. Skipped when every note exists, and on a rerun of the same seed
   (its picks are kept in notes/_research/<key>.json).
2. GENERATE (slot `generate`, generate.md): seed + notes + steering rules -> N cards.
3. CHECK (slot `check`, Codex, check.md, one call for all cards): consequence test, every steering rule, the
   closest note and how close, the biggest weakness, a score. A card is dropped when fewer than
   `quick.consequence_min` of 3 consequence dimensions differ, or when a hard rule fails.
4. PRIOR ART (slot `ingest`, prior_art.md, web): only when a surviving card claims "never done"; a
   counterexample counts only with a page the call retrieved, and downgrades the claim.
Output: build/quick/<timestamp>_<seed key>.md (private) with the survivors ranked by the check, each with
its weakness line and sources, plus a .json twin.
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
from animedex.ideate.steering import Rule, load_rules, rule_lines
from animedex.light.ingest import render_user as shows_user
from animedex.light.ingest import web_limits
from animedex.light.notes import (
    ENGINE,
    TEXT,
    _arr,
    _obj,
    index_line,
    make_note,
    note_item,
    note_lines,
    note_problems,
    note_schema,
    note_titles,
    read_notes,
    source_urls,
    values_lines,
    write_note,
)
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.quarantine import quarantine
from animedex.textutil import name_leaks, norm_url, sha256_text

MAYBE = {"type": ["string", "null"]}
BOOL, INT = {"type": "boolean"}, {"type": "integer"}
SEED_KINDS = ("fight_image", "lane", "concept")
CLOSENESS = ("near", "medium", "far")
DIMS = ("choices", "relationships", "outcomes")
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


def seed_key(seed: str, anomaly: bool = False) -> str:
    normalized = " ".join(seed.lower().split())
    return sha256_text(("anomaly: " if anomaly else "") + normalized).split(":")[-1][:12]


def call(client: LLMClient, pass_: str, record_id: str, system: str, user: str, schema: dict[str, Any],
         params: dict[str, Any] | None, validate: Any, paths: Paths) -> tuple[Any, str | None, str | None]:
    """(completion or None, problem, stop reason)."""
    ctx = CallContext(pass_=pass_, record_id=record_id, upstream=sha256_text(user))
    try:
        return client.complete_ex(system, user, schema, params, ctx=ctx, validate=validate), None, None
    except InvalidOutput as exc:
        quarantine(paths.quarantine, pass_, "quick", record_id, exc.raw, exc.errors)
        return None, f"no valid answer after one repair ({exc.errors[-1][:160]})", None
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        return None, None, str(exc)
    except ProviderError as exc:
        return None, f"the call failed ({str(exc)[:160]})", None


def raise_problems(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems[:25]))


# ---------------------------------------------------------------- research
def research_schema() -> dict[str, Any]:
    """The picks are decided in the same call, so a note's `show` is free text here (an empty enum is not a
    valid JSON Schema: the CLI refuses it)."""
    pick = _obj({"show": TEXT, "year": {"type": ["integer", "null"]}, "in_index": BOOL, "index_slug": MAYBE, "why": TEXT})
    return _obj({"picks": _arr(pick), "notes": _arr(note_item(TEXT))})


def research_problems(out: dict[str, Any], notes: dict[str, dict[str, Any]], vocab: Vocab, lo: int, hi: int) -> list[str]:
    problems: list[str] = []
    picks = out.get("picks") or []
    if not lo <= len(picks) <= hi:
        problems.append(f"picks: {lo} to {hi} shows")
    new_shows = []
    for i, p in enumerate(picks):
        if p.get("in_index"):
            if p.get("index_slug") not in notes:
                problems.append(f"picks[{i}].index_slug: not in the index (set in_index false and write its note)")
        else:
            new_shows.append(str(p.get("show") or ""))
    return problems + note_problems({"notes": out.get("notes") or []}, new_shows, vocab, set())


def seed_user(seed: str, notes: dict[str, dict[str, Any]], vocab: Vocab, limits: dict[str, int], lo: int, hi: int,
              anomaly: bool = False) -> str:
    label = "anomaly (user observation, unverified)" if anomaly else "seed"
    return "\n".join(["job: seed", f"{label}: {seed}", f"picks: {lo} to {hi} shows", *(index_line(n) for n in notes.values()),
                      f"limits: searches {limits['max_searches']}, fetches {limits['max_fetches']} for this whole call",
                      *values_lines(vocab)])


def _numbers(numbers: Numbers, r: Resolved, res: QuickResult) -> dict[str, Any] | None:
    try:
        return numbers(r)
    except Exception as exc:  # the note still stands
        res.problems.append(f"{r.entry['title_id']}: catalog numbers unavailable ({str(exc)[:100]})")
        return None


def do_research(paths: Paths, settings: Settings, vocab: Vocab, *, seed: str, anomaly: bool, shows: list[str] | None,
                notes: dict[str, dict[str, Any]], client: LLMClient, resolve: Resolver, numbers: Numbers,
                run_id: str, created_at: str | None, res: QuickResult) -> list[str]:
    """Returns the picks (slugs with a note). Writes notes and the seed's research record."""
    key = seed_key(seed, anomaly)
    prompt = read_prompt(paths.prompts / "ingest.md")
    client.prompt_version = prompt.version
    if shows:  # the owner named the shows: notes only for the ones that lack them
        resolved = []
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
        limits = web_limits(settings, len(missing))
        t0 = time.monotonic()
        done, problem, stop = call(client, "INGEST", "+".join(r.entry["title_id"] for r in missing), prompt.body,
                                   shows_user(missing, vocab, limits), note_schema(titles), {"web": limits},
                                   lambda out: raise_problems(note_problems(out, titles, vocab, {t.lower() for t in titles})),
                                   paths)
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
                             prompt_version=prompt.version, vocab=vocab, cache_key=done.cache_key,
                             created_at=created_at, web_urls=web_urls)
            write_note(paths, note)
            notes[note["slug"]] = note
            res.notes_written.append(note["slug"])
        res.research = f"ran (notes for {len(res.notes_written)} named show(s))"
        return [p for p in picks if p in notes]

    record = paths.research / f"{key}.json"
    if record.is_file():  # the same seed again: its picks stand
        saved = json.loads(record.read_text(encoding="utf-8"))
        picks = [p for p in saved.get("picks") or [] if p in notes]
        if picks:
            res.research = f"skipped (picks kept from {saved.get('created_at', '')[:10]}: {', '.join(picks)})"
            return picks
    cfg = settings.section("quick")
    lo, hi = int(cfg.get("picks_min", 3)), int(cfg.get("picks_max", 5))
    limits = web_limits(settings, hi)
    t0 = time.monotonic()
    done, problem, stop = call(client, "INGEST", f"research:{key}", prompt.body,
                               seed_user(seed, notes, vocab, limits, lo, hi, anomaly),
                               research_schema(), {"web": limits},
                               lambda out: raise_problems(research_problems(out, notes, vocab, lo, hi)), paths)
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
        r = resolve(f"{p['show']} ({p['year']})" if p.get("year") else str(p["show"]))
        raw = by_show.get(p.get("show"))
        if r is None or raw is None:
            res.problems.append(f"research: pick dropped, {'not in the catalog' if r is None else 'no note came back'}: "
                                f"{p.get('show')}")
            continue
        slug = r.entry["title_id"]
        if slug not in notes:
            note = make_note(raw, r, _numbers(numbers, r, res), run_id=run_id, model=done.provenance_model,
                             prompt_version=prompt.version, vocab=vocab, cache_key=done.cache_key, created_at=created_at,
                             web_urls=web_urls)
            write_note(paths, note)
            notes[slug] = note
            res.notes_written.append(slug)
        picks.append(slug)
    picks = list(dict.fromkeys(picks))
    atomic_write_text(record, json.dumps({"seed": seed, "input_kind": "anomaly" if anomaly else "seed",
                                          "key": key, "picks": picks, "run_id": run_id,
                                          "created_at": created_at or datetime.now(UTC).isoformat()}, indent=2) + "\n")
    res.research = f"ran (picked {', '.join(picks)}; {len(res.notes_written)} new note(s))"
    return picks


# ---------------------------------------------------------------- generate
def card_schema(picks: list[str], anomaly: bool = False, selected_frame: bool = False) -> dict[str, Any]:
    fields = {"logline": TEXT, "premise": TEXT, "engine": _obj({k: TEXT for k in ENGINE}), "mc_edge": TEXT,
                 "power_kit": _obj({"medium": TEXT, "functions": _arr(TEXT), "tools": _arr(TEXT), "limits": TEXT}),
                 "consequences": _obj({d: TEXT for d in DIMS}),
                 "closest_existing": {"type": "string", "enum": picks}, "why_not_a_clone": TEXT,
                 "never_done_claim": MAYBE}
    if anomaly:
        fields["hypothesis"] = TEXT
    kinds = ["anomaly"] if anomaly else (["concept"] if selected_frame else list(SEED_KINDS))
    return _obj({"seed_kind": {"type": "string", "enum": kinds},
                 "cards": _arr(_obj(fields))})


def card_problems(out: dict[str, Any], n: int, picks: list[str], titles: set[str],
                  anomaly: bool = False) -> list[str]:
    """Structure only (word counts are the prompt's guidance): the count, three functions and tools, a known
    closest note, and no existing title reused."""
    problems: list[str] = []
    cards = out.get("cards") or []
    if len(cards) != n:
        problems.append(f"cards: exactly {n} cards")
    if anomaly:
        hypotheses = [str(c.get("hypothesis") or "").strip() for c in cards]
        if any(not h for h in hypotheses) or len({h.casefold() for h in hypotheses}) != len(hypotheses):
            problems.append("cards: each anomaly card needs a distinct explanatory hypothesis")
    for i, c in enumerate(cards):
        kit = c.get("power_kit") or {}
        for key in ("functions", "tools"):
            if len([x for x in (kit.get(key) or []) if isinstance(x, str) and x.strip()]) != 3:
                problems.append(f"cards[{i}].power_kit.{key}: exactly 3 items")
        if c.get("closest_existing") not in picks:
            problems.append(f"cards[{i}].closest_existing: one of {picks}")
        leaks = name_leaks(f"{c.get('logline')} {c.get('premise')}", titles, set())
        if leaks:
            problems.append(f"cards[{i}]: uses an existing title ({', '.join(leaks[:3])}); invent your own names")
    return problems


def generate_user(seed: str, rules: list[Rule], n: int, notes: dict[str, dict[str, Any]], picks: list[str],
                  anomaly: bool = False, selected_frame: dict[str, Any] | None = None) -> str:
    label = "anomaly (user observation, unverified)" if anomaly else "seed"
    lines = [f"{label}: {seed}", *(rule_lines(rules) or ["rules: none"]), f"cards: {n}"]
    if selected_frame:
        lines += [f"selected_frame: {selected_frame['sentence']}",
                  f"originating_gap: {selected_frame['anomaly']}",
                  f"discourse_source: {selected_frame['source_url']}"]
    for slug in picks:
        lines += note_lines(notes[slug])
    return "\n".join(lines)


# ---------------------------------------------------------------- check (quick cards and diagnosed concepts)
def check_schema(refs: list[str], rule_ids: list[str], picks: list[str], anomaly: bool = False,
                 selected_frame: bool = False) -> dict[str, Any]:
    rule = _obj({"id": {"type": "string", "enum": rule_ids}, "verdict": {"type": "string", "enum": ["pass", "fail"]},
                 "reason": TEXT})
    fields = {"ref": {"type": "string", "enum": refs}, **{f"{d}_differs": BOOL for d in DIMS},
                 "consequence_reason": TEXT, "rules": _arr(rule),
                 "closest_slug": {"type": "string", "enum": picks}, "closeness": {"type": "string", "enum": list(CLOSENESS)},
                 "closeness_reason": TEXT, "weakness": TEXT, "score": INT}
    if anomaly:
        fields.update({"explains_anomaly": BOOL, "explanation_reason": TEXT})
    if selected_frame:
        fields.update({"keeps_frame": BOOL, "frame_reason": TEXT})
    return _obj({"cards": _arr(_obj(fields))})


def check_problems(out: dict[str, Any], refs: list[str], rule_ids: list[str], anomaly: bool = False,
                   selected_frame: bool = False) -> list[str]:
    problems: list[str] = []
    cards = out.get("cards") or []
    if sorted(c.get("ref") for c in cards) != sorted(refs):
        problems.append(f"check every card exactly once: {refs}")
    for i, c in enumerate(cards):
        if sorted(r.get("id") for r in c.get("rules") or []) != sorted(rule_ids):
            problems.append(f"cards[{i}].rules: one verdict per rule: {rule_ids}")
        if not isinstance(c.get("score"), int) or not 0 <= c["score"] <= 100:
            problems.append(f"cards[{i}].score: an integer from 0 to 100")
        if anomaly and not str(c.get("explanation_reason") or "").strip():
            problems.append(f"cards[{i}].explanation_reason: explain the verdict")
        if selected_frame and not str(c.get("frame_reason") or "").strip():
            problems.append(f"cards[{i}].frame_reason: explain the verdict")
    return problems


def card_text(ref: str, c: dict[str, Any]) -> list[str]:
    e, kit, q = c.get("engine") or {}, c.get("power_kit") or {}, c.get("consequences")
    lines = [f"=== CARD {ref}"]
    if c.get("logline"):
        lines.append(f"logline: {c['logline']}")
    if c.get("hypothesis"):
        lines.append(f"hypothesis: {c['hypothesis']}")
    lines += [f"premise: {c.get('premise')}", "engine: " + "; ".join(f"{k} {e.get(k)}" for k in ENGINE),
              f"mc_edge: {c.get('mc_edge')}",
              f"power_kit: medium {kit.get('medium')}; functions {' / '.join(kit.get('functions') or [])}; "
              f"tools {' / '.join(kit.get('tools') or [])}; limits {kit.get('limits')}"]
    if q:
        lines.append(f"consequences: choices {q.get('choices')}; relationships {q.get('relationships')}; "
                     f"outcomes {q.get('outcomes')}")
        lines.append(f"closest note (the card's own claim): {c.get('closest_existing')}; why not a clone: "
                     f"{c.get('why_not_a_clone')}")
        lines.append(f"never done claim: {c.get('never_done_claim') or 'none'}")
    else:  # an author's concept, written as a note (diagnose)
        lines.append("consequences: not stated (judge them from the premise, engine and kit); closest note: not stated")
        lines += [f"element {i}: {el.get('element')}" for i, el in enumerate(c.get("elements") or [], start=1)]
    return lines


def check_user(rules: list[Rule], notes: dict[str, dict[str, Any]], picks: list[str], cards: dict[str, dict[str, Any]],
               anomaly: str | None = None, selected_frame: dict[str, Any] | None = None) -> str:
    lines = ([f"anomaly (user observation, unverified): {anomaly}"] if anomaly else [])
    if selected_frame:
        lines += [f"selected_frame: {selected_frame['sentence']}",
                  f"originating_gap: {selected_frame['anomaly']}"]
    lines += list(rule_lines(rules) or ["rules: none"])
    for slug in picks:
        lines += note_lines(notes[slug])
    for ref, c in cards.items():
        lines += card_text(ref, c)
    return "\n".join(lines)


def verdict_dims(check: dict[str, Any]) -> int:
    return sum(1 for d in DIMS if check.get(f"{d}_differs"))


# ---------------------------------------------------------------- prior art
def prior_art_schema(refs: list[str]) -> dict[str, Any]:
    item = _obj({"ref": {"type": "string", "enum": refs}, "found": BOOL, "counterexample": MAYBE, "url": MAYBE,
                 "note": TEXT})
    return _obj({"claims": _arr(item)})


# ---------------------------------------------------------------- the run
def run_quick(paths: Paths, settings: Settings, vocab: Vocab, *, seed: str, shows: list[str] | None, n: int,
              clients: dict[str, LLMClient], resolve: Resolver, numbers: Numbers, run_id: str,
              created_at: str | None = None, echo: Callable[[str], None] = lambda s: None,
              anomaly: bool = False, selected_frame: dict[str, Any] | None = None) -> QuickResult:
    started = time.monotonic()
    seed = " ".join(seed.split())
    if not seed:
        raise QuickError("the seed is empty")
    rules = load_rules(paths)
    hard = [r.id for r in rules if r.strength == "hard"]
    notes = read_notes(paths)
    res = QuickResult()
    # the seed key keeps two runs started in the same second apart (2026-09-27: one overwrote the other)
    stamp = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{seed_key(seed, anomaly)[:6]}"
    while (paths.quick / f"{stamp}.md").exists():
        stamp += "b"
    record: dict[str, Any] = {"seed": seed, "input_kind": "anomaly" if anomaly else "seed",
                              "run_id": run_id, "created_at": created_at or datetime.now(UTC).isoformat(),
                              "rules": [r.__dict__ for r in rules]}
    if selected_frame:
        record["source_frame"] = selected_frame

    echo("quick: research")
    picks = do_research(paths, settings, vocab, seed=seed, anomaly=anomaly, shows=shows,
                        notes=notes, client=clients["ingest"],
                        resolve=resolve, numbers=numbers, run_id=run_id, created_at=created_at, res=res)
    res.picks = picks
    record["picks"] = picks
    if res.stopped or not picks:
        if not picks and not res.stopped:
            res.problems.append("no notes to measure against: name shows with SHOWS=... or run make ingest")
        return _finish(paths, res, record, [], {}, stamp, started)

    echo(f"quick: generate {n} card(s) against {', '.join(picks)}")
    gen_prompt = read_prompt(paths.prompts / "generate.md")
    gen = clients["generate"]
    gen.prompt_version = gen_prompt.version
    titles = note_titles({s: notes[s] for s in picks})
    key = seed_key(seed, anomaly)
    t0 = time.monotonic()
    done, problem, stop = call(gen, "GENERATE", f"generate:{key}:{stamp}", gen_prompt.body,
                               generate_user(seed, rules, n, notes, picks, anomaly, selected_frame),
                               card_schema(picks, anomaly, bool(selected_frame)), None,
                               lambda out: raise_problems(card_problems(out, n, picks, titles, anomaly)), paths)
    res.timings["generate"] = time.monotonic() - t0
    res.calls += 1
    if done is None:
        res.stopped = stop
        res.problems.append(f"generate: {stop or problem}")
        return _finish(paths, res, record, [], {}, stamp, started)
    record["seed_kind"] = done.data["seed_kind"]
    cards = {f"C{i}": c for i, c in enumerate(done.data["cards"], start=1)}
    res.cards_in = len(cards)

    echo("quick: check")
    chk_prompt = read_prompt(paths.prompts / "check.md")
    judge = clients["check"]
    judge.prompt_version = chk_prompt.version
    refs, rule_ids = list(cards), [r.id for r in rules]
    t0 = time.monotonic()
    cdone, problem, stop = call(judge, "CHECK", f"check:{key}:{stamp}", chk_prompt.body,
                                check_user(rules, notes, picks, cards, seed if anomaly else None, selected_frame),
                                check_schema(refs, rule_ids, picks, anomaly, bool(selected_frame)), None,
                                lambda out: raise_problems(check_problems(out, refs, rule_ids, anomaly,
                                                                           bool(selected_frame))), paths)
    res.timings["check"] = time.monotonic() - t0
    res.calls += 1
    if cdone is None:
        res.stopped = stop
        res.problems.append(f"check: {stop or problem}")
        return _finish(paths, res, record, [], cards, stamp, started)
    need = int(settings.section("quick").get("consequence_min", 2))
    checks = {c["ref"]: c for c in cdone.data["cards"]}
    survivors: list[str] = []
    for ref in refs:
        c = checks[ref]
        c["dims"] = verdict_dims(c)
        failed_hard = [r for r in c["rules"] if r["id"] in hard and r["verdict"] == "fail"]
        if anomaly and not c["explains_anomaly"]:
            res.dropped.append(f"{ref}: hypothesis does not explain the anomaly ({c['explanation_reason']})")
        elif selected_frame and not c["keeps_frame"]:
            res.dropped.append(f"{ref}: card abandons the selected frame ({c['frame_reason']})")
        elif c["dims"] < need:
            res.dropped.append(f"{ref}: consequence test {c['dims']} of 3 ({c['consequence_reason']})")
        elif failed_hard:
            res.dropped.append(f"{ref}: hard rule failed (" + "; ".join(f"{r['id']}: {r['reason']}" for r in failed_hard) + ")")
        else:
            survivors.append(ref)
    survivors.sort(key=lambda r: (-int(checks[r]["score"]), r))
    res.survivors = len(survivors)
    record["checks"] = checks

    claims = [r for r in survivors if cards[r].get("never_done_claim")]
    if claims:
        echo(f"quick: prior art for {len(claims)} claim(s)")
        pa_prompt = read_prompt(paths.prompts / "prior_art.md")
        pa = clients["ingest"]
        pa.prompt_version = pa_prompt.version
        limits = web_limits(settings, len(claims))
        user = "\n".join([f"limits: searches {limits['max_searches']}, fetches {limits['max_fetches']} for this whole call",
                          *(f"claim {r}: {cards[r]['never_done_claim']} | logline: {cards[r]['logline']}" for r in claims)])
        t0 = time.monotonic()
        pdone, problem, stop = call(pa, "PRIOR_ART", f"prior_art:{key}:{stamp}", pa_prompt.body, user,
                                    prior_art_schema(claims), {"web": limits},
                                    lambda out: raise_problems([] if sorted(c.get("ref") for c in out.get("claims") or [])
                                                               == sorted(claims) else [f"answer every claim once: {claims}"]),
                                    paths)
        res.timings["prior_art"] = time.monotonic() - t0
        res.calls += 1
        if pdone is None:
            res.stopped = stop
            res.problems.append(f"prior art: {stop or problem}")
            for r in claims:
                cards[r]["prior_art"] = f"not checked ({stop or problem})"
        else:
            fetched = {norm_url(u) for u in (pdone.meta.get("web") or {}).get("urls") or []}
            for c in pdone.data["claims"]:
                card = cards[c["ref"]]
                if c.get("found") and c.get("counterexample") and c.get("url") and norm_url(c["url"]) in fetched:
                    card["prior_art"] = f"downgraded: {c['counterexample']} already does this ({c['url']})"
                    card["prior_art_url"] = c["url"]
                else:  # an uncited counterexample is no counterexample
                    card["prior_art"] = f"claim stands: no counterexample found ({c.get('note') or 'searched'})"
    return _finish(paths, res, record, survivors, cards, stamp, started)


def _finish(paths: Paths, res: QuickResult, record: dict[str, Any], survivors: list[str], cards: dict[str, dict[str, Any]],
            stamp: str, started: float) -> QuickResult:
    res.seconds = time.monotonic() - started
    record.update({"cards": cards, "survivors": survivors, "dropped": res.dropped, "timings": res.timings,
                   "calls": res.calls, "research": res.research, "problems": res.problems, "stopped": res.stopped,
                   "seconds": round(res.seconds, 1)})
    base = paths.quick / stamp
    atomic_write_text(base.with_suffix(".json"), json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(base.with_suffix(".md"), render_md(record, read_notes(paths), res))
    res.path = str(base.with_suffix(".md").relative_to(paths.root))
    res.json_path = str(base.with_suffix(".json").relative_to(paths.root))
    return res


def render_md(record: dict[str, Any], notes: dict[str, dict[str, Any]], res: QuickResult) -> str:
    cards, checks = record.get("cards") or {}, record.get("checks") or {}
    picks = record.get("picks") or []
    label = "Anomaly (user observation, unverified)" if record.get("input_kind") == "anomaly" else "Seed"
    lines = [f"# Quick cards {record.get('created_at', '')[:19]}", "", f"**{label}.** {record['seed']}"
             + (f" (read as: {record['seed_kind'].replace('_', ' ')})" if record.get("seed_kind") else ""), "",
             "**Measured against.** " + (", ".join(f"{s} ({notes[s]['title']})" if s in notes else s for s in picks) or "nothing"),
             "", f"**Research.** {res.research or 'not run'}", "",
             f"**Run.** {res.calls} call(s); " + ", ".join(f"{k} {v:.0f}s" for k, v in res.timings.items())
             + f"; total {res.seconds / 60:.1f} min", ""]
    source_frame = record.get("source_frame")
    if source_frame:
        lines += [f"**Selected frame.** {source_frame['id']}: {source_frame['sentence']}", "",
                  f"**Originating gap.** {source_frame['anomaly']} ({source_frame['source_url']})", ""]
    if res.problems:
        lines += ["**Notes on this run.** " + " ".join(res.problems), ""]
    for rank, ref in enumerate(record.get("survivors") or [], start=1):
        c, k = cards[ref], checks.get(ref, {})
        e, kit, q = c["engine"], c["power_kit"], c["consequences"]
        near = k.get("closest_slug") or c["closest_existing"]
        lines += [f"## {rank}. {c['logline']}", "",
                  f"*Score {k.get('score')}; closest {notes.get(near, {}).get('title', near)} ({k.get('closeness')}: "
                  f"{k.get('closeness_reason')})*", "",
                  *([f"**Hypothesis.** {c['hypothesis']}", "",
                     f"**Anomaly check.** {'Explains' if k.get('explains_anomaly') else 'Does not explain'}: "
                     f"{k.get('explanation_reason')}", ""] if record.get("input_kind") == "anomaly" else []),
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
