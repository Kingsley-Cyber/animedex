"""codex_cli provider: `codex exec` on Kingsley's ChatGPT plan login (G1a). The non-Claude family
for CHECK and the ideation judge.

Ephemeral, read-only sandbox, `--ignore-user-config` (skips ~/.codex/config.toml: MCP servers and
defaults), `--ignore-rules`, run from an empty scratch dir, schema-constrained final message via
`--output-schema`, JSONL events via `--json`. The shell, browser, apps, plugins, image and
multi-agent features are switched off per call, as are the environment-context and permissions
blocks. An explicitly web-enabled profile keeps code_mode_host available for Codex's web-search
tool while shell execution remains disabled. codex exec has no system-prompt flag, so the pass
prompt leads the prompt. Commands the agent runs anyway are reported (they should be none).

Checked with `codex debug prompt-input` (2026-09-27, codex-cli 0.157.1): one user-level item still
reaches the model and cannot be switched off per call without moving CODEX_HOME (which holds the
login): ~/.codex/AGENTS.md. `USER_LEVEL_LEAKS` names it so every call's metadata reports it. Models
whose catalog entry has multi_agent_version v2 (gpt-5.6-sol/terra) also get codex's built-in
multi-agent "team" instructions; the collaboration tools themselves are off.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from animedex.providers.base import ProviderError, ProviderResponse, Usage
from animedex.providers.cli_common import (
    Runner,
    classify,
    cli_version,
    login_status,
    run,
    timed_events,
)
from animedex.textutil import blocked_source

CLI = "codex_cli"


def codex_timing(timed: list[tuple[float | None, dict[str, Any]]], wall_s: float | None) -> dict[str, Any]:
    """Split measured call time between startup, model, completed web tools, and shutdown."""
    out: dict[str, Any] = {"wall_s": round(wall_s, 2) if wall_s is not None else None}
    times = [ts for ts, _ in timed]
    if wall_s is None or not times or None in times:
        return out
    first, last = min(times), max(times)  # type: ignore[type-var]
    web_s = sum(max(0.0, ts - timed[i - 1][0]) for i, (ts, event) in enumerate(timed) if i
                and event.get("type") == "item.completed"
                and (event.get("item") or {}).get("type") == "web_search")
    return {**out, "startup_s": round(first, 2), "model_s": round(max(0.0, last - first - web_s), 2),
            "web_s": round(web_s, 2), "tools_s": 0.0, "other_s": round(max(0.0, wall_s - last), 2)}
PREFIX = ("You are answering one structured-output request. Do not run commands, read files, or browse. "
          "Reply only with the final JSON object.\n\n## Instructions\n")
WEB_PREFIX = ("You are answering one structured-output request. Use live web search and open each page "
              "used as evidence. Do not run commands or read files. Reply only with the final JSON object."
              "\n\n## Instructions\n")
_MODEL_LINE = re.compile(r"^\s*model:\s*(\S+)", re.M)
# Features that add tools or instructions to an agent turn; off by default.
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "unified_exec_tty", "shell_snapshot", "apps", "plugins", "remote_plugin",
    "skill_search", "skill_mcp_dependency_install", "tool_suggest", "image_generation", "view_image", "browser_use",
    "browser_use_external", "browser_use_full_cdp_access", "computer_use", "in_app_browser", "in_app_chat",
    "in_app_local_automation", "multi_agent", "goals", "hooks", "personality", "code_mode_host",
    "workspace_dependencies", "sleep_tool", "worktrees", "realtime_conversation", "daemon_auto_start",
)
CONFIG_OVERRIDES = (
    "include_environment_context=false", "include_permissions_instructions=false",
    "include_apps_instructions=false", "skills.include_instructions=false", 'web_search="disabled"',
)
USER_LEVEL_LEAKS = ("~/.codex/AGENTS.md",)


def codex_web_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep opened-page URLs, never snippets or page text, from Codex web-search events."""
    queries: list[str] = []
    found: set[str] = set()
    fetched: set[str] = set()
    fetch_count = 0
    for event in events:
        item = event.get("item") or {}
        if event.get("type") != "item.completed" or item.get("type") != "web_search":
            continue
        action = item.get("action") or {}
        if action.get("type") == "search":
            queries.append(str(action.get("query") or item.get("query") or ""))
        for result in item.get("results") or []:
            if not isinstance(result, dict) or not result.get("url"):
                continue
            url = str(result["url"])
            if action.get("type") == "search":
                found.add(url)
            elif action.get("type") == "open_page" or re.search(r"view\d+$", str(result.get("ref_id") or "")):
                fetched.add(url)
                fetch_count += 1
    return {"searches": len(queries), "fetches": fetch_count, "queries": queries,
            "fetched": sorted(fetched), "found": sorted(found), "urls": sorted(fetched | found)}


