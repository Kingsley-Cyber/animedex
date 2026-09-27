"""Operate ANIMEDEX from a chat harness (request A, "operate" scope; D-045).

A harness that talks to the MCP server can start the long commands (`backfill`, `ideate`, `diagnose`,
`census`) detached, one at a time, and read their progress. The server itself still calls no model: the
launched command does, under the owner's instruction, with the same caps and logs as the CLI. Only one
job runs at a time (a batch started with `make batch` counts), because every pipeline stage writes the
same canonical data.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animedex.batch import animedex_command, pid_alive, running_pid
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

KINDS = {"backfill": "add titles and run the full pipeline", "ideas": "one ideation run (60 calls)",
         "diagnose": "check one concept (3 calls)", "census": "count the top titles (counts only)"}
Launcher = Callable[[list[str], Path], Any]   # (command, log file) -> an object with .pid


class JobRunning(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def jobs_dir(paths: Paths) -> Path:
    return paths.root / "data" / "jobs"


def live_file(paths: Paths) -> Path:
    return jobs_dir(paths) / "live.json"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(pid: Any) -> bool:
    """Is the job's process still running? A child of this process that has exited is reaped here, so it
    never lingers as a zombie that `kill -0` would still count as alive."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass  # not our child (another server session started it): fall back to the signal probe
    return pid_alive(pid)


def live_job(paths: Paths) -> dict[str, Any] | None:
    """The running job, or None. A job whose process is gone is moved to last.json on the way."""
    info = _read(live_file(paths))
    if info is None:
        return None
    if _alive(info.get("pid")):
        return info
    info["finished_at"] = info.get("finished_at") or _now()
    atomic_write_text(jobs_dir(paths) / "last.json", json.dumps(info, indent=2) + "\n")
    live_file(paths).unlink(missing_ok=True)
    return None


def running_batch(paths: Paths) -> str | None:
    """The name of a `make batch` run that is still alive, if any (its pid file under build/status/)."""
    folder = paths.root / "build" / "status"
    for f in sorted(folder.glob("*.pid")) if folder.is_dir() else []:
        if running_pid(paths, f.stem) is not None:
            return f.stem
    return None


def _launch(cmd: list[str], log: Path) -> subprocess.Popen:
    awake = shutil.which("caffeinate")  # macOS: no idle sleep while a job runs
    if awake:
        cmd = [awake, "-i", *cmd]
    with log.open("a", encoding="utf-8") as out:
        return subprocess.Popen(cmd, cwd=str(log.parents[2]), stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)


def start_job(paths: Paths, kind: str, argv: list[str], *, note: str = "", launcher: Launcher | None = None
              ) -> dict[str, Any]:
    """Start `animedex <argv>` detached and record it as the live job. Refuses while another job or a
    batch is running: the stages all write the canonical data."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}; one of {sorted(KINDS)}")
    live = live_job(paths)
    if live is not None:
        raise JobRunning(f"{live['kind']} job {live['job_id']} is still running (process {live['pid']}); "
                         "wait for it or stop it first")
    batch = running_batch(paths)
    if batch is not None:
        raise JobRunning(f"batch {batch} is running (make status NAME={batch}); wait for it first")
    job_id = f"{kind}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    log = jobs_dir(paths) / f"{job_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [*animedex_command(), *argv]
    with log.open("a", encoding="utf-8") as out:
        out.write(f"== {_now()}  {' '.join(argv)}\n")
    proc = (launcher or _launch)(cmd, log)
    info = {"job_id": job_id, "kind": kind, "pid": int(proc.pid), "command": argv, "note": note,
            "started_at": _now(), "finished_at": None, "log": str(log.relative_to(paths.root))}
    atomic_write_text(live_file(paths), json.dumps(info, indent=2) + "\n")
    return info


def stop_job(paths: Paths) -> dict[str, Any] | None:
    """Stop the live job (its whole process group). Finished calls stay cached; a rerun continues."""
    live = live_job(paths)
    if live is None:
        return None
    try:
        os.killpg(os.getpgid(live["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    live["finished_at"], live["stopped"] = _now(), True
    atomic_write_text(jobs_dir(paths) / "last.json", json.dumps(live, indent=2) + "\n")
    live_file(paths).unlink(missing_ok=True)
    return live


def log_tail(paths: Paths, info: dict[str, Any] | None, lines: int = 20) -> list[str]:
    if not info:
        return []
    try:
        return (paths.root / info["log"]).read_text(encoding="utf-8").splitlines()[-lines:]
    except OSError:
        return []


def job_status(paths: Paths) -> dict[str, Any]:
    """The live job with the tail of its log, the last finished job, and every batch status page's head."""
    live = live_job(paths)
    last = _read(jobs_dir(paths) / "last.json")
    folder = paths.root / "build" / "status"
    batches = []
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        head = f.read_text(encoding="utf-8").splitlines()[:6]
        batches.append({"name": f.stem, "summary": [line for line in head if line.strip()]})
    return {"live": live, "live_log": log_tail(paths, live), "last": last, "last_log": log_tail(paths, last, 12),
            "batches": batches, "running_batch": running_batch(paths)}


