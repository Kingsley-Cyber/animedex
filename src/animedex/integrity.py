"""Cross-record invariants (04, 06 CANON "referential integrity"). Pure functions over state.

`state` maps record type -> list of canonical records (dicts).
"""

from __future__ import annotations

import re
from typing import Any

from animedex.activation import violations as activation_violations
from animedex.eligibility import eligible_atom_ids
from animedex.models.characters import (
    ANTAGONIST_ROLES,
    MAX_CHARACTERS,
    MAX_POWER_KITS,
    ROLE_LIMITS,
    SHARED_SLOT,
)
from animedex.ontology import Vocab

State = dict[str, list[dict[str, Any]]]

_STOP = {
    "The", "A", "An", "And", "But", "Or", "If", "When", "While", "After", "Before", "His", "Her",
    "Their", "Its", "This", "That", "These", "Those", "Only", "Every", "Each", "One", "Two", "I",
}
# Capitalized words that are never a show's own name: number words, universal nouns, real places, the
# calendar and everyday acronyms (D-039)
COMMON_CAPITALS = frozenset(
    "Three Four Five Six Seven Eight Nine Ten Eleven Twelve Hundred Thousand Million First Second Third Tenth "
    "God Gods Heaven Hell Earth Moon Sun World Japan Japanese Tokyo Kyoto Osaka Shibuya America American Asian "
    "Europe European China Chinese Korea Korean English Heian Edo Shaolin January February March April May June "
    "July August September October November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
    "CIA FBI SAS NEET "
    # generic nouns that shows capitalize inside their own names; the names themselves are caught as phrases
    "Academy Arena Army Association Chief Clan Coalition Compound Corps Council Department East West North South "
    "Eastern Western Northern Southern Election Empire Expansion Father Mother Fire Water Flash Globe Grade "
    "Guardians Guild Helmet International Inventory Justice King Queen Kingdom Knights League Lord Lower Upper "
    "Marshal Monarch Moons Nation Navy Note Oath Ocean Order Phantom Planets Realm Religion School Scars Selection "
    "Shrine Sound Stone Temp Tribe Troupe Village Wrath Boys".split())
_CAPITAL_RUN = re.compile(r"\b[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)+")


def capital_runs(text: str) -> set[str]:
    """Multi-word capitalized names ("Fire Nation", "Upper Moons"), lowercased, with leading stop words
    dropped: a show's compound name is a leak even when each of its words is common (D-039)."""
    out = set()
    for m in _CAPITAL_RUN.finditer(text):
        words = m.group(0).split()
        before = text[:m.start()].rstrip()
        if not before or before[-1] in ".!?;:":  # a sentence's first word is capitalized anyway
            words = words[1:]
        while words and words[0] in _STOP:
            words = words[1:]
        if len(words) >= 2:
            out.add(" ".join(words).lower())
    return out


def _base(token: str) -> str:
    """A token without its possessive or hyphenated tail: "Earth's" -> Earth, "League-style" -> League."""
    return token.split("'")[0].split("-")[0]


def _prose(state: State) -> list[str]:
    """Every model-written sentence in the index: the lowercase evidence that a capitalized word is common."""
    out: list[str] = []
    for m in state.get("mechanism", []):
        out += [str(v) for part in ("effect", "engine") for v in (m.get(part) or {}).values() if isinstance(v, str)]
    for p in state.get("proof", []):
        out += [str(c.get("difference") or "") for c in p.get("contrast") or []]
        out += [str((p.get("explanation_test") or {}).get("note") or ""), str((p.get("ablation") or {}).get("if_removed") or "")]
    for t in state.get("transfer", []):
        out += [str(t.get(k) or "") for k in ("pattern", "mechanism", "principle", "anti_pattern")]
        out += [str(x) for k in ("essential_conditions", "variable_details", "failure_conditions") for x in t.get(k) or []]
    return out
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _index(state: State, record_type: str, key: str) -> dict[str, dict[str, Any]]:
    return {str(r[key]): r for r in state.get(record_type, [])}


def _phrases(record: dict[str, Any], vocab: Vocab) -> list[str]:
    """A title's phrase values, with the phrase parts of list and group values (vocab 1.5.0)."""
    out = []
    for f in vocab.lens_fields():
        value = ((record.get(f.block) or {}).get(f.name) or {}).get("value")
        if not value:
            continue
        if f.kind == "phrase":
            out.append(value)
            continue
        objs = value if f.kind == "list" and isinstance(value, list) else [value] if f.kind == "group" else []
        for obj in objs:
            for p in f.parts:
                text = obj.get(p.name) if isinstance(obj, dict) else None
                if p.kind == "phrase" and isinstance(text, str) and text:
                    out.append(text)
    return out


