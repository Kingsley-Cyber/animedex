"""Operate tools (request A, D-045): one detached job at a time, honest status, a stop that continues later."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest
import yaml

from animedex.mcpserver import jobs
from tests.unit.test_catalog import fake_anilist

pytestmark = pytest.mark.unit


def sleeper(records: list[list[str]]):
    """A launcher that records the command it was given and starts a harmless sleeping process instead."""
    def launch(cmd, log):
        records.append(cmd)
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return launch


def wait_gone(pid: int) -> bool:
    for _ in range(100):
        if not jobs._alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_one_job_at_a_time_status_and_stop(repo):
    recs: list[list[str]] = []
    info = jobs.start_job(repo, "ideas", ["ideate", "--arm", "animedex"], note="arm animedex", launcher=sleeper(recs))
    assert recs[0][-3:] == ["ideate", "--arm", "animedex"] and jobs.live_job(repo)["job_id"] == info["job_id"]
    with pytest.raises(jobs.JobRunning, match="still running"):
        jobs.start_job(repo, "census", ["census"], launcher=sleeper(recs))
    st = jobs.job_status(repo)
    assert st["live"]["kind"] == "ideas" and st["live_log"][0].startswith("== ") and st["last"] is None
    stopped = jobs.stop_job(repo)
    assert stopped["stopped"] is True and wait_gone(info["pid"])
    assert jobs.live_job(repo) is None and jobs.job_status(repo)["last"]["job_id"] == info["job_id"]
    again = jobs.start_job(repo, "census", ["census"], launcher=sleeper(recs))  # free again
    jobs.stop_job(repo)
    assert again["kind"] == "census" and wait_gone(again["pid"])


def test_a_finished_job_is_noticed_without_a_stop(repo):
    recs: list[list[str]] = []

    def quick(cmd, log):
        recs.append(cmd)
        return subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)

    info = jobs.start_job(repo, "diagnose", ["diagnose", "--text", "a concept"], launcher=quick)
    assert wait_gone(info["pid"])
    assert jobs.live_job(repo) is None  # reaped and moved to last.json, not a zombie counted as alive
    assert jobs.job_status(repo)["last"]["command"][:2] == ["diagnose", "--text"]


def test_a_running_batch_blocks_jobs(repo):
    (repo.root / "build" / "status").mkdir(parents=True, exist_ok=True)
    (repo.root / "build" / "status" / "m9.pid").write_text(f"{os.getpid()}\n")
    with pytest.raises(jobs.JobRunning, match="batch m9"):
        jobs.start_job(repo, "census", ["census"], launcher=sleeper([]))
    assert jobs.job_status(repo)["running_batch"] == "m9"


def test_add_titles_previews_then_starts_the_backfill(repo):
    repo.corpus_file.write_text(yaml.safe_dump({"titles": []}))
    preview = jobs.add_titles(repo, ["Iron Tide (2015)", "No Such Show", "  "], run=False, catalog=fake_anilist())
    assert [p["title_id"] for p in preview["picks"]] == ["iron_tide_2015"]
    assert preview["not_found"] == ["No Such Show"] and preview["started"] is None
    assert not (repo.root / "data" / "queue").exists()  # a preview writes nothing
    recs: list[list[str]] = []
    out = jobs.add_titles(repo, ["Iron Tide (2015)"], catalog=fake_anilist(), launcher=sleeper(recs))
    assert out["started"]["kind"] == "backfill" and recs[0][-3:-1] == ["backfill", "--list"]
    assert (repo.root / out["list"]).read_text().strip().endswith("Iron Tide (2015)")
    jobs.stop_job(repo)
    with pytest.raises(ValueError, match="at least one title"):
        jobs.add_titles(repo, ["# comment"], run=False, catalog=fake_anilist())
