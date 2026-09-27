"""search_atoms (request A, D-033): rank mechanism and transfer atoms by meaning.

The pipeline's embedder ranks (Polymath's sidecar, then the Ollama backup, D-008). When neither is
reachable, word overlap ranks instead, and every answer names the ranker that ran and how often this
session fell back (silent-fallback rule). Vectors are cached in memory for the server's lifetime only, so
searching never writes a file.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable
from typing import Any

from animedex.embeddings.base import Embedder, EmbedderUnavailable, cosine
from animedex.mcpserver.tools import ToolError, all_atoms
from animedex.paths import Paths

STOP = frozenset("the and for with that this from into their them they its his her are was were has have not but "
                 "who what when because each every more than only one".split())
REPROBE_S = 300.0   # after the embedder was unreachable, try it again at most this often


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOP}


def word_overlap(query: str, text: str) -> float:
    q, t = tokens(query), tokens(text)
    return len(q & t) / math.sqrt(len(q) * len(t)) if q and t else 0.0


class AtomSearch:
    def __init__(self, paths: Paths, make_embedder: Callable[[], Embedder] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.paths = paths
        self.make_embedder = make_embedder
        self.clock = clock
        self.embedder: Embedder | None = None
        self.down_since: float | None = None
        self.down_reason = ""
        self.vectors: dict[str, list[float]] = {}
        self.counts = {"embedding": 0, "word_overlap": 0}

    def _ready_embedder(self) -> Embedder | None:
        if self.embedder is not None or self.make_embedder is None:
            return self.embedder
        if self.down_since is not None and self.clock() - self.down_since < REPROBE_S:
            return None
        try:
            self.embedder = self.make_embedder()
            self.down_since = None
        except (EmbedderUnavailable, ValueError) as exc:
            self.down_since, self.down_reason = self.clock(), str(exc)
        return self.embedder

    def _key(self, text: str) -> str:
        name = getattr(self.embedder, "name", "embedder")
        return hashlib.sha256(f"{name}\n{text}".encode()).hexdigest()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        assert self.embedder is not None
        missing = sorted({t for t in texts if self._key(t) not in self.vectors})
        if missing:
            for text, vec in zip(missing, self.embedder.embed(missing), strict=True):
                self.vectors[self._key(text)] = vec
        return [self.vectors[self._key(t)] for t in texts]

    def search(self, query: str, *, kind: str = "any", title_id: str | None = None, eligible_only: bool = False,
               limit: int = 10) -> dict[str, Any]:
        if not query.strip():
            raise ToolError("give a query, e.g. 'a power that costs the user their memories'")
        if kind not in ("any", "mechanism", "transfer"):
            raise ToolError("kind is any, mechanism or transfer")
        rows = [r for r in all_atoms(self.paths)
                if (kind == "any" or r["kind"] == kind) and (title_id is None or r["title_id"] == title_id)
                and (r["eligible"] or not eligible_only)]
        ranker, note = "word_overlap", ""
        scores: list[float] = []
        embedder = self._ready_embedder()
        if embedder is not None and rows:
            try:
                qv, *vs = self._embed([query, *(r["text"] for r in rows)])
                scores, ranker = [cosine(qv, v) for v in vs], "embedding"
            except EmbedderUnavailable as exc:
                self.embedder, self.down_since, self.down_reason = None, self.clock(), str(exc)
        if ranker == "word_overlap":
            scores = [word_overlap(query, r["text"]) for r in rows]
            note = f"embedder unavailable ({self.down_reason})" if self.down_reason else "no embedder configured"
        self.counts[ranker] += 1
        ranked = sorted(zip(scores, rows, strict=True), key=lambda p: (-p[0], p[1]["id"]))[:max(1, min(limit, 50))]
        return {"ranker": ranker, "note": note, "session_rankers": dict(self.counts), "searched": len(rows),
                "results": [{**r, "score": round(s, 4)} for s, r in ranked]}
