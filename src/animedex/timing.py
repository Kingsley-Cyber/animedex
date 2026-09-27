"""Where pipeline time goes (owner request 2026-09-27), read from the run logs.

Each live call row carries `timing` (since per-stage timing landed): the call's wall time split into
startup (spawn to the CLI's init event), model, web (WebSearch/WebFetch in flight), tools and other
(result and shutdown), plus the pacing slept before it. Older rows have no timing: their total is
estimated from log timestamps (the gap since the previous row, or since the run started) and they
carry no breakdown. Retries are repair attempts (attempt > 0) and P1 length repairs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animedex.store.jsonl import read_jsonl

PARTS = ("startup_s", "model_s", "web_s", "tools_s", "other_s")
LABELS = {"startup_s": "Startup", "model_s": "Model", "web_s": "Web", "tools_s": "Tools", "other_s": "Other"}


@dataclass
class CallTime:
    run: str
    stage: str
    title: str
    seconds: float
    retry: bool
    estimated: bool
    pacing: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)


def run_started(run_id: str) -> datetime | None:
    """Run ids are `run_YYYYMMDD_HHMMSS_micro` in UTC."""
    try:
        return datetime.strptime(run_id[4:19], "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def load_calls(runs_dir: Path) -> list[CallTime]:
    out: list[CallTime] = []
    for run in sorted(p for p in runs_dir.glob("run_*") if (p / "calls.jsonl").is_file()):
        prev = run_started(run.name)
        for row in sorted(read_jsonl(run / "calls.jsonl"), key=lambda r: r["ts"]):
            ts = datetime.fromisoformat(row["ts"])
            timing = row.get("timing") or {}
            gap = (ts - prev).total_seconds() if prev else None
            prev = ts
            if row.get("cache_hit") or row.get("provider") == "mock":
                continue
            record = str(row.get("record_id") or "")
            shorten = record.endswith(".shorten")
            seconds = timing.get("call_s") if "call_s" in timing else gap
            if seconds is None:
                continue
            out.append(CallTime(run=run.name, stage=str(row.get("pass")), title=record.removesuffix(".shorten"),
                                seconds=float(seconds), retry=shorten or int(row.get("attempt") or 0) > 0,
                                estimated="call_s" not in timing, pacing=float(timing.get("pacing_s") or 0.0),
                                parts={k: float(timing[k]) for k in PARTS if k in timing}))
    return out


def fmt(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def report(calls: list[CallTime]) -> str:
    """Markdown: by stage, then by title. Only timings appear here, never outputs, so gold titles are
    listed like any other (blind rule: counts only)."""
    if not calls:
        return "# Where the time goes\n\nNo live calls logged yet.\n"
    est = sum(c.estimated for c in calls)
    lines = ["# Where the time goes", "",
             f"{len(calls)} live model calls in {len({c.run for c in calls})} runs. "
             f"{est} are estimated from log timestamps (calls made before per-stage timing): their totals "
             "include pacing and process startup, and they have no breakdown.", "",
             "## By stage", "",
             "| Stage | Calls | Total | Per call | " + " | ".join(LABELS.values()) + " | Pacing | Retries |",
             "|---|---|---|---|" + "---|" * (len(PARTS) + 2)]
    by_stage: dict[str, list[CallTime]] = defaultdict(list)
    for c in calls:
        by_stage[c.stage].append(c)
    for stage in sorted(by_stage):
        cs = by_stage[stage]
        total = sum(c.seconds for c in cs)
        timed = [c for c in cs if c.parts]
        cells = [fmt(sum(c.parts.get(k, 0.0) for c in timed)) if timed else "—" for k in PARTS]
        retries = [c for c in cs if c.retry]
        lines.append(f"| {stage} | {len(cs)} | {fmt(total)} | {fmt(total / len(cs))} | " + " | ".join(cells)
                     + f" | {fmt(sum(c.pacing for c in cs))} | {len(retries)} ({fmt(sum(c.seconds for c in retries))}) |")
    lines += ["", "Breakdown columns cover only calls with per-stage timing.", "",
              "## By title", "", "| Title | " + " | ".join(sorted(by_stage)) + " | Retries | Total |",
              "|---|" + "---|" * (len(by_stage) + 2)]
    titles: dict[str, list[CallTime]] = defaultdict(list)
    for c in calls:
        titles[c.title].append(c)
    for title in sorted(titles, key=lambda t: -sum(c.seconds for c in titles[t])):
        cs = titles[title]
        per = [fmt(sum(c.seconds for c in cs if c.stage == s)) if any(c.stage == s for c in cs) else "—"
               for s in sorted(by_stage)]
        retries = [c for c in cs if c.retry]
        lines.append(f"| {title} | " + " | ".join(per)
                     + f" | {len(retries)} ({fmt(sum(c.seconds for c in retries))}) | {fmt(sum(c.seconds for c in cs))} |")
    lines += ["", "Startup: launch until the CLI is ready. Model: waiting on the model. Web: searches and page "
              "fetches in flight. Other: the final answer and shutdown. Pacing: the gap kept between calls. "
              "Retries: repair attempts and P1 length repairs (count, time).", ""]
    return "\n".join(lines)


def write_report(runs_dir: Path, out: Path) -> tuple[Path, list[CallTime]]:
    from animedex.store.atomic import atomic_write_text

    calls = load_calls(runs_dir)
    atomic_write_text(out, report(calls))
    return out, calls


def summary(calls: list[CallTime]) -> dict[str, Any]:
    """Machine-readable totals by stage (for reports and comparisons, e.g. v1.7 gather-first)."""
    out: dict[str, Any] = {}
    for c in calls:
        s = out.setdefault(c.stage, {"calls": 0, "seconds": 0.0, "estimated": 0, "retries": 0,
                                     **{k: 0.0 for k in PARTS}, "pacing_s": 0.0})
        s["calls"] += 1
        s["seconds"] += c.seconds
        s["estimated"] += c.estimated
        s["retries"] += c.retry
        s["pacing_s"] += c.pacing
        for k, v in c.parts.items():
            s[k] += v
    return {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in out.items()}
