"""Lens values by kind (vocab 1.5.0): the checks P1 drafts and VERIFY corrections share.

A non-null value is checked for its shape (a string; a list of enum values; up to N items with typed
parts; one object with fixed parts), for its enum members (a listed value or `other:<phrase>`), and
its phrases are listed with their own word caps, so P1 can spend its length-only repair on them.
Sub-paths name a place inside a value: "" is the value itself, ".2" a member, ".0.role" an item part,
".resolution" a group part.
"""

from __future__ import annotations

from typing import Any

from animedex.ontology import LensField, Vocab

ENUM_HINT = "use a listed value or other:<phrase>"


def enum_ok(vocab: Vocab, vocab_field: str, value: Any) -> bool:
    return isinstance(value, str) and (
        value in vocab.enum(vocab_field) or (value.lower().startswith("other:") and bool(value[6:].strip())))


def _parts(f: LensField, obj: Any, prefix: str, vocab: Vocab, *, every_part: bool) -> list[tuple[str, str]]:
    names = [p.name for p in f.parts]
    if not isinstance(obj, dict):
        return [(prefix, f"must be an object with {', '.join(names)}")]
    out = [(prefix, f"unknown parts {sorted(set(obj) - set(names))}")] if set(obj) - set(names) else []
    for p in f.parts:
        where, value = f"{prefix}.{p.name}", obj.get(p.name)
        if p.name not in obj:
            out.append((where, "is missing"))
        elif value is None:
            if every_part:
                out.append((where, "is required in every item"))
        elif not isinstance(value, str) or not value.strip():
            out.append((where, "must be a non-blank string"))
        elif p.kind == "enum" and not enum_ok(vocab, p.vocab or "", value):
            out.append((where, f"{value!r}: {ENUM_HINT}"))
    return out


def shape_problems(f: LensField, value: Any, vocab: Vocab) -> list[tuple[str, str]]:
    """(sub-path, problem) for a non-null value of `f`; word caps are left to `phrase_texts`."""
    if f.kind in ("phrase", "enum"):
        if not isinstance(value, str):
            return [("", "must be a string or null")]
        if not value.strip():
            return [("", "must not be blank")]
        if f.kind == "enum" and not enum_ok(vocab, f.vocab or f.path, value):
            return [("", f"{value!r}: {ENUM_HINT}")]
        return []
    if f.kind == "enum_multi":
        if not isinstance(value, list) or not value:
            return [("", "must be a list of one or more listed values, or null")]
        out = [(f".{i}", f"{v!r}: {ENUM_HINT}") for i, v in enumerate(value) if not enum_ok(vocab, f.vocab or "", v)]
        if len({str(v) for v in value}) != len(value):
            out.append(("", "lists a value twice"))
        if "none" in value and len(value) > 1:
            out.append(("", "none cannot be combined with other values"))
        return out
    if f.kind == "list":
        if not isinstance(value, list):
            return [("", f"must be a list of up to {f.max_items} items ([] when there are none), or null")]
        out = [] if len(value) <= (f.max_items or 0) else [("", f"at most {f.max_items} items (got {len(value)})")]
        for i, item in enumerate(value):
            out += _parts(f, item, f".{i}", vocab, every_part=True)
        return out
    out = _parts(f, value, "", vocab, every_part=False)  # group
    if isinstance(value, dict) and all(value.get(p.name) is None for p in f.parts):
        out.append(("", "no part is known; write value null instead"))
    return out


def phrase_texts(f: LensField, value: Any) -> list[tuple[str, str, int]]:
    """(sub-path, text, word cap) for every phrase inside a value."""
    if f.kind == "phrase":
        return [("", value, f.max_words or 0)] if isinstance(value, str) else []
    if f.kind == "list" and isinstance(value, list):
        objs = [(f".{i}", item) for i, item in enumerate(value)]
    elif f.kind == "group" and isinstance(value, dict):
        objs = [("", value)]
    else:
        return []
    out = []
    for prefix, obj in objs:
        for p in f.parts:
            text = obj.get(p.name) if isinstance(obj, dict) else None
            if p.kind == "phrase" and isinstance(text, str):
                out.append((f"{prefix}.{p.name}", text, p.max_words or 0))
    return out


def describe(f: LensField, vocab: Vocab, *, values: bool = True) -> str:
    """What a value of `f` looks like, for prompts and schema descriptions."""
    def part(p: Any) -> str:
        if p.kind == "enum":
            return f"{p.name} ({' | '.join(vocab.enum(p.vocab))})" if values else f"{p.name} (a listed value)"
        return f"{p.name} ({p.max_words} words or fewer)"

    if f.kind == "phrase":
        return f"a phrase of {f.max_words} words or fewer"
    if f.kind == "enum":
        return f"one of: {' | '.join(vocab.enum(f.vocab or ''))}" if values else "a listed enum value"
    if f.kind == "enum_multi":
        return (f"one or more of: {' | '.join(vocab.enum(f.vocab or ''))}" if values
                else "one or more listed enum values")
    if f.kind == "list":
        return f"up to {f.max_items} items, each with {'; '.join(part(p) for p in f.parts)}"
    return f"an object with {'; '.join(part(p) for p in f.parts)}; an unknown part is null"
