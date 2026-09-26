"""Atomic file writes (06 CANON): temp file in the same directory, fsync, rename."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write_text(path: Path, text: str) -> None:
    """Replace `path` with `text` all-or-nothing. A crash leaves the old file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def stale_temp_files(directory: Path) -> list[Path]:
    """Leftovers from a writer killed mid-write (safe to delete; the target file is intact)."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp"))
