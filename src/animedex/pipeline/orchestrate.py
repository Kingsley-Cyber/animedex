"""Run titles through the whole pipeline, stage by stage, skipping work that is already canonical.

P1 -> VERIFY -> CANONICALIZE -> P2 -> P3 -> CHECK -> CANONICALIZE -> P4 -> CANONICALIZE

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

STAGES = ("P1", "VERIFY", "P2", "P3", "CHECK", "P4")


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
            if p in done:
                done[p].add(c["title_id"])
    for t in state.get("title", []):
        done["P1"].add(t["title_id"])
    return done


def _summ(result: Any) -> dict[str, Any]:
    return {k: getattr(result, k, []) for k in ("done", "quarantined", "failed", "refused", "skipped", "flags")} | {
        "counts": dict(getattr(result, "counts", {}) or {})}


def run_batch(paths: Paths, title_ids: list[str], settings: Settings, env: dict[str, str], vocab: Vocab, *,
              stages: tuple[str, ...] = STAGES, clients: Callable[[str, RunLog], Any] | None = None,
              search: Any = "auto", echo: Callable[[str], None] = lambda s: None) -> BatchReport:
    """`clients(model_key, runlog)` builds an LLMClient (tests pass mocks); `search` defaults to config."""
    from animedex.pipeline.check import run_check
    from animedex.pipeline.p1 import run_p1
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
    todo = [t for t in ids if t not in done["P1"]]
    ok = stage("P1", lambda client, run_id: run_p1(paths, [corpus[t] for t in todo], client, vocab, settings,
                                                     run_id=run_id), todo, "p1")
    if ok and "VERIFY" in stages:
        pending = [t for t in todo if (paths.candidates / "verify" / f"{t}.json").is_file()]
        engine = build_search(settings, env) if search == "auto" else search
        ok = stage("VERIFY", lambda client, run_id: run_verify(paths, [corpus[t] for t in pending], client, engine,
                                                               vocab, settings, run_id=run_id), pending, "verify")
    canon("P1/VERIFY")
    if ok:
        done = _state_done(paths)
        need = [t for t in ids if t in done["P1"] and t not in done["P2"]]
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
