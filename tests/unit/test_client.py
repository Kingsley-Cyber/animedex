"""LLMClient: cache, one repair attempt, budget, guard, redacted logging."""

from __future__ import annotations

import json

import pytest

from animedex.budget import Budget, BudgetExceeded, Price
from animedex.config import ModelSpec
from animedex.providers.base import ProviderResponse, Usage
from animedex.providers.client import CallContext, ClientConfigError, InvalidOutput, LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog, TransientText

pytestmark = pytest.mark.unit

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def make_client(tmp_path, provider, **kw):
    return LLMClient(provider=provider, provider_name=getattr(provider, "name", "p"), spec=ModelSpec(provider="p", model="m"),
                     prompt_version="1.0.0", schema_version="1.2.0", vocab_version="1.2.0",
                     cache=ResponseCache(tmp_path / "cache"), runlog=RunLog(tmp_path / "runs", "run_t"), **kw)


def ctx(record_id="x_2020", **kw):
    return CallContext(pass_="P1", record_id=record_id, upstream="sha256:up", **kw)


def check_ok(data):
    if data.get("ok") is not True:
        raise ValueError("ok must be true")


def test_complete_returns_json_and_second_call_hits_cache(tmp_path):
    mock = MockProvider(responses={("P1", "x_2020"): {"ok": True}})
    client = make_client(tmp_path, mock)
    data, usage = client.complete("sys", "user", SCHEMA, ctx=ctx())
    assert data == {"ok": True} and usage.input_tokens > 0
    again = client.complete_ex("sys", "user", SCHEMA, ctx=ctx())
    assert again.cache_hit and again.usage == Usage() and len(mock.calls) == 1


def test_malformed_json_gets_one_repair(tmp_path):
    mock = MockProvider(responses={("P1", "x_2020"): ["```json\n{not json", {"ok": True}]})
    data, _ = make_client(tmp_path, mock).complete("s", "u", SCHEMA, ctx=ctx(), validate=check_ok)
    assert data == {"ok": True}
    assert [c["attempt"] for c in mock.calls] == [0, 1]
    assert "previous reply was rejected" in mock.calls[1]["user"]


def test_invalid_twice_raises_invalid_output(tmp_path):
    mock = MockProvider(responses={("P1", "x_2020"): ["nope", {"ok": False}]})
    with pytest.raises(InvalidOutput) as err:
        make_client(tmp_path, mock).complete("s", "u", SCHEMA, ctx=ctx(), validate=check_ok)
    assert len(err.value.errors) == 2 and len(mock.calls) == 2


def test_fenced_json_is_accepted(tmp_path):
    mock = MockProvider(responses={("P1", "x_2020"): '```json\n{"ok": true}\n```'})
    assert make_client(tmp_path, mock).complete("s", "u", SCHEMA, ctx=ctx())[0] == {"ok": True}


class FakeLive:
    name = "live"
    live = True

    def __init__(self):
        self.calls = 0

    def generate(self, system, user, json_schema, params):
        self.calls += 1
        assert "_meta" not in params
        return ProviderResponse(json.dumps({"ok": True}), Usage(1_000_000, 0), "live/m")


def test_live_client_requires_price_budget_and_guard(tmp_path):
    with pytest.raises(ClientConfigError):
        make_client(tmp_path, FakeLive())


def test_live_call_runs_guard_then_budget_and_charges(tmp_path):
    seen = []
    budget = Budget(run_cap=10.0, per_title_cap=2.5, per_episode_cap=1.0)
    live = FakeLive()
    client = make_client(tmp_path, live, price=Price(2.0, 0.0), budget=budget, title_guard=seen.append)
    client.complete("s", "u", SCHEMA, ctx=ctx(title_id="x_2020"))
    assert seen == ["x_2020"] and budget.spent_run == pytest.approx(2.0)
    client.complete("s", "u2", SCHEMA, ctx=ctx("x_2020.b", title_id="x_2020"))
    assert budget.spent_title["x_2020"] == pytest.approx(4.0)
    with pytest.raises(BudgetExceeded):
        client.complete("s", "u3", SCHEMA, ctx=ctx("x_2020.c", title_id="x_2020"))
    assert live.calls == 2  # stopped cleanly after the unit that crossed the cap


