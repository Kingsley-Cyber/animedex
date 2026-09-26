"""Embeddings adapter (local OpenAI-compatible + deterministic mock) and the search interface."""

from __future__ import annotations

import json

import httpx
import pytest

from animedex.embeddings.base import LocalEmbedder, MockEmbedder, cosine
from animedex.search.base import MockSearch, SearchResult
from animedex.store.runlog import TransientText

pytestmark = pytest.mark.unit


def test_mock_embedder_is_deterministic_and_normalized():
    e = MockEmbedder(dim=32)
    a, b, c = e.embed(["A lantern keeper", "a  lantern   keeper", "A courier"])
    assert a == b and len(a) == 32
    assert cosine(a, b) == pytest.approx(1.0)
    assert cosine(a, c) < 0.99


def test_local_embedder_posts_to_embeddings_and_orders_by_index():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0.0, 1.0]},
                                                  {"index": 0, "embedding": [1.0, 0.0]}]})

    emb = LocalEmbedder("http://localhost:11434/v1", "embed-model", transport=httpx.MockTransport(handler))
    vectors = emb.embed(["first", "second"])
    assert seen["path"] == "/v1/embeddings" and seen["body"] == {"model": "embed-model", "input": ["first", "second"]}
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_mock_search_returns_transient_pages_and_counts_calls():
    s = MockSearch(results={"q": [SearchResult("https://e.org/a", "A", "snippet")]}, pages={"https://e.org/a": "page"})
    assert s.search("q")[0].url == "https://e.org/a"
    page = s.fetch("https://e.org/a")
    assert isinstance(page, TransientText) and page.text == "page"
    assert (s.search_calls, s.fetch_calls) == (1, 1)
    with pytest.raises(KeyError):
        s.fetch("https://e.org/missing")