# ---------------------------------------------------------------- titles
def queue_file(paths: Paths, titles: list[str]) -> Path:
    folder = paths.root / "data" / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"add_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.txt"
    f.write_text("# added through the MCP server\n" + "\n".join(titles) + "\n", encoding="utf-8")
    return f


def resolve_titles(paths: Paths, titles: list[str], *, catalog: Any = None) -> dict[str, Any]:
    """What `backfill` would pick for each line, without writing anything: the version, its scope, and
    the other matches, plus the lines already in the corpus and the ones the catalog can't find."""
    from animedex.catalog.anilist import AniList
    from animedex.catalog.backfill import plan_backfill
    from animedex.guards import load_corpus

    cat = catalog or AniList(cache_dir=paths.cache / "anilist")
    plan = plan_backfill(cat, titles, load_corpus(paths), suggest=False)
    picks = []
    for r in plan.new:
        e = r.entry
        picks.append({"line": getattr(r, "line", e["title"]), "title_id": e["title_id"], "title": e["title"],
                      "year": e.get("year"), "medium": e["medium"], "scope": (e.get("scope") or {}).get("version"),
                      "seasons": (e.get("scope") or {}).get("seasons"), "how": getattr(r, "how", ""),
                      "other_matches": [str(o) for o in (getattr(r, "others", None) or [])][:3]})
    return {"picks": picks, "already_in_corpus": [{"line": line, "why": why} for line, why in plan.skipped],
            "not_found": list(getattr(plan, "unresolved", []) or []), "warnings": list(plan.warnings)}


def add_titles(paths: Paths, titles: list[str], *, run: bool = True, catalog: Any = None,
               launcher: Launcher | None = None) -> dict[str, Any]:
    """Resolve the lines; with `run`, write them to a queue file and start the backfill on it. A line with
    the year in parentheses uses that version; otherwise the most-watched adaptation is picked."""
    clean = [" ".join(t.split()) for t in titles if t and t.strip() and not t.strip().startswith("#")]
    if not clean:
        raise ValueError("give at least one title, e.g. 'Levius (2019)'")
    resolved = resolve_titles(paths, clean, catalog=catalog)
    if not run:
        return {**resolved, "started": None}
    if not resolved["picks"]:
        return {**resolved, "started": None, "note": "nothing new to index"}
    f = queue_file(paths, clean)
    job = start_job(paths, "backfill", ["backfill", "--list", str(f.relative_to(paths.root))],
                    note=f"{len(resolved['picks'])} title(s)", launcher=launcher)
    return {**resolved, "started": job, "list": str(f.relative_to(paths.root))}
