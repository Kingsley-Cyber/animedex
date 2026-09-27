"""Provider interface (03): one call shape for every adapter.

Adapters return raw text; LLMClient (providers/client.py) owns caching, JSON parsing, the one
repair attempt, budgets, logging, and the gold blind guard, and exposes
`complete(system, user, json_schema, params) -> (json, usage)`.

All pass calls are single-turn, so no reasoning content has to be carried between turns. A
future multi-turn step must preserve it (03 Providers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

_DATE_STAMP = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")


def same_model(requested: str, served: str) -> bool:
    """Equal, or the same id with a date-stamp suffix (-YYYYMMDD / -YYYY-MM-DD) on one side.

    Version suffixes do NOT count: claude-opus-5 is not claude-opus-5-5.
    """
    return _DATE_STAMP.sub("", requested) == _DATE_STAMP.sub("", served)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: Usage
    model: str                     # the model that actually served the call
    stop_reason: str | None = None
    request_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)  # CLI providers: cli, cli_version, shadow_cost_usd, init


class ProviderError(RuntimeError):
    """Non-retryable provider failure (bad request, auth, exhausted retries)."""


class ProviderRefusal(ProviderError):
    """The model declined (Anthropic stop_reason == "refusal")."""


class ProviderTruncated(ProviderError):
    """Output hit the token limit; the JSON is incomplete."""


class Provider(Protocol):
    name: str
    live: bool

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        """`params` carries `model` plus any forwarded generation params."""
        ...

    def resolve_model(self, model_id: str) -> str:
        """Confirm the model id exists at the provider; raise ProviderError if not."""
        ...


def schema_instruction(json_schema: dict[str, Any]) -> str:
    """Appended to the system prompt when the endpoint lacks native JSON-schema mode."""
    import json

    return (
        "\n\nReturn only one JSON object that validates against this JSON Schema. No prose, "
        "no code fences.\n" + json.dumps(json_schema, sort_keys=True)
    )
