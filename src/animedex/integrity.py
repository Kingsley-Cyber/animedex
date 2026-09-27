"""Cross-record invariants (04, 06 CANON "referential integrity"). Pure functions over state.

`state` maps record type -> list of canonical records (dicts).
"""

from __future__ import annotations

import re
from typing import Any

from animedex.activation import violations as activation_violations
from animedex.ontology import Vocab

State = dict[str, list[dict[str, Any]]]

_STOP = {
    "The", "A", "An", "And", "But", "Or", "If", "When", "While", "After", "Before", "His", "Her",
    "Their", "Its", "This", "That", "These", "Those", "Only", "Every", "Each", "One", "Two", "I",
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _index(state: State, record_type: str, key: str) -> dict[str, dict[str, Any]]:
    return {str(r[key]): r for r in state.get(record_type, [])}


def _phrases(record: dict[str, Any], vocab: Vocab) -> list[str]:
    out = []
    for f in vocab.lens_fields():
        if f.kind != "phrase":
            continue
        block = record.get(f.block) or {}
        value = (block.get(f.name) or {}).get("value")
        if value:
            out.append(value)
    return out


def name_list(state: State, vocab: Vocab) -> tuple[set[str], set[str]]:
    """(full titles lowercased, capitalized mid-sentence tokens) from canonical titles, moments,
    and episodes: the 04 name-leak list for P4 patterns."""
    titles = {str(t["title"]).lower() for t in state.get("title", [])}
    texts: list[str] = []
    for t in state.get("title", []):
        texts.extend(_phrases(t, vocab))
    for m in state.get("moment", []):
        texts.extend([m.get("description", ""), m.get("why_it_hit", "")])
    for e in state.get("episode", []):
        texts.append(e.get("summary", ""))
    tokens: set[str] = set()
    for text in texts:
        for sentence in _SENTENCE_SPLIT.split(text):
            words = _WORD.findall(sentence)
            for w in words[1:]:
                if w[0].isupper() and len(w) >= 3 and w not in _STOP:
                    tokens.add(w)
    return titles, tokens


def name_leaks(pattern: str, titles: set[str], tokens: set[str]) -> list[str]:
    hits = [t for t in titles if t and t in pattern.lower()]
    words = set(_WORD.findall(pattern))
    hits.extend(sorted(words & tokens))
    return sorted(set(hits))


def integrity_errors(state: State, vocab: Vocab) -> list[str]:
    errors: list[str] = []
    titles = _index(state, "title", "title_id")
    moments = _index(state, "moment", "moment_id")
    mechs = _index(state, "mechanism", "atom_id")
    proofs = _index(state, "proof", "atom_id")
    transfers = _index(state, "transfer", "transfer_id")
    episodes = _index(state, "episode", "episode_id")
    ideas = _index(state, "idea", "idea_id")
    lens_paths = {f.path for f in vocab.lens_fields()}

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    for tid, t in titles.items():
        for problem in activation_violations(vocab, t["medium"], t["format"], t.get("modules_active", [])):
            errors.append(f"title {tid}: {problem}")
    for r in state.get("moment", []):
        need(r["title_id"] in titles, f"moment {r['moment_id']}: unknown title {r['title_id']}")
    for r in state.get("outcome", []):
        need(r["title_id"] in titles, f"outcome: unknown title {r['title_id']}")
    for r in state.get("coverage", []):
        need(r["title_id"] in titles, f"coverage: unknown title {r['title_id']}")
    for r in state.get("mechanism", []):
        aid = r["atom_id"]
        need(r["title_id"] in titles, f"mechanism {aid}: unknown title {r['title_id']}")
        for ref in r.get("evidence_refs", []):
            need(ref in lens_paths or ref in moments or ref in episodes,
                 f"mechanism {aid}: evidence_ref {ref!r} is not a field path, moment, or episode")
        eref = (r.get("effect") or {}).get("element_ref") or {}
        if eref.get("moment_id"):
            need(eref["moment_id"] in moments, f"mechanism {aid}: unknown element_ref moment")
        if eref.get("field"):
            need(eref["field"] in lens_paths, f"mechanism {aid}: unknown element_ref field")
    for r in state.get("proof", []):
        aid = r["atom_id"]
        atom = mechs.get(aid)
        need(atom is not None, f"proof {aid}: unknown atom")
        for c in r.get("contrast", []):
            need(c["partner_title_id"] in titles, f"proof {aid}: unknown partner {c['partner_title_id']}")
        et = r.get("explanation_test")
        if et:
            need(et["via_partner"] in titles, f"proof {aid}: unknown via_partner {et['via_partner']}")
        if atom is not None and atom.get("atom_kind") == "effect":
            need(bool(et), f"proof {aid}: effect atoms need an explanation_test")
    for r in state.get("check", []):
        target = r["target_id"]
        pool = mechs if r["target_type"] == "mechanism" else proofs
        need(target in pool, f"check: unknown {r['target_type']} {target}")
    for r in state.get("transfer", []):
        src = mechs.get(r["source_atom_id"])
        need(src is not None, f"transfer {r['transfer_id']}: unknown source atom")
        if src is not None:
            need(src.get("atom_kind") == r.get("atom_kind"), f"transfer {r['transfer_id']}: atom_kind differs from source")
    for r in state.get("episode", []):
        eid = r["episode_id"]
        title = titles.get(r["title_id"])
        need(title is not None, f"episode {eid}: unknown title")
        if title is not None:
            seasons = (title.get("scope") or {}).get("seasons") or []
            need(r["locator"]["season"] in seasons, f"episode {eid}: season outside the title's scope")
        for mid in r.get("moment_refs", []):
            need(mid in moments, f"episode {eid}: unknown moment {mid}")
        for s in r.get("atom_support", []):
            need(s["atom_id"] in mechs, f"episode {eid}: unknown atom {s['atom_id']}")
        beat = r.get("engine_beat")
        if beat:
            atom = mechs.get(beat["engine_atom_id"])
            need(atom is not None and atom.get("atom_kind") == "engine", f"episode {eid}: engine_beat needs an engine atom")
        for p in r.get("payoffs", []):
            if p.get("setup_episode_id"):
                need(p["setup_episode_id"] in episodes, f"episode {eid}: unknown setup episode")
    linkable = set(episodes) | set(mechs) | set(moments) | set(titles)
    for r in state.get("link", []):
        need(r["title_id"] in titles, f"link {r['link_id']}: unknown title")
        need(r["from_id"] in linkable, f"link {r['link_id']}: unknown from_id {r['from_id']}")
        need(r["to_id"] in linkable, f"link {r['link_id']}: unknown to_id {r['to_id']}")
    for r in state.get("pattern", []):
        pid = r["pattern_id"]
        need(all(t in transfers for t in r.get("transfer_ids", [])), f"pattern {pid}: unknown transfer")
        need(all(t in titles for t in r.get("supporting_titles", [])), f"pattern {pid}: unknown supporting title")
        need(all(c["title_id"] in titles for c in r.get("counterexamples", [])), f"pattern {pid}: unknown counterexample title")
    for r in state.get("idea", []):
        iid = r["idea_id"]
        used = set(r.get("atoms_used", [])) | set(r.get("transformation", {}).get("source_transfer_ids", []))
        need(used <= set(transfers), f"idea {iid}: uses unknown transfer atoms {sorted(used - set(transfers))}")
        need(r["closest_existing"] in titles, f"idea {iid}: unknown closest_existing")
        need(all(t in titles for t in r.get("borrowed_from", [])), f"idea {iid}: unknown borrowed_from title")
        need(all(p in ideas for p in r.get("parent_ids", [])), f"idea {iid}: unknown parent")
    for r in state.get("archive", []):
        need(r["idea_id"] in ideas, f"archive {r['cell_key']}: unknown idea")
        if r.get("replaced_idea_id"):
            need(r["replaced_idea_id"] in ideas, f"archive {r['cell_key']}: unknown replaced idea")

    if state.get("transfer"):
        full_titles, tokens = name_list(state, vocab)
        for r in state["transfer"]:
            leaks = name_leaks(r.get("pattern", ""), full_titles, tokens)
            need(not leaks, f"transfer {r['transfer_id']}: pattern contains names {leaks}")
    return errors
