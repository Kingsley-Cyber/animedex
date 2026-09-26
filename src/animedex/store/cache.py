"""Cache keys and the response cache (05 "Caching and idempotency", AC-06).

cache_key = sha256(id | pass | prompt_version | schema_version | vocab_version | model | params |
upstream_hash). upstream_hash hashes the canonical inputs a pass reads, with two rules:
- support-count changes (episode id lists in `support`) are excluded, so a new supporting
  episode never invalidates anything;
- status, explanation, origin, and upstream provenance (pass, model, prompt/schema/vocab version)
  are included, so a status change or an upstream prompt change does invalidate.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from animedex.store.atomic import atomic_write_text
from animedex.textutil import sha256_text, stable_json

SUPPORT_COUNT_KEYS = ("supporting_episodes", "contradicting_episodes", "reframing_episodes")
PROVENANCE_KEEP = ("pass", "model", "prompt_version", "schema_version", "vocab_version")


def upstream_projection(record: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(record)
    support = out.get("support")
    if isinstance(support, dict):
        for key in SUPPORT_COUNT_KEYS:
            support.pop(key, None)
    prov = out.get("provenance")
    if isinstance(prov, dict):
        out["provenance"] = {k: prov.get(k) for k in PROVENANCE_KEEP}
    return out


def upstream_hash(records: Iterable[dict[str, Any]]) -> str:
    lines = sorted(stable_json(upstream_projection(r)) for r in records)
    return sha256_text("\n".join(lines))


def key_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Params that shape the output. Keys starting with '_' are transport metadata."""
    return {k: v for k, v in sorted((params or {}).items()) if not k.startswith("_")}


def cache_key(
    *,
    record_id: str,
    pass_: str,
    prompt_version: str | None,
    schema_version: str,
    vocab_version: str,
    model: str | None,
    params: dict[str, Any] | None,
    upstream: str,
) -> str:
    parts = [
        record_id,
        pass_,
        prompt_version or "",
        schema_version,
        vocab_version,
        model or "",
        stable_json(key_params(params)),
        upstream,
    ]
    return sha256_text("|".join(parts))


class ResponseCache:
    """data/cache/<pass>/<aa>/<key>.json. Local only (gitignored); reruns skip cached calls."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, pass_: str, key: str) -> Path:
        digest = key.split(":", 1)[-1]
        return self.root / pass_ / digest[:2] / f"{digest}.json"

    def get(self, pass_: str, key: str) -> dict[str, Any] | None:
        path = self._path(pass_, key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, pass_: str, key: str, entry: dict[str, Any]) -> None:
        atomic_write_text(self._path(pass_, key), json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
