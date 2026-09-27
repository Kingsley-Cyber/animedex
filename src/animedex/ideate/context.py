"""What IDEATE works from, rebuilt from canonical data each run (never from chat or memory).

- the atom pool: transfer atoms whose source atom is load-bearing-eligible (04, AC-26);
- each title's structural set (the six power/relationship enums + bridge concepts of its
  load-bearing transfers) and procedural set (gate, cost, progression, counter) for the clone gate;
- the graveyard (premise-level flops warn; execution-level flops feed the revival operator);
- imported/export lanes for T4 evidence; coverage adequacy for "zero is not novel": by the rule of
  three (statistics as gates, item 2), zeros are open only when 3/n < 0.02, with n the corpus titles
  that have power_combat and good field completion plus the powered census rows;
- optional census counts (v1.6): occupancy only, never ideation input. Census rows count (for
  adequacy and the novelty gate's PMI) only with at least `ideate.census_novelty_min_rows` (200)
  powered census rows (owner ruling 2026-09-27, before M5 item 5; kept, since it is stricter);
- the rows the novelty gate measures PMI over (statistics as gates, item 4): each title's structural
  values and bridge concepts, and each powered census row's structural values;
- the fields the agreement eval flagged unreliable (`eval/agreement/reliability.json`): they leave
  the novelty pairs and the grid-zero claims;
- per-cell counts (corpus titles, census rows) and the prior-art verdicts already recorded for
  each cell, for the M5 call brief.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from animedex import stats
from animedex.analyze import graveyard_index, structural_set
from animedex.config import Settings
from animedex.eligibility import eligible_atom_ids
from animedex.integrity import name_list
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.statgates import unreliable_fields
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


def cell_key(profile: dict[str, str], dims: list[str]) -> str:
    return "|".join(f"{d.split('.')[-1]}={profile.get(d.split('.')[-1])}" for d in dims)


def _title_cell(rec: dict[str, Any], dims: list[str]) -> str | None:
    values = {}
    for d in dims:
        block, name = d.split(".")
        value = ((rec.get(block) or {}).get(name) or {}).get("value")
        if not value or str(value).startswith("other"):
            return None
        values[name] = value
    return cell_key(values, dims)


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
    adequate: bool                                  # zeros open by the rule of three (3/n < 0.02)
    themes: list[str]
    names: tuple[set[str], set[str]]
    census_systems: Counter = field(default_factory=Counter)  # borrowed_system -> titles using it as a power
    census_size: int = 0
    powered_census: int = 0                         # census rows with has_power_system true
    census_novelty_min_rows: int = 200              # census-backed zeros count only from here (M5 ruling)
    cell_titles: Counter = field(default_factory=Counter)   # grid cell key -> corpus titles in it
    cell_census: Counter = field(default_factory=Counter)   # grid cell key -> census rows in it (counts only)
    prior_art_by_cell: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    census_rows: list[frozenset[str]] = field(default_factory=list)  # powered census rows' structural values
    adequacy_n: int = 0                             # the rows behind `adequate`
    unreliable: dict[str, dict[str, Any]] = field(default_factory=dict)  # fields the agreement eval flagged

    @property
    def census_zeros_trusted(self) -> bool:
        """Census rows count (adequacy, novelty PMI) only with enough powered census rows."""
        return self.powered_census >= self.census_novelty_min_rows

    @property
    def rule_of_three(self) -> float:
        return stats.rule_of_three(self.adequacy_n)

    def enum_rows(self) -> list[frozenset[str]]:
        """Rows for enum-pair PMI: each title's structural values, plus the powered census rows once the
        census floor holds (the same counts the novelty gate used before PMI replaced "unseen pair")."""
        titles = [frozenset(i for i in s if not i.startswith("bridge:")) for _, s in sorted(self.title_struct.items())]
        return [r for r in titles if r] + (list(self.census_rows) if self.census_zeros_trusted else [])

    def concept_rows(self) -> list[frozenset[str]]:
        """Rows for bridge-pair PMI: the bridge concepts of each title's load-bearing patterns."""
        rows = [frozenset(i for i in s if i.startswith("bridge:")) for _, s in sorted(self.title_struct.items())]
        return [r for r in rows if r]

    def unreliable_dims(self, dims: list[str]) -> list[str]:
        """Grid dimensions the agreement eval flagged unreliable: their zeros are never claimed open."""
        return [d for d in dims if d in self.unreliable]

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
    completion = float(settings.coverage.get("min_field_completion", 0.8))
    adequate_titles = [c for c in state.get("coverage", []) if "power_combat" in c.get("modules_active", [])
                       and c.get("field_completion", 0) >= completion]
    dims = list(settings.ideate.get("grid_dims") or [])
    min_rows = int(settings.ideate.get("census_novelty_min_rows", 200))
    census = state.get("census", [])
    census_systems: Counter = Counter()
    cell_census: Counter = Counter()
    census_rows: list[frozenset[str]] = []
    for c in census:  # v1.6: counts only
        values = {f"{PROFILE_PATHS[k]}={c[k]}" for k in PROFILE_PATHS if c.get(k)}
        pair_counts.update(_pairs(values))
        if c.get("has_power_system"):
            census_rows.append(frozenset(v for v in values if not v.split("=", 1)[1].startswith("other")))
        if c.get("has_power_system") and c.get("borrowed_system"):
            census_systems[c["borrowed_system"]] += 1
        if dims and all(c.get(d.split(".")[-1]) for d in dims):
            cell_census[cell_key({d.split(".")[-1]: c[d.split(".")[-1]] for d in dims}, dims)] += 1
    powered_census = sum(1 for c in census if c.get("has_power_system"))
    cell_titles: Counter = Counter(k for k in (_title_cell(rec, dims) for rec in titles.values()) if dims and k)
    cells_of_ideas = {i["idea_id"]: i.get("grid_cell") for i in state.get("idea", [])}
    prior_art_by_cell: dict[str, list[dict[str, Any]]] = {}
    for pa in sorted(state.get("prior_art", []), key=lambda r: r["check_id"]):
        cell = cells_of_ideas.get(pa.get("subject_id"))
        if cell:
            prior_art_by_cell.setdefault(cell, []).append(pa)
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
    # rule of three over the well-covered power_combat titles, plus the powered census rows once the census
    # floor holds (census-backed adequacy keeps the M5 ruling's 200-row floor)
    n = len(adequate_titles) + (powered_census if powered_census >= min_rows else 0)
    return Context(titles=titles, outcomes=outcomes, pool=pool, title_struct=title_struct, title_proc=title_proc,
                   graveyard=graveyard_index(state), lanes=lanes, pair_counts=pair_counts,
                   concept_pairs=concept_pairs, adequate=stats.zero_is_open(n),
                   themes=themes, names=name_list(state, vocab), census_systems=census_systems,
                   census_size=len(census), powered_census=powered_census, census_novelty_min_rows=min_rows,
                   cell_titles=cell_titles, cell_census=cell_census, prior_art_by_cell=prior_art_by_cell,
                   census_rows=census_rows, adequacy_n=n, unreliable=unreliable_fields(paths))
