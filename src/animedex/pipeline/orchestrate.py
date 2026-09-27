"""Run titles through the whole pipeline, stage by stage, skipping work that is already canonical.

Gold titles (full rigor):
GATHER -> INTERPRET -> VERIFY -> CANONICALIZE -> P2 -> P3 -> CHECK -> CANONICALIZE -> P4 -> CANONICALIZE
(gather-first since v1.7, D-042: the recall-first P1 path is no longer run)

Non-gold titles (speed pass v1.10, D-048, `speed:` in settings): PROFILE (gather + interpret in one call) ->
VERIFY (outcome and moment locators) -> CANONICALIZE -> P2 -> P3 -> CHECK (three titles per call) ->
CANONICALIZE -> P4 -> CANONICALIZE, every call at medium effort, up to four titles at once in each stage
under one budget.

A batch moves one stage at a time across all its titles, so partners are canonical before P3
needs them. A usage limit, an expired login, or a budget cap stops the batch cleanly: finished
calls are cached and a rerun picks up where it stopped. Output is counts only (owner ruling:
never show gold-title outputs before "annotations done"/"annotations waived").
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from animedex.config import Settings
from animedex.guards import load_corpus
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.canonicalize import canonicalize
from animedex.store.canonical import CanonicalStore
from animedex.store.runlog import RunLog, new_run_id

STAGES = ("GATHER", "INTERPRET", "PROFILE", "VERIFY", "P2", "P3", "CHECK", "P4")   # gold: GATHER+INTERPRET; others: PROFILE
FAST_STAGES = ("PROFILE", "VERIFY", "P2", "P3", "CHECK", "P4")   # v1.10: the non-gold path (PROFILE = GATHER + INTERPRET)
PASS_STAGE = {"P1": "INTERPRET"}   # coverage records the profile pass as P1; INTERPRET writes that record


@dataclass
class BatchReport:
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    stopped: str | None = None
    canonical: dict[str, int] = field(default_factory=dict)
    calls: int = 0
    shadow_cost_usd: float = 0.0

    def lines(self) -> list[str]:
        out = []
        for stage, s in self.stages.items():
            bits = [f"{len(s['done'])} done"]
            for key in ("quarantined", "failed", "refused", "skipped"):
                if s.get(key):
                    bits.append(f"{len(s[key])} {key}")
            if s.get("flags"):
                bits.append(f"{len(s['flags'])} flagged")
            if s.get("counts"):
                bits.append(", ".join(f"{k} {v}" for k, v in sorted(s["counts"].items())))
            out.append(f"{stage}: " + "; ".join(bits))
        out.append(f"calls {self.calls}; reported plan cost ${self.shadow_cost_usd:.2f} (not billed)")
        if self.stopped:
            out.append(f"STOPPED: {self.stopped}")
        return out


def _state_done(paths: Paths) -> dict[str, set[str]]:
    """Titles already past each stage (from canonical records and pending candidates)."""
    state = CanonicalStore(paths).state()
    done: dict[str, set[str]] = {s: set() for s in STAGES}
    for c in state.get("coverage", []):
        for p in c.get("passes_done", []):
            p = PASS_STAGE.get(p, p)
            if p in done:
                done[p].add(c["title_id"])
    done["PROFILE"] = set()
    for t in state.get("title", []):  # a canonical profile is past GATHER, INTERPRET and VERIFY
        for stage in ("GATHER", "INTERPRET", "VERIFY", "PROFILE"):
            done[stage].add(t["title_id"])
    for f in (paths.candidates / "gathered").glob("*.json"):
        done["GATHER"].add(f.stem)
    for f in (paths.candidates / "title").glob("*.jsonl"):
        done["INTERPRET"].add(f.stem)
        done["PROFILE"].add(f.stem)
    return done


def _merge(into: Any, res: Any) -> None:
    """Fold one worker's result into the stage's (PROFILE, GATHER and VERIFY report `titles`, not `done`)."""
    into.done.extend(_done_ids(res))
    for key in ("quarantined", "failed", "refused", "skipped", "flags"):
        getattr(into, key).extend(getattr(res, key, []) or [])
    for k, v in (getattr(res, "counts", {}) or {}).items():
        into.counts[k] = into.counts.get(k, 0) + v
    if getattr(res, "stopped", None) and not into.stopped:
        into.stopped = res.stopped


def _locked(fn: Callable[..., Any] | None) -> Callable[..., Any] | None:
    """One catalog / reception call at a time across the workers (the clients pace themselves per client)."""
    if fn is None:
        return None
    lock = threading.Lock()

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with lock:
            return fn(*args, **kwargs)
    return wrapped


def _done_ids(result: Any) -> list[str]:
    if getattr(result, "done", None):
        return list(result.done)
    out = []
    for t in getattr(result, "titles", []) or []:  # P1 returns records, VERIFY returns per-title results
        out.append(t["title_id"] if isinstance(t, dict) else t.title_id)
    return out


def _summ(result: Any) -> dict[str, Any]:
    return {"done": _done_ids(result)} | {k: getattr(result, k, []) for k in (
        "quarantined", "failed", "refused", "skipped", "flags")} | {"counts": dict(getattr(result, "counts", {}) or {})}


def cli_reception(paths: Paths, env: dict[str, str]) -> Callable[[Any], tuple[Any, list[str]]]:
    """The API reception source the `gather` command uses (AniList + the reception APIs; owner rule A2)."""
    from animedex.catalog.anilist import AniList
    from animedex.catalog.reception import ReceptionClient, reception_for

    anilist = AniList(cache_dir=paths.cache / "anilist")
    rec_client = ReceptionClient.from_env(paths, env)

    def reception(entry: Any) -> tuple[Any, list[str]]:
        rec_client.notes.clear()
        return reception_for(entry, anilist=anilist, client=rec_client), list(rec_client.notes)
    return reception


def cli_adaptation(paths: Paths) -> Callable[[Any], dict[str, Any] | None]:
    """The screen-adaptation source for print titles (v1.9): the catalog's relations."""
    from animedex.catalog.anilist import AniList
    from animedex.catalog.resolve import adaptation_for

    anilist = AniList(cache_dir=paths.cache / "anilist")
    return lambda entry: adaptation_for(entry, anilist)


