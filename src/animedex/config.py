"""config/settings.yaml + .env. Model calls go through the subscription CLIs; no API keys are read."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from animedex.paths import Paths


class ProviderProfile(BaseModel):
    """An adapter plus its endpoint. `models.<slot>.provider` names one of these. `openai_compatible` and
    `polymath_embedder` serve embeddings only (the diagnose premise check)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["mock", "claude_cli", "codex_cli", "polymath_embedder", "openai_compatible"]
    binary: str | None = None  # CLI providers: executable name or path
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    structured_output: Literal["json_schema", "json_object", "prompt"] = "json_schema"
    timeout_s: float = 300.0
    send_params: list[str] = Field(default_factory=list)
    allow_web: bool = False  # explicit opt-in for a Codex CLI profile that gathers source evidence


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    strict_model: bool = False  # refuse any response served by a different model (the check)
    fallback: ModelSpec | None = None   # embeddings only: the backend used when the primary isn't ready


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")
    providers: dict[str, ProviderProfile]
    models: dict[str, ModelSpec]
    budget: dict[str, Any] = Field(default_factory=dict)

    def section(self, name: str) -> dict[str, Any]:
        """An optional block (notes, quick, diagnose, data_repo) as a dict."""
        return dict((self.model_extra or {}).get(name) or {})


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
