"""G1a: fallbacks can't silently change the model. The served model is what's recorded; a
substituted answer is never cached; strict slots (CHECK, judge) refuse substitution; model ids
must resolve before live runs; smoke readiness is per milestone."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from animedex.budget import Budget, Price
from animedex.cli import app
from animedex.config import ModelSpec
from animedex.providers.anthropic_adapter import AnthropicProvider
from animedex.providers.base import ProviderError, ProviderResponse, Usage
from animedex.providers.client import CallContext, LLMClient, ModelSubstituted, same_model
from animedex.providers.openai_compatible import OpenAICompatibleProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog

pytestmark = pytest.mark.unit

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


class Serving:
    name, live = "live", True

    def __init__(self, served: str):
        self.served, self.calls = served, 0

    def generate(self, system, user, json_schema, params):
        self.calls += 1
        return ProviderResponse(json.dumps({"ok": True}), Usage(10, 5), self.served)

    def resolve_model(self, model_id):
        return model_id


def client(tmp_path, provider, *, strict=False, model="claude-opus-5-5"):
    return LLMClient(provider=provider, provider_name="anthropic", spec=ModelSpec(provider="anthropic", model=model, strict_model=strict),
                     prompt_version="1", schema_version="1.2.0", vocab_version="1.2.1", cache=ResponseCache(tmp_path / "c"),
                     runlog=RunLog(tmp_path / "r", "run_m"), price=Price(1, 1), budget=Budget(10, 10, 10),
                     title_guard=lambda t: None)


CTX = CallContext(pass_="P2", record_id="x_2020", upstream="sha256:u", title_id="x_2020")


@pytest.mark.parametrize("requested, served, same", [
    ("claude-sonnet-5", "claude-sonnet-5", True),
    ("claude-haiku-4-5", "claude-haiku-4-5-20251001", True),
    ("claude-haiku-4-5-20251001", "claude-haiku-4-5", True),
    ("claude-opus-5-5", "claude-opus-5", False),
    ("openai/some-model", "anthropic/claude-sonnet-5", False),
])
def test_same_model(requested, served, same):
    assert same_model(requested, served) is same


def test_fallback_answer_recorded_but_never_cached(tmp_path):
    live = Serving("claude-opus-5")
    c = client(tmp_path, live)
    first = c.complete_ex("s", "u", SCHEMA, ctx=CTX)
    assert first.substituted and first.model == "claude-opus-5"
    second = c.complete_ex("s", "u", SCHEMA, ctx=CTX)
    assert not second.cache_hit and live.calls == 2  # rerun retries the requested model
    log = (tmp_path / "r" / "run_m" / "calls.jsonl").read_text()
    assert "substituted: served by claude-opus-5" in log


def test_same_model_answer_is_cached(tmp_path):
    live = Serving("claude-opus-5-5")
    c = client(tmp_path, live)
    c.complete_ex("s", "u", SCHEMA, ctx=CTX)
    assert c.complete_ex("s", "u", SCHEMA, ctx=CTX).cache_hit and live.calls == 1


def test_strict_slot_refuses_substitution(tmp_path):
    live = Serving("anthropic/claude-sonnet-5")
    c = client(tmp_path, live, strict=True, model="openai/some-judge")
    with pytest.raises(ModelSubstituted):
        c.complete_ex("s", "u", SCHEMA, ctx=CTX)
    assert not list((tmp_path / "c").rglob("*.json"))
    assert "refused: strict slot" in (tmp_path / "r" / "run_m" / "calls.jsonl").read_text()


def test_anthropic_resolve_model_uses_models_api():
    fake = SimpleNamespace(models=SimpleNamespace(retrieve=lambda mid: SimpleNamespace(id=mid, display_name="Claude Opus 5.5")))
    assert AnthropicProvider("anthropic", client=fake).resolve_model("claude-opus-5-5") == "Claude Opus 5.5"


def test_openai_compatible_resolve_model_lists_models():
    def handler(request):
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "openai/some-judge"}]})

    p = OpenAICompatibleProvider("or", "https://openrouter.example/api/v1", "k", transport=httpx.MockTransport(handler))
    assert p.resolve_model("openai/some-judge") == "openai/some-judge"
    with pytest.raises(ProviderError, match="not listed"):
        p.resolve_model("openai/missing")


def test_smoke_m2_blocks_only_on_m2_needs(repo, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL", "SEARCH_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    data = yaml.safe_load(repo.config_file.read_text(encoding="utf-8"))
    data["models"]["check"]["model"] = "<codex-model>"  # an unfilled slot that only M3 needs
    data["search"] = {"backend": "brave", "api_key_env": "SEARCH_API_KEY"}  # a missing key that M2 needs
    repo.config_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = CliRunner().invoke(app, ["smoke", "--stage", "m2"])
    assert result.exit_code == 1
    assert "SEARCH_API_KEY" in result.output
    assert "API_KEY" not in result.output.replace("SEARCH_API_KEY", "")  # CLI slots never need a model key (G1a)
    assert "models.check" not in result.output and "embeddings" not in result.output
    result = CliRunner().invoke(app, ["smoke", "--stage", "m3"])
    assert "models.check.model" in result.output
