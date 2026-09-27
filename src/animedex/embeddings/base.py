"""Embeddings adapter (03): premise similarity and ROLLUP proposal matching.

Default is a local model behind an OpenAI-compatible /embeddings endpoint (Ollama, LM Studio),
called with httpx, so no torch or sentence-transformers dependency. The mock is deterministic.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Protocol

import httpx


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


class LocalEmbedder:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout_s: float = 60.0):
        self.name = f"local/{model}"
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s,
                                    transport=transport)

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.post("/embeddings", json={"model": self.model, "input": texts})
        resp.raise_for_status()
        rows = sorted(resp.json()["data"], key=lambda r: r["index"])
        return [list(map(float, r["embedding"])) for r in rows]


class MockEmbedder:
    """Deterministic unit vectors from a hash of the normalized text (identical text -> cosine 1)."""

    def __init__(self, dim: int = 64):
        self.name = "mock/embeddings"
        self.dim = dim

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


def build_embedder(settings, env: dict[str, str]) -> Embedder:
    """The `models.embeddings` slot: a local OpenAI-compatible endpoint (Ollama) or the mock."""
    from animedex.config import resolve_base_url

    spec = settings.models["embeddings"]
    profile = settings.providers[spec.provider]
    if profile.type == "mock":
        return MockEmbedder()
    base = resolve_base_url(profile, env)
    if not base:
        raise ValueError(f"providers.{spec.provider}: no base_url for embeddings")
    key = env.get(profile.api_key_env) if profile.api_key_env else None
    return LocalEmbedder(base, spec.model, api_key=key or None)
