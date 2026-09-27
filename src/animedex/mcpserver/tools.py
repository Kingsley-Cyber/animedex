"""Request A (D-033): the MCP server's tools, as plain functions over the built index.

Index tools only read: canonical records, the ANALYZE build (CQ answers, gap ranking) and the blind-review
state. `add_commentary` is the one write, to data/commentary/commentary.jsonl (private data repo). No tool
calls a model or the web. Idea cards stay hidden until every card of the latest blind packet is rated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from animedex.content_guards import GuardConfig, record_problems
from animedex.eligibility import eligible_atom_ids
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.textutil import word_count

COMMENTARY_MAX_WORDS = 200
COMMENTARY_FILE = ("data", "commentary", "commentary.jsonl")
PROFILE_BLOCKS = ("core", "power_combat", "relationships", "anime_production", "series_engine", "sensory",
                  "comedy_satire", "film")


class ToolError(ValueError):
    """A request the index can't answer (unknown id, bad filter); the message says what to fix."""


def _state(paths: Paths) -> dict[str, list[dict[str, Any]]]:
    return CanonicalStore(paths).state()


def _value(rec: dict[str, Any], path: str) -> Any:
    block, _, name = path.partition(".")
    fv = (rec.get(block) or {}).get(name)
    return fv.get("value") if isinstance(fv, dict) else None


# ---------------------------------------------------------------- titles
def title_summary(rec: dict[str, Any], outcome: dict[str, Any] | None = None) -> dict[str, Any]:
    """The compact profile: identity, scope, every non-null field value (paraphrased phrases and enums),
    the outcome label, and how the values were sourced."""
    fields: dict[str, Any] = {}
    mix: dict[str, int] = {}
    for block in PROFILE_BLOCKS:
        for name, fv in (rec.get(block) or {}).items():
            if isinstance(fv, dict) and fv.get("value") not in (None, [], ""):
                fields[f"{block}.{name}"] = fv["value"]
                mix[str(fv.get("verification"))] = mix.get(str(fv.get("verification")), 0) + 1
    out = {"title_id": rec["title_id"], "title": rec["title"], "year": rec["year"], "medium": rec["medium"],
           "format": rec["format"], "scope": rec.get("scope"), "modules_active": rec.get("modules_active", []),
           "fields": fields, "verification_mix": dict(sorted(mix.items()))}
    if outcome:
        out["outcome"] = {k: outcome.get(k) for k in ("label", "failure_level", "failure_reason") if outcome.get(k)}
    return out


def get_title(paths: Paths, title_id: str) -> dict[str, Any]:
    st = _state(paths)
    rec = next((t for t in st["title"] if t["title_id"] == title_id), None)
    if rec is None:
        raise ToolError(f"no title {title_id!r}; list_titles shows the ids")
    outcome = next((o for o in st["outcome"] if o["title_id"] == title_id), None)
    out = title_summary(rec, outcome)
    out["characters"] = [{"name": c.get("name"), "role": c.get("role")} for c in st.get("character", [])
                         if c.get("title_id") == title_id]
    out["atoms"] = sorted(m["atom_id"] for m in st["mechanism"] if m["title_id"] == title_id)
    out["commentary"] = commentary(paths, title_id)
    return out


def list_titles(paths: Paths) -> list[dict[str, Any]]:
    st = _state(paths)
    labels = {o["title_id"]: o["label"] for o in st["outcome"]}
    return [{"title_id": t["title_id"], "title": t["title"], "year": t["year"], "medium": t["medium"],
             "outcome": labels.get(t["title_id"])} for t in sorted(st["title"], key=lambda t: t["title_id"])]


def find_titles(paths: Paths, filters: dict[str, str]) -> list[dict[str, Any]]:
    """Titles whose field at each path holds the value (a list field matches when it contains it)."""
    if not filters:
        raise ToolError("give at least one filter, e.g. {\"power_combat.gate\": \"contract\"}")
    out = []
    for rec in _state(paths)["title"]:
        ok = True
        for path, want in filters.items():
            got = _value(rec, path)
            ok = ok and (want in got if isinstance(got, list) else got == want)
        if ok:
            out.append({"title_id": rec["title_id"], "title": rec["title"],
                        **{p: _value(rec, p) for p in filters}})
    return sorted(out, key=lambda r: r["title_id"])


