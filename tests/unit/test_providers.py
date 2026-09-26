"""Provider adapters, offline: httpx MockTransport for OpenAI-compatible, a fake SDK client for Anthropic."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from animedex.providers.anthropic_adapter import FALLBACK_BETA, AnthropicProvider
from animedex.providers.base import ProviderError, ProviderRefusal, ProviderTruncated
from animedex.providers.mock import MockProvider
from animedex.providers.openai_compatible import OpenAICompatibleProvider

pytestmark = pytest.mark.unit

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def ok_body(content='{"ok": true}', finish="stop"):
    return {"id": "cmpl-1", "model": "served-model", "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3}}


def make_oai(handler, **kw):
    return OpenAICompatibleProvider("oai", "https://api.example.test/v1", kw.pop("api_key", "k"),
                                    transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_openai_compatible_json_schema_mode_and_usage():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=ok_body())

    resp = make_oai(handler, send_params=["max_tokens"]).generate(
        "sys", "user", SCHEMA, {"model": "cheap-model", "max_tokens": 50, "temperature": 0.9})
    body = seen["body"]
    assert body["model"] == "cheap-model" and body["max_tokens"] == 50 and "temperature" not in body
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert seen["auth"] == "Bearer k"
    assert (resp.text, resp.usage.input_tokens, resp.usage.output_tokens, resp.model) == ('{"ok": true}', 11, 3, "served-model")


def test_openai_compatible_local_endpoint_without_key_and_json_object_mode():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=ok_body())

    make_oai(handler, api_key=None, structured_output="json_object").generate("sys", "u", SCHEMA, {"model": "local-m"})
    assert seen["auth"] is None
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in seen["body"]["messages"][0]["content"]


def test_openai_compatible_retries_429_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "0"}) if len(calls) < 3 else httpx.Response(200, json=ok_body())

    assert make_oai(handler).generate("s", "u", SCHEMA, {"model": "m"}).text == '{"ok": true}'
    assert len(calls) == 3


def test_openai_compatible_gives_up_after_max_retries_and_on_4xx():
    with pytest.raises(ProviderError, match="HTTP 503"):
        make_oai(lambda r: httpx.Response(503), max_retries=2).generate("s", "u", SCHEMA, {"model": "m"})
    with pytest.raises(ProviderError, match="HTTP 400"):
        make_oai(lambda r: httpx.Response(400, text="bad")).generate("s", "u", SCHEMA, {"model": "m"})


def test_openai_compatible_truncation():
    with pytest.raises(ProviderTruncated):
        make_oai(lambda r: httpx.Response(200, json=ok_body(finish="length"))).generate("s", "u", SCHEMA, {"model": "m"})


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_response(stop_reason="end_turn", blocks=None, model="claude-served"):
    blocks = blocks if blocks is not None else [SimpleNamespace(type="thinking", thinking=""),
                                                SimpleNamespace(type="text", text='{"ok": true}')]
    usage = SimpleNamespace(input_tokens=20, output_tokens=4, cache_read_input_tokens=5, cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason=stop_reason, content=blocks, usage=usage, model=model, id="msg_1",
                           stop_details=SimpleNamespace(category="cyber", explanation="x"))


def fake_client(response):
    stable, beta = FakeMessages(response), FakeMessages(response)
    return SimpleNamespace(messages=stable, beta=SimpleNamespace(messages=beta)), stable, beta


def test_anthropic_structured_output_effort_and_no_sampling_params():
    client, stable, beta = fake_client(fake_response())
    p = AnthropicProvider("anthropic", client=client, send_params=["max_tokens", "effort"])
    resp = p.generate("sys", "user", SCHEMA, {"model": "strong", "effort": "high", "max_tokens": 900, "temperature": 0.7})
    kw = stable.kwargs
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "high"}
    assert kw["max_tokens"] == 900 and "temperature" not in kw and kw["system"] == "sys"
    assert beta.kwargs is None
    assert (resp.text, resp.usage.input_tokens, resp.usage.cache_read_tokens, resp.model) == ('{"ok": true}', 20, 5, "claude-served")


def test_anthropic_fallbacks_use_beta_endpoint_and_record_served_model():
    client, stable, beta = fake_client(fake_response(model="fallback-model"))
    resp = AnthropicProvider("anthropic", client=client, fallbacks="default").generate("s", "u", SCHEMA, {"model": "strong"})
    assert stable.kwargs is None
    assert beta.kwargs["betas"] == [FALLBACK_BETA] and beta.kwargs["fallbacks"] == "default"
    assert resp.model == "fallback-model"


@pytest.mark.parametrize("stop, exc", [("refusal", ProviderRefusal), ("max_tokens", ProviderTruncated)])
def test_anthropic_stop_reasons_checked_before_content(stop, exc):
    client, _, _ = fake_client(fake_response(stop_reason=stop))
    with pytest.raises(exc):
        AnthropicProvider("anthropic", client=client).generate("s", "u", SCHEMA, {"model": "strong"})


def test_mock_provider_fixtures_and_attempt_lists(tmp_path):
    (tmp_path / "P1").mkdir()
    (tmp_path / "P1" / "x_2020.txt").write_text("not json")
    (tmp_path / "P1" / "x_2020.repair.json").write_text('{"ok": true}')
    m = MockProvider(fixtures_dir=tmp_path, responses={("P2", "y_2020"): ["bad", {"ok": True}]})
    meta = lambda p, r, a: {"model": "m", "_meta": {"pass": p, "record_id": r, "attempt": a}}  # noqa: E731
    assert m.generate("s", "u", SCHEMA, meta("P1", "x_2020", 0)).text == "not json"
    assert json.loads(m.generate("s", "u", SCHEMA, meta("P1", "x_2020", 1)).text) == {"ok": True}
    assert m.generate("s", "u", SCHEMA, meta("P2", "y_2020", 0)).text == "bad"
    with pytest.raises(ProviderError):
        m.generate("s", "u", SCHEMA, meta("P3", "z_2020", 0))
