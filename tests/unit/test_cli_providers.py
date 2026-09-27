"""Subscription CLI providers (G1a 2026-09-26): isolation, billing, parsing, caps, clean stops.

Fake `claude` / `codex` executables stand in for the real CLIs. They record argv, cwd, the
environment they received, and stdin, then answer like the real stream formats.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from animedex.budget import Budget, BudgetConfigError, BudgetExceeded
from animedex.cli import app
from animedex.config import ModelSpec
from animedex.pipeline.p1 import run_p1
from animedex.providers.base import ProviderError, ProviderResponse, Usage
from animedex.providers.claude_cli import ClaudeCliProvider, served_model
from animedex.providers.cli_common import (
    CliAuthError,
    RateLimited,
    clean_env,
    login_status,
    stripped_names,
    summarize_init,
    unexpected_loads,
)
from animedex.providers.client import CallContext, LLMClient
from animedex.providers.codex_cli import DISABLED_FEATURES, PREFIX, CodexCliProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog

pytestmark = pytest.mark.unit

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}
POISON = {"ANTHROPIC_API_KEY": "sk-ant-test", "OPENAI_API_KEY": "sk-test", "ANTHROPIC_BASE_URL": "https://x",
          "CLAUDECODE": "1", "CLAUDE_CODE_OAUTH_TOKEN": "tok", "CLAUDE_CODE_ENTRYPOINT": "cli", "CODEX_API_KEY": "k"}

FAKE_CLAUDE = r'''
import json, os, sys
from pathlib import Path
here = Path(__file__)
cfg = json.loads(here.with_suffix(".json").read_text())
args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.251 (Claude Code)"); sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": cfg["logged_in"], "authMethod": cfg["auth_method"], "apiProvider": "firstParty"}))
    sys.exit(0)
stdin = sys.stdin.read()
with open(here.with_suffix(".calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": args, "cwd": os.getcwd(), "listing": os.listdir("."), "env": dict(os.environ),
                         "stdin": stdin}) + "\n")
model = args[args.index("--model") + 1]
init = {"type": "system", "subtype": "init", "model": model, "cwd": os.getcwd(), "apiKeySource": "none",
        "tools": ["StructuredOutput"], "mcp_servers": [], "slash_commands": ["simplify"], "agents": ["Plan"],
        "skills": ["simplify"], "plugins": [],
        "permissionMode": "default", "output_style": "default"}
print(json.dumps(init))
mode = cfg["mode"]
if mode == "ok":
    served = cfg.get("served", model)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "",
                      "structured_output": {"ok": True}, "total_cost_usd": 0.0123, "session_id": "s1",
                      "usage": {"input_tokens": 11, "output_tokens": 7},
                      "modelUsage": {served: {"outputTokens": 7}}}))
    sys.exit(0)
text = {"rate_limit": "Claude AI usage limit reached|1790000000", "auth": "Not logged in · Please run /login"}[mode]
print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": text}))
sys.exit(1)
'''

FAKE_CODEX = r'''
import json, os, sys
from pathlib import Path
here = Path(__file__)
cfg = json.loads(here.with_suffix(".json").read_text())
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.146.0"); sys.exit(0)
if args[:2] == ["login", "status"]:
    print(cfg["login"]); sys.exit(0)
stdin = sys.stdin.read()
schema = Path(args[args.index("--output-schema") + 1]).read_text()
with open(here.with_suffix(".calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": args, "cwd": os.getcwd(), "listing": os.listdir("."), "env": dict(os.environ),
                         "stdin": stdin, "schema": schema}) + "\n")
print(json.dumps({"type": "thread.started", "thread_id": "th_1"}))
print(json.dumps({"type": "turn.started"}))
if cfg["mode"] == "rate_limit":
    print(json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}))
    sys.exit(1)
Path(args[args.index("-o") + 1]).write_text(json.dumps({"ok": True}))
print(json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "error", "message": "demo warning"}}))
print(json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "{}"}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 5,
                                                       "output_tokens": 3}}))
'''


def fake_cli(tmp_path: Path, name: str, source: str, **cfg: Any) -> Path:
    path = tmp_path / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    path.with_suffix(".json").write_text(json.dumps(cfg), encoding="utf-8")
    return path


def calls(binary: Path) -> list[dict[str, Any]]:
    log = binary.with_suffix(".calls.jsonl")
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def poisoned_env(monkeypatch):
    for k, v in POISON.items():
        monkeypatch.setenv(k, v)


# --- isolation -------------------------------------------------------------------------------

def test_clean_env_keeps_only_the_allowlist():
    src = {"HOME": "/h", "PATH": "/bin", "FOO": "bar", **POISON}
    assert clean_env(src) == {"HOME": "/h", "PATH": "/bin"}
    assert stripped_names(src) == sorted(POISON)


def test_claude_call_runs_stripped_in_an_empty_scratch_dir(tmp_path, poisoned_env):
    binary = fake_cli(tmp_path, "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode="ok")
    p = ClaudeCliProvider(binary=str(binary), send_params=["effort"])
    resp = p.generate("PASS PROMPT", "USER INPUT", SCHEMA, {"model": "claude-sonnet-5", "effort": "high"})
    (call,) = calls(binary)
    assert not set(POISON) & set(call["env"]), "credential/session variables reached the CLI"
    assert call["listing"] == [] and Path(call["cwd"]).name.startswith("animedex-call-")
    assert not Path(call["cwd"]).exists(), "scratch dir must be removed after the call"
    argv = call["argv"]
    assert argv[argv.index("--system-prompt") + 1] == "PASS PROMPT" and call["stdin"] == "USER INPUT"
    assert argv[argv.index("--tools") + 1] == ""
    for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--json-schema"):
        assert flag in argv
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert "--bare" not in argv and "--fallback-model" not in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5" and argv[argv.index("--effort") + 1] == "high"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
    assert json.loads(resp.text) == {"ok": True} and resp.model == "claude-sonnet-5"
    assert resp.meta["shadow_cost_usd"] == 0.0123 and resp.meta["cli_version"] == "2.1.251"
    assert p.identity == "claude_cli@2.1.251" and unexpected_loads(p.last_init, {}) == []


def test_codex_call_is_ephemeral_read_only_and_feature_stripped(tmp_path, poisoned_env):
    binary = fake_cli(tmp_path, "codex", FAKE_CODEX, login="Logged in using ChatGPT", mode="ok")
    p = CodexCliProvider(binary=str(binary), send_params=["effort"])
    resp = p.generate("CHECK PROMPT", "CHECK INPUT", SCHEMA, {"model": "gpt-6-astra", "effort": "high"})
    (call,) = calls(binary)
    assert not set(POISON) & set(call["env"])
    assert call["listing"] == [] and not Path(call["cwd"]).exists()
    argv = call["argv"]
    assert argv[0] == "exec" and argv[-1] == "-"
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--json"):
        assert flag in argv
    disabled = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
    assert set(DISABLED_FEATURES) <= disabled and "shell_tool" in disabled
    assert argv[argv.index("-m") + 1] == "gpt-6-astra" and 'model_reasoning_effort="high"' in argv
    assert "skills.include_instructions=false" in argv and "include_environment_context=false" in argv
    assert os.path.realpath(argv[argv.index("-C") + 1]) == os.path.realpath(call["cwd"])
    assert json.loads(call["schema"]) == SCHEMA
    assert call["stdin"].startswith(PREFIX + "CHECK PROMPT") and call["stdin"].endswith("CHECK INPUT")
    assert json.loads(resp.text) == {"ok": True}
    assert resp.usage == Usage(20, 3, 5, 0) and resp.meta["billing"] == "subscription"
    assert p.last_init["served_model_source"] == "requested" and p.last_init["commands_run"] == 0
    assert "~/.codex/AGENTS.md" in p.last_init["user_level_leaks"]
    assert p.last_init["warnings"] == ["demo warning"] and "CLI warning: demo warning" in unexpected_loads(p.last_init, {})


# --- errors, login, served model ---------------------------------------------------------------

def test_expired_oauth_session_is_an_auth_error():
    from animedex.providers.cli_common import classify

    err = classify("claude_cli", "Failed to authenticate: OAuth session expired and could not be refreshed success")
    assert isinstance(err, CliAuthError)


def test_slash_prompts_are_not_read_as_commands(tmp_path):
    binary = fake_cli(tmp_path, "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode="ok")
    ClaudeCliProvider(binary=str(binary)).generate("s", "/compact now", SCHEMA, {"model": "claude-sonnet-5"})
    assert calls(binary)[0]["stdin"] == "Input:\n/compact now"


def test_rate_limit_and_auth_errors_are_distinct(tmp_path):
    for mode, exc in (("rate_limit", RateLimited), ("auth", CliAuthError)):
        binary = fake_cli(tmp_path / mode, "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode=mode)
        with pytest.raises(exc):
            ClaudeCliProvider(binary=str(binary)).generate("s", "u", SCHEMA, {"model": "claude-sonnet-5"})
    binary = fake_cli(tmp_path / "cx", "codex", FAKE_CODEX, login="Logged in using ChatGPT", mode="rate_limit")
    with pytest.raises(RateLimited):
        CodexCliProvider(binary=str(binary)).generate("s", "u", SCHEMA, {"model": "gpt-6-astra"})


def test_login_status_flags_api_key_logins(tmp_path):
    ok = fake_cli(tmp_path / "a", "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode="ok")
    assert ClaudeCliProvider(binary=str(ok)).login_status() == {"logged_in": True, "method": "claude.ai",
                                                                "api_key": False}
    key = fake_cli(tmp_path / "b", "claude", FAKE_CLAUDE, logged_in=True, auth_method="api_key", mode="ok")
    assert ClaudeCliProvider(binary=str(key)).login_status()["api_key"] is True
    out = fake_cli(tmp_path / "c", "claude", FAKE_CLAUDE, logged_in=False, auth_method="none", mode="ok")
    assert ClaudeCliProvider(binary=str(out)).login_status()["logged_in"] is False
    cx = fake_cli(tmp_path / "d", "codex", FAKE_CODEX, login="Logged in using an API key", mode="ok")
    assert CodexCliProvider(binary=str(cx)).login_status()["api_key"] is True
    assert login_status([str(tmp_path / "missing")])["logged_in"] is False


def test_served_model_comes_from_usage_not_the_request():
    assert served_model("claude-sonnet-5", {"model": "claude-sonnet-5"}, {"claude-sonnet-5": {}}) == (
        "claude-sonnet-5", [])
    # the requested model never ran: the model that did the work is reported
    assert served_model("claude-opus-5-5", {"model": "claude-opus-5-5"},
                        {"claude-sonnet-5": {"outputTokens": 900}, "claude-haiku-4-5-20251001": {"outputTokens": 4}}
                        ) == ("claude-sonnet-5", ["claude-haiku-4-5-20251001"])
    # a helper model alongside the requested one is surfaced, not hidden
    assert served_model("claude-sonnet-5", None, {"claude-sonnet-5": {}, "claude-haiku-4-5-20251001": {}}) == (
        "claude-sonnet-5", ["claude-haiku-4-5-20251001"])


def test_unexpected_loads_are_reported():
    init = summarize_init({"type": "system", "model": "m", "tools": ["StructuredOutput", "Bash"],
                           "mcp_servers": [{"name": "x"}], "skills": ["simplify", "graphify"],
                           "slash_commands": ["graphify"], "apiKeySource": "ANTHROPIC_API_KEY", "session_id": "x"})
    report = unexpected_loads(init, {"skills": {"graphify"}, "agents": set(), "slash_commands": {"graphify"}})
    assert "session_id" not in init
    assert "tools: Bash" in report and any(r.startswith("mcp_servers") for r in report)
    assert "user-level skills: graphify" in report and "user-level slash_commands: graphify" in report
    assert not any("simplify" in r for r in report), "bundled skills are not user-level"
    assert any("apiKeySource=ANTHROPIC_API_KEY" in r for r in report)
    assert unexpected_loads({"model": "gpt-6-astra", "commands_run": 2, "other_items": ["collab_tool_call"]}, {}) == [
        "commands run by the agent: 2", "agent actions beyond the answer: collab_tool_call"]


def test_user_level_names_reads_names_only(tmp_path):
    from animedex.providers.cli_common import user_level_names

    (tmp_path / ".claude" / "skills" / "graphify").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md").write_text("x")
    (tmp_path / ".claude" / "skills" / "not-a-skill").mkdir()
    (tmp_path / ".claude" / "agents").mkdir()
    (tmp_path / ".claude" / "agents" / "reviewer.md").write_text("x")
    names = user_level_names(tmp_path)
    assert names == {"skills": {"graphify"}, "agents": {"reviewer"}, "slash_commands": {"graphify"}}


# --- client: call caps, shadow cost, identity in keys and provenance -------------------------------

class FakeCli:
    live = True
    billing = "subscription"

    def __init__(self, identity="claude_cli@2.1.251", served=None, fail=None):
        self.name, self.identity, self.served, self.fail, self.n = "claude_cli", identity, served, fail, 0

    def generate(self, system, user, json_schema, params):
        self.n += 1
        if self.fail:
            raise self.fail
        return ProviderResponse('{"ok": true}', Usage(10, 5), self.served or params["model"],
                                meta={"cli": "claude_cli", "cli_version": "2.1.251", "shadow_cost_usd": 0.02,
                                      "init": {"model": params["model"]}})

    def resolve_model(self, model_id):
        return model_id


def cli_client(tmp_path, provider, budget, **kw):
    return LLMClient(provider=provider, provider_name="claude_cli", spec=ModelSpec(provider="claude_cli",
                     model="claude-sonnet-5"), prompt_version="p1", schema_version="1", vocab_version="1",
                     cache=ResponseCache(tmp_path / "cache"), runlog=RunLog(tmp_path / "runs", "run_c"),
                     budget=budget, title_guard=lambda tid: None, **kw)


def ctx(tid="solo_leveling_2024", record=None):
    return CallContext(pass_="P1", record_id=record or tid, title_id=tid, upstream="u")


def test_subscription_calls_need_call_caps_not_pricing(tmp_path):
    c = cli_client(tmp_path, FakeCli(), Budget(None, None, None))  # no price: fine for a subscription
    with pytest.raises(BudgetConfigError, match="calls_per_run"):
        c.complete_ex("s", "u", SCHEMA, ctx=ctx())


def test_shadow_cost_is_logged_never_charged_and_calls_are_counted(tmp_path):
    budget = Budget(1.0, 1.0, 1.0, calls_per_run=5, calls_per_title=2)
    c = cli_client(tmp_path, FakeCli(), budget)
    done = c.complete_ex("s", "u", SCHEMA, ctx=ctx())
    assert budget.spent_run == 0.0 and budget.calls_run == 1 and budget.calls_title["solo_leveling_2024"] == 1
    entry = json.loads((tmp_path / "runs" / "run_c" / "calls.jsonl").read_text().splitlines()[0])
    assert entry["billing"] == "subscription" and entry["cost_usd"] == 0.0 and entry["shadow_cost_usd"] == 0.02
    assert entry["provider"] == "claude_cli@2.1.251" and entry["cli"]["cli_version"] == "2.1.251"
    ledger = json.loads(c.runlog.write_ledger().read_text())
    assert ledger["total_cost_usd"] == 0.0 and ledger["total_shadow_cost_usd"] == 0.02
    assert done.provenance_model == "claude_cli@2.1.251/claude-sonnet-5"
    hit = c.complete_ex("s", "u", SCHEMA, ctx=ctx())
    assert hit.cache_hit and hit.provenance_model == done.provenance_model and budget.calls_run == 1


def test_call_caps_stop_before_the_next_call(tmp_path):
    budget = Budget(None, None, None, calls_per_run=2, calls_per_title=1)
    provider = FakeCli()
    c = cli_client(tmp_path, provider, budget)
    c.complete_ex("s", "u", SCHEMA, ctx=ctx())
    with pytest.raises(BudgetExceeded, match="for solo_leveling_2024"):
        c.complete_ex("s", "u2", SCHEMA, ctx=ctx(record="solo_leveling_2024.b"))
    c.complete_ex("s", "u", SCHEMA, ctx=ctx("mob_psycho_100_2016"))
    with pytest.raises(BudgetExceeded, match="2/2 calls this run"):
        c.complete_ex("s", "u", SCHEMA, ctx=ctx("invincible_2021"))
    assert provider.n == 2


def test_cli_version_is_part_of_the_cache_key(tmp_path):
    budget = Budget(None, None, None, calls_per_run=9, calls_per_title=9)
    a = cli_client(tmp_path, FakeCli("claude_cli@2.1.251"), budget)
    b = cli_client(tmp_path, FakeCli("claude_cli@2.2.0"), budget)
    assert a.key_for(ctx()) != b.key_for(ctx())


def test_rate_limit_propagates_and_counts_the_call(tmp_path):
    budget = Budget(None, None, None, calls_per_run=9, calls_per_title=9)
    c = cli_client(tmp_path, FakeCli(fail=RateLimited("claude_cli: usage limit")), budget)
    with pytest.raises(RateLimited):
        c.complete_ex("s", "u", SCHEMA, ctx=ctx())
    assert budget.calls_run == 1 and not list((tmp_path / "cache").rglob("*.json"))


def test_calls_are_paced(tmp_path):
    slept: list[float] = []
    budget = Budget(None, None, None, calls_per_run=9, calls_per_title=9)
    c = cli_client(tmp_path, FakeCli(), budget, min_interval_s=5.0, sleep=slept.append)
    c.complete_ex("s", "u", SCHEMA, ctx=ctx())
    c.complete_ex("s", "u", SCHEMA, ctx=ctx("mob_psycho_100_2016"))
    assert len(slept) == 1 and 4.0 < slept[0] <= 5.0


# --- stages stop cleanly on a usage limit ------------------------------------------------------------

class LimitedMock:
    """Offline provider whose plan limit is already used up."""

    live = False
    billing = "subscription"
    name = "claude_cli"
    identity = "claude_cli@test"

    def __init__(self):
        self.n = 0

    def generate(self, system, user, json_schema, params):
        self.n += 1
        raise RateLimited("claude_cli: usage/rate limit hit; stop and resume from cache later")

    def resolve_model(self, model_id):
        return model_id


def test_p1_stops_the_run_on_a_rate_limit(repo):
    from animedex.config import load_settings
    from animedex.guards import load_corpus
    from animedex.ontology import get_vocab

    settings = load_settings(repo)
    vocab = get_vocab(repo)
    entries = [e for e in load_corpus(repo).values() if "gold" not in e.role_tags][:3]
    assert len(entries) == 3
    provider = LimitedMock()
    client = LLMClient(provider=provider, provider_name="claude_cli", spec=settings.models["p1"], prompt_version="x",
                       schema_version="1", vocab_version=vocab.version, cache=ResponseCache(repo.cache),
                       runlog=RunLog(repo.raw_runs, "run_rl"))
    result = run_p1(repo, entries, client, vocab, settings, run_id="run_rl")
    assert provider.n == 1, "the run must stop at the first usage-limit error, not try every title"
    assert result.stopped and "limit" in result.stopped and not result.failed


# --- `animedex smoke --providers`: the G1a first live step, end to end with fake CLIs ----------------

def point_config_at(repo, claude: Path, codex: Path) -> None:
    data = yaml.safe_load(repo.config_file.read_text(encoding="utf-8"))
    data["providers"]["claude_cli"]["binary"] = str(claude)
    data["providers"]["codex_cli"]["binary"] = str(codex)
    data["budget"]["min_seconds_between_calls"] = 0
    repo.config_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_smoke_providers_makes_one_tiny_call_per_cli_and_reports(repo, tmp_path, poisoned_env):
    claude = fake_cli(tmp_path, "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode="ok")
    codex = fake_cli(tmp_path, "codex", FAKE_CODEX, login="Logged in using ChatGPT", mode="ok")
    point_config_at(repo, claude, codex)
    result = CliRunner().invoke(app, ["smoke", "--providers"])
    assert result.exit_code == 0, result.output
    assert len(calls(claude)) == 1 and len(calls(codex)) == 1
    out = result.output
    assert "ANTHROPIC_API_KEY" in out and "sk-ant-test" not in out  # names reported, values never
    assert "requested=claude-sonnet-5 served=claude-sonnet-5 ok=True" in out
    assert "requested=gpt-5.6-terra served=gpt-5.6-terra ok=True" in out
    assert "REPORT: user-level: ~/.codex/AGENTS.md" in out and "calls made: 2" in out
    ledger = json.loads(next(repo.raw_runs.rglob("ledger.json")).read_text())
    assert ledger["total_cost_usd"] == 0.0 and ledger["total_shadow_cost_usd"] == 0.0123


def test_smoke_providers_only_calls_the_named_provider(repo, tmp_path):
    claude = fake_cli(tmp_path, "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode="ok")
    codex = fake_cli(tmp_path, "codex", FAKE_CODEX, login="Logged in using ChatGPT", mode="ok")
    point_config_at(repo, claude, codex)
    result = CliRunner().invoke(app, ["smoke", "--providers", "--only", "claude_cli"])
    assert result.exit_code == 0, result.output
    assert len(calls(claude)) == 1 and calls(codex) == [] and "calls made: 1" in result.output


def test_smoke_providers_refuses_without_a_plan_login(repo, tmp_path):
    claude = fake_cli(tmp_path / "c", "claude", FAKE_CLAUDE, logged_in=False, auth_method="none", mode="ok")
    codex = fake_cli(tmp_path / "x", "codex", FAKE_CODEX, login="Logged in using an API key", mode="ok")
    point_config_at(repo, claude, codex)
    result = CliRunner().invoke(app, ["smoke", "--providers"])
    assert result.exit_code == 1
    assert calls(claude) == [] and calls(codex) == [], "no model call without a subscription login"
    assert "not logged in" in result.output and "would bill the API" in result.output


def test_env_var_names_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    assert "sk-secret-value" not in " ".join(stripped_names())
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-secret-value"  # the parent env is untouched


def test_provider_errors_are_provider_errors():
    assert issubclass(RateLimited, ProviderError) and issubclass(CliAuthError, ProviderError)


# --- native web search (VERIFY) and the test guard ---------------------------------------------------

WEB_STREAM = [
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "WebSearch", "input": {"query": "Ironvale Circuit 2021 anime"}},
        {"type": "tool_use", "id": "t2", "name": "WebFetch", "input": {"url": "https://ref.example/a", "prompt": "p"}},
        {"type": "tool_use", "id": "t3", "name": "WebFetch", "input": {"url": "https://down.example/b", "prompt": "p"}},
    ]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1",
         "content": 'Links: [{"title":"A","url":"https://ref.example/a"},{"title":"C","url":"https://c.example/x?y=1"}]'},
        {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "SECRET PAGE TEXT"}]},
        {"type": "tool_result", "tool_use_id": "t3", "is_error": True, "content": "fetch failed"},
    ]}},
]


def test_web_evidence_keeps_urls_never_text():
    from animedex.providers.claude_cli import web_evidence

    web = web_evidence(WEB_STREAM)
    assert web["queries"] == ["Ironvale Circuit 2021 anime"] and (web["searches"], web["fetches"]) == (1, 2)
    assert web["fetched"] == ["https://ref.example/a"]  # the failed fetch is not evidence
    assert web["urls"] == ["https://c.example/x?y=1", "https://ref.example/a"]
    assert "SECRET" not in json.dumps(web)


def test_web_calls_get_exactly_the_web_tools_with_a_turn_cap(tmp_path):
    binary = fake_cli(tmp_path, "claude", FAKE_CLAUDE, logged_in=True, auth_method="claude.ai", mode="ok")
    p = ClaudeCliProvider(binary=str(binary))
    web = {"max_searches": 5, "outcome_extra": 2, "max_fetches": 10, "max_turns": 17}
    resp = p.generate("s", "u", SCHEMA, {"model": "claude-sonnet-5", "web": web})
    argv = calls(binary)[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch,WebFetch" and argv[argv.index("--max-turns") + 1] == "17"
    assert resp.meta["web"]["urls"] == [] and "WebSearch" in resp.meta["expected_tools"]
    plain = p.args("s", SCHEMA, {"model": "claude-sonnet-5"})
    assert plain[plain.index("--tools") + 1] == "" and "--allowedTools" not in plain and "--max-turns" not in plain


class WebFake(FakeCli):
    def generate(self, system, user, json_schema, params):
        import dataclasses

        resp = super().generate(system, user, json_schema, params)
        return dataclasses.replace(resp, meta={**resp.meta, "web": {"urls": ["https://ref.example/a"], "searches": 1},
                                               "expected_tools": ["StructuredOutput", "WebSearch", "WebFetch"]})


def test_validate_sees_the_web_evidence_and_the_cache_keeps_it(tmp_path):
    seen = []
    c = cli_client(tmp_path, WebFake(), Budget(None, None, None, calls_per_run=9, calls_per_title=9))
    first = c.complete_ex("s", "u", SCHEMA, {"web": {"max_turns": 3}}, ctx=ctx(),
                          validate=lambda data, meta: seen.append(meta))
    assert seen == [{"web": {"urls": ["https://ref.example/a"], "searches": 1}}] and first.meta == seen[0]
    hit = c.complete_ex("s", "u", SCHEMA, {"web": {"max_turns": 3}}, ctx=ctx(), validate=lambda data, meta: 1 / 0)
    assert hit.cache_hit and hit.meta == first.meta  # cached answers keep their evidence, never re-validated
    entry = json.loads((tmp_path / "runs" / "run_c" / "calls.jsonl").read_text().splitlines()[0])
    assert entry["cli"]["web"]["urls"] == ["https://ref.example/a"] and entry["cli"]["unexpected"] == []


def test_codex_refuses_web_calls(tmp_path):
    binary = fake_cli(tmp_path, "codex", FAKE_CODEX, login="Logged in using ChatGPT", mode="ok")
    with pytest.raises(ProviderError, match="claude_cli only"):
        CodexCliProvider(binary=str(binary)).generate("s", "u", SCHEMA, {"model": "gpt-5.6-terra", "web": {"max_turns": 3}})
    assert calls(binary) == []


def test_tests_can_never_run_the_real_clis():
    with pytest.raises(ProviderError, match="blocked"):
        ClaudeCliProvider(binary="claude")
    with pytest.raises(ProviderError, match="blocked"):
        CodexCliProvider(binary="codex")


def test_milestone_smoke_in_tests_stops_before_any_real_call(repo, monkeypatch):
    for key in ("SEARCH_API_KEY",):
        monkeypatch.delenv(key, raising=False)
    result = CliRunner().invoke(app, ["smoke", "--stage", "m2"])
    assert result.exit_code == 1 and "blocked" in result.output + (result.stderr if result.stderr_bytes else "")