def _character_texts(c: dict[str, Any]) -> list[str]:
    kit = c.get("power_kit") or {}
    texts = [c.get(k) or "" for k in ("origin", "wound", "want", "need")]
    texts += [(c.get(k) or {}).get(sub) or "" for k in ("flaw", "moral_line") for sub in ("value", "condition")]
    texts += [t.get("event", "") for t in c.get("turning_points") or []]
    texts += [kit.get("medium") or "", kit.get("evolution") or "", *(kit.get("functions") or []),
              *(kit.get("limits") or []), *(t.get("tool", "") for t in kit.get("tools") or []),
              *(m.get("move", "") for m in kit.get("creativity_moves") or [])]
    texts += [f.get(k, "") for f in kit.get("forms") or [] for k in ("name", "trigger", "cost")]
    return texts


def proper_nouns(text: str) -> list[str]:
    """Capitalized words after the first word of a sentence: the name-leak tokenization of one text."""
    out = []
    for sentence in _SENTENCE_SPLIT.split(text):
        out += [w for w in _WORD.findall(sentence)[1:] if w[0].isupper() and len(w) >= 3 and w not in _STOP]
    return sorted(set(out))


def _name_tokens(name: str) -> set[str]:
    """Every capitalized word of a character's name (its first word too), so a first name alone is caught."""
    return {w for w in _WORD.findall(name) if w[0].isupper() and len(w) >= 3 and w not in _STOP}


def name_list(state: State, vocab: Vocab) -> tuple[set[str], set[str]]:
    """(full titles lowercased, capitalized tokens) from canonical titles, moments, episodes, and (v1.8)
    characters: the 04 name-leak list for P4 transfers, pattern cards and idea cards. Every word of a
    character's name joins it; other texts give their capitalized mid-sentence words."""
    titles = {str(t["title"]).lower() for t in state.get("title", [])}
    texts: list[str] = []
    tokens: set[str] = set()
    for t in state.get("title", []):
        texts.extend(_phrases(t, vocab))
    for m in state.get("moment", []):
        texts.extend([m.get("description", ""), m.get("why_it_hit", "")])
    for e in state.get("episode", []):
        texts.append(e.get("summary", ""))
    names: set[str] = set()
    for c in state.get("character", []):
        names |= _name_tokens(str(c.get("name") or ""))
        texts.extend(_character_texts(c))
    # a capitalized word the corpus also writes in lowercase ("become God" and "a god") is a common word,
    # not a name; characters' own names always count (D-039)
    lowercase = {w.lower() for text in [*texts, *_prose(state)] for w in _WORD.findall(text) if w[0].islower()}
    phrases: set[str] = set()
    for text in texts:
        tokens.update(w for w in proper_nouns(text) if _base(w).lower() not in lowercase)
        phrases |= capital_runs(text)
    # compound names join the full titles as phrases (matched case-insensitively as substrings)
    return titles | phrases, {t for t in tokens | names if _base(t) not in COMMON_CAPITALS and len(_base(t)) >= 2}


