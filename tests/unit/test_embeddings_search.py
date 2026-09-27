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


# ---------------------------------------------------------------- v1.7: Polymath's embedder first, Ollama fallback
POLYMATH = "127.0.0.1:8742"
QWEN = "Qwen/Qwen3-Embedding-0.6B"


class Services:
    """Fake Polymath sidecar (127.0.0.1:8742) and Ollama (localhost:11434); records every request."""

    def __init__(self, *, polymath="ready", ollama="ready", served=QWEN, dim=4):
        self.polymath, self.ollama, self.served, self.dim = polymath, ollama, served, dim
        self.seen: list[httpx.Request] = []

    def vector(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0, 0.0][: self.dim]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if request.url.port == 8742:
            if self.polymath == "down":
                raise httpx.ConnectError("connection refused", request=request)
            if path == "/ready":
                ok = self.polymath == "ready"
                return httpx.Response(200 if ok else 503, json={"ready": ok} if ok else {"ready": False, "reason": "model not loaded"})
            if path == "/manifest":
                return httpx.Response(200, json={"identity": {"model": {"id": self.served}}})
            if path == "/infer":
                body = json.loads(request.content)
                assert 1 <= len(body["texts"]) <= 32 and body["representation_kind"] == "child_chunk"
                return httpx.Response(200, json={"vectors": [self.vector(t) for t in body["texts"]],
                                                 "contract_id": "neural-embed-v1", "dimension": self.dim,
                                                 "model_release": "neural-embed-v1", "queued_ms": 0.0,
                                                 "priority": "background"})
        if request.url.port == 11434:
            if self.ollama == "down":
                raise httpx.ConnectError("connection refused", request=request)
            if path == "/v1/models":
                ids = ["llama3:8b"] + (["qwen3-embedding:0.6b"] if self.ollama == "ready" else [])
                return httpx.Response(200, json={"object": "list", "data": [{"id": i} for i in ids]})
            if path == "/v1/embeddings":
                if self.ollama == "no_model":
                    return httpx.Response(404, json={"error": {"message": 'model "qwen3-embedding:0.6b" not found, '
                                                                          "try pulling it first"}})
                texts = json.loads(request.content)["input"]
                return httpx.Response(200, json={"data": [{"index": i, "embedding": self.vector(t)}
                                                          for i, t in enumerate(texts)]})
        raise AssertionError(f"unexpected request {request.url}")

    def ports(self) -> list[int]:
        return [r.url.port for r in self.seen]


def backend(repo, services):
    from animedex.config import load_settings
    from animedex.embeddings.base import build_embedder

    return build_embedder(load_settings(repo), {}, transport=httpx.MockTransport(services))


def test_config_puts_polymaths_embedder_first_and_ollama_second(repo):
    from animedex.config import load_settings

    s = load_settings(repo)
    spec = s.models["embeddings"]
    assert (spec.provider, spec.model) == ("polymath_embedder", QWEN)
    assert s.providers["polymath_embedder"].type == "polymath_embedder"
    assert s.providers["polymath_embedder"].base_url == f"http://{POLYMATH}"
    assert (spec.fallback.provider, spec.fallback.model) == ("local", "qwen3-embedding:0.6b")
    assert s.providers["local"].base_url == "http://localhost:11434/v1"


def test_polymath_embedder_batches_by_32_and_sends_no_priority_header():
    from animedex.embeddings.base import PolymathEmbedder

    services = Services()
    emb = PolymathEmbedder(f"http://{POLYMATH}", QWEN, transport=httpx.MockTransport(services))
    texts = [f"premise {'x' * i}" for i in range(70)]
    vectors = emb.embed(texts)
    assert emb.name == "polymath/Qwen3-Embedding-0.6B"
    assert [len(json.loads(r.content)["texts"]) for r in services.seen] == [32, 32, 6]
    assert vectors == [services.vector(t) for t in texts]  # order kept across batches
    assert all("x-polymath-priority" not in r.headers for r in services.seen)  # background priority
    assert emb.embed([]) == [] and len(services.seen) == 3