def test_guard_refusal_prevents_the_call(tmp_path):
    class Refuse(RuntimeError):
        pass

    def guard(title_id):
        raise Refuse(title_id)

    live = FakeLive()
    client = make_client(tmp_path, live, price=Price(1, 1), budget=Budget(10, 10, 10), title_guard=guard)
    with pytest.raises(Refuse):
        client.complete("s", "u", SCHEMA, ctx=ctx(title_id="gold_title_2011"))
    assert live.calls == 0


def test_fetched_text_redacted_in_logs_but_sent_to_provider(tmp_path):
    page = "A fetched synthetic page body long enough to trip the redaction leak check for sure."
    mock = MockProvider(responses={("P1", "x_2020"): {"ok": True}})
    client = make_client(tmp_path, mock)
    client.complete("s", f"Evidence: {page}", SCHEMA, ctx=ctx(transients=(TransientText("https://e.org/p", page),)))
    assert page in mock.calls[0]["user"]
    logged = (tmp_path / "runs" / "run_t" / "calls.jsonl").read_text()
    assert page not in logged and "https://e.org/p" in logged


# ---------------------------------------------------------------- length repair, last resort (D-030)
def check_notes(data):
    from animedex.pipeline.common import raise_problems
    from animedex.textutil import word_count

    problems = []
    for i, p in enumerate(data.get("proofs") or []):
        n = word_count(p["test"]["note"])
        if n > 5:
            problems.append(f"t.m.{i:03d}: test.note: Value error, {n} words exceeds the 5-word limit")
        if p.get("quote"):
            problems.append(f"t.m.{i:03d}: no quotes")
    raise_problems(problems)


LONG = {"proofs": [{"test": {"note": "one two three four five six"}}, {"test": {"note": "short enough"}}]}


def test_a_text_over_its_cap_is_shortened_instead_of_regenerating_the_answer(tmp_path):
    mock = MockProvider(responses={("P1", "x_2020"): [LONG],
                                   ("P1", "x_2020.shorten"): {"items": [{"path": "proofs.0.test.note",
                                                                         "text": "one two three"}]}})
    client = make_client(tmp_path, mock)
    done = client.complete_ex("s", "u", SCHEMA, ctx=ctx(), validate=check_notes)
    assert done.data["proofs"][0]["test"]["note"] == "one two three"
    assert done.data["proofs"][1] == LONG["proofs"][1]  # everything else as the model wrote it
    assert [c["record_id"] for c in mock.calls] == ["x_2020", "x_2020.shorten"]  # no full regeneration
    assert mock.calls[1]["user"] == "proofs.0.test.note: one two three four five six [max 5 words]"
    again = client.complete_ex("s", "u", SCHEMA, ctx=ctx(), validate=check_notes)
    assert again.cache_hit and again.data == done.data and len(mock.calls) == 2  # the repaired output is cached


def test_other_problems_or_a_failed_shortening_still_quarantine(tmp_path):
    mixed = {"proofs": [{"test": {"note": "one two three four five six"}, "quote": True}]}
    mock = MockProvider(responses={("P1", "x_2020"): [mixed, mixed]})
    with pytest.raises(InvalidOutput):
        make_client(tmp_path, mock).complete_ex("s", "u", SCHEMA, ctx=ctx(), validate=check_notes)
    assert len(mock.calls) == 2  # not a length-only problem: no shorten call
    bad = {"items": [{"path": "proofs.0.test.note", "text": "still one two three four five six"}]}
    mock = MockProvider(responses={("P1", "x_2020"): [LONG, LONG], ("P1", "x_2020.shorten"): [bad, bad, bad, bad]})
    with pytest.raises(InvalidOutput) as err:
        make_client(tmp_path / "b", mock).complete_ex("s", "u", SCHEMA, ctx=ctx(), validate=check_notes)
    assert "6 words exceeds the 5-word limit" in err.value.errors[-1]
    # shorten (2 attempts), full repair, shorten again as the last resort (2 attempts)
    assert [c["record_id"] for c in mock.calls] == ["x_2020", *["x_2020.shorten"] * 2, "x_2020",
                                                    *["x_2020.shorten"] * 2]
