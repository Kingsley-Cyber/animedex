"""codex_cli provider: `codex exec` on Kingsley's ChatGPT plan login (G1a). The non-Claude family
for CHECK and the ideation judge.

Ephemeral, read-only sandbox, `--ignore-user-config` (skips ~/.codex/config.toml: MCP servers and
defaults), `--ignore-rules`, run from an empty scratch dir, schema-constrained final message via
`--output-schema`, JSONL events via `--json`. The shell, browser, apps, plugins, image and
multi-agent features are switched off per call, as are the environment-context and permissions
blocks. codex exec has no system-prompt flag, so the pass prompt leads the prompt. Commands the
agent runs anyway are reported (they should be none).

Checked with `codex debug prompt-input` (2026-09-26, codex-cli 0.146.0): two user-level items
still reach the model and cannot be switched off per call without moving CODEX_HOME (which holds
the login): ~/.codex/AGENTS.md and the installed-skills list. `USER_LEVEL_LEAKS` names them so
every call's metadata reports them.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from animedex.providers.base import ProviderError, ProviderResponse, Usage
from animedex.providers.cli_common import Runner, classify, cli_version, login_status, run

CLI = "codex_cli"
PREFIX = ("You are answering one structured-output request. Do not run commands, read files, or browse. "
          "Reply only with the final JSON object.\n\n## Instructions\n")
_MODEL_LINE = re.compile(r"^\s*model:\s*(\S+)", re.M)
# Features that add tools or instructions to an agent turn; off for every extraction call.
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "apps", "plugins", "remote_plugin", "skill_search",
    "skill_mcp_dependency_install", "tool_suggest", "image_generation", "browser_use", "browser_use_external",
    "computer_use", "in_app_browser", "multi_agent", "goals", "hooks", "personality", "code_mode_host",
    "workspace_dependencies",
)
CONFIG_OVERRIDES = (
    "include_environment_context=false", "include_permissions_instructions=false",
    "include_apps_instructions=false", 'web_search="disabled"', "tools.view_image=false",
)
USER_LEVEL_LEAKS = ("~/.codex/AGENTS.md", "installed skills list")


class CodexCliProvider:
    live = True
    billing = "subscription"

    def __init__(self, name: str = CLI, *, binary: str = "codex", send_params: list[str] | None = None,
                 timeout_s: float = 900.0, runner: Runner | None = None, version: str | None = None):
        import subprocess

        self.name = name
        self.binary = binary
        self.send_params = list(send_params or [])
        self.timeout_s = timeout_s
        self._runner = runner or subprocess.run
        self.version = version or cli_version(binary, self._runner)
        self.identity = f"{CLI}@{self.version}"
        self.last_init: dict[str, Any] = {}

    def args(self, cwd: str, schema_path: str, out_path: str, params: dict[str, Any]) -> list[str]:
        args = [
            self.binary, "exec",
            "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--json", "--color", "never",
            "-C", cwd, "--output-schema", schema_path, "-o", out_path,
        ]
        for feature in DISABLED_FEATURES:
            args += ["--disable", feature]
        for override in CONFIG_OVERRIDES:
            args += ["-c", override]
        model = str(params.get("model") or "default")
        if model != "default":
            args += ["-m", model]
        if "effort" in self.send_params and params.get("effort"):
            args += ["-c", f"model_reasoning_effort={json.dumps(str(params['effort']))}"]
        return args + ["-"]

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        with tempfile.TemporaryDirectory(prefix="animedex-call-") as cwd, \
                tempfile.TemporaryDirectory(prefix="animedex-io-") as io_dir:
            schema_path = str(Path(io_dir) / "schema.json")
            out_path = str(Path(io_dir) / "last_message.json")
            Path(schema_path).write_text(json.dumps(json_schema, sort_keys=True), encoding="utf-8")
            proc = run(self.args(cwd, schema_path, out_path, params), input_text=f"{PREFIX}{system}\n\n## Input\n{user}",
                       cwd=cwd, timeout_s=self.timeout_s, runner=self._runner)
            last = Path(out_path).read_text(encoding="utf-8") if Path(out_path).is_file() else ""
        events = []
        for line in (proc.stdout or "").splitlines():
            if line.strip().startswith("{"):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        failures = [e for e in events if e.get("type") in ("error", "turn.failed")]
        commands = [e for e in events if (e.get("item") or {}).get("type") == "command_execution"]
        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None) or {}
        event_model = next((str(e["model"]) for e in events if e.get("model")), None)
        m = _MODEL_LINE.search(proc.stderr or "")
        if event_model:
            served, source = event_model, "cli_event"
        elif m:
            served, source = m.group(1), "stderr"
        else:  # codex reports no served model: recorded as requested, marked unverified
            served, source = str(params.get("model") or "default"), "requested"
        self.last_init = {"model": served, "served_model_source": source, "commands_run": len(commands),
                          "thread": next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None),
                          "user_level_leaks": list(USER_LEVEL_LEAKS)}
        if proc.returncode != 0 or failures or not last.strip():
            detail = " ".join(json.dumps(f) for f in failures) + " " + (proc.stderr or "")[-600:]
            raise classify(self.name, detail)
        return ProviderResponse(
            text=last,
            usage=Usage(int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0),
                        int(usage.get("cached_input_tokens", 0) or 0), 0),
            model=served,
            stop_reason="completed",
            request_id=self.last_init["thread"],
            meta={"cli": CLI, "cli_version": self.version, "shadow_cost_usd": None, "init": self.last_init,
                  "billing": self.billing},
        )

    def resolve_model(self, model_id: str) -> str:
        """No models API on a plan login: the smoke call reports the served model."""
        if not model_id:
            raise ProviderError(f"{self.name}: empty model id")
        return model_id

    def login_status(self) -> dict[str, Any]:
        return login_status([self.binary, "login", "status"], self._runner)
