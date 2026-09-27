"""Embeddings adapter (03): premise similarity (the IDEATE clone gate) and ROLLUP proposal matching.

Owner ruling 2026-09-27 (v1.7 §2): the model is Qwen3-Embedding-0.6B, the one allowed local model.
- Primary: Polymath's embedder sidecar, which already serves that model at full precision on the Mac
  GPU. `POST /infer` takes 1-32 texts with `representation_kind: child_chunk` (no query prefix, so
  premise-vs-premise similarity stays symmetric) and returns L2-normalized vectors. No priority header
  is sent: requests run at background priority and never pre-empt Polymath's interactive work.
- Fallback: the Ollama copy (`qwen3-embedding:0.6b`) behind its OpenAI-compatible /embeddings
  endpoint, used only when Polymath's embedder isn't ready (a second copy on the same GPU contends).
`build_embedder` picks ONE backend per run and never switches mid-run: two backends' cosines are not
on one scale. The chosen backend's `name` is what callers record. The mock is deterministic.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

READY_TIMEOUT_S = 6.0  # readiness probes; Polymath's /ready can wait up to 5 s for a busy GPU (DECISIONS D-020)
POLYMATH_BATCH = 32    # the sidecar's per-request limit
AGAIN = "then run the same command again."
OLLAMA_DOWN = f"Ollama is not running. Start it (open the Ollama app, or run `ollama serve`), {AGAIN}"


class EmbedderUnavailable(RuntimeError):
    """A plain-language stop: which embedder isn't available and how to start it."""


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Readiness:
    ok: bool
    problem: str = ""  # what is wrong, as a clause ("Ollama isn't running")
    fix: str = ""      # what to do, as a clause ("start Ollama ...")
    alone: str = ""    # the whole message when this is the only backend

    @property
    def needs_start(self) -> bool:
        return self.fix.startswith("start ")


READY = Readiness(True)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def model_missing(model: str) -> str:
    return f"The embedding model isn't installed. Run: ollama pull {model}"


def _host(base_url: str) -> str:
    return urlsplit(base_url).netloc or base_url


class PolymathEmbedder:
    """Polymath's embedder sidecar (Qwen3-Embedding-0.6B on the Mac GPU)."""

    def __init__(self, base_url: str, model: str, *, transport: httpx.BaseTransport | None = None,
                 timeout_s: float = 300.0):
        self.name = f"polymath/{model.rsplit('/', 1)[-1]}"
        self.model = model
        self.where = _host(base_url)
        # no X-Polymath-Priority header, ever: background priority (owner rule)
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport)

    def _not_ready(self, why: str = "isn't ready") -> Readiness:
        problem = f"Polymath's embedder at {self.where} {why}"
        return Readiness(False, problem, "start Polymath's embedder", f"{problem}. Start it, {AGAIN}")

    def readiness(self, timeout_s: float = READY_TIMEOUT_S) -> Readiness:
        """Usable when /ready says ready (a real forward pass) and /manifest names the configured model."""
        try:
            ready = self._client.get("/ready", timeout=timeout_s)
            if ready.status_code != 200 or ready.json().get("ready") is not True:
                return self._not_ready()
            manifest = self._client.get("/manifest", timeout=timeout_s).json()
        except (httpx.HTTPError, ValueError, AttributeError):
            return self._not_ready()
        served = ((manifest.get("identity") or {}).get("model") or {}).get("id")
        if served != self.model:
            return self._not_ready(f"serves {served or 'an unknown model'}, not {self.model}")
        return READY

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), POLYMATH_BATCH):
            chunk = texts[start:start + POLYMATH_BATCH]
            try:
                resp = self._client.post("/infer", json={"texts": chunk, "representation_kind": "child_chunk"})
            except httpx.HTTPError as exc:
                raise EmbedderUnavailable(f"Polymath's embedder at {self.where} stopped answering "
                                          f"({type(exc).__name__}). Make sure it is running, {AGAIN}") from None
            if resp.status_code != 200:
                raise EmbedderUnavailable(f"Polymath's embedder at {self.where} refused the request "
                                          f"(HTTP {resp.status_code}). Check it is ready, {AGAIN}")
            try:
                body = resp.json()
                vectors, dim = body.get("vectors") or [], body.get("dimension")
            except (ValueError, AttributeError):
                raise EmbedderUnavailable(f"Polymath's embedder at {self.where} answered without vectors; "
                                          "nothing was used.") from None
            if len(vectors) != len(chunk) or (dim and any(len(v) != dim for v in vectors)):
                raise EmbedderUnavailable(f"Polymath's embedder at {self.where} returned {len(vectors)} vectors "
                                          f"for {len(chunk)} texts (dimension {dim}); nothing was used.")
            out += [list(map(float, v)) for v in vectors]
        return out


