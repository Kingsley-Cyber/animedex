"""Batch runner (owner request): at most three titles at once, steps in order, a clean pause on
`stopped:`, resume, lock, plain status page, detached start. A fake executor stands in for the
`animedex` CLI, so no subprocess runs and no model is called."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from animedex import batch as batch_mod
from animedex.batch import (
    EXIT_PAUSED,
    MAX_PARALLEL,
    BatchError,
    animedex_command,
    failure_line,
    human_duration,
    load_batch,
    pause_reason,
    pid_alive,
    read_status,
    run_jobs,
    status_path,
    tail_lines,
)
from animedex.cli import app

pytestmark = pytest.mark.unit

A, B, C = "ironvale_circuit_2021", "lantern_debt_2019", "glass_meridian_2016"
DEAD_PID = 2**22 + 12345  # above every OS pid limit: never a live process


def write_batch(root: Path, jobs: dict[str, list[str]], *, name: str = "trial", max_parallel: int | None = None) -> Path:
    data: dict[str, Any] = {"name": name}
    if max_parallel is not None:
        data["max_parallel"] = max_parallel
    data["jobs"] = [{"title": title, "steps": steps} for title, steps in jobs.items()]
    path = root / "batches" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


class FakeCli:
    """Stands in for `animedex <step> --title <title>`: records each call, answers from `script`
    (an (exit code, output) pair, or a function of title and step returning one)."""

    def __init__(self, script: dict[tuple[str, str], Any] | None = None):
        self.script = script or {}
        self.calls: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        self.prefix = len(animedex_command())

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        assert argv[-2] == "--title"
        title, step = argv[-1], shlex.join(argv[self.prefix:-2])
        with self.lock:
            self.calls.append((title, step))
        answer = self.script.get((title, step), (0, f"{step} finished for {title}\nnext: animedex canonicalize"))
        return answer(title, step) if callable(answer) else answer


def quiet(line: str) -> None:
    pass


def wait_until(check: Callable[[], Any], timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.002)
    return False


def statuses(repo) -> dict[tuple[str, str], str]:
    data = read_status(repo, "trial")
    return {(job["title"], rec["step"]): rec["status"] for job in data["jobs"] for rec in job["steps"]}


def md(repo) -> str:
    return status_path(repo, "trial", ".md").read_text()


def test_at_most_three_titles_run_at_once_and_each_title_runs_its_steps_in_order(repo):
    titles = [A, B, C, "salt_bridge_2022", "night_loom_2021"]
    batch = load_batch(write_batch(repo.root, {t: ["p1", "verify"] for t in titles}, max_parallel=5))
    assert batch.max_parallel == MAX_PARALLEL == 3 and "running 3 titles at once" in batch.notes[0]
    calls: list[tuple[str, str]] = []
    active, peak, lock = [0], [0], threading.Lock()
    gate = threading.Barrier(3, timeout=5)  # the first three steps meet here: three really run at once

    def fake(argv: list[str]) -> tuple[int, str]:
        with lock:
            calls.append((argv[-1], argv[-3]))
            first_round = len(calls) <= 3
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        if first_round:
            gate.wait()
        time.sleep(0.002)
        with lock:
            active[0] -= 1
        return 0, "ok"

    assert run_jobs(repo, batch, executor=fake, echo=quiet) == 0
    assert peak[0] == 3 and len(calls) == 10
    assert all([s for t, s in calls if t == title] == ["p1", "verify"] for title in titles)
    assert read_status(repo, "trial")["state"] == "done"


def paused_run(repo) -> tuple[Path, FakeCli, int, dict[str, str]]:
    """Two titles at once: the first hits a plan limit while the second is still running a step."""
    path = write_batch(repo.root, {A: ["p1", "verify"], B: ["p1", "verify"], C: ["verify"]}, max_parallel=2)
    b_running, seen = threading.Event(), {}

    def a_p1(title: str, step: str) -> tuple[int, str]:
        assert b_running.wait(5)
        return 0, "P1 run_a: 0 profile(s)\n  stopped: usage limit reached (synthetic)"

    def b_p1(title: str, step: str) -> tuple[int, str]:
        b_running.set()
        assert wait_until(lambda: "## Pausing" in md(repo))
        seen["md"] = md(repo)
        return 0, "P1 run_b: 1 profile(s)\nnext: animedex canonicalize"

    fake = FakeCli({(A, "p1"): a_p1, (B, "p1"): b_p1})
    return path, fake, run_jobs(repo, load_batch(path), executor=fake, echo=quiet), seen


def test_a_stopped_line_pauses_the_batch_and_lets_running_steps_finish(repo):
    _, fake, code, seen = paused_run(repo)
    assert code == EXIT_PAUSED == 3
    assert sorted(fake.calls) == sorted([(A, "p1"), (B, "p1")])  # nothing new started after the stop
    assert statuses(repo) == {(A, "p1"): "paused", (A, "verify"): "pending", (B, "p1"): "done",
                              (B, "verify"): "pending", (C, "verify"): "pending"}
    data = read_status(repo, "trial")
    assert data["state"] == "paused" and data["paused_reason"] == "usage limit reached (synthetic)"
    assert "## Pausing" in seen["md"] and f"{B}: p1 (started" in seen["md"]  # B was still running then
    page = md(repo)
    assert "# Batch trial: paused" in page and "Reason: usage limit reached (synthetic)" in page
    assert "make batch FILE=batches/trial.yaml" in page and "Nothing new was started." in page
    assert not status_path(repo, "trial", ".pid").exists()


def test_rerun_skips_done_steps_and_retries_the_paused_one(repo):
    path, _, _, _ = paused_run(repo)
    fake = FakeCli()
    assert run_jobs(repo, load_batch(path), executor=fake, echo=quiet) == 0
    assert (B, "p1") not in fake.calls  # done in the first run
    assert [s for t, s in fake.calls if t == A] == ["p1", "verify"]  # the paused step runs again first
    assert sorted(fake.calls) == sorted([(A, "p1"), (A, "verify"), (B, "verify"), (C, "verify")])
    data = read_status(repo, "trial")
    assert data["state"] == "done" and data["resumed"] and set(statuses(repo).values()) == {"done"}
    assert "5 of 5 steps done" in md(repo) and "(continued from an earlier run)" in md(repo)


def test_a_step_whose_text_changed_is_not_skipped(repo):
    run_jobs(repo, load_batch(write_batch(repo.root, {A: ["p1", "verify"]})), executor=FakeCli(), echo=quiet)
    fake = FakeCli()
    edited = write_batch(repo.root, {A: ["p1 --agreement", "verify"], B: ["verify"]})
    assert run_jobs(repo, load_batch(edited), executor=fake, echo=quiet) == 0
    assert fake.calls == [(A, "p1 --agreement"), (A, "verify"), (B, "verify")]


def test_a_failed_step_skips_the_rest_of_its_title_while_other_titles_finish(repo):
    path = write_batch(repo.root, {A: ["p1", "verify"], B: ["p1", "verify"], C: ["verify"]}, max_parallel=3)
    fake = FakeCli({(A, "p1"): (1, "Traceback (most recent call last):\nValueError: synthetic crash"),
                    (B, "p1"): (0, f"  not written {B}: phrases over their word limits\nP1 run_b: 0 profile(s)\ncalls 1")})
    assert run_jobs(repo, load_batch(path), executor=fake, echo=quiet) == 1
    assert sorted(fake.calls) == sorted([(A, "p1"), (B, "p1"), (C, "verify")])
    assert statuses(repo) == {(A, "p1"): "failed", (A, "verify"): "skipped", (B, "p1"): "failed",
                              (B, "verify"): "skipped", (C, "verify"): "done"}
    page = md(repo)
    assert "# Batch trial: done with failures" in page and "1 of 5 steps done, 2 failed" in page
    assert "> ValueError: synthetic crash" in page and f"> not written {B}: phrases over" in page
    assert page.count("Skipped because of this: verify") == 2 and "make batch FILE=batches/trial.yaml" in page
    again = FakeCli()  # a rerun retries the failed steps; the finished one is kept
    assert run_jobs(repo, load_batch(path), executor=again, echo=quiet) == 0
    assert sorted(again.calls) == sorted([(A, "p1"), (A, "verify"), (B, "p1"), (B, "verify")])


def test_a_live_lock_refuses_a_second_run_and_a_dead_one_is_replaced(repo):
    path = write_batch(repo.root, {A: ["verify"]})
    pid_file = status_path(repo, "trial", ".pid")
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text(f"{os.getpid()}\n")  # a live process holds the lock
    said: list[str] = []
    fake = FakeCli()
    assert run_jobs(repo, load_batch(path), executor=fake, echo=said.append) == 2
    assert not fake.calls and "already running" in said[0] and "make status NAME=trial" in said[0]
    assert pid_file.read_text().strip() == str(os.getpid()) and read_status(repo, "trial") is None
    assert not pid_alive(DEAD_PID)
    pid_file.write_text(f"{DEAD_PID}\n")  # left by a run that died
    assert run_jobs(repo, load_batch(path), executor=fake, echo=said.append) == 0
    assert fake.calls == [(A, "verify")] and not pid_file.exists()


@pytest.mark.parametrize("body, needle", [
    ("name: trial\nmax_parallel: 0\njobs: [{title: tern_2020, steps: [verify]}]", "max_parallel"),
    ("name: trial\njobs: [{title: tern_2020, steps: [verify]}, {title: tern_2020, steps: [p1]}]", "one job"),
    ("name: trial\njobs: [{title: tern_2020, steps: ['p1 --all']}]", "the runner adds --title"),
    ("name: trial\njobs: [{title: tern_2020, steps: []}]", "at least one step"),
    ("name: ../trial\njobs: [{title: tern_2020, steps: [verify]}]", "`name`"),
    ("jobs: nothing", "`name`"),
])
def test_batch_file_problems_are_reported_in_plain_words(tmp_path, body, needle):
    path = tmp_path / "b.yaml"
    path.write_text(body)
    with pytest.raises(BatchError, match=needle):
        load_batch(path)


def test_status_page_is_plain_shows_progress_and_is_rewritten_when_a_step_starts(repo):
    path = write_batch(repo.root, {A: ["p1", "verify"], B: ["verify"]})
    during: list[str] = []

    def a_verify(title: str, step: str) -> tuple[int, str]:
        during.append(md(repo))
        return 0, "VERIFY: 3 confirmed; outcome recorded"

    assert run_jobs(repo, load_batch(path), executor=FakeCli({(A, "verify"): a_verify}), echo=quiet) == 0
    assert "- Progress: 1 of 3 steps done" in during[0] and f"  - {A}: verify (started" in during[0]
    page = md(repo)
    assert page.startswith("# Batch trial: done\n") and "- Progress: 3 of 3 steps done" in page
    assert "- Running now: nothing" in page and "## Done" in page and "  > VERIFY: 3 confirmed" in page
    assert f"- {B}: verify (0s)" in page and "Logs: build/logs/trial/" in page
    assert not any(ch in page for ch in '{}"')  # words, not JSON
    log = (repo.root / "build" / "logs" / "trial" / f"{A}.log").read_text()
    assert f"animedex p1 --title {A}" in log and f"animedex verify --title {A}" in log and "outcome recorded" in log


def test_pause_and_failure_signals_and_durations():
    assert pause_reason(0, "P1 run_x\n  stopped: usage limit reached") == "usage limit reached"
    assert pause_reason(3, "STOPPED: P2: login expired\nPaused. Rerun the same command later") == "P2: login expired"
    assert pause_reason(3, "Paused: call cap reached.") == "Paused: call cap reached."
    assert pause_reason(0, "all good") is None and pause_reason(1, "boom") is None
    assert failure_line(A, f"  not verified {A}: no P1 candidate") == f"not verified {A}: no P1 candidate"
    assert failure_line(A, f"  fallback served {A}: codex") is None
    assert [human_duration(s) for s in (4, 372, 3725)] == ["4s", "6m 12s", "1h 02m"]
    assert tail_lines("│ frame │\nValueError: synthetic crash\n╰──────╯\n") == ["│ frame │", "ValueError: synthetic crash"]


def test_status_command_shows_the_latest_batch_and_spots_a_run_that_died(repo):
    runner = CliRunner()
    result = runner.invoke(app, ["batch", "status"])
    assert result.exit_code == 0 and "No batches yet" in result.output
    run_jobs(repo, load_batch(write_batch(repo.root, {A: ["verify"]})), executor=FakeCli(), echo=quiet)
    result = runner.invoke(app, ["batch", "status"])
    assert result.exit_code == 0 and "# Batch trial: done" in result.output and "1 of 1 steps done" in result.output
    data = read_status(repo, "trial")
    data.update(state="running", pid=DEAD_PID)
    status_path(repo, "trial").write_text(json.dumps(data))
    result = runner.invoke(app, ["batch", "status", "trial"])
    assert "stopped without finishing" in result.output and "make batch FILE=batches/trial.yaml" in result.output
    result = runner.invoke(app, ["batch", "status", "nope"])
    assert result.exit_code == 1 and "No batch named nope. Known batches: trial." in result.output


def test_start_launches_a_detached_run_and_never_waits(repo, monkeypatch):
    path = write_batch(repo.root, {A: ["verify"]})
    launched: list[tuple[list[str], dict[str, Any]]] = []

    class FakePopen:
        pid = 4242

        def __init__(self, argv: list[str], **kwargs: Any):
            launched.append((argv, kwargs))

        def wait(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("batch start must never wait for the batch")

        communicate = wait

    monkeypatch.setattr(batch_mod.subprocess, "Popen", FakePopen)
    runner = CliRunner()
    result = runner.invoke(app, ["batch", "start", str(path)])
    assert result.exit_code == 0, result.output
    (argv, kw), = launched
    assert argv[-3:] == ["batch", "run", str(path.resolve())]
    assert kw["start_new_session"] is True and kw["stdin"] is subprocess.DEVNULL and kw["stderr"] is subprocess.STDOUT
    assert Path(kw["stdout"].name) == repo.root / "build" / "logs" / "trial" / "batch.log" and kw["cwd"] == repo.root
    assert "build/status/trial.md" in result.output and "check progress: make status NAME=trial" in result.output
    pid_file = status_path(repo, "trial", ".pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()}\n")  # while it runs, a second start is refused
    result = runner.invoke(app, ["batch", "start", str(path)])
    assert result.exit_code == 2 and "already running" in result.output and len(launched) == 1
    pid_file.unlink()
    run_jobs(repo, load_batch(path), executor=FakeCli(), echo=quiet)
    result = runner.invoke(app, ["batch", "start", str(path)])  # all done: nothing to launch
    assert result.exit_code == 0 and "Nothing to run" in result.output and len(launched) == 1
