"""Batch runs (owner request): long per-title pipeline work that runs in the background.

A batch file (YAML) names the batch and lists jobs: a title and its steps, e.g. `p1` then `verify`.
Each step is one `animedex <step> --title <title>` call from the repo root. Up to three titles run
at once (owner rule); the steps of one title run in order. At every step start and finish the run
rewrites build/status/<name>.md (plain words) and <name>.json (what a rerun resumes from); each
title's output is appended to build/logs/<name>/<title>.log.

A plan limit, budget cap or expired login (a `stopped:` line, or the CLI's exit code 3) pauses the
batch: steps already running finish and nothing new starts. Running the same batch again skips the
steps that are done and continues each title from its first step that is not.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

MAX_PARALLEL = 3  # owner rule: never more than three titles at once
EXIT_DONE, EXIT_FAILURES, EXIT_REFUSED, EXIT_PAUSED = 0, 1, 2, 3  # 3 = paused, as for `run` and `ideate`
# batch states
RUNNING, PAUSED, DONE, DONE_WITH_FAILURES, FAILED_TO_START = (
    "running", "paused", "done", "done with failures", "failed to start")
# step states (plus RUNNING, PAUSED, DONE)
PENDING, FAILED, SKIPPED = "pending", "failed", "skipped"
TAIL_LINES = 2
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")  # batch names and title ids become file names
# Lines the CLI prints for a title it could not finish while still exiting 0 (P1, VERIFY, P2-P4).
FAILURE_LABELS = ("not written", "not verified", "not replayed", "refused", "quarantined", "failed")

Executor = Callable[[list[str]], tuple[int, str]]
Echo = Callable[[str], None]


class BatchError(ValueError):
    """A batch file the runner cannot use. `name` is set when the file does name its batch."""

    def __init__(self, message: str, name: str | None = None):
        super().__init__(message)
        self.name = name


class BatchRunning(RuntimeError):
    """A batch with this name is already running."""


@dataclass(frozen=True)
class Job:
    title: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Batch:
    name: str
    file: Path
    jobs: tuple[Job, ...]
    max_parallel: int = 1
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------- batch file
def load_batch(path: Path | str) -> Batch:
    """Read and check a batch file; every problem is a BatchError in plain words."""
    path = Path(path)
    if not path.is_file():
        raise BatchError(f"batch file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BatchError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise BatchError(f"{path.name} needs `name:` and `jobs:` (see USAGE.md, Long runs)")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise BatchError(f"{path.name}: `name` must be letters, digits, _ . or - (got {name!r})")
    notes: list[str] = []
    most = raw.get("max_parallel", 1)
    if isinstance(most, bool) or not isinstance(most, int) or most < 1:
        raise BatchError(f"{path.name}: max_parallel must be a whole number from 1 to {MAX_PARALLEL}", name)
    if most > MAX_PARALLEL:
        notes.append(f"max_parallel {most} is above the limit; running {MAX_PARALLEL} titles at once")
        most = MAX_PARALLEL
    items = raw.get("jobs")
    if not isinstance(items, list) or not items:
        raise BatchError(f"{path.name}: `jobs` must list at least one title with its steps", name)
    jobs: list[Job] = []
    for n, item in enumerate(items, 1):
        where = f"{path.name} job {n}"
        title = item.get("title") if isinstance(item, dict) else None
        if not isinstance(title, str) or not NAME.fullmatch(title):
            raise BatchError(f"{where}: `title` must be a title id such as ironvale_circuit_2021 (got {title!r})",
                             name)
        if any(job.title == title for job in jobs):
            raise BatchError(f"{where}: {title} is already in another job; put all its steps in one job", name)
        steps = item.get("steps")
        if isinstance(steps, str):  # `steps: verify` is one step
            steps = [steps]
        if not isinstance(steps, list) or not steps:
            raise BatchError(f"{where} ({title}): `steps` must list at least one step, e.g. [verify]", name)
        jobs.append(Job(title, tuple(_check_step(step, f"{where} ({title})", name) for step in steps)))
    return Batch(name=name, file=path.resolve(), jobs=tuple(jobs), max_parallel=most, notes=tuple(notes))


def _check_step(step: Any, where: str, name: str) -> str:
    if not isinstance(step, str) or not step.strip():
        raise BatchError(f"{where}: each step must be text such as `verify` or `p1 --agreement`", name)
    try:
        words = shlex.split(step)
    except ValueError as exc:
        raise BatchError(f"{where}: cannot read step `{step}`: {exc}", name) from exc
    if words[0].startswith("-"):
        raise BatchError(f"{where}: step `{step}` must start with a command such as `verify`", name)
    if any(w in ("--title", "--all") or w.startswith("--title=") for w in words):
        raise BatchError(f"{where}: remove --title/--all from step `{step}`; the runner adds --title itself", name)
    return step.strip()


# ---------------------------------------------------------------- files
def status_path(paths: Paths, name: str, suffix: str = ".json") -> Path:
    return paths.build / "status" / f"{name}{suffix}"


def log_dir(paths: Paths, name: str) -> Path:
    return paths.build / "logs" / name


def resume_command(paths: Paths, file: Path | str) -> str:
    """What the owner types to continue: `make batch FILE=...`, relative to the repo root when inside it."""
    path = Path(file).resolve()
    try:
        shown: Path = path.relative_to(paths.root.resolve())
    except ValueError:
        shown = path
    return f"make batch FILE={shlex.quote(str(shown))}"


def read_status(paths: Paths, name: str) -> dict[str, Any] | None:
    try:
        data = json.loads(status_path(paths, name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_status(paths: Paths, data: dict[str, Any]) -> None:
    """Rewrite both status files, each atomically."""
    data["updated_at"] = _iso(_now())
    atomic_write_text(status_path(paths, data["name"]), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(status_path(paths, data["name"], ".md"), status_markdown(data))


def known_batches(paths: Paths) -> list[str]:
    """Names of batches with a status file, newest first."""
    folder = paths.build / "status"
    if not folder.is_dir():
        return []
    return [p.stem for p in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)]


def mark_failed_to_start(paths: Paths, name: str, file: Path | str, error: str) -> None:
    """Record why a batch did not start. Progress from an earlier run is kept for the resume."""
    if running_pid(paths, name) is not None:
        return  # never overwrite the status of a run that is going
    data = read_status(paths, name) or {"name": name, "jobs": []}
    data.update(name=name, state=FAILED_TO_START, error=error, resume_command=resume_command(paths, file),
                log_dir=str(log_dir(paths, name).relative_to(paths.root)))
    write_status(paths, data)


# ---------------------------------------------------------------- time and output
def _now() -> datetime:
    return datetime.now().astimezone()  # local time: the owner reads these


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _show(iso: str | None, fmt: str = "%a %d %b %H:%M") -> str:
    return datetime.fromisoformat(iso).strftime(fmt) if iso else "-"


def human_duration(seconds: float | None) -> str:
    """`6m 12s`; past an hour, `1h 02m`."""
    hours, rest = divmod(int(round(seconds or 0)), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def tail_lines(output: str, n: int = TAIL_LINES) -> list[str]:
    """The last n lines with words in them (rich panel borders carry none)."""
    lines = [line.strip() for line in output.splitlines() if any(ch.isalnum() for ch in line)]
    return [line if len(line) <= 200 else line[:197] + "..." for line in lines[-n:]]


def pause_reason(exit_code: int, output: str) -> str | None:
    """Why a step pauses the batch, else None: a `stopped:` line (plan limit, budget cap, expired
    login; `run` prints it as STOPPED:) or exit code 3, the CLI's "paused" (`run`, `ideate`)."""
    for line in output.splitlines():
        text = line.strip()
        if text.lower().startswith("stopped:"):
            return text[len("stopped:"):].strip() or "stopped"
    if exit_code == EXIT_PAUSED:
        last = tail_lines(output, 1)
        return last[0] if last else "paused (exit code 3)"
    return None