def _ollama_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
    except (ValueError, AttributeError):
        return resp.text
    return str(err.get("message") if isinstance(err, dict) else err or "")


def _missing_model(resp: httpx.Response) -> bool:
    text = _ollama_error(resp).lower()
    return "model" in text and ("not found" in text or "pull" in text)


class LocalEmbedder:
    """A local OpenAI-compatible /embeddings endpoint: the Ollama copy of the model."""

    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout_s: float = 60.0):
        self.name = f"local/{model}"
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s,
                                    transport=transport)

    def readiness(self, timeout_s: float = READY_TIMEOUT_S) -> Readiness:
        """Usable when the server answers and lists the model (`GET /models`)."""
        try:
            resp = self._client.get("/models", timeout=timeout_s)
        except httpx.HTTPError:
            return Readiness(False, "Ollama isn't running", "start Ollama (open the Ollama app, or run "
                             "`ollama serve`)", OLLAMA_DOWN)
        if resp.status_code != 200:
            problem = f"Ollama isn't answering (HTTP {resp.status_code})"
            return Readiness(False, problem, "restart Ollama", f"{problem}. Restart it, {AGAIN}")
        try:
            ids = {str(m.get("id")) for m in resp.json().get("data") or []}
        except (ValueError, AttributeError):
            ids = set()
        if self.model in ids or (":" not in self.model and f"{self.model}:latest" in ids):
            return READY
        return Readiness(False, "the embedding model isn't installed in Ollama", f"run: ollama pull {self.model}",
                         model_missing(self.model))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = self._client.post("/embeddings", json={"model": self.model, "input": texts})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise EmbedderUnavailable(OLLAMA_DOWN) from None
        if resp.status_code >= 400 and _missing_model(resp):
            raise EmbedderUnavailable(model_missing(self.model))
        resp.raise_for_status()
        rows = sorted(resp.json()["data"], key=lambda r: r["index"])
        return [list(map(float, r["embedding"])) for r in rows]


class MockEmbedder:
    """Deterministic unit vectors from a hash of the normalized text (identical text -> cosine 1)."""

    def __init__(self, dim: int = 64):
        self.name = "mock/embeddings"
        self.dim = dim

    def readiness(self, timeout_s: float = READY_TIMEOUT_S) -> Readiness:
        return READY

    def _vector(self, text: str) -> list[float]:
        norm = " ".join(text.lower().split())
        raw = b""
        counter = 0
        while len(raw) < self.dim * 4:
            raw += hashlib.sha256(f"{counter}:{norm}".encode()).digest()
            counter += 1
        values = [v / 2**31 - 1.0 for v in struct.unpack(f"<{self.dim}I", raw[: self.dim * 4])]
        length = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / length for v in values]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


def readiness(embedder: Any) -> Readiness:
    probe = getattr(embedder, "readiness", None)
    return probe() if probe is not None else READY