def name_leaks(pattern: str, titles: set[str], tokens: set[str]) -> list[str]:
    hits = [t for t in titles if t and t in pattern.lower()]
    words = set(_WORD.findall(pattern))
    words |= {_base(w) for w in words}  # "Kirito's" and "Omni-Man's" still name Kirito and Omni-Man
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
    characters = _index(state, "character", "character_id")
    errors.extend(character_errors(state, titles))
    for r in state.get("outcome", []):
        need(r["title_id"] in titles, f"outcome: unknown title {r['title_id']}")
    for r in state.get("coverage", []):
        need(r["title_id"] in titles, f"coverage: unknown title {r['title_id']}")
    for r in state.get("mechanism", []):
        aid = r["atom_id"]
        need(r["title_id"] in titles, f"mechanism {aid}: unknown title {r['title_id']}")
        for ref in r.get("evidence_refs", []):  # v1.8: P2 may cite a character record
            need(ref in lens_paths or ref in moments or ref in episodes or ref in characters,
                 f"mechanism {aid}: evidence_ref {ref!r} is not a field path, moment, episode, or character")
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
            need(et.get("via_partner") is None or et["via_partner"] in titles,
                 f"proof {aid}: unknown via_partner {et.get('via_partner')}")
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
    eligible = eligible_atom_ids(state) if any(r.get("predictive_evidence") for r in state.get("pattern", [])) else set()
    for r in state.get("pattern", []):
        pid = r["pattern_id"]
        need(all(t in transfers for t in r.get("transfer_ids", [])), f"pattern {pid}: unknown transfer")
        need(all(t in titles for t in r.get("supporting_titles", [])), f"pattern {pid}: unknown supporting title")
        need(all(c["title_id"] in titles for c in r.get("counterexamples", [])), f"pattern {pid}: unknown counterexample title")
        for ev in r.get("predictive_evidence", []):  # v1.8 M7: a held-out load-bearing atom the principle explains
            need(ev["title_id"] in titles, f"pattern {pid}: unknown predictive-evidence title {ev['title_id']}")
            need(ev["atom_id"] in eligible, f"pattern {pid}: predictive evidence {ev['atom_id']} is not a "
                                            "load-bearing-eligible atom")
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

    if state.get("transfer") or state.get("pattern"):
        full_titles, tokens = name_list(state, vocab)
        for r in state.get("transfer", []):
            for key in ("pattern", "mechanism", "principle", "anti_pattern"):
                leaks = name_leaks(r.get(key) or "", full_titles, tokens)
                need(not leaks, f"transfer {r['transfer_id']}: {key} contains names {leaks}")
        for r in state.get("pattern", []):
            leaks = name_leaks(r.get("statement", ""), full_titles, tokens)
            need(not leaks, f"pattern {r['pattern_id']}: statement contains names {leaks}")
    # the clone check's text (vocab 1.5.0): no names. Checked against the title's own name and cast and
    # any mid-sentence capital, so adding another title never changes this one's result.
    cast: dict[str, set[str]] = {}
    for c in state.get("character", []):
        cast.setdefault(c["title_id"], set()).update(_name_tokens(str(c.get("name") or "")))
    for tid, t in titles.items():
        for f in (f for f in vocab.lens_fields() if f.abstract):
            text = ((t.get(f.block) or {}).get(f.name) or {}).get("value") or ""
            leaks = sorted(set(name_leaks(text, {str(t["title"]).lower()}, cast.get(tid, set())))
                           | set(proper_nouns(text)))
            need(not leaks, f"title {tid}: {f.path} contains names {leaks}")
    return errors


def character_errors(state: State, titles: dict[str, dict[str, Any]]) -> list[str]:
    """v1.8 characters: a known title; per title at most 4, one per role (mentor or deuteragonist share
    a slot), exactly one protagonist; at most 3 power kits, the protagonist's first; villain fields
    only on antagonists; turning points at in-scope episodes (films need none)."""
    errors: list[str] = []
    by_title: dict[str, list[dict[str, Any]]] = {}
    for c in state.get("character", []):
        by_title.setdefault(c["title_id"], []).append(c)
    for tid, cast in sorted(by_title.items()):
        title = titles.get(tid)
        if title is None:
            errors.append(f"characters of {tid}: unknown title")
            continue
        roles = [c["role"] for c in cast]
        if len(cast) > MAX_CHARACTERS:
            errors.append(f"characters of {tid}: {len(cast)} records; at most {MAX_CHARACTERS}")
        for role, limit in ROLE_LIMITS.items():
            if roles.count(role) > limit:
                errors.append(f"characters of {tid}: {roles.count(role)} {role} records; at most {limit}")
        if sum(roles.count(r) for r in SHARED_SLOT) > 1:
            errors.append(f"characters of {tid}: one {' or '.join(SHARED_SLOT)} at most")
        if roles.count("protagonist") != 1:
            errors.append(f"characters of {tid}: a cast needs its protagonist")
        kits = [c for c in cast if c.get("power_kit")]
        if len(kits) > MAX_POWER_KITS:
            errors.append(f"characters of {tid}: {len(kits)} power kits; at most {MAX_POWER_KITS}")
        if kits and not any(c["role"] == "protagonist" for c in kits):
            errors.append(f"characters of {tid}: power kits start with the protagonist's")
        seasons = (title.get("scope") or {}).get("seasons") or []
        film = title.get("format") == "film"
        for c in cast:
            cid = c["character_id"]
            if c.get("villain") and c["role"] not in ANTAGONIST_ROLES:
                errors.append(f"character {cid}: villain fields on a {c['role']}")
            for tp in c.get("turning_points") or []:
                loc = tp.get("locator") or {}
                if not film and loc.get("episode") is None:
                    errors.append(f"character {cid}: a turning point needs its episode")
                if loc.get("season") is not None and loc["season"] not in seasons:
                    errors.append(f"character {cid}: a turning point's season is outside the title's scope")
    return errors