# ---------------------------------------------------------------- atoms
def atom_text(atom: dict[str, Any]) -> str:
    """The words search ranks an atom by."""
    if "pattern" in atom:  # a transfer
        return " ".join(str(atom.get(k) or "") for k in ("pattern", "mechanism", "principle")).strip()
    if atom["atom_kind"] == "effect":
        e = atom["effect"]
        return f"{e['element']}. {e['because']}"
    g = atom["engine"]
    return ". ".join(g[k] for k in ("goal", "constraint", "strategy", "cost", "dilemma"))


def atom_row(atom: dict[str, Any], eligible: set[str], titles: dict[str, str]) -> dict[str, Any]:
    is_transfer = "pattern" in atom
    source = atom["source_atom_id"] if is_transfer else atom["atom_id"]
    tid = source.split(".")[0]
    row: dict[str, Any] = {"id": atom["transfer_id"] if is_transfer else atom["atom_id"],
                           "kind": "transfer" if is_transfer else "mechanism", "atom_kind": atom["atom_kind"],
                           "title_id": tid, "title": titles.get(tid), "text": atom_text(atom),
                           "eligible": source in eligible}
    if is_transfer:
        row["bridge"] = atom.get("bridge", [])
        row["source_atom_id"] = source
    else:
        row["support"] = (atom.get("support") or {}).get("status")
        row["explanation"] = atom.get("explanation")
    return row


def all_atoms(paths: Paths) -> list[dict[str, Any]]:
    st = _state(paths)
    eligible = eligible_atom_ids(st)
    titles = {t["title_id"]: t["title"] for t in st["title"]}
    return [atom_row(a, eligible, titles) for a in [*st["mechanism"], *st["transfer"]]]


def get_atom(paths: Paths, atom_id: str) -> dict[str, Any]:
    st = _state(paths)
    atom = next((m for m in st["mechanism"] if m["atom_id"] == atom_id), None)
    transfer = next((t for t in st["transfer"] if t["transfer_id"] == atom_id), None)
    if atom is None and transfer is not None:
        atom = next((m for m in st["mechanism"] if m["atom_id"] == transfer["source_atom_id"]), None)
    if atom is None:
        raise ToolError(f"no atom {atom_id!r}; search_atoms finds ids")
    aid = atom["atom_id"]
    return {"atom": {k: v for k, v in atom.items() if k != "provenance"},
            "eligible": aid in eligible_atom_ids(st),
            "proof": next(({k: v for k, v in p.items() if k != "provenance"} for p in st["proof"]
                           if p["atom_id"] == aid), None),
            "checks": [{k: c.get(k) for k in ("target_type", "verdict", "reasons")} for c in st["check"]
                       if c["target_id"] == aid],
            "transfers": [{k: v for k, v in t.items() if k != "provenance"} for t in st["transfer"]
                          if t["source_atom_id"] == aid],
            "commentary": commentary(paths, aid)}


# ---------------------------------------------------------------- analysis
def list_cqs(paths: Paths) -> list[dict[str, str]]:
    folder = paths.build / "cq_answers"
    if not folder.is_dir():
        raise ToolError("no CQ answers yet: run `make analyze`")
    out = []
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": data["id"], "question": data.get("text", ""), "rows": len(data.get("rows") or [])})
    return out


