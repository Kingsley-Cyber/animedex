"""claude_cli provider: headless Claude Code on Kingsley's subscription login (G1a).

`claude -p --output-format stream-json --verbose --json-schema <schema> --model <id>` with the pass
prompt as the system prompt, from an empty scratch dir, with `--safe-mode` (no CLAUDE.md, skills,
plugins, hooks, MCP servers, memory), `--setting-sources project` (no user settings file: the
scratch dir has no project settings), `--tools ""` (the only tool left is StructuredOutput, which
returns the schema answer), `--strict-mcp-config`, and `--no-session-persistence`. Never `--bare` (that mode only authenticates with an API key) and never
`--fallback-model` (no silent substitution). The init event is kept so every call shows what loaded.
"""

from __future__ import annotations

import json
import tempfile
from typing import Any

from animedex.providers.base import ProviderError, ProviderResponse, Usage, same_model
from animedex.providers.cli_common import (
    Runner,
    classify,
    cli_version,
    login_status,
    run,
    summarize_init,
)

CLI = "claude_cli"


def served_model(requested: str, init: dict[str, Any] | None, model_usage: dict[str, Any]) -> tuple[str, list[str]]:
    """The model that answered, from the per-model usage the CLI reports (what actually ran), not
    from the init event (what was asked for). Other models in the usage (a helper call) are
    returned separately so they are logged, not hidden."""
    if model_usage:
        match = next((m for m in model_usage if same_model(requested, m)), None)
        if match is None:  # the requested model did not run: the busiest model answered
            match = max(model_usage, key=lambda m: int((model_usage[m] or {}).get("outputTokens", 0) or 0))
        return match, sorted(m for m in model_usage if m != match)
    return str((init or {}).get("model") or requested), []


class ClaudeCliProvider:
    live = True
    billing = "subscription"

    def __init__(self, name: str = CLI, *, binary: str = "claude", send_params: list[str] | None = None,
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

    def args(self, system: str, json_schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
        args = [
            self.binary, "-p",
            "--output-format", "stream-json", "--verbose",
            "--model", str(params["model"]),
            "--system-prompt", system,
            "--json-schema", json.dumps(json_schema, sort_keys=True),
            "--tools", "",
            "--safe-mode",
            "--setting-sources", "project",  # the scratch dir has none: no user settings (model, effort)
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if "effort" in self.send_params and params.get("effort"):
            args += ["--effort", str(params["effort"])]
        return args

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        with tempfile.TemporaryDirectory(prefix="animedex-call-") as cwd:
            # a prompt that starts with "/" would be read as a slash command
            text_in = f"Input:\n{user}" if user.lstrip().startswith("/") else user
            proc = run(self.args(system, json_schema, params), input_text=text_in, cwd=cwd,
                       timeout_s=self.timeout_s, runner=self._runner)
        events = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        self.last_init = summarize_init(init)
        if proc.returncode != 0 or result is None or result.get("is_error"):
            detail = " ".join(str(x) for x in ((result or {}).get("result"), (result or {}).get("subtype"),
                                                proc.stderr) if x)
            raise classify(self.name, detail)
        structured = result.get("structured_output")
        text = json.dumps(structured, sort_keys=True) if structured is not None else str(result.get("result") or "")
        if not text.strip():
            raise ProviderError(f"{self.name}: empty result")
        usage = result.get("usage") or {}
        served, others = served_model(str(params["model"]), init, result.get("modelUsage") or {})
        return ProviderResponse(
            text=text,
            usage=Usage(int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0),
                        int(usage.get("cache_read_input_tokens", 0) or 0),
                        int(usage.get("cache_creation_input_tokens", 0) or 0)),
            model=str(served),
            stop_reason=result.get("subtype"),
            request_id=result.get("session_id"),
            meta={"cli": CLI, "cli_version": self.version, "shadow_cost_usd": result.get("total_cost_usd"),
                  "init": self.last_init, "billing": self.billing, "other_models": others},
        )

    def resolve_model(self, model_id: str) -> str:
        """No models API on a subscription login: the smoke call's served model is the check."""
        return model_id

    def login_status(self) -> dict[str, Any]:
        return login_status([self.binary, "auth", "status"], self._runner)
