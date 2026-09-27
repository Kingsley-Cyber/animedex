"""claude_cli provider: headless Claude Code on Kingsley's subscription login (G1a).

`claude -p --output-format stream-json --verbose --json-schema <schema> --model <id>` with the pass
prompt as the system prompt, from an empty scratch dir, with `--safe-mode` (no CLAUDE.md, skills,
plugins, hooks, MCP servers, memory), `--setting-sources project` (no user settings file: the
scratch dir has no project settings), `--tools ""` (the only tool left is StructuredOutput, which
returns the schema answer), `--strict-mcp-config`, and `--no-session-persistence`. Never `--bare`
(that mode only authenticates with an API key) and never `--fallback-model` (no silent
substitution). The init event is kept so every call shows what loaded.

Native web search (VERIFY, G1a 2026-09-27): a call with `params["web"]` gets exactly WebSearch and
WebFetch, pre-approved, with a hard `--max-turns`. The stream's tool calls are read for the web
evidence (queries, fetched URLs, URLs the searches returned). Page text is never kept.
"""

from __future__ import annotations

import json
import re
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
    timed_events,
)

CLI = "claude_cli"
WEB_TOOLS = ("WebSearch", "WebFetch")
# Owner rule 2026-09-27: pipeline code must not scrape MyAnimeList pages (use AniList, Jikan, or MAL's API).
BLOCKED_FETCH = ("WebFetch(domain:myanimelist.net)", "WebFetch(domain:www.myanimelist.net)")
_URL = re.compile(r"https?://[^\s\"'<>\[\]{}\\]+")


def clean_url(url: str) -> str:
    """Trim trailing punctuation; keep parentheses that belong to the URL (Wikipedia titles)."""
    url = url.rstrip(".,;:")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(".,;:")
    return url


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def web_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Queries, fetched URLs and search-result URLs from one call's tool traffic. URLs only: the
    page text in the tool results is read for links and dropped (web text is transient)."""
    uses: dict[str, tuple[str, dict[str, Any]]] = {}
    for e in events:
        if e.get("type") == "assistant":
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in WEB_TOOLS:
                    uses[str(block.get("id"))] = (block["name"], block.get("input") or {})
    fetched: set[str] = set()
    found: set[str] = set()
    for e in events:
        if e.get("type") != "user":
            continue
        for block in (e.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("is_error"):
                continue
            name, inp = uses.get(str(block.get("tool_use_id")), ("", {}))
            if name == "WebFetch" and inp.get("url"):
                fetched.add(str(inp["url"]))
            elif name == "WebSearch":
                found.update(clean_url(u) for u in _URL.findall(_block_text(block.get("content"))))
    queries = [str(inp.get("query", "")) for name, inp in uses.values() if name == "WebSearch"]
    return {"searches": len(queries), "fetches": sum(1 for name, _ in uses.values() if name == "WebFetch"),
            "queries": queries, "fetched": sorted(fetched), "found": sorted(found), "urls": sorted(fetched | found)}


def event_timing(timed: list[tuple[float | None, dict[str, Any]]], wall_s: float | None,
                 result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Where one call's wall time went (seconds). Each gap between stdout events is charged to what
    ended it: startup (the init event), model (an assistant message, or the result event: the CLI
    delivers the structured answer there, so the gap before it is the model writing that answer),
    web (a WebSearch/WebFetch result), tools (another tool's result), other (anything else, and
    shutdown after the result). Without event times (a test runner) only the wall time is known."""
    res = result or {}
    out: dict[str, Any] = {"wall_s": round(wall_s, 2) if wall_s is not None else None, "turns": res.get("num_turns")}
    if isinstance(res.get("duration_api_ms"), (int, float)):
        out["api_s"] = round(res["duration_api_ms"] / 1000, 2)  # the CLI's own count; includes helper models
    if wall_s is None or not timed or any(ts is None for ts, _ in timed):
        return out
    names: dict[str, str] = {}
    spent = dict.fromkeys(("startup_s", "model_s", "web_s", "tools_s", "other_s"), 0.0)
    prev = 0.0
    for ts, e in timed:
        gap, prev = max(0.0, ts - prev), max(prev, ts)  # type: ignore[operator, type-var]
        blocks = [b for b in (e.get("message") or {}).get("content") or [] if isinstance(b, dict)]
        if e.get("type") == "system" and e.get("subtype") == "init":
            key = "startup_s"
        elif e.get("type") in ("assistant", "result"):
            key = "model_s"
            names.update({str(b.get("id")): str(b.get("name")) for b in blocks if b.get("type") == "tool_use"})
        elif e.get("type") == "user":
            used = [names.get(str(b.get("tool_use_id"))) for b in blocks if b.get("type") == "tool_result"]
            key = "web_s" if any(n in WEB_TOOLS for n in used) else "tools_s"
        else:
            key = "other_s"
        spent[key] += gap
    spent["other_s"] += max(0.0, wall_s - prev)
    return {**out, "v": 2, **{k: round(v, 2) for k, v in spent.items()}}


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
        web = params.get("web")
        args = [
            self.binary, "-p",
            "--output-format", "stream-json", "--verbose",
            "--model", str(params["model"]),
            "--system-prompt", system,
            "--json-schema", json.dumps(json_schema, sort_keys=True),
            "--tools", ",".join(WEB_TOOLS) if web else "",
            "--safe-mode",
            "--setting-sources", "project",  # the scratch dir has none: no user settings (model, effort)
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if "effort" in self.send_params and params.get("effort"):
            args += ["--effort", str(params["effort"])]
        if web:  # exactly the web tools, pre-approved (headless calls cannot answer a permission prompt)
            args += ["--allowedTools", ",".join(WEB_TOOLS), "--max-turns", str(int(web["max_turns"]))]
            args += ["--disallowedTools", ",".join(BLOCKED_FETCH)]  # owner rule: never scrape these sites
        return args

    def generate(self, system: str, user: str, json_schema: dict[str, Any], params: dict[str, Any]) -> ProviderResponse:
        with tempfile.TemporaryDirectory(prefix="animedex-call-") as cwd:
            # a prompt that starts with "/" would be read as a slash command
            text_in = f"Input:\n{user}" if user.lstrip().startswith("/") else user
            proc = run(self.args(system, json_schema, params), input_text=text_in, cwd=cwd,
                       timeout_s=self.timeout_s, runner=self._runner)
        timed = timed_events(proc)
        events = [e for _, e in timed]
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
                  "init": self.last_init, "billing": self.billing, "other_models": others,
                  "expected_tools": ["StructuredOutput", *WEB_TOOLS] if params.get("web") else ["StructuredOutput"],
                  "timing": event_timing(timed, getattr(proc, "wall_s", None), result),
                  **({"web": web_evidence(events)} if params.get("web") else {})},
        )

    def resolve_model(self, model_id: str) -> str:
        """No models API on a subscription login: the smoke call's served model is the check."""
        return model_id

    def login_status(self) -> dict[str, Any]:
        return login_status([self.binary, "auth", "status"], self._runner)
