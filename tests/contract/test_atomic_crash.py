"""AC-05: an interrupted write leaves canonical files intact (process killed mid-write)."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from animedex.store.atomic import atomic_write_text, stale_temp_files
from animedex.store.jsonl import read_jsonl
from animedex.validate import validate_repo
from tests.conftest import REPO, make_title, synthetic_state, write_state

pytestmark = pytest.mark.contract

CHILD = textwrap.dedent("""
    import os, signal, sys
    sys.path.insert(0, {src!r})
    from pathlib import Path
    import animedex.store.atomic as atomic
    target = Path({target!r})
    def die(*a, **k):
        os.kill(os.getpid(), signal.SIGKILL)
    setattr({module}, {attr!r}, die)
    atomic.atomic_write_text(target, "PARTIAL-OVERWRITE " * 50000)
""")


def crash_child(target, module: str, attr: str) -> int:
    code = CHILD.format(src=str(REPO / "src"), target=str(target), module=module, attr=attr)
    return subprocess.run([sys.executable, "-c", code], capture_output=True).returncode


@pytest.mark.parametrize("module, attr", [
    ("os", "replace"),   # killed after the temp file is written, before the rename
    ("os", "fsync"),     # killed while flushing the temp file
])
def test_kill_mid_write_leaves_canonical_intact(repo, module, attr):
    write_state(repo, synthetic_state())
    target = repo.canonical / "titles.jsonl"
    before = target.read_bytes()
    rc = crash_child(target, module, attr)
    assert rc == -9, "child must die from SIGKILL mid-write"
    assert target.read_bytes() == before
    assert len(read_jsonl(target)) == 3
    assert stale_temp_files(repo.canonical)  # leftover temp is visible...
    report = validate_repo(repo)
    assert report.ok, report.errors             # ...and canonical data still validates
    assert any("stale temp file" in w for w in report.warnings)


def test_exception_during_write_cleans_up_temp(tmp_path, monkeypatch):
    target = tmp_path / "x.jsonl"
    target.write_text("original\n")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("animedex.store.atomic.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(target, "new content\n")
    assert target.read_text() == "original\n" and stale_temp_files(tmp_path) == []


def test_store_write_survives_crash_of_a_previous_writer(repo):
    write_state(repo, synthetic_state())
    crash_child(repo.canonical / "titles.jsonl", "os", "replace")
    from animedex.store.canonical import CanonicalStore

    CanonicalStore(repo).write("title", [make_title("zephyr_arc_2022", "Zephyr Arc")])
    assert len(read_jsonl(repo.canonical / "titles.jsonl")) == 4
