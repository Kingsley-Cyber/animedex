"""AC-05: an interrupted write leaves canonical files intact (process killed mid-write)."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from animedex.store.atomic import atomic_write_text, stale_temp_files
from tests.conftest import REPO

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


def test_exception_during_write_cleans_up_temp(tmp_path, monkeypatch):
    target = tmp_path / "x.jsonl"
    target.write_text("original\n")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("animedex.store.atomic.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(target, "new content\n")
    assert target.read_text() == "original\n" and stale_temp_files(tmp_path) == []


