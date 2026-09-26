"""OpenAI-compatible adapter (OpenRouter, Ollama, vLLM, LM Studio, hosted APIs), 03.

Works against a local endpoint with no API key (10 §16). Retries 429/5xx/timeouts with
exponential backoff, at most `max_retries` times (11).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from animedex.providers.base import (
    ProviderError,
    ProviderResponse,
    ProviderTruncated,
    Usage,
    schema_instruction,
)

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


class OpenAICompatibleProvider:
    live = True

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        *,
        structured_output: str = "json_schema",
        send_params: list[str] | None = None,
        timeout_s: float = 300.0,
        max_retries: int = 5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.name = name
        self.structured_output = structured_output
        self.send_params = list(send_params or [])
        self.max_retries = max_retries
        self._sleep = sleep
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport
        )

    def _body(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        if self.structured_output != "json_schema":
            system = system + schema_instruction(json_schema)
        body: dict[str, Any] = {
            "model": params["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.structured_output == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "record", "schema": json_schema, "strict": False},
            }
        elif self.structured_output == "json_object":
            body["response_format"] = {"type": "json_object"}
        for key in self.send_params:
            if key in params:
                body[key] = params[key]
        return body

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        body = self._body(system, user, json_schema, params)
        attempt = 0
        while True:
            try:
                resp = self._client.post("/chat/completions", content=json.dumps(body))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError(f"{self.name}: network error after {attempt} retries: {exc}") from exc
                self._backoff(attempt, None)
                attempt += 1
                continue
            if resp.status_code in RETRYABLE and attempt < self.max_retries:
                self._backoff(attempt, resp.headers.get("retry-after"))
                attempt += 1
                continue
            if resp.status_code >= 400:
                raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:500]}")
            return self._parse(resp.json(), params["model"])

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = min(2.0**attempt, 30.0)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        self._sleep(delay)

    def _parse(self, data: dict[str, Any], requested_model: str) -> ProviderResponse:
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name}: unexpected response shape") from exc
        if choice.get("finish_reason") == "length":
            raise ProviderTruncated(f"{self.name}: output truncated at the token limit")
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=text,
            usage=Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
            model=str(data.get("model") or requested_model),
            stop_reason=choice.get("finish_reason"),
            request_id=data.get("id"),
        )