class CodexCliProvider:
    live = True
    billing = "subscription"

    def __init__(self, name: str = CLI, *, binary: str = "codex", send_params: list[str] | None = None,
                 timeout_s: float = 900.0, runner: Runner | None = None, version: str | None = None,
                 allow_web: bool = False):
        import subprocess

        self.name = name
        self.binary = binary
        self.send_params = list(send_params or [])
        self.timeout_s = timeout_s
        self._runner = runner or subprocess.run
        self.version = version or cli_version(binary, self._runner)
        self.identity = f"{CLI}@{self.version}"
        self.last_init: dict[str, Any] = {}
        self.allow_web = allow_web

    def args(self, cwd: str, schema_path: str, out_path: str, params: dict[str, Any]) -> list[str]:
        args = [
            self.binary, "exec",
            "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--json", "--color", "never",
            "-C", cwd, "--output-schema", schema_path, "-o", out_path,
        ]
        for feature in DISABLED_FEATURES:
            if params.get("web") and feature == "code_mode_host":
                continue
            args += ["--disable", feature]
        for override in CONFIG_OVERRIDES:
            if params.get("web") and override == 'web_search="disabled"':
                override = 'web_search="live"'
            args += ["-c", override]
        model = str(params.get("model") or "default")
        if model != "default":
            args += ["-m", model]
        if "effort" in self.send_params and params.get("effort"):
            args += ["-c", f"model_reasoning_effort={json.dumps(str(params['effort']))}"]
        return args + ["-"]

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        if params.get("web") and not self.allow_web:
            raise ProviderError(f"{self.name}: native web search is wired for claude_cli only in this profile (models.verify)")
        with tempfile.TemporaryDirectory(prefix="animedex-call-") as cwd, \
                tempfile.TemporaryDirectory(prefix="animedex-io-") as io_dir:
            schema_path = str(Path(io_dir) / "schema.json")
            out_path = str(Path(io_dir) / "last_message.json")
            Path(schema_path).write_text(json.dumps(json_schema, sort_keys=True), encoding="utf-8")
            prefix = WEB_PREFIX if params.get("web") else PREFIX
            proc = run(self.args(cwd, schema_path, out_path, params), input_text=f"{prefix}{system}\n\n## Input\n{user}",
                       cwd=cwd, timeout_s=self.timeout_s, runner=self._runner)
            last = Path(out_path).read_text(encoding="utf-8") if Path(out_path).is_file() else ""
        timed = timed_events(proc)
        events = [e for _, e in timed]
        failures = [e for e in events if e.get("type") in ("error", "turn.failed")]
        commands = [e for e in events if (e.get("item") or {}).get("type") == "command_execution"]
        item_types = sorted({str((e.get("item") or {}).get("type")) for e in events
                             if e.get("type") == "item.completed" and (e.get("item") or {}).get("type")
                             not in ("agent_message", "reasoning")})
        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None) or {}
        event_model = next((str(e["model"]) for e in events if e.get("model")), None)
        m = _MODEL_LINE.search(proc.stderr or "")
        if event_model:
            served, source = event_model, "cli_event"
        elif m:
            served, source = m.group(1), "stderr"
        else:  # codex reports no served model: recorded as requested, marked unverified
            served, source = str(params.get("model") or "default"), "requested"
        warnings = [str((e.get("item") or {}).get("message") or "")[:200] for e in events
                    if e.get("type") == "item.completed" and (e.get("item") or {}).get("type") == "error"]
        self.last_init = {"model": served, "served_model_source": source, "commands_run": len(commands),
                          "other_items": item_types, "warnings": warnings,
                          "thread": next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None),
                          "user_level_leaks": list(USER_LEVEL_LEAKS)}
        if proc.returncode != 0 or failures or not last.strip():
            detail = " ".join(json.dumps(f) for f in failures) + " " + (proc.stderr or "")[-600:]
            raise classify(self.name, detail)
        web = codex_web_evidence(events) if params.get("web") else None
        if web is not None:
            limits = params["web"]
            if (web["searches"] > int(limits["max_searches"])
                    or web["fetches"] > int(limits["max_fetches"])
                    or any(blocked_source(url) for url in web["fetched"])):
                raise ProviderError(f"{self.name}: web search exceeded limits or opened a blocked source")
        return ProviderResponse(
            text=last,
            usage=Usage(int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0),
                        int(usage.get("cached_input_tokens", 0) or 0), 0),
            model=served,
            stop_reason="completed",
            request_id=self.last_init["thread"],
            meta={"cli": CLI, "cli_version": self.version, "shadow_cost_usd": None, "init": self.last_init,
                  "billing": self.billing, "timing": codex_timing(timed, getattr(proc, "wall_s", None)),
                  **({"web": web} if web is not None else {})},
        )

    def resolve_model(self, model_id: str) -> str:
        """No models API on a plan login: the smoke call reports the served model."""
        if not model_id:
            raise ProviderError(f"{self.name}: empty model id")
        return model_id

    def login_status(self) -> dict[str, Any]:
        return login_status([self.binary, "login", "status"], self._runner)
