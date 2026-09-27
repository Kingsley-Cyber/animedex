"""Shared plumbing for subscription CLI providers (G1a, 2026-09-26).

Every call runs:
- with an allowlisted environment: no ANTHROPIC_*, OPENAI_*, CLAUDE_* or CODEX_* variables, so an
  API key (or a parent Claude Code session's auth) can never switch billing away from the plan;
- from a fresh, empty scratch directory, so no repo CLAUDE.md / AGENTS.md, hooks, or MCP config
  can load;
- with a timeout; rate-limit and auth failures raise distinct errors.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from animedex.providers.base import ProviderError

ENV_ALLOW = (
    "HOME", "PATH", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "TZ",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE",
)
ENV_DENY_PREFIXES = ("ANTHROPIC_", "OPENAI_", "CLAUDE", "CODEX_")

_RATE = re.compile(r"rate.?limit|usage limit|limit reached|too many requests|\b429\b|overloaded|quota", re.I)
_AUTH = re.compile(r"not logged in|please run /login|auth(entication)? (failed|required|error)|invalid api key|"
                   r"failed to authenticate|oauth session expired|could not be refreshed|"
                   r"log ?in to|login required|unauthori[sz]ed|\b401\b", re.I)

Runner = Callable[..., subprocess.CompletedProcess]
# Tests install a guard so only fake CLIs can run: a real call would spend Kingsley's plan.
BINARY_GUARD: Callable[[str], bool] | None = None


def guard(binary: str) -> None:
    if BINARY_GUARD is not None and not BINARY_GUARD(binary):
        raise ProviderError(f"{binary}: real CLI calls are blocked here (test guard)")


class RateLimited(ProviderError):
    """The plan's usage limit was hit: stop the run cleanly; finished calls stay cached."""


class CliAuthError(ProviderError):
    """The CLI is not logged in to the subscription."""


def clean_env(source: dict[str, str] | None = None) -> dict[str, str]:
    src = dict(os.environ if source is None else source)
    return {k: v for k, v in src.items() if k in ENV_ALLOW and not k.startswith(ENV_DENY_PREFIXES)}


def stripped_names(source: dict[str, str] | None = None) -> list[str]:
    """Names (never values) of credential-like variables removed from a CLI subprocess."""
    src = dict(os.environ if source is None else source)
    return sorted(k for k in src if k.startswith(ENV_DENY_PREFIXES))


def classify(name: str, text: str) -> ProviderError:
    if _RATE.search(text):
        return RateLimited(f"{name}: usage/rate limit hit; stop and resume from cache later")
    if _AUTH.search(text):
        return CliAuthError(f"{name}: not logged in to the subscription ({text.strip()[:160]})")
    return ProviderError(f"{name}: {text.strip()[:400] or 'failed with no output'}")


def run(args: list[str], *, input_text: str, cwd: str, timeout_s: float, runner: Runner = subprocess.run
        ) -> subprocess.CompletedProcess:
    guard(args[0])
    try:
        return runner(args, input=input_text, capture_output=True, text=True, cwd=cwd, env=clean_env(),
                      timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{args[0]}: timed out after {timeout_s:.0f}s") from exc
    except FileNotFoundError as exc:
        raise ProviderError(f"{args[0]}: CLI not found on PATH") from exc


def cli_version(binary: str, runner: Runner = subprocess.run) -> str:
    guard(binary)
    try:
        out = runner([binary, "--version"], capture_output=True, text=True, env=clean_env(), timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ProviderError(f"{binary}: CLI not available") from exc
    m = re.search(r"\d+\.\d+\.\d+", out.stdout or out.stderr or "")
    if not m:
        raise ProviderError(f"{binary}: could not read the CLI version")
    return m.group(0)


def login_status(args: list[str], runner: Runner = subprocess.run) -> dict[str, Any]:
    """`<cli> auth/login status` under the stripped env: logged in? by what method? Never returns
    account details. An API-key login is flagged: it would bill the API, not the plan."""
    guard(args[0])
    try:
        out = runner(args, capture_output=True, text=True, env=clean_env(), timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"logged_in": False, "method": "unavailable", "api_key": False, "detail": str(exc)[:120]}
    text = f"{out.stdout or ''}\n{out.stderr or ''}".strip()
    try:
        data = json.loads(out.stdout or "")
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):  # claude auth status
        method = str(data.get("authMethod") or "none")
        logged_in = bool(data.get("loggedIn"))
    else:  # codex login status: "Logged in using ChatGPT" / "... using an API key"
        m = re.search(r"logged in using (.+)", text, re.I)
        method = m.group(1).strip() if m else "none"
        logged_in = bool(m) and "not logged in" not in text.lower()
    return {"logged_in": logged_in, "method": method, "api_key": bool(re.search(r"api.?key|console", method, re.I))}


def summarize_init(init: dict[str, Any] | None) -> dict[str, Any]:
    """The parts of a CLI init event that show what loaded into the call."""
    if not init:
        return {}
    keys = ("model", "cwd", "apiKeySource", "permissionMode", "output_style", "tools", "mcp_servers",
            "slash_commands", "agents", "skills", "plugins", "memory_paths")
    return {k: init[k] for k in keys if k in init}


EXPECTED_TOOLS = {"StructuredOutput"}  # how `--json-schema` returns the answer


def user_level_names(home: Path | None = None) -> dict[str, set[str]]:
    """Names (never contents) of Kingsley's own skills, agents and commands under ~/.claude."""
    base = (home or Path.home()) / ".claude"
    skills = {p.name for p in (base / "skills").iterdir() if (p / "SKILL.md").is_file()} \
        if (base / "skills").is_dir() else set()
    agents = {p.stem for p in (base / "agents").glob("*.md")} if (base / "agents").is_dir() else set()
    commands = {p.stem for p in (base / "commands").rglob("*.md")} if (base / "commands").is_dir() else set()
    return {"skills": skills, "agents": agents, "slash_commands": skills | commands}


def unexpected_loads(summary: dict[str, Any], user_names: dict[str, set[str]] | None = None,
                     expected_tools: set[str] | list[str] | None = None) -> list[str]:
    """What a call should not have: tools beyond StructuredOutput, MCP servers, plugins, memory
    files, an API key, or anything from the user's own ~/.claude skills/agents/commands. The CLI's
    bundled skills and agents are not listed: with no Skill or Agent tool the model cannot reach them."""
    if not summary:
        return []
    names = user_level_names() if user_names is None else user_names
    out = []
    extra_tools = sorted(set(summary.get("tools") or []) - set(expected_tools or EXPECTED_TOOLS))
    if extra_tools:
        out.append(f"tools: {', '.join(extra_tools)}")
    for key in ("mcp_servers", "plugins", "memory_paths"):
        value = summary.get(key)
        if value:
            out.append(f"{key}: {value if isinstance(value, (str, int)) else len(value)} loaded")
    for key in ("skills", "agents", "slash_commands"):
        mine = sorted(set(summary.get(key) or []) & names.get(key, set()))
        if mine:
            out.append(f"user-level {key}: {', '.join(mine)}")
    if summary.get("commands_run"):
        out.append(f"commands run by the agent: {summary['commands_run']}")
    other = [i for i in summary.get("other_items") or [] if i != "error"]
    if other:
        out.append(f"agent actions beyond the answer: {', '.join(other)}")
    for warning in summary.get("warnings") or []:
        out.append(f"CLI warning: {warning}")
    src = summary.get("apiKeySource")
    if src not in (None, "none"):
        out.append(f"apiKeySource={src} (an API key, not the subscription)")
    return out