def test_polymath_is_chosen_when_ready_and_ollama_is_never_asked(repo):
    services = Services()
    emb = backend(repo, services)
    assert emb.name == "polymath/Qwen3-Embedding-0.6B" and set(services.ports()) == {8742}
    assert [r.url.path for r in services.seen] == ["/ready", "/manifest"]
    emb.embed(["a courier trades memories for power"])
    assert set(services.ports()) == {8742}


@pytest.mark.parametrize("polymath,served", [("not_ready", QWEN), ("down", QWEN), ("ready", "other/embedder-1")])
def test_the_ollama_copy_serves_the_whole_run_when_polymath_is_not_usable(repo, polymath, served):
    services = Services(polymath=polymath, served=served)
    emb = backend(repo, services)
    assert emb.name == "local/qwen3-embedding:0.6b"
    before = len(services.seen)
    emb.embed(["one premise", "another premise"])
    assert services.ports()[before:] == [11434]  # one backend for the run: never back to Polymath


def test_no_ready_backend_stops_with_a_message_naming_both(repo):
    from animedex.embeddings.base import EmbedderUnavailable

    with pytest.raises(EmbedderUnavailable) as both_down:
        backend(repo, Services(polymath="down", ollama="down"))
    assert str(both_down.value) == ("Polymath's embedder at 127.0.0.1:8742 isn't ready and Ollama isn't running. "
                                    "Start one of them, then run the same command again.")
    with pytest.raises(EmbedderUnavailable, match="ollama pull qwen3-embedding:0.6b"):
        backend(repo, Services(polymath="not_ready", ollama="no_model"))


def test_ollama_alone_says_how_to_start_it_or_pull_the_model():
    from animedex.embeddings.base import OLLAMA_DOWN, EmbedderUnavailable, model_missing

    assert OLLAMA_DOWN == ("Ollama is not running. Start it (open the Ollama app, or run `ollama serve`), "
                           "then run the same command again.")
    assert model_missing("qwen3-embedding:0.6b") == ("The embedding model isn't installed. "
                                                     "Run: ollama pull qwen3-embedding:0.6b")
    down = LocalEmbedder("http://localhost:11434/v1", "qwen3-embedding:0.6b",
                         transport=httpx.MockTransport(Services(ollama="down")))
    assert down.readiness().alone == OLLAMA_DOWN
    with pytest.raises(EmbedderUnavailable) as exc:
        down.embed(["a premise"])
    assert str(exc.value) == OLLAMA_DOWN
    missing = LocalEmbedder("http://localhost:11434/v1", "qwen3-embedding:0.6b",
                            transport=httpx.MockTransport(Services(ollama="no_model")))
    assert missing.readiness().alone == model_missing("qwen3-embedding:0.6b")
    with pytest.raises(EmbedderUnavailable) as exc:
        missing.embed(["a premise"])
    assert str(exc.value) == model_missing("qwen3-embedding:0.6b")


def test_polymath_failing_mid_run_stops_instead_of_switching_backends():
    from animedex.embeddings.base import EmbedderUnavailable, PolymathEmbedder

    services = Services()
    emb = PolymathEmbedder(f"http://{POLYMATH}", QWEN, transport=httpx.MockTransport(services))
    services.polymath = "down"
    with pytest.raises(EmbedderUnavailable, match="Polymath's embedder at 127.0.0.1:8742 stopped answering"):
        emb.embed(["a premise"])
    assert 11434 not in services.ports()


def test_embeddings_only_providers_are_not_model_providers(repo):
    from animedex.config import live_problems, load_settings
    from animedex.providers.factory import ProviderConfigError, build_provider

    s = load_settings(repo)
    with pytest.raises(ProviderConfigError, match="embeddings only"):
        build_provider("polymath_embedder", s, {})
    assert not [p for p in live_problems(s, {}, ["embeddings"]) if "embeddings" in p or "polymath" in p]
    s.providers["polymath_embedder"].base_url = None
    s.models["embeddings"].fallback.provider = "nowhere"
    problems = live_problems(s, {}, ["embeddings"])
    assert "providers.polymath_embedder: set base_url" in problems
    assert any("models.embeddings.fallback.provider" in p for p in problems)
