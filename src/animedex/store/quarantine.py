"""Quarantine (03): invalid JSON, schema failures, rejected atoms, with reasons. Gitignored."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animedex.store.atomic import atomic_write_text


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "unknown"


def quarantine(
    root: Path, pass_: str, record_type: str, record_id: str, record: Any, reasons: list[str]
) -> Path:
    path = root / _safe(pass_) / _safe(record_type) / f"{_safe(record_id)}.json"
    payload = {
        "pass": pass_,
        "record_type": record_type,
        "record_id": record_id,
        "reasons": reasons,
        "record": record,
        "quarantined_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")
    return path
