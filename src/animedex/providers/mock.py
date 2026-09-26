"""Mock provider (03): fixtures, no network. Development and tests run on this (10 §7).

Responses resolve in order:
1. `responses[(pass, record_id)]`: a dict (returned as JSON), a str (returned verbatim, so
   malformed JSON can be simulated), or a list of those for successive attempts (repair tests);
2. `<fixtures_dir>/<pass>/<record_id>.json` (attempt 0) or `.repair.json` (attempt 1),
   `.txt` for raw text;
3. `default(system, user, json_schema, params)` if given.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from animedex.providers.base import ProviderError, ProviderResponse, Usage

Responder = Callable[[str, str, dict[str, Any], dict[str, Any]], Any]


class MockProvider:
    live = False

    def __init__(
        self,
        name: str = "mock",
        *,
        fixtures_dir: Path | None = None,
        responses: dict[tuple[str, str], Any] | None = None,
        default: Responder | None = None,
    ):
        self.name = name
        self.fixtures_dir = fixtures_dir
        self.responses = dict(responses or {})
        self.default = default
        self.calls: list[dict[str, Any]] = []

    def _fixture(self, pass_: str, record_id: str, attempt: int) -> Any:
        if self.fixtures_dir is None:
            return None
        stem = f"{record_id}.repair" if attempt else record_id
        for suffix in (".json", ".txt"):
            path = self.fixtures_dir / pass_ / f"{stem}{suffix}"
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                return json.loads(text) if suffix == ".json" else text
        return None

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        meta = params.get("_meta") or {}
        pass_, record_id, attempt = meta.get("pass", ""), meta.get("record_id", ""), int(meta.get("attempt", 0))
        self.calls.append({"pass": pass_, "record_id": record_id, "attempt": attempt, "user": user})
        value = self.responses.get((pass_, record_id))
        if isinstance(value, list):
            value = value[min(attempt, len(value) - 1)]
        if value is None:
            value = self._fixture(pass_, record_id, attempt)
        if value is None and self.default is not None:
            value = self.default(system, user, json_schema, params)
        if value is None:
            raise ProviderError(f"mock: no fixture for pass={pass_} record_id={record_id} attempt={attempt}")
        text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        return ProviderResponse(
            text=text,
            usage=Usage(max(1, (len(system) + len(user)) // 4), max(1, len(text) // 4)),
            model=f"mock/{params.get('model', 'mock')}",
            stop_reason="end_turn",
        )
