"""Build providers and clients from config (model per pass is configuration, not code)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from animedex import SCHEMA_VERSION
from animedex.budget import Budget, price_for
from animedex.config import Settings, resolve_base_url
from animedex.guards import live_title_guard
from animedex.ontology import get_vocab
from animedex.paths import Paths
from animedex.providers.anthropic_adapter import AnthropicProvider
from animedex.providers.base import Provider
from animedex.providers.claude_cli import ClaudeCliProvider
from animedex.providers.client import LLMClient
from animedex.providers.codex_cli import CodexCliProvider
from animedex.providers.mock import MockProvider
from animedex.providers.openai_compatible import OpenAICompatibleProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog


class ProviderConfigError(RuntimeError):
    pass


def build_provider(
    name: str, settings: Settings, env: dict[str, str], *, transport: httpx.BaseTransport | None = None,
    anthropic_client: Any = None, runner: Callable[..., Any] | None = None,
) -> Provider:
    profile = settings.providers.get(name)
    if profile is None:
        raise ProviderConfigError(f"unknown provider profile {name!r}")
    if profile.type == "mock":
        return MockProvider(name)
    if profile.type == "polymath_embedder":
        raise ProviderConfigError(f"providers.{name} serves embeddings only (animedex.embeddings.base.build_embedder)")
    if profile.type == "claude_cli":  # subscription login; no key is read or passed (G1a)
        return ClaudeCliProvider(name, binary=profile.binary or "claude", send_params=profile.send_params,
                                 timeout_s=profile.timeout_s, runner=runner)
    if profile.type == "codex_cli":
        return CodexCliProvider(name, binary=profile.binary or "codex", send_params=profile.send_params,
                                timeout_s=profile.timeout_s, runner=runner)
    key = env.get(profile.api_key_env) if profile.api_key_env else None
    if profile.type == "openai_compatible":
        base = resolve_base_url(profile, env)
        if not base:
            raise ProviderConfigError(f"providers.{name}: no base_url (set {profile.base_url_env})")
        return OpenAICompatibleProvider(
            name, base, key, structured_output=profile.structured_output, send_params=profile.send_params,
            timeout_s=profile.timeout_s, max_retries=profile.max_retries, transport=transport,
        )
    return AnthropicProvider(
        name, key or None, fallbacks=profile.fallbacks, send_params=profile.send_params,
        timeout_s=profile.timeout_s, max_retries=profile.max_retries, client=anthropic_client,
    )


def build_client(
    model_key: str,
    *,
    paths: Paths,
    settings: Settings,
    env: dict[str, str],
    runlog: RunLog,
    prompt_version: str,
    budget: Budget | None = None,
    provider: Provider | None = None,
) -> LLMClient:
    spec = settings.models[model_key]
    provider = provider or build_provider(spec.provider, settings, env)
    vocab = get_vocab(paths)
    live = provider.live
    subscription = getattr(provider, "billing", "api") == "subscription"
    return LLMClient(
        provider=provider,
        provider_name=spec.provider,
        spec=spec,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        vocab_version=vocab.version,
        cache=ResponseCache(paths.cache),
        runlog=runlog,
        price=price_for(settings, spec.provider, spec.model) if live and not subscription else None,
        budget=(budget or Budget.from_settings(settings)) if live else None,
        title_guard=live_title_guard(paths, settings, vocab) if live else None,
        min_interval_s=float(settings.budget.get("min_seconds_between_calls") or 0) if subscription else 0.0,
    )