def run_batch(paths: Paths, title_ids: list[str], settings: Settings, env: dict[str, str], vocab: Vocab, *,
              stages: tuple[str, ...] = STAGES, clients: Callable[[str, RunLog], Any] | None = None,
              search: Any = "auto", reception: Any = "auto", echo: Callable[[str], None] = lambda s: None
              ) -> BatchReport:
    """`clients(model_key, runlog)` builds an LLMClient (tests pass mocks); `search` and `reception` default
    to the config and the API sources (tests pass None)."""
    from animedex.budget import Budget
    from animedex.pipeline.check import run_check
    from animedex.pipeline.common import StageResult
    from animedex.pipeline.gather import run_gather
    from animedex.pipeline.interpret import run_interpret
    from animedex.pipeline.p2 import run_p2
    from animedex.pipeline.p3 import run_p3
    from animedex.pipeline.p4 import run_p4
    from animedex.pipeline.profile import run_profile
    from animedex.pipeline.verify import run_verify
    from animedex.providers.factory import build_client
    from animedex.search.web import build_search

    report = BatchReport()
    corpus = load_corpus(paths)
    shared = None if clients else Budget.from_settings(settings)   # one cap for the whole run, across workers
    make = clients or (lambda key, runlog: build_client(key, paths=paths, settings=settings, env=env,
                                                          runlog=runlog, prompt_version="unset", budget=shared))
    logs: list[RunLog] = []
    speed = (settings.model_extra or {}).get("speed") or {}
    # the fast path, unless the caller asked for the classic gather/interpret stages by name (tests, `animedex run`)
    fast_on = bool(speed.get("merged_profile", False)) and ("PROFILE" in stages or not ({"GATHER", "INTERPRET"} & set(stages)))
    workers = max(1, int(speed.get("parallel_titles", 1)))
    fast_params = {"effort": str(speed.get("effort", "medium"))}
    check_batch = max(1, int(speed.get("check_batch_titles", 1)))

    def client_for(key: str) -> Any:
        runlog = RunLog(paths.raw_runs, new_run_id())
        logs.append(runlog)
        return make(key, runlog)

    def canon(label: str) -> None:
        res = canonicalize(paths, new_run_id())
        for rtype, keys in res.written.items():
            report.canonical[rtype] = report.canonical.get(rtype, 0) + len(keys)
        if res.quarantined:
            report.stages.setdefault(f"canonicalize ({label})", {"done": [], "quarantined": res.quarantined})

    def stage(name: str, fn: Callable[..., Any], ids: list[str], key: str, **kw: Any) -> bool:
        if name not in stages or not ids:
            return True
        echo(f"{name}: {len(ids)} title(s)")
        result = fn(**kw, client=client_for(key), run_id=new_run_id())
        report.stages[name] = _summ(result)
        if result.stopped:
            report.stopped = f"{name}: {result.stopped}"
            return False
        return True

    def parallel(name: str, items: list[Any], key: str, one: Callable[[Any, Any, str], Any]) -> bool:
        """The fast path's stage: `one(item, client, run_id)` for each item, `workers` at a time."""
        if name not in stages or not items:
            return True
        echo(f"{name}: {len(items)} item(s), {min(workers, len(items))} at once")
        merged = StageResult()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(lambda item: one(item, client_for(key), new_run_id()), items):
                _merge(merged, res)
        report.stages[name] = _summ(merged)
        if merged.stopped:
            report.stopped = f"{name}: {merged.stopped}"
            return False
        return True

    all_ids = [t for t in title_ids if t in corpus]
    fast = [t for t in all_ids if fast_on and "gold" not in corpus[t].role_tags]
    ids = [t for t in all_ids if t not in fast]   # gold titles (or every title when the speed pass is off)
    done = _state_done(paths)
    ok = True
    if fast:  # ---- the speed pass (non-gold titles)
        todo = [t for t in fast if t not in done["PROFILE"]]
        live_sources = reception == "auto" and todo and "PROFILE" in stages
        rec = _locked(cli_reception(paths, env)) if live_sources else (None if reception == "auto" else _locked(reception))
        adapt = _locked(cli_adaptation(paths)) if live_sources else None
        ok = parallel("PROFILE", todo, "profile", lambda t, client, run_id: run_profile(
            paths, [corpus[t]], client, vocab, settings, run_id=run_id, reception=rec, adaptation=adapt, params=fast_params))
        retry = [t for t, _ in report.stages.get("PROFILE", {}).get("quarantined", []) if t in todo]
        if ok and retry:  # one fresh run for quarantined titles (a new run, not a second repair)
            first = report.stages.pop("PROFILE")
            ok = parallel("PROFILE", retry, "profile", lambda t, client, run_id: run_profile(
                paths, [corpus[t]], client, vocab, settings, run_id=run_id, reception=rec, adaptation=adapt,
                params={**fast_params, "attempt_run": 2}))
            again = report.stages.get("PROFILE", {})
            report.stages["PROFILE"] = {**first, "done": first["done"] + again.get("done", []),
                                        "quarantined": again.get("quarantined", []),
                                        "counts": {**first.get("counts", {}), "retried": len(retry)}}
        if ok and "VERIFY" in stages:
            pending = [t for t in fast if (paths.candidates / "verify" / f"{t}.json").is_file()]
            engine = build_search(settings, env) if search == "auto" else search
            ok = parallel("VERIFY", pending, "verify", lambda t, client, run_id: run_verify(
                paths, [corpus[t]], client, engine, vocab, settings, run_id=run_id))
        canon("PROFILE/VERIFY")
        if ok:
            done = _state_done(paths)
            need = [t for t in fast if t in done["INTERPRET"] and t not in done["P2"]]
            ok = parallel("P2", need, "p2", lambda t, client, run_id: run_p2(
                paths, [t], client, vocab, settings, run_id=run_id, params=fast_params))
        if ok:
            with_atoms = [t for t in fast if (paths.candidates / "mechanism" / f"{t}.jsonl").is_file()
                          and not (paths.candidates / "proof" / f"{t}.jsonl").is_file()]
            ok = parallel("P3", with_atoms, "p3", lambda t, client, run_id: run_p3(
                paths, [t], client, vocab, settings, run_id=run_id, params=fast_params))
        if ok:
            proved = [t for t in fast if (paths.candidates / "proof" / f"{t}.jsonl").is_file()
                      and not (paths.candidates / "check" / f"{t}.jsonl").is_file()]
            groups = [proved[i:i + check_batch] for i in range(0, len(proved), check_batch)]
            ok = parallel("CHECK", groups, "check", lambda g, client, run_id: run_check(
                paths, g, client, vocab, settings, run_id=run_id, params=fast_params, batch_titles=len(g)))
        canon("CHECK")
        if ok:
            done = _state_done(paths)
            need = [t for t in fast if t in done["CHECK"] and t not in done["P4"]]
            ok = parallel("P4", need, "p4", lambda t, client, run_id: run_p4(
                paths, [t], client, vocab, settings, run_id=run_id, params=fast_params))
            canon("P4")
        if ok:
            done = _state_done(paths)
    if not ok or not ids:
        for log in logs:
            log.write_ledger()
            report.calls += sum(v["calls"] for v in log.tokens.values())
            report.shadow_cost_usd += sum(log.shadow_cost.values())
        return report
    # ---- the full path (gold titles, or every title when the speed pass is off)
    todo_gather = [t for t in ids if t not in done["GATHER"] and t not in done["INTERPRET"]]
    live_sources = reception == "auto" and todo_gather and "GATHER" in stages
    rec = cli_reception(paths, env) if live_sources else reception
    adapt = cli_adaptation(paths) if live_sources else None
    ok = stage("GATHER", lambda client, run_id: run_gather(paths, [corpus[t] for t in todo_gather], client, vocab,
                                                           settings, run_id=run_id, reception=None if rec == "auto" else rec,
                                                           adaptation=adapt),
               todo_gather, "gather")
    if ok:
        gathered = {f.stem for f in (paths.candidates / "gathered").glob("*.json")}
        todo = [t for t in ids if t not in done["INTERPRET"] and t in gathered]
        ok = stage("INTERPRET", lambda client, run_id: run_interpret(paths, [corpus[t] for t in todo], client, vocab,
                                                                     settings, run_id=run_id), todo, "interpret")
        retry = [t for t, _ in report.stages.get("INTERPRET", {}).get("quarantined", [])]
        if ok and retry:  # one fresh run for quarantined titles (a new run, not a second repair)
            first = report.stages.pop("INTERPRET")
            ok = stage("INTERPRET", lambda client, run_id: run_interpret(paths, [corpus[t] for t in retry], client,
                                                                         vocab, settings, run_id=run_id,
                                                                         params={"attempt_run": 2}), retry, "interpret")
            again = report.stages.get("INTERPRET", {})
            report.stages["INTERPRET"] = {**first, "done": first["done"] + again.get("done", []),
                                          "quarantined": again.get("quarantined", []),
                                          "counts": {**first.get("counts", {}), "retried": len(retry)}}
    if ok and "VERIFY" in stages:
        pending = [t for t in ids if (paths.candidates / "verify" / f"{t}.json").is_file()]
        engine = build_search(settings, env) if search == "auto" else search
        ok = stage("VERIFY", lambda client, run_id: run_verify(paths, [corpus[t] for t in pending], client, engine,
                                                               vocab, settings, run_id=run_id), pending, "verify")
        retry_v = [t for t, _ in report.stages.get("VERIFY", {}).get("quarantined", [])]
        if ok and retry_v:  # one fresh run for quarantined titles (their P1 candidates are still in place)
            first = report.stages.pop("VERIFY")
            ok = stage("VERIFY", lambda client, run_id: run_verify(paths, [corpus[t] for t in retry_v], client, engine,
                                                                   vocab, settings, run_id=run_id), retry_v, "verify")
            again = report.stages.get("VERIFY", {})
            report.stages["VERIFY"] = {**first, "done": first["done"] + again.get("done", []),
                                       "quarantined": again.get("quarantined", []),
                                       "counts": {**first.get("counts", {}), "retried": len(retry_v)}}
    canon("INTERPRET/VERIFY")
    if ok:
        done = _state_done(paths)
        need = [t for t in ids if t in done["INTERPRET"] and t not in done["P2"]]
        ok = stage("P2", lambda client, run_id: run_p2(paths, need, client, vocab, settings, run_id=run_id), need, "p2")
    if ok:
        with_atoms = [t for t in ids if (paths.candidates / "mechanism" / f"{t}.jsonl").is_file()
                      and not (paths.candidates / "proof" / f"{t}.jsonl").is_file()]
        ok = stage("P3", lambda client, run_id: run_p3(paths, with_atoms, client, vocab, settings, run_id=run_id),
                   with_atoms, "p3")
    if ok:
        proved = [t for t in ids if (paths.candidates / "proof" / f"{t}.jsonl").is_file()
                  and not (paths.candidates / "check" / f"{t}.jsonl").is_file()]
        ok = stage("CHECK", lambda client, run_id: run_check(paths, proved, client, vocab, settings, run_id=run_id),
                   proved, "check")
    canon("CHECK")
    if ok:
        done = _state_done(paths)
        need = [t for t in ids if t in done["CHECK"] and t not in done["P4"]]
        ok = stage("P4", lambda client, run_id: run_p4(paths, need, client, vocab, settings, run_id=run_id), need, "p4")
        canon("P4")
    for log in logs:
        log.write_ledger()
        report.calls += sum(v["calls"] for v in log.tokens.values())
        report.shadow_cost_usd += sum(log.shadow_cost.values())
    return report
