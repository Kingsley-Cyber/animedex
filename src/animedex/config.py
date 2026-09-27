"""config/settings.yaml + .env (05 Config). Placeholders like "<set>" block live runs, not offline work."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from animedex.paths import Paths

PLACEHOLDER = re.compile(r"^<[^>]*>$")
CLI_TYPES = ("claude_cli", "codex_cli")


def is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER.match(value.strip()))


class ProviderProfile(BaseModel):
    """An adapter plus its endpoint. `models.<pass>.provider` names one of these."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["openai_compatible", "anthropic", "mock", "claude_cli", "codex_cli"]
    binary: str | None = None  # CLI providers: executable name or path
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    structured_output: Literal["json_schema", "json_object", "prompt"] = "json_schema"
    fallbacks: str | None = None
    timeout_s: float = 300.0
    max_retries: int = Field(default=5, ge=0, le=10)
    send_params: list[str] = Field(default_factory=list)


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    strict_model: bool = False  # refuse any response served by a different model (CHECK, judge)


# Model slots each milestone needs live (smoke readiness checks only these).
STAGE_SLOTS: dict[str, list[str]] = {
    "m2": ["p1", "verify"],
    "m3": ["p1", "verify", "p2", "p3", "check", "p4", "eval_match"],
    "m5": ["p1", "verify", "p2", "p3", "check", "p4", "eval_match", "ideate_generate", "ideate_judge", "embeddings"],
    "m6": ["p1", "verify", "p2", "p3", "check", "p4", "eval_match", "ideate_generate", "ideate_judge", "embeddings",
           "ep", "rollup_match"],
}


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")
    providers: dict[str, ProviderProfile]
    models: dict[str, ModelSpec]
    search: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    pricing: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verify: dict[str, Any] = Field(default_factory=dict)
    p2: dict[str, Any] = Field(default_factory=dict)
    p3: dict[str, Any] = Field(default_factory=dict)
    check: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    episodes: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)
    ideate: dict[str, Any] = Field(default_factory=dict)
    eval: dict[str, Any] = Field(default_factory=dict)


def load_settings(paths: Paths | None = None) -> Settings:
    paths = paths or Paths.discover()
    data = yaml.safe_load(paths.config_file.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines. Comments only on their own line (inline '#' is part of the value)."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def environment(paths: Paths | None = None) -> dict[str, str]:
    """.env values, overridden by the real process environment."""
    paths = paths or Paths.discover()
    env = parse_env_file(paths.env_file)
    env.update({k: v for k, v in os.environ.items()})
    return env


def resolve_base_url(profile: ProviderProfile, env: dict[str, str]) -> str | None:
    if profile.base_url_env and env.get(profile.base_url_env):
        return env[profile.base_url_env]
    return profile.base_url


def live_problems(settings: Settings, env: dict[str, str], model_keys: list[str] | None = None) -> list[str]:
    """Everything that blocks a live call for the given model slots (default: all)."""
    problems: list[str] = []
    keys = model_keys or sorted(settings.models)
    uses_cli = uses_api = False
    for key in keys:
        spec = settings.models.get(key)
        if spec is None:
            problems.append(f"models.{key}: missing")
            continue
        if is_placeholder(spec.model):
            problems.append(f"models.{key}.model: fill in {spec.model}")
        profile = settings.providers.get(spec.provider)
        if profile is None:
            problems.append(f"models.{key}.provider: unknown provider profile {spec.provider!r}")
            continue
        if profile.type == "mock":
            continue
        if profile.type in CLI_TYPES:
            uses_cli = True
            continue  # subscription login, no key or pricing; checked by `animedex smoke`
        uses_api = True
        if profile.api_key_env and not env.get(profile.api_key_env):
            problems.append(f"providers.{spec.provider}: set {profile.api_key_env} in .env")
        if profile.type == "openai_compatible" and not resolve_base_url(profile, env):
            problems.append(f"providers.{spec.provider}: set base_url or {profile.base_url_env} in .env")
        if key != "embeddings" and not is_placeholder(spec.model):
            price = settings.pricing.get(f"{spec.provider}/{spec.model}")
            if not price or any(is_placeholder(v) for v in price.values()):
                problems.append(f'pricing."{spec.provider}/{spec.model}": set input_per_mtok and output_per_mtok')
    caps = (["run_cap_usd", "per_title_cap_usd", "per_episode_cap_usd"] if uses_api else []) + (
        ["calls_per_run", "calls_per_title"] if uses_cli else [])
    for cap in caps:
        value = settings.budget.get(cap)
        if value is None or is_placeholder(value):
            problems.append(f"budget.{cap}: set a cap")
    backend = settings.search.get("backend")
    if backend is None or is_placeholder(backend):
        problems.append("search.backend: choose a search backend")
    elif backend == "brave" and not env.get(str(settings.search.get("api_key_env", "SEARCH_API_KEY"))):
        problems.append("search: set SEARCH_API_KEY in .env (Brave)")
    elif backend == "searxng" and not settings.search.get("base_url"):
        problems.append("search.base_url: set the SearXNG URL")
    elif backend == "native":  # the verify model searches with its CLI's own web tools
        spec = settings.models.get("verify")
        profile = settings.providers.get(spec.provider) if spec else None
        if profile is None or profile.type != "claude_cli":
            problems.append("search.backend native: models.verify must use a claude_cli provider")
    return sorted(set(problems))
