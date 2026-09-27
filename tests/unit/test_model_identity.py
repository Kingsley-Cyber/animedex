"""G1a: fallbacks can't silently change the model. The served model is what's recorded; a
substituted answer is never cached; strict slots (CHECK, judge) refuse substitution; model ids
must resolve before live runs; smoke readiness is per milestone."""

from __future__ import annotations

import json

import pytest

from animedex.budget import Budget
from animedex.config import ModelSpec
from animedex.providers.base import ProviderResponse, Usage
from animedex.providers.client import CallContext, LLMClient, ModelSubstituted, same_model
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
                     runlog=RunLog(tmp_path / "r", "run_m"), budget=Budget(10))


CTX = CallContext(pass_="P2", record_id="x_2020", upstream="sha256:u")


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


