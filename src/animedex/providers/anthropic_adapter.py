"""Anthropic adapter (03) on the official SDK.

- Native structured outputs: `output_config.format = {type: json_schema, schema}`; the first text
  block is the JSON.
- `stop_reason` is checked before reading content: `refusal` -> ProviderRefusal, `max_tokens` ->
  ProviderTruncated.
- Optional server-side refusal fallbacks (`fallbacks="default"`, beta header); the model that
  actually served the call (`response.model`) is what gets recorded.
- Sampling params (temperature, top_p) are never sent: current Claude models reject them. Depth is
  controlled with `effort` (inside output_config).
- The SDK retries connection errors, 408, 409, 429, and >= 500 (`max_retries`).
"""

from __future__ import annotations

from typing import Any

import anthropic

from animedex.providers.base import (
    ProviderError,
    ProviderRefusal,
    ProviderResponse,
    ProviderTruncated,
    Usage,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MAX_TOKENS = 16000


class AnthropicProvider:
    live = True

    def __init__(
        self,
        name: str,
        api_key: str | None = None,
        *,
        fallbacks: str | None = None,
        send_params: list[str] | None = None,
        timeout_s: float = 600.0,
        max_retries: int = 5,
        client: Any = None,
    ):
        self.name = name
        self.fallbacks = fallbacks
        self.send_params = list(send_params or [])
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=max_retries, timeout=timeout_s)

    def resolve_model(self, model_id: str) -> str:
        """Models API lookup: confirms the id resolves before any live run (G1a). Returns the display name."""
        try:
            info = self._client.models.retrieve(model_id)
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"{self.name}: model {model_id!r} does not resolve") from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"{self.name}: could not check model {model_id!r}: {exc}") from exc
        return str(getattr(info, "display_name", None) or getattr(info, "id", model_id))

    def _kwargs(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": json_schema}}
        if "effort" in self.send_params and params.get("effort"):
            output_config["effort"] = params["effort"]
        max_tokens = DEFAULT_MAX_TOKENS
        if "max_tokens" in self.send_params and params.get("max_tokens"):
            max_tokens = int(params["max_tokens"])
        return {
            "model": params["model"],
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        kwargs = self._kwargs(system, user, json_schema, params)
        try:
            if self.fallbacks:
                response = self._client.beta.messages.create(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks=self.fallbacks
                )
            else:
                response = self._client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"{self.name}: bad request: {exc.message}") from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError(f"{self.name}: authentication failed; check the API key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError(f"{self.name}: permission denied: {exc.message}") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"{self.name}: unknown model or endpoint: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(f"{self.name}: rate limited after SDK retries") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"{self.name}: HTTP {exc.status_code} after SDK retries") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"{self.name}: connection failed after SDK retries") from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderRefusal(f"{self.name}: model declined (category={category})")
        if response.stop_reason == "max_tokens":
            raise ProviderTruncated(f"{self.name}: output truncated at max_tokens")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise ProviderError(f"{self.name}: response had no text block")
        u = response.usage
        return ProviderResponse(
            text=text,
            usage=Usage(
                int(getattr(u, "input_tokens", 0) or 0),
                int(getattr(u, "output_tokens", 0) or 0),
                int(getattr(u, "cache_read_input_tokens", 0) or 0),
                int(getattr(u, "cache_creation_input_tokens", 0) or 0),
            ),
            model=str(response.model),
            stop_reason=response.stop_reason,
            request_id=getattr(response, "_request_id", None) or getattr(response, "id", None),
        )
