"""Run titles through the whole pipeline, stage by stage, skipping work that is already canonical.

GATHER -> INTERPRET -> VERIFY -> CANONICALIZE -> P2 -> P3 -> CHECK -> CANONICALIZE -> P4 -> CANONICALIZE
(gather-first since v1.7, D-042: the recall-first P1 path is no longer run)

A batch moves one stage at a time across all its titles, so partners are canonical before P3
needs them. A usage limit, an expired login, or a budget cap stops the batch cleanly: finished
calls are cached and a rerun picks up where it stopped. Output is counts only (owner ruling:
never show gold-title outputs before "annotations done"/"annotations waived").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from animedex.config import Settings
from animedex.guards import load_corpus
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.canonicalize import canonicalize
from animedex.store.canonical import CanonicalStore
from animedex.store.runlog import RunLog, new_run_id

STAGES = ("GATHER", "INTERPRET", "VERIFY", "P2", "P3", "CHECK", "P4")
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
    for t in state.get("title", []):  # a canonical profile is past GATHER, INTERPRET and VERIFY
        for stage in ("GATHER", "INTERPRET", "VERIFY"):
            done[stage].add(t["title_id"])
    for f in (paths.candidates / "gathered").glob("*.json"):
        done["GATHER"].add(f.stem)
    for f in (paths.candidates / "title").glob("*.jsonl"):
        done["INTERPRET"].add(f.stem)
    return done


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
    from animedex.pipeline.check import run_check
    from animedex.pipeline.gather import run_gather
    from animedex.pipeline.interpret import run_interpret
    from animedex.pipeline.p2 import run_p2
    from animedex.pipeline.p3 import run_p3
    from animedex.pipeline.p4 import run_p4
    from animedex.pipeline.verify import run_verify
    from animedex.providers.factory import build_client
    from animedex.search.web import build_search

    report = BatchReport()
    corpus = load_corpus(paths)
    make = clients or (lambda key, runlog: build_client(key, paths=paths, settings=settings, env=env,
                                                          runlog=runlog, prompt_version="unset"))
    logs: list[RunLog] = []

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

    ids = [t for t in title_ids if t in corpus]
    done = _state_done(paths)
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
