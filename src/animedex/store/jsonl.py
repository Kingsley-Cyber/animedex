"""JSONL io with deterministic serialization (sorted keys, one record per line)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from animedex.textutil import stable_json


class JsonlError(ValueError):
    pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise JsonlError(f"{path.name}:{lineno}: invalid JSON ({exc.msg})") from exc
        if not isinstance(obj, dict):
            raise JsonlError(f"{path.name}:{lineno}: each line must be a JSON object")
        records.append(obj)
    return records


def dumps_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(stable_json(r) + "\n" for r in records)
