"""What IDEATE works from, rebuilt from canonical data each run (never from chat or memory).

- the atom pool: transfer atoms whose source atom is load-bearing-eligible (04, AC-26);
- each title's structural set (the six power/relationship enums + bridge concepts of its
  load-bearing transfers) and procedural set (gate, cost, progression, counter) for the clone gate;
- the graveyard (premise-level flops warn; execution-level flops feed the revival operator);
- imported/export lanes for T4 evidence; coverage adequacy for "zero is not novel";
- optional census counts (v1.6): occupancy only, never ideation input.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from animedex.analyze import graveyard_index, structural_set
from animedex.config import Settings
from animedex.eligibility import eligible_atom_ids
from animedex.integrity import name_list
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.store.canonical import CanonicalStore

PROFILE_PATHS = {"gate": "power_combat.gate", "cost_of_power": "power_combat.cost_of_power",
                 "progression": "power_combat.progression", "visible_counter": "power_combat.visible_counter",
                 "fight_medium": "power_combat.fight_medium", "power_is": "relationships.power_is"}
PROCEDURAL = ("gate", "cost_of_power", "progression", "visible_counter")
WESTERN = ("western_animation", "adult_animation", "live_action", "film")


def profile_set(profile: dict[str, str], keys: tuple[str, ...] = tuple(PROFILE_PATHS)) -> set[str]:
    return {f"{PROFILE_PATHS[k]}={profile[k]}" for k in keys if profile.get(k) and not str(profile[k]).startswith("other")}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


@dataclass
class Context:
    titles: dict[str, dict[str, Any]]
    outcomes: dict[str, dict[str, Any]]
    pool: list[dict[str, Any]]                      # eligible transfers, with source title + medium
    title_struct: dict[str, set[str]]
    title_proc: dict[str, set[str]]
    graveyard: list[dict[str, Any]]
    lanes: dict[str, set[str]]                      # imported / export bridge concepts
    pair_counts: Counter                            # enum-pair co-occurrence across titles (+ census)
    concept_pairs: set[tuple[str, str]]             # bridge-concept pairs seen together in one title
    adequate: bool                                  # power_combat coverage adequate for zeros
    themes: list[str]
    names: tuple[set[str], set[str]]
    census_systems: Counter = field(default_factory=Counter)  # borrowed_system -> titles using it as a power
    census_size: int = 0

    def label(self, tid: str) -> str | None:
        o = self.outcomes.get(tid) or {}
        return o.get("label") or ((self.titles[tid].get("core") or {}).get("outcome") or {}).get("value")

    def execution_flops(self) -> list[dict[str, Any]]:
        return [g for g in self.graveyard if g["failure_level"] == "execution"]


def _pairs(values: set[str]) -> set[tuple[str, str]]:
    return {tuple(sorted(p)) for p in combinations(sorted(values), 2)}


def build_context(paths: Paths, settings: Settings, vocab: Vocab) -> Context:
    state = CanonicalStore(paths).state()
    titles = {t["title_id"]: t for t in state.get("title", [])}
    outcomes = {o["title_id"]: o for o in state.get("outcome", [])}
    eligible = eligible_atom_ids(state)
    atoms = {m["atom_id"]: m for m in state.get("mechanism", [])}
    pool, concepts_by_title = [], {}
    for t in sorted(state.get("transfer", []), key=lambda t: t["transfer_id"]):
        if t["source_atom_id"] not in eligible:
            continue
        tid = t["source_atom_id"].split(".")[0]
        pool.append({**t, "title_id": tid, "medium": titles[tid]["medium"],
                     "support": (atoms.get(t["source_atom_id"]) or {}).get("support", {}).get("status", "profile_only")})
        concepts_by_title.setdefault(tid, set()).update(t["bridge"])
    title_struct, title_proc, pair_counts, concept_pairs = {}, {}, Counter(), set()
    for tid, rec in titles.items():
        enums = set(structural_set(rec))
        title_struct[tid] = enums | {f"bridge:{c}" for c in concepts_by_title.get(tid, set())}
        title_proc[tid] = {e for e in enums if e.split("=")[0] in {PROFILE_PATHS[k] for k in PROCEDURAL}}
        pair_counts.update(_pairs(enums))
        concept_pairs |= _pairs(concepts_by_title.get(tid, set()))
    cov = settings.coverage
    need, completion = int(cov.get("min_titles_with_module", 5)), float(cov.get("min_field_completion", 0.8))
    adequate_titles = [c for c in state.get("coverage", []) if "power_combat" in c.get("modules_active", [])
                       and c.get("field_completion", 0) >= completion]
    census = state.get("census", [])
    census_systems: Counter = Counter()
    for c in census:  # v1.6: counts only
        values = {f"{PROFILE_PATHS[k]}={c[k]}" for k in PROFILE_PATHS if c.get(k)}
        pair_counts.update(_pairs(values))
        if c.get("has_power_system") and c.get("borrowed_system"):
            census_systems[c["borrowed_system"]] += 1
    powered_census = sum(1 for c in census if c.get("has_power_system"))
    lanes: dict[str, set[str]] = {"imported": set(), "export": set()}
    by_concept: dict[str, set[str]] = {}
    for item in pool:
        for concept in item["bridge"]:
            by_concept.setdefault(concept, set()).add(item["title_id"])
    for concept, tids in by_concept.items():
        media = [titles[t]["medium"] for t in tids]
        if sum(m != "anime" for m in media) >= 2 and "anime" not in media:
            lanes["imported"].add(concept)
        if "anime" in media and not any(m in WESTERN for m in media):
            lanes["export"].add(concept)
    themes = sorted({((r.get("core") or {}).get("core_question") or {}).get("value") for r in titles.values()} - {None})
    return Context(titles=titles, outcomes=outcomes, pool=pool, title_struct=title_struct, title_proc=title_proc,
                   graveyard=graveyard_index(state), lanes=lanes, pair_counts=pair_counts,
                   concept_pairs=concept_pairs, adequate=len(adequate_titles) >= need or powered_census >= need,
                   themes=themes, names=name_list(state, vocab), census_systems=census_systems,
                   census_size=len(census))