def failure_line(title: str, output: str) -> str | None:
    """The CLI's line for a title it could not finish (exit code 0), e.g. `not written <id>: ...`."""
    for line in output.splitlines():
        text = line.strip()
        if any(text.startswith(f"{label} {title}:") for label in FAILURE_LABELS):
            return text
    return None


# ---------------------------------------------------------------- running steps
def animedex_command() -> list[str]:
    """How a child process calls this CLI: the script next to this Python, else PATH, else the module."""
    script = Path(sys.executable).parent / "animedex"
    if script.is_file() and os.access(script, os.X_OK):
        return [str(script)]
    found = shutil.which("animedex")
    if found:
        return [found]
    return [sys.executable, "-c", "from animedex.cli import main; main()"]


def subprocess_executor(root: Path) -> Executor:
    """Run one step from the repo root; stdout and stderr come back as one text."""

    def run(argv: list[str]) -> tuple[int, str]:
        proc = subprocess.run(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", check=False)
        return proc.returncode, proc.stdout or ""

    return run


def _print(line: str) -> None:
    print(line, flush=True)  # flush: a detached run's log is a file


# ---------------------------------------------------------------- lock
def pid_alive(pid: Any) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, owned by another user
        return True
    except OSError:
        return False
    return True


def running_pid(paths: Paths, name: str) -> int | None:
    """The pid in the batch's lock file, when that process is alive."""
    try:
        pid = int(status_path(paths, name, ".pid").read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def _already_running(name: str, pid: int | None) -> str:
    who = f" (process {pid})" if pid else ""
    return (f"Batch {name} is already running{who}. Check progress: make status NAME={name}. "
            f"If it is not running, delete build/status/{name}.pid and try again.")


def _take_lock(paths: Paths, name: str) -> None:
    """Create build/status/<name>.pid, or raise BatchRunning while a live run holds it."""
    path = status_path(paths, name, ".pid")
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = running_pid(paths, name)
            if holder is not None or attempt:
                raise BatchRunning(_already_running(name, holder)) from None
            path.unlink(missing_ok=True)  # left by a run that died; its steps resume
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{os.getpid()}\n")
        return


def _release_lock(paths: Paths, name: str) -> None:
    path = status_path(paths, name, ".pid")
    try:
        mine = int(path.read_text().strip()) == os.getpid()
    except (FileNotFoundError, ValueError):
        return
    if mine:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------- resume
def _done_records(prior: dict[str, Any] | None) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    out: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for job in (prior or {}).get("jobs") or []:
        for rec in (job.get("steps") or []) if isinstance(job, dict) else []:
            if isinstance(rec, dict) and rec.get("status") == DONE:
                out[(job.get("title"), rec.get("index"), rec.get("step"))] = rec
    return out


def resume_points(batch: Batch, prior: dict[str, Any] | None) -> list[int]:
    """Per job, the index of its first step that is not done (len(steps) when all are). A step
    counts as done only when title, position and text match the earlier run."""
    done = _done_records(prior)
    points = []
    for job in batch.jobs:
        i = 0
        while i < len(job.steps) and (job.title, i, job.steps[i]) in done:
            i += 1
        points.append(i)
    return points


def remaining_steps(paths: Paths, batch: Batch) -> int:
    points = resume_points(batch, read_status(paths, batch.name))
    return sum(len(job.steps) - i for job, i in zip(batch.jobs, points, strict=True))


def _blank(index: int, step: str) -> dict[str, Any]:
    return {"index": index, "step": step, "status": PENDING, "started_at": None, "finished_at": None,
            "duration_s": None, "exit_code": None, "tail": [], "reason": None}


# ---------------------------------------------------------------- the run
class _Run:
    """One run of a batch. Worker threads share `data` (the status JSON) behind one lock."""

    def __init__(self, paths: Paths, batch: Batch, executor: Executor, echo: Echo):
        self.paths, self.batch, self.executor, self.echo = paths, batch, executor, echo
        self.command = animedex_command()
        self.lock = threading.Lock()
        self.pause = threading.Event()
        prior = read_status(paths, batch.name)
        done = _done_records(prior)
        self.points = resume_points(batch, prior)
        jobs = [{"title": job.title,
                 "steps": [dict(done[(job.title, i, step)]) if i < start else _blank(i, step)
                           for i, step in enumerate(job.steps)]}
                for job, start in zip(batch.jobs, self.points, strict=True)]
        now = _iso(_now())
        self.data: dict[str, Any] = {
            "name": batch.name, "state": RUNNING, "batch_file": str(batch.file), "max_parallel": batch.max_parallel,
            "pid": os.getpid(), "started_at": now, "updated_at": now, "finished_at": None,
            "resumed": any(self.points), "paused_reason": None, "paused_by": None, "error": None,
            "resume_command": resume_command(paths, batch.file),
            "log_dir": str(log_dir(paths, batch.name).relative_to(paths.root)), "notes": list(batch.notes),
            "jobs": jobs}

    def go(self) -> int:
        todo = [(j, start) for j, start in enumerate(self.points) if start < len(self.batch.jobs[j].steps)]
        total = sum(len(job.steps) for job in self.batch.jobs)
        already = total - sum(len(self.batch.jobs[j].steps) - start for j, start in todo)
        with self.lock:
            self._write()
        self.echo(f"batch {self.batch.name}: {total} step(s) for {len(self.batch.jobs)} title(s), "
                  f"up to {self.batch.max_parallel} at once" + (f"; {already} already done" if already else ""))
        if not todo:
            self.echo("nothing left to run: every step is done (give the batch a new name to run them again)")
        else:
            with ThreadPoolExecutor(max_workers=self.batch.max_parallel, thread_name_prefix="batch") as pool:
                futures = [pool.submit(self._job, j, start) for j, start in todo]
                while True:
                    try:
                        wait(futures)
                        break
                    except KeyboardInterrupt:  # Ctrl+C in a foreground run pauses like a plan limit
                        with self.lock:
                            self._pause("stopped by hand (Ctrl+C)")
                            self._write()
            for future in futures:
                future.result()
        return self._finish()

    def _job(self, j: int, start: int) -> None:
        steps = self.batch.jobs[j].steps
        for i in range(start, len(steps)):
            status = self._step(j, i)
            if status == FAILED:
                with self.lock:
                    for rec in self.data["jobs"][j]["steps"][i + 1:]:
                        rec.update(status=SKIPPED, reason=f"{steps[i]} failed")
                    self._write()
            if status != DONE:
                return

    def _step(self, j: int, i: int) -> str | None:
        """Run step i of job j and return its status; None when the batch is pausing (not started)."""
        title, step = self.batch.jobs[j].title, self.batch.jobs[j].steps[i]
        rec = self.data["jobs"][j]["steps"][i]
        with self.lock:
            if self.pause.is_set():
                return None
            rec.update(_blank(i, step), status=RUNNING, started_at=_iso(_now()))
            self._log(title, f"\n== {_show(rec['started_at'], '%Y-%m-%d %H:%M:%S')}  animedex {step} --title {title}\n")
            self.echo(f"start {title}: {step}")
            self._write()
        clock = time.monotonic()
        try:
            code, output = self.executor([*self.command, *shlex.split(step), "--title", title])
        except Exception as exc:  # a step that cannot even start fails like any other
            code, output = 1, f"could not run the step: {exc}"
        seconds = time.monotonic() - clock
        reason = pause_reason(code, output)
        found = None if reason else failure_line(title, output)
        why = found or (f"exit code {code}" if code and not reason else None)
        status = PAUSED if reason else FAILED if why else DONE
        tail = tail_lines(output)
        if found and found not in tail:
            tail = [found, *tail[-1:]]
        took = human_duration(seconds)
        with self.lock:
            rec.update(status=status, finished_at=_iso(_now()), duration_s=round(seconds, 1), exit_code=code,
                       tail=tail, reason=reason or why)
            self._log(title, output.rstrip("\n") + f"\n== {status} after {took} (exit code {code})\n")
            if reason:
                self.echo(f"PAUSED at {title}: {step} ({took}): {reason}")
                self._pause(reason, f"{title}: {step}")
            elif why:
                self.echo(f"FAILED {title}: {step} ({took}): {found or (tail[-1] if tail else why)}")
            else:
                self.echo(f"done {title}: {step} ({took})")
            self._write()
        return status

    def _pause(self, reason: str, by: str | None = None) -> None:
        """Stop starting steps; the caller holds the lock."""
        if self.pause.is_set():
            return
        self.pause.set()
        self.data.update(paused_reason=reason, paused_by=by)
        self.echo("pausing: steps already running may finish; nothing new starts")

    def _finish(self) -> int:
        with self.lock:
            steps = [rec for job in self.data["jobs"] for rec in job["steps"]]
            if self.pause.is_set():
                state, code = PAUSED, EXIT_PAUSED
            elif any(rec["status"] == FAILED for rec in steps):
                state, code = DONE_WITH_FAILURES, EXIT_FAILURES
            else:
                state, code = DONE, EXIT_DONE
            self.data.update(state=state, finished_at=_iso(_now()))
            self._write()
        md = status_path(self.paths, self.batch.name, ".md").relative_to(self.paths.root)
        self.echo(f"batch {self.batch.name}: {state}; {_progress(steps)}; status: {md}")
        backup = _backup(self.paths)
        if backup:
            self.echo(backup)
        if code:
            self.echo(f"to continue: {self.data['resume_command']}")
        return code

    def _write(self) -> None:
        write_status(self.paths, self.data)

    def _log(self, title: str, text: str) -> None:
        path = log_dir(self.paths, self.batch.name) / f"{title}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)


def _backup(paths: Paths) -> str | None:
    """Owner rule: push the private data backup after every batch run (once its clone exists)."""
    try:
        from animedex.config import load_settings
        from animedex.datarepo import push_after_batch

        return push_after_batch(paths, load_settings(paths))
    except Exception as exc:  # noqa: BLE001 - a backup problem never fails the batch
        return f"data backup skipped: {exc}"


def run_jobs(paths: Paths, batch: Batch, *, executor: Executor | None = None, echo: Echo | None = None) -> int:
    """Run (or resume) a batch in this process. Exit code: 0 done, 1 done with failures,
    2 refused (already running), 3 paused."""
    say = echo or _print
    try:
        _take_lock(paths, batch.name)
    except BatchRunning as exc:
        say(str(exc))
        return EXIT_REFUSED
    try:
        return _Run(paths, batch, executor or subprocess_executor(paths.root), say).go()
    finally:
        _release_lock(paths, batch.name)


def start_detached(paths: Paths, batch: Batch) -> subprocess.Popen:
    """Launch `animedex batch run <file>` in its own session, so it outlives this terminal and the chat."""
    holder = running_pid(paths, batch.name)
    if holder is not None:
        raise BatchRunning(_already_running(batch.name, holder))
    log = log_dir(paths, batch.name) / "batch.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [*animedex_command(), "batch", "run", str(batch.file)]
    awake = shutil.which("caffeinate")  # macOS: the computer does not idle to sleep while the batch runs
    if awake:
        cmd = [awake, "-i", *cmd]
    with log.open("a", encoding="utf-8") as out:
        out.write(f"\n== {_show(_iso(_now()), '%Y-%m-%d %H:%M:%S')}  batch start {batch.name}\n")
        out.flush()
        return subprocess.Popen(cmd, cwd=paths.root, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)


# ---------------------------------------------------------------- the status page
def _progress(steps: list[dict[str, Any]]) -> str:
    done = sum(rec.get("status") == DONE for rec in steps)
    failed = sum(rec.get("status") == FAILED for rec in steps)
    return f"{done} of {len(steps)} steps done" + (f", {failed} failed" if failed else "")


def status_markdown(data: dict[str, Any], now: datetime | None = None) -> str:
    """The plain-words status page. `now` (from `batch status`) adds how long running steps have run."""
    state = data.get("state", RUNNING)
    rows = [(job.get("title", "?"), rec) for job in data.get("jobs") or [] for rec in job.get("steps") or []]

    def having(*states: str) -> list[tuple[str, dict[str, Any]]]:
        return [(title, rec) for title, rec in rows if rec.get("status") in states]

    def listed(items: list[tuple[str, dict[str, Any]]]) -> list[str]:
        out = []
        for title, rec in items:
            out.append(f"- {title}: {rec.get('step')} ({human_duration(rec.get('duration_s'))})")
            out += [f"  > {line}" for line in rec.get("tail") or []]
            skipped = [r.get("step") for t, r in having(SKIPPED) if t == title]
            if rec.get("status") == FAILED and skipped:
                out.append(f"  Skipped because of this: {', '.join(skipped)}")
        return out

    resume = data.get("resume_command") or "make batch FILE=<batch file>"
    out = [f"# Batch {data.get('name', '?')}: {state}", ""]
    if state != FAILED_TO_START and data.get("started_at"):
        again = " (continued from an earlier run)" if data.get("resumed") else ""
        out.append(f"- Started: {_show(data['started_at'])}{again}")
    out.append(f"- Updated: {_show(data.get('updated_at'))}")
    if rows:
        out.append(f"- Progress: {_progress([rec for _, rec in rows])}")
        running = having(RUNNING)
        out.append("- Running now:" + ("" if running else " nothing"))
        for title, rec in running:
            since = f"started {_show(rec.get('started_at'), '%H:%M')}"
            if now is not None and rec.get("started_at"):
                ran = (now - datetime.fromisoformat(rec["started_at"])).total_seconds()
                since += f", {human_duration(ran)} so far"
            out.append(f"  - {title}: {rec.get('step')} ({since})")
    out += [f"- Note: {note}" for note in data.get("notes") or []]
    if state == FAILED_TO_START:
        out += ["", "## Could not start", str(data.get("error") or "unknown reason"),
                f"After fixing that, run: {resume}"]
    elif data.get("paused_reason"):
        where = f" (at {data['paused_by']})" if data.get("paused_by") else ""
        if state == PAUSED:
            out += ["", "## Paused", f"Reason: {data['paused_reason']}{where}",
                    "Steps that were already running were allowed to finish. Nothing new was started.",
                    "To continue where it stopped, run this later:", "", f"    {resume}"]
        else:
            out += ["", "## Pausing", f"Reason: {data['paused_reason']}{where}",
                    "No new steps will start. Waiting for the running steps to finish."]
    if having(DONE):
        out += ["", "## Done", *listed(having(DONE))]
    if having(FAILED):
        out += ["", "## Failed", *listed(having(FAILED))]
        if state == DONE_WITH_FAILURES:
            out += ["", "To retry the failed steps (finished steps are kept), run:", "", f"    {resume}"]
    todo = having(PENDING, PAUSED)
    if todo:
        out += ["", "## Still to do"]
        for title in dict.fromkeys(t for t, _ in todo):
            steps = [f"{r.get('step')}{' (paused)' if r.get('status') == PAUSED else ''}" for t, r in todo if t == title]
            out.append(f"- {title}: {', '.join(steps)}")
    out += ["", f"Logs: {data.get('log_dir') or 'build/logs'}/ (one file per title)", ""]
    return "\n".join(out)


def status_report(paths: Paths, name: str | None = None) -> str | None:
    """`animedex batch status`: the named batch (default: the latest) in plain words; None if there is none."""
    if name is None:
        names = known_batches(paths)
        name = names[0] if names else None
    data = read_status(paths, name) if name else None
    if data is None:
        return None
    text = status_markdown(data, now=_now())
    if data.get("state") == RUNNING and not pid_alive(data.get("pid")):
        text = ("Note: this batch stopped without finishing (the computer may have restarted, or the job was "
                f"ended). To continue where it stopped, run: {data.get('resume_command')}\n\n{text}")
    return text
