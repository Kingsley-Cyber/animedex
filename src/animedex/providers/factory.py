"""Build providers and clients from config (the model per slot is configuration, not code)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from animedex import SCHEMA_VERSION
from animedex.budget import Budget
from animedex.config import Settings
from animedex.ontology import get_vocab
from animedex.paths import Paths
from animedex.providers.base import Provider
from animedex.providers.claude_cli import ClaudeCliProvider
from animedex.providers.client import LLMClient
from animedex.providers.codex_cli import CodexCliProvider
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog


class ProviderConfigError(RuntimeError):
    pass


def build_provider(name: str, settings: Settings, *, runner: Callable[..., Any] | None = None) -> Provider:
    profile = settings.providers.get(name)
    if profile is None:
        raise ProviderConfigError(f"unknown provider profile {name!r}")
    if profile.type == "mock":
        return MockProvider(name)
    if profile.type == "claude_cli":  # subscription login; no key is read or passed
        return ClaudeCliProvider(name, binary=profile.binary or "claude", send_params=profile.send_params,
                                 timeout_s=profile.timeout_s, runner=runner)
    if profile.type == "codex_cli":
        return CodexCliProvider(name, binary=profile.binary or "codex", send_params=profile.send_params,
                                timeout_s=profile.timeout_s, runner=runner, allow_web=profile.allow_web)
    raise ProviderConfigError(f"providers.{name}: a {profile.type} profile serves embeddings only")


def build_client(model_key: str, *, paths: Paths, settings: Settings, runlog: RunLog, prompt_version: str = "unset",
                 budget: Budget | None = None, provider: Provider | None = None) -> LLMClient:
    spec = settings.models[model_key]
    provider = provider or build_provider(spec.provider, settings)
    return LLMClient(
        provider=provider,
        provider_name=spec.provider,
        spec=spec,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        vocab_version=get_vocab(paths).version,
        cache=ResponseCache(paths.cache),
        runlog=runlog,
        budget=(budget or Budget.from_settings(settings)) if provider.live else None,
        min_interval_s=float(settings.budget.get("min_seconds_between_calls") or 0) if provider.live else 0.0,
    )