def cq_answer(paths: Paths, cq_id: str, limit: int = 50) -> dict[str, Any]:
    f = paths.build / "cq_answers" / f"{cq_id}.json"
    if not f.is_file():
        raise ToolError(f"no saved answer for {cq_id!r}; list_cqs shows the ids")
    data = json.loads(f.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    return {"id": data["id"], "question": data.get("text", ""), "columns": data.get("columns", []),
            "rows": rows[:limit], "total_rows": len(rows), "note": data.get("note", "")}


def gaps(paths: Paths, limit: int = 20) -> dict[str, Any]:
    """Real gaps (expected >= 3 with none observed) per gap question, from the last ANALYZE."""
    f = paths.build / "stats" / "analysis.json"
    if not f.is_file():
        raise ToolError("no analysis yet: run `make analyze`")
    data = json.loads(f.read_text(encoding="utf-8"))
    out: dict[str, Any] = {"unreliable_fields": sorted(data.get("unreliable") or {})}
    for cq, g in sorted((data.get("gaps") or {}).items()):
        out[cq] = {"n": g.get("n"), "source": g.get("source"), "real_gaps": (g.get("real_gaps") or [])[:limit],
                   "excluded": g.get("excluded", [])}
    return out


# ---------------------------------------------------------------- ideas (after the blind review only)
def review_complete(paths: Paths) -> bool:
    from animedex.ideate.review import latest_packet, load_ratings

    blind = paths.root / "eval" / "blind"
    try:
        packet = json.loads(latest_packet(blind).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    ids = [c["id"] for c in packet["cards"]]
    ratings = load_ratings(blind, str(packet["date"]))
    return bool(ids) and all(isinstance((ratings.get(i) or {}).get("rating"), int) for i in ids)


def champions(paths: Paths) -> list[dict[str, Any]]:
    if not review_complete(paths):
        raise ToolError("idea cards stay hidden until every card in the blind packet is rated "
                        "(make review), so the review stays blind")
    keep = ("idea_id", "logline", "premise", "grid_cell", "operator", "closest_existing", "why_not_a_clone")
    return [{k: i.get(k) for k in keep} for i in _state(paths)["idea"] if i.get("status") == "champion"]


# ---------------------------------------------------------------- commentary (the one write)
def _commentary_file(paths: Paths):
    return paths.root.joinpath(*COMMENTARY_FILE)


def commentary(paths: Paths, target_id: str) -> list[dict[str, Any]]:
    f = _commentary_file(paths)
    rows = [r for r in read_jsonl(f) if r["target_id"] == target_id] if f.is_file() else []
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def _target_type(paths: Paths, target_id: str) -> str | None:
    st = _state(paths)
    kinds = (("title", "title", "title_id"), ("atom", "mechanism", "atom_id"), ("transfer", "transfer", "transfer_id"),
             ("idea", "idea", "idea_id"))
    for label, rtype, key in kinds:
        if any(r[key] == target_id for r in st.get(rtype, [])):
            return label
    if (paths.build / "cq_answers" / f"{target_id}.json").is_file():
        return "cq"
    return None


def add_commentary(paths: Paths, target_id: str, text: str, *, now: str | None = None) -> dict[str, Any]:
    """Append one owner note to an existing target. Owner voice, not evidence: no stage reads it."""
    text = " ".join(str(text).split())
    if not text:
        raise ToolError("the note is empty")
    if word_count(text) > COMMENTARY_MAX_WORDS:
        raise ToolError(f"keep a note to {COMMENTARY_MAX_WORDS} words (this one has {word_count(text)})")
    kind = _target_type(paths, target_id)
    if kind is None:
        raise ToolError(f"no title, atom, transfer, idea or CQ {target_id!r}")
    try:
        from animedex.config import load_settings

        guards = GuardConfig.from_settings(load_settings(paths))
    except Exception:  # noqa: BLE001 - guards default when settings can't load
        guards = GuardConfig()
    problems = record_problems({"text": text}, guards)
    if problems:
        raise ToolError("; ".join(problems[:3]))
    created = now or datetime.now(UTC).isoformat(timespec="seconds")
    row = {"commentary_id": "cm_" + hashlib.sha256(f"{target_id}|{created}|{text}".encode()).hexdigest()[:12],
           "target_id": target_id, "target_type": kind, "text": text, "author": "owner", "created_at": created}
    f = _commentary_file(paths)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, dumps_jsonl([*(read_jsonl(f) if f.is_file() else []), row]))
    return row