def embedder_for(spec: Any, settings: Any, env: dict[str, str], *,
                 transport: httpx.BaseTransport | None = None) -> Embedder:
    """One backend from a model spec, unprobed."""
    from animedex.config import resolve_base_url

    profile = settings.providers.get(spec.provider)
    if profile is None:
        raise ValueError(f"models.embeddings: unknown provider profile {spec.provider!r}")
    if profile.type == "mock":
        return MockEmbedder()
    base = resolve_base_url(profile, env)
    if not base:
        raise ValueError(f"providers.{spec.provider}: no base_url for embeddings")
    if profile.type == "polymath_embedder":
        return PolymathEmbedder(base, spec.model, transport=transport, timeout_s=profile.timeout_s)
    if profile.type == "openai_compatible":
        key = env.get(profile.api_key_env) if profile.api_key_env else None
        return LocalEmbedder(base, spec.model, api_key=key or None, transport=transport, timeout_s=profile.timeout_s)
    raise ValueError(f"providers.{spec.provider}: a {profile.type} provider can't serve embeddings")


def embedding_backends(settings: Any, env: dict[str, str], *,
                       transport: httpx.BaseTransport | None = None) -> list[Embedder]:
    """The configured backends in order: `models.embeddings`, then its `fallback` if one is set."""
    spec = settings.models["embeddings"]
    specs = [spec, *([spec.fallback] if spec.fallback is not None else [])]
    return [embedder_for(s, settings, env, transport=transport) for s in specs]


def unavailable_message(problems: list[Readiness]) -> str:
    if len(problems) == 1:
        return problems[0].alone
    first, *rest = problems
    joined = " and ".join([first.problem, *(p.problem for p in rest)])
    if all(p.needs_start for p in problems):
        return f"{joined}. Start one of them, {AGAIN}"
    fixes = ", or ".join(p.fix for p in problems)
    return f"{joined}. {fixes[0].upper()}{fixes[1:]}; {AGAIN}"


class ChainEmbedder:
    """The configured backends in order. A backend that stops answering mid-run hands over to the next one
    that is ready; every hand-over is counted and named in `fallbacks` (the silent-fallback rule), and
    the run fails only when no backend is left. The two copies of the model differ by at most 0.0035 in
    cosine (D-013), so vectors from both may share one run."""

    def __init__(self, backends: list[Embedder], start: int = 0):
        if not backends:
            raise ValueError("no embedding backends configured")
        self.backends = list(backends)
        self.index = start
        self.fallbacks: list[str] = []

    @property
    def current(self) -> Embedder:
        return self.backends[self.index]

    @property
    def name(self) -> str:
        return getattr(self.current, "name", "embedder")

    def readiness(self, timeout_s: float = READY_TIMEOUT_S) -> Readiness:
        return readiness(self.current)

    def embed(self, texts: list[str]) -> list[list[float]]:
        problems: list[str] = []
        while self.index < len(self.backends):
            backend = self.current
            try:
                return backend.embed(texts)
            except EmbedderUnavailable as exc:
                problems.append(str(exc))
                self.index += 1
                while self.index < len(self.backends):
                    state = readiness(self.current)
                    if state.ok:
                        self.fallbacks.append(f"{getattr(backend, 'name', 'embedder')} -> {self.name}: {exc}")
                        break
                    problems.append(state.alone or state.problem)
                    self.index += 1
        raise EmbedderUnavailable(" Then: ".join(problems) if problems else "no embedding backend is available")


def build_embedder(settings: Any, env: dict[str, str], *,
                   transport: httpx.BaseTransport | None = None) -> Embedder:
    """The run's embedder: the configured backends in a chain that starts at the first one ready
    (Polymath's GPU copy, then the Ollama fallback) and hands over mid-run if that one stops answering.
    Call it once per run. When none is ready, EmbedderUnavailable names each backend and how to start one."""
    backends = embedding_backends(settings, env, transport=transport)
    problems = []
    for i, embedder in enumerate(backends):
        state = readiness(embedder)
        if state.ok:
            return ChainEmbedder(backends, start=i)
        problems.append(state)
    raise EmbedderUnavailable(unavailable_message(problems))
