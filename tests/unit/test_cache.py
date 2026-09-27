"""AC-06: stable cache keys; P3 prompt change does not invalidate P1/P2; support-count changes
invalidate nothing; status changes do."""

from __future__ import annotations

import pytest

from animedex.store.cache import ResponseCache, cache_key

pytestmark = pytest.mark.unit


def key(pass_: str, prompt_version: str, upstream: str, params: dict | None = None, record_id: str = "t_2020") -> str:
    return cache_key(record_id=record_id, pass_=pass_, prompt_version=prompt_version, schema_version="1.2.0",
                     vocab_version="1.2.0", model="anthropic/strong", params=params or {}, upstream=upstream)




def test_keys_are_stable_and_prefixed():
    a, b = key("P1", "1.0.0", "sha256:x"), key("P1", "1.0.0", "sha256:x")
    assert a == b and a.startswith("sha256:") and len(a) == len("sha256:") + 64


def test_transport_params_ignored_real_params_count():
    base = key("P1", "1.0.0", "sha256:x", {"max_tokens": 100})
    assert key("P1", "1.0.0", "sha256:x", {"max_tokens": 100, "_meta": {"attempt": 1}}) == base
    assert key("P1", "1.0.0", "sha256:x", {"max_tokens": 200}) != base
    assert key("P1", "1.0.0", "sha256:x", {"max_tokens": 100, "rerun": 2}) != base  # agreement reruns


def test_response_cache_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path)
    k = key("P1", "1.0.0", "sha256:x")
    assert cache.get("P1", k) is None
    cache.put("P1", k, {"json": {"a": 1}, "model": "m"})
    assert cache.get("P1", k) == {"json": {"a": 1}, "model": "m"}
