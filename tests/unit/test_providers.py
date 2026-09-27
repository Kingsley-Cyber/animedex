"""Provider adapters, offline: httpx MockTransport for OpenAI-compatible, a fake SDK client for Anthropic."""

from __future__ import annotations

import json

import pytest

from animedex.providers.base import ProviderError
from animedex.providers.mock import MockProvider

pytestmark = pytest.mark.unit

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}




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


def test_a_session_limit_message_is_a_pause_not_a_failure():
    from animedex.providers.cli_common import RateLimited, classify

    err = classify("claude_cli", "You've hit your session limit · resets 12:30pm (America/Denver)")
    assert isinstance(err, RateLimited)
    assert isinstance(classify("claude_cli", "Rate limit exceeded"), RateLimited)
