"""Length-only repair for structured outputs (M3, 2026-09-27; D-030).

When every problem in a call's output is a text over its word cap, one short call rewrites just those
texts, before the full repair (a full regeneration can break something else, as a live P3 retry did) and
again as the last resort after it (P3 lost a title to a 26-word note under a 25-word cap). Nothing is
truncated, every other value stays as the model wrote it, and the repaired output goes through the same
validation, guards included.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from animedex.textutil import word_count

LIMIT = re.compile(r"(\d+) words exceeds the (\d+)-word limit")
SYSTEM = ("You shorten phrases. Rewrite each listed phrase within the word limit shown after it, keeping its "
          "meaning and facts and dropping filler words. Paraphrase only; no quotes. Output JSON only.")

Path = tuple[str | int, ...]


def _loc(clause: str) -> tuple[str, ...]:
    """The field path a problem names, as parts: `effects[0].because: Value error, ...` -> (effects, 0,
    because); `x.m.005: explanation_test.note: Value error, ...` -> (explanation_test, note)."""
    head = clause.split(": Value error")[0] if ": Value error" in clause else clause.rsplit(":", 1)[0]
    last = head.split(": ")[-1]
    return tuple(p for p in re.sub(r"\[(\d+)\]", r".\1", last).split(".") if p)


def _leaves(node: Any, path: Path = ()) -> Iterator[tuple[Path, str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, (*path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, (*path, i))
    elif isinstance(node, str):
        yield path, node


def targets(data: dict[str, Any], error: str) -> list[tuple[Path, str, int]] | None:
    """(path, text, cap) for each over-cap text the error names. None unless every problem in the error is
    a word-cap problem that points at a text in `data` with exactly the word count the problem states."""
    clauses = [c.strip() for c in error.split("; ") if c.strip()]
    if not clauses:
        return None
    found: dict[Path, tuple[str, int]] = {}
    for clause in clauses:
        m = LIMIT.search(clause)
        loc = _loc(clause) if m else ()
        if not m or not loc:
            return None
        n, cap = int(m.group(1)), int(m.group(2))
        hits = [(p, t) for p, t in _leaves(data)
                if len(p) >= len(loc) and tuple(str(x) for x in p[-len(loc):]) == loc and word_count(t) == n]
        if not hits:
            return None
        for p, t in hits:
            found[p] = (t, min(cap, found[p][1]) if p in found else cap)
    return [(p, t, c) for p, (t, c) in sorted(found.items(), key=lambda kv: [str(x) for x in kv[0]])]


def dotted(path: Path) -> str:
    return ".".join(str(x) for x in path)


def request(items: list[tuple[Path, str, int]]) -> tuple[str, dict[str, Any]]:
    """The user text and JSON schema of the shorten call."""
    names = [dotted(p) for p, _, _ in items]
    item = {"type": "object", "additionalProperties": False, "required": ["path", "text"],
            "properties": {"path": {"type": "string", "enum": names}, "text": {"type": "string"}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["items"],
              "properties": {"items": {"type": "array", "items": item}}}
    return "\n".join(f"{dotted(p)}: {t} [max {c} words]" for p, t, c in items), schema


def check(items: list[tuple[Path, str, int]], out: dict[str, Any]) -> None:
    caps = {dotted(p): c for p, _, c in items}
    got = {i.get("path"): i.get("text") or "" for i in out.get("items") or []}
    bad = [f"{p}: missing" for p in caps if p not in got]
    bad += [f"{p}: has {word_count(t)} words; {caps[p]} or fewer" for p, t in got.items()
            if p in caps and (word_count(t) > caps[p] or not t.strip())]
    if bad:
        raise ValueError("; ".join(bad))


def apply(data: dict[str, Any], items: list[tuple[Path, str, int]], out: dict[str, Any]) -> dict[str, Any]:
    """A copy of `data` with each listed text replaced by its shortened version."""
    import json

    fixed = json.loads(json.dumps(data))
    by_name = {dotted(p): p for p, _, _ in items}
    for i in out["items"]:
        path = by_name[i["path"]]
        node = fixed
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = i["text"]
    return fixed
