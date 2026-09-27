"""A query and a saved answer for every competency question (AC-21), deterministic (AC-24).

Answers go to build/cq_answers/<CQ-ID>.json with sorted rows. Gap questions carry a
coverage-adequacy flag (AC-22). Statistics as gates (owner ruling 2026-09-27):
- a zero is "open" only when the rule-of-three bound 3/n is below 0.02 (n >= 151), with n the titles that
  have the module active and good field completion (`coverage.min_field_completion`), or the powered
  census rows for census-backed questions; this replaced the old five-title minimum;
- the grid-gap questions rank their empty cells by expected count under independence (n x p(x) x p(y)):
  expected >= 3 with none observed is a real gap, the rest are unsurprising (`gap_ranking`);
- a question whose zeros rest on a field the agreement eval flagged unreliable is excluded from the gap
  reports (`zeros_are: excluded: unreliable field`).
Questions whose data arrives later (ideas at M5, episodes at M6) have real queries that return no
rows until then.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from animedex import stats
from animedex.config import Settings
from animedex.models.ideation import BORROWED_SYSTEMS
from animedex.ontology import CQSet, Vocab
from animedex.statgates import MIN_OPEN_N, why_unreliable
from animedex.statgates import adequacy as rule_of_three_adequacy
from animedex.store.atomic import atomic_write_text
from animedex.textutil import sha256_text, stable_json

LABEL = ("label AS (SELECT t.title_id, COALESCE(o.label, f.value) AS label FROM titles t "
         "LEFT JOIN outcomes o USING (title_id) "
         "LEFT JOIN title_fields f ON f.title_id = t.title_id AND f.path = 'core.outcome')")
LB = ("lb AS (SELECT tr.transfer_id, m.title_id, t.medium FROM transfers tr "
      "JOIN v_load_bearing m ON m.atom_id = tr.source_atom_id JOIN titles t ON t.title_id = m.title_id)")
WESTERN = "('western_animation', 'adult_animation', 'live_action', 'film')"


def _pivot(title_col: str, paths: list[str]) -> str:
    return ", ".join(f"MAX(CASE WHEN f.path = '{p}' THEN f.value END) AS \"{p.split('.')[-1]}\"" for p in paths)


def _wide(paths: list[str]) -> str:
    """A CTE body: one row per title with the given fields as columns (named by their last path part)."""
    return f"SELECT f.title_id, {_pivot('f', paths)} FROM title_fields f GROUP BY 1"


def _parts(path: str, parts: list[str], by_item: bool = True) -> str:
    """A CTE body: list items (or a group) of a v1.5.0 field, one row per item with its parts as columns."""
    cols = ", ".join(f"MAX(CASE WHEN part = '{p}' THEN value END) AS \"{p}\"" for p in parts)
    keys = "title_id, idx" if by_item else "title_id"
    return f"SELECT {keys}, {cols} FROM title_field_parts WHERE path = '{path}' GROUP BY {keys}"


NEAR = 0.3  # CQ-I24: content-word overlap at or above this counts as a lexical near-neighbor


@dataclass(frozen=True)
class Query:
    sql: str
    params: tuple[str, ...] = ()   # names resolved by `_params`
    note: str = ""
    module: str | None = None      # adequacy flag for this module's zeros
    census: bool = False           # zeros are census counts: adequacy over the powered census rows


QUERIES: dict[str, Query] = {
    "CQ-G01": Query(
        "WITH g AS (SELECT unnest(?::VARCHAR[]) AS gate), c AS (SELECT unnest(?::VARCHAR[]) AS cost_of_power), "
        "p AS (SELECT a.value AS gate, b.value AS cost_of_power, COUNT(DISTINCT a.title_id) AS n FROM v_incidence a "
        "JOIN v_incidence b ON a.title_id = b.title_id AND a.path = 'power_combat.gate' "
        "AND b.path = 'power_combat.cost_of_power' GROUP BY 1, 2) "
        "SELECT g.gate, c.cost_of_power FROM g CROSS JOIN c LEFT JOIN p ON p.gate = g.gate "
        "AND p.cost_of_power = c.cost_of_power WHERE p.n IS NULL",
        ("enum:power_combat.gate", "enum:power_combat.cost_of_power"), module="power_combat"),
    "CQ-G02": Query(
        f"WITH {LABEL}, cell AS (SELECT a.title_id, a.value AS gate, b.value AS cost_of_power FROM v_incidence a "
        "JOIN v_incidence b ON a.title_id = b.title_id AND a.path = 'power_combat.gate' "
        "AND b.path = 'power_combat.cost_of_power') "
        "SELECT cell.gate, cell.cost_of_power, cell.title_id, l.label, o.failure_level, o.failure_reason "
        "FROM cell JOIN label l USING (title_id) LEFT JOIN outcomes o USING (title_id) "
        "WHERE l.label IN ('mixed', 'flop') AND NOT EXISTS (SELECT 1 FROM cell c2 JOIN label l2 USING (title_id) "
        "WHERE c2.gate = cell.gate AND c2.cost_of_power = cell.cost_of_power AND l2.label = 'hit')",
        note="cells no hit occupies, tried by mixed/flop titles; only premise-level failures are warnings (v1.3)"),
    "CQ-G03": Query(
        f"WITH {LABEL}, cites AS (SELECT m.title_id, COUNT(*) AS n FROM v_load_bearing m WHERE "
        "m.evidence_refs LIKE '%core.unserved_appetite%' OR m.evidence_refs LIKE '%core.borrowed_template%' "
        "OR m.evidence_refs LIKE '%core.broken_rule%' GROUP BY 1), "
        f"w AS (SELECT f.title_id, {_pivot('f', ['core.unserved_appetite', 'core.borrowed_template', 'core.broken_rule'])} "
        "FROM title_fields f GROUP BY 1) "
        "SELECT w.title_id, w.unserved_appetite, w.borrowed_template, w.broken_rule, COALESCE(c.n, 0) AS "
        "n_load_bearing_atoms_citing FROM w JOIN label l USING (title_id) LEFT JOIN cites c USING (title_id) "
        "WHERE l.label = 'hit' AND w.unserved_appetite IS NOT NULL AND COALESCE(c.n, 0) > 0",
        note="appetite phrases are free text; cross-title matching arrives with M7 clusters"),
    "CQ-G04": Query(
        "WITH g AS (SELECT unnest(?::VARCHAR[]) AS progression), c AS (SELECT unnest(?::VARCHAR[]) AS fight_medium), "
        "p AS (SELECT a.value AS progression, b.value AS fight_medium FROM v_incidence a JOIN v_incidence b "
        "ON a.title_id = b.title_id AND a.path = 'power_combat.progression' AND b.path = 'power_combat.fight_medium') "
        "SELECT g.progression, c.fight_medium FROM g CROSS JOIN c WHERE NOT EXISTS (SELECT 1 FROM p "
        "WHERE p.progression = g.progression AND p.fight_medium = c.fight_medium)",
        ("enum:power_combat.progression", "enum:power_combat.fight_medium"), module="power_combat"),
    "CQ-G05": Query(
        f"WITH {LB}, x AS (SELECT tb.concept, COUNT(DISTINCT CASE WHEN lb.medium <> 'anime' THEN lb.title_id END) "
        "AS n_non_anime, COUNT(DISTINCT CASE WHEN lb.medium = 'anime' THEN lb.title_id END) AS n_anime "
        "FROM transfer_bridge tb JOIN lb USING (transfer_id) GROUP BY 1) "
        "SELECT concept, n_non_anime, n_anime FROM x WHERE n_non_anime >= 2 AND n_anime = 0",
        note="imported lanes by bridge concept (M7 clusters will refine the pattern key)"),
    "CQ-G06": Query(
        f"WITH {LB}, x AS (SELECT tb.concept, COUNT(DISTINCT CASE WHEN lb.medium = 'anime' THEN lb.title_id END) "
        f"AS n_anime, COUNT(DISTINCT CASE WHEN lb.medium IN {WESTERN} THEN lb.title_id END) AS n_western "
        "FROM transfer_bridge tb JOIN lb USING (transfer_id) GROUP BY 1) "
        "SELECT concept, n_anime, n_western FROM x WHERE n_anime >= 1 AND n_western = 0",
        note="export lanes by bridge concept"),
    "CQ-G07": Query(
        "WITH m AS (SELECT unnest(?::VARCHAR[]) AS module) SELECT m.module, "
        "COUNT(c.title_id) FILTER (WHERE c.field_completion >= ?) AS n_adequate_titles "
        "FROM m LEFT JOIN coverage c ON c.modules_active LIKE '%\"' || m.module || '\"%' GROUP BY 1",
        ("modules", "min_completion"),
        note="a zero is trustworthy only where the rule-of-three bound 3/n_adequate_titles is below 0.02 (the minimum)"),
    "CQ-G08": Query(
        "SELECT a.title_id, a.value AS tone, b.value AS premise_engine FROM title_fields a JOIN title_fields b "
        "ON a.title_id = b.title_id AND a.path = 'core.tone' AND b.path = 'core.premise_engine' "
        "JOIN titles t ON t.title_id = a.title_id WHERE t.medium = 'anime' AND t.modules_active LIKE "
        "'%\"power_combat\"%' AND a.value IS NOT NULL AND b.value IS NOT NULL",
        note="phrase fields: lists what battle anime use; unused combinations need M7 clusters"),
    "CQ-G09": Query(
        f"WITH {LABEL} SELECT f.field, f.value, l.label, COUNT(DISTINCT f.title_id) AS n_titles, "
        "array_to_string(list_sort(list_distinct(list(o.studio))), '; ') AS studios, "
        "array_to_string(list_sort(list_distinct(list(o.source_popularity))), '; ') AS source_popularity "
        "FROM title_fields f JOIN label l USING (title_id) LEFT JOIN outcomes o USING (title_id) "
        "WHERE f.path IN ('anime_production.source_medium', 'anime_production.demographic', "
        "'anime_production.adaptation_fidelity') AND f.value IS NOT NULL GROUP BY 1, 2, 3",
        note="confounders shown next to each cluster"),
    "CQ-I01": Query(
        f"WITH {LB} SELECT tb.concept, COUNT(DISTINCT lb.medium) AS n_media, "
        "array_to_string(list_sort(list_distinct(list(lb.medium))), ', ') AS media, "
        "COUNT(DISTINCT tb.transfer_id) AS n_transfers FROM transfer_bridge tb JOIN lb USING (transfer_id) "
        "GROUP BY 1 HAVING COUNT(DISTINCT lb.medium) >= 2"),
    "CQ-I02": Query(
        f"WITH {LABEL}, {LB}, hc AS (SELECT DISTINCT tb.concept, lb.title_id FROM transfer_bridge tb "
        "JOIN lb USING (transfer_id) JOIN label l ON l.title_id = lb.title_id WHERE l.label = 'hit'), "
        "c AS (SELECT DISTINCT concept FROM hc) SELECT a.concept AS concept_a, b.concept AS concept_b "
        "FROM c a JOIN c b ON a.concept < b.concept WHERE NOT EXISTS (SELECT 1 FROM hc x JOIN hc y "
        "ON x.title_id = y.title_id WHERE x.concept = a.concept AND y.concept = b.concept)",
        note="bridge-concept level; both appear in hits' load-bearing transfers but never in one title"),
    "CQ-I03": Query(
        "SELECT q.value AS core_question, g.value AS gate, q.title_id FROM title_fields q LEFT JOIN title_fields g "
        "ON g.title_id = q.title_id AND g.path = 'power_combat.gate' WHERE q.path = 'core.core_question' "
        "AND q.value IS NOT NULL", note="themes are free text; per-theme gaps need M7 clusters"),
    "CQ-I04": Query("SELECT idea_id, closest_existing, structural_jaccard_max, premise_cosine_max FROM ideas"),
    "CQ-I05": Query("SELECT idea_id, graveyard_hits FROM ideas WHERE graveyard_hits <> '[]'"),
    "CQ-I06": Query(
        f"WITH w AS (SELECT f.title_id, {_pivot('f', ['core.central_mystery', 'core.knowledge_gap', 'core.reveal_cadence', 'power_combat.visible_counter'])} "
        "FROM title_fields f GROUP BY 1) SELECT * FROM w WHERE central_mystery IS NOT NULL OR knowledge_gap IS NOT NULL"),
    "CQ-I07": Query(
        "WITH v AS (SELECT unnest(?::VARCHAR[]) AS power_is), used AS (SELECT DISTINCT f.value FROM title_fields f "
        "JOIN titles t USING (title_id) WHERE f.path = 'relationships.power_is' AND t.medium = 'anime' "
        "AND t.modules_active LIKE '%\"power_combat\"%') SELECT v.power_is, v.power_is IN (SELECT value FROM used) "
        "AS used_in_battle_anime FROM v", ("enum:relationships.power_is",), module="relationships"),
    "CQ-I08": Query(
        "SELECT t.title_id, t.medium, c.value AS comedic_engine, r.value AS ranking_ladder FROM titles t "
        "JOIN title_fields c ON c.title_id = t.title_id AND c.path = 'comedy_satire.comedic_engine' "
        "LEFT JOIN title_fields r ON r.title_id = t.title_id AND r.path = 'power_combat.ranking_ladder' "
        "WHERE t.medium IN ('western_animation', 'adult_animation') AND c.value IS NOT NULL"),
    "CQ-I09": Query(
        f"SELECT f.title_id, {_pivot('f', ['film.act_structure', 'film.runtime_compression', 'film.set_pieces', 'film.closure'])} "
        "FROM title_fields f WHERE f.block = 'film' GROUP BY 1"),
    "CQ-I10": Query(
        f"WITH {LABEL}, w AS (SELECT f.title_id, {_pivot('f', ['core.want_vs_need', 'core.flaw', 'core.moral_line', 'core.central_opposition', 'core.opposition_logic', 'core.stakes_clock', 'core.world_rules'])} "
        "FROM title_fields f GROUP BY 1) SELECT w.*, l.label FROM w JOIN label l USING (title_id)"),
    "CQ-I11": Query(
        f"WITH {LABEL} SELECT m.atom_id, m.engine_goal, m.engine_constraint, m.engine_cost, m.engine_dilemma, "
        "g.value AS gate, c.value AS cost_of_power FROM v_load_bearing m JOIN label l USING (title_id) "
        "LEFT JOIN title_fields g ON g.title_id = m.title_id AND g.path = 'power_combat.gate' "
        "LEFT JOIN title_fields c ON c.title_id = m.title_id AND c.path = 'power_combat.cost_of_power' "
        "WHERE m.atom_kind = 'engine' AND l.label = 'hit'"),
    "CQ-I12": Query("SELECT tb.concept, tr.transfer_id, tr.variable_details FROM transfer_bridge tb "
                    "JOIN transfers tr USING (transfer_id)"),
    "CQ-I13": Query("SELECT operator, status, COUNT(*) AS n FROM ideas GROUP BY 1, 2"),
    "CQ-I14": Query(
        "SELECT o.title_id, o.label, o.failure_reason, o.failure_evidence, (SELECT COUNT(*) FROM v_load_bearing m "
        "WHERE m.title_id = o.title_id) AS n_load_bearing FROM outcomes o WHERE o.failure_level = 'execution'"),
    "CQ-G10": Query(
        "WITH g AS (SELECT unnest(?::VARCHAR[]) AS gate), c AS (SELECT unnest(?::VARCHAR[]) AS cost_of_power), "
        "p AS (SELECT gate, cost_of_power, COUNT(*) AS n FROM census WHERE has_power_system GROUP BY 1, 2) "
        "SELECT g.gate, c.cost_of_power FROM g CROSS JOIN c LEFT JOIN p ON p.gate = g.gate "
        "AND p.cost_of_power = c.cost_of_power WHERE p.n IS NULL",
        ("enum:power_combat.gate", "enum:power_combat.cost_of_power"),
        note="census counts only (v1.6): recall-based occupancy across the catalog", census=True),
    "CQ-I15": Query("SELECT claim_kind, verdict, COUNT(*) AS n FROM prior_art GROUP BY 1, 2"),
    # Light path (owner instruction 2026-09-27, D-055): the notes index answers the lane and gap questions
    "CQ-N01": Query(
        "SELECT COALESCE(story_engine, 'unknown') AS lane, COALESCE(outcome, 'unknown') AS outcome, COUNT(*) AS n, "
        "string_agg(slug, ', ' ORDER BY slug) AS notes FROM notes GROUP BY 1, 2 ORDER BY 1, 2",
        note="light path: lanes are the notes' story engines; outcome is the catalog label"),
    "CQ-N02": Query(
        "WITH g AS (SELECT unnest(?::VARCHAR[]) AS gate), c AS (SELECT unnest(?::VARCHAR[]) AS cost_of_power), "
        "p AS (SELECT gate, cost_of_power, COUNT(*) AS n FROM notes GROUP BY 1, 2) "
        "SELECT g.gate, c.cost_of_power FROM g CROSS JOIN c LEFT JOIN p ON p.gate = g.gate "
        "AND p.cost_of_power = c.cost_of_power WHERE p.n IS NULL",
        ("enum:power_combat.gate", "enum:power_combat.cost_of_power"),
        note="light path: gate x cost_of_power pairs no note holds; ranked by expected count over the notes"),
    "CQ-N03": Query(
        "WITH g AS (SELECT unnest(?::VARCHAR[]) AS progression), c AS (SELECT unnest(?::VARCHAR[]) AS visible_counter), "
        "p AS (SELECT progression, visible_counter, COUNT(*) AS n FROM notes GROUP BY 1, 2) "
        "SELECT g.progression, c.visible_counter FROM g CROSS JOIN c LEFT JOIN p ON p.progression = g.progression "
        "AND p.visible_counter = c.visible_counter WHERE p.n IS NULL",
        ("enum:power_combat.progression", "enum:power_combat.visible_counter"),
        note="light path: progression x visible_counter pairs no note holds; ranked by expected count over the notes"),
    "CQ-N04": Query("", note="not tracked: set_structure and power_is are not in the notes index (heavy path, gold "
                             "titles only)"),
    "CQ-N05": Query(
        "SELECT medium, COALESCE(outcome, 'unknown') AS outcome, COUNT(*) AS n FROM notes GROUP BY 1, 2 ORDER BY 1, 2",
        note="light path: what the index covers, by medium and outcome"),
    "CQ-P01": Query(  # v1.9 print: the lanes are the census's story engines; popularity is AniList's count
        "SELECT COALESCE(story_engine, 'unknown') AS lane, medium, title, year, popularity FROM census "
        "WHERE medium IN ('manga', 'manhwa', 'webtoon', 'light_novel') AND adaptation = 'none' "
        "ORDER BY lane, popularity DESC NULLS LAST, title",
        note="print census rows with no screen adaptation (catalog relations), grouped by story engine; counts only"),
    "CQ-E01": Query(
        "SELECT mo.moment_type, COUNT(DISTINCT mo.moment_id) AS n_moments, COUNT(DISTINCT mo.title_id) AS n_titles, "
        "array_to_string(list_sort(list_distinct(list(pf.value))), '; ') AS primary_feelings, "
        "COUNT(DISTINCT m.atom_id) AS n_effect_atoms_citing FROM moments mo LEFT JOIN title_fields pf "
        "ON pf.title_id = mo.title_id AND pf.path = 'core.primary_feeling' LEFT JOIN mechanisms m "
        "ON m.element_moment_id = mo.moment_id GROUP BY 1"),
    "CQ-E02": Query("SELECT e.title_id, e.function, e.end_hook, e.gap_change, o.label FROM episodes e "
                    "LEFT JOIN outcomes o USING (title_id) WHERE e.selection_reason = 'pilot'", note="data from M6"),
    "CQ-E03": Query(
        "SELECT mo.moment_id, mo.moment_type, ps.value AS power_source, g.value AS gate, fm.value AS fight_medium, "
        "st.value AS signature_technique, cs.value AS choreography_style, vs.value AS power_visual_signature "
        "FROM moments mo LEFT JOIN title_fields ps ON ps.title_id = mo.title_id AND ps.path = 'power_combat.power_source' "
        "LEFT JOIN title_fields g ON g.title_id = mo.title_id AND g.path = 'power_combat.gate' "
        "LEFT JOIN title_fields fm ON fm.title_id = mo.title_id AND fm.path = 'power_combat.fight_medium' "
        "LEFT JOIN title_fields st ON st.title_id = mo.title_id AND st.path = 'power_combat.signature_technique' "
        "LEFT JOIN title_fields cs ON cs.title_id = mo.title_id AND cs.path = 'sensory.choreography_style' "
        "LEFT JOIN title_fields vs ON vs.title_id = mo.title_id AND vs.path = 'sensory.power_visual_signature' "
        "WHERE mo.moment_type IN ('first_victory', 'power_up', 'transformation', 'defeat', 'reversal', 'sacrifice')"),
    "CQ-E04": Query(
        f"WITH {LABEL} SELECT t.medium, l.label, f.field, f.value, COUNT(DISTINCT t.title_id) AS n_titles "
        "FROM titles t JOIN label l USING (title_id) JOIN title_fields f ON f.title_id = t.title_id "
        "AND f.block = 'series_engine' AND f.value IS NOT NULL GROUP BY 1, 2, 3, 4"),
    "CQ-E05": Query("SELECT title_id, episode_id, engine_atom_id, engine_advances FROM episodes "
                    "WHERE selection_reason = 'control'", note="data from M6"),
    "CQ-E06": Query("SELECT title_id, from_id, to_id, type FROM links WHERE type IN ('sets_up', 'pays_off')",
                    note="data from M6"),
    "CQ-E07": Query("SELECT support_status, COUNT(*) AS n FROM mechanisms GROUP BY 1", note="episode-backed from M6"),
    "CQ-E08": Query("SELECT title_id, episode_id, n_decisions FROM episodes WHERE n_decisions > 0",
                    note="data from M6"),
    # ---------------------------------------------------------------- v1.8: concept, character, abstract layers
    "CQ-G11": Query(
        f"WITH {LABEL}, g AS (SELECT unnest(?::VARCHAR[]) AS gate), e AS (SELECT unnest(?::VARCHAR[]) AS mc_edge), "
        "p AS (SELECT a.value AS gate, b.value AS mc_edge, COUNT(DISTINCT a.title_id) AS n_titles, "
        "COUNT(DISTINCT a.title_id) FILTER (WHERE l.label = 'hit') AS n_hits FROM v_incidence a JOIN v_incidence b "
        "ON a.title_id = b.title_id AND a.path = 'power_combat.gate' AND b.path = 'power_combat.mc_edge' "
        "JOIN label l ON l.title_id = a.title_id GROUP BY 1, 2) "
        "SELECT g.gate, e.mc_edge, COALESCE(p.n_titles, 0) AS n_titles, COALESCE(p.n_hits, 0) AS n_hits "
        "FROM g CROSS JOIN e LEFT JOIN p ON p.gate = g.gate AND p.mc_edge = e.mc_edge",
        ("enum:power_combat.gate", "enum:power_combat.mc_edge"), module="power_combat",
        note="every gate x mc_edge cell: n_hits > 0 shows the edges hits use; n_titles = 0 is an unused cell"),
    "CQ-G12": Query(
        "WITH k AS (SELECT unnest(?::VARCHAR[]) AS power_kind), c AS (SELECT unnest(?::VARCHAR[]) AS creativity_level), "
        "used AS (SELECT DISTINCT power_kind, creativity_level FROM characters WHERE has_kit "
        "AND creativity_level IS NOT NULL) SELECT k.power_kind, c.creativity_level FROM k CROSS JOIN c "
        "WHERE k.power_kind NOT IN ('stat_block', 'none') AND NOT EXISTS (SELECT 1 FROM used u "
        "WHERE u.power_kind = k.power_kind AND u.creativity_level = c.creativity_level)",
        ("enum:character.power_kind", "enum:character.creativity_level"), module="power_combat",
        note="stat_block kits generate drama through drama_source instead (CQ-I18)"),
    "CQ-G13": Query(
        "WITH s AS (SELECT unnest(?::VARCHAR[]) AS story_engine), bound AS (SELECT title_id FROM title_fields "
        "WHERE path = 'power_combat.power_embodiment' AND value = 'bound_entity' UNION "
        "SELECT title_id FROM characters WHERE power_kind = 'bound_entity'), "
        "paired AS (SELECT DISTINCT f.value FROM title_fields f JOIN bound USING (title_id) "
        "WHERE f.path IN ('core.story_engine', 'core.story_engine_secondary') AND f.value IS NOT NULL) "
        "SELECT s.story_engine, (SELECT COUNT(*) FROM bound) AS n_bound_entity_titles FROM s "
        "WHERE s.story_engine NOT IN (SELECT value FROM paired)",
        ("enum:core.story_engine",), module="power_combat",
        note="bound-entity powers: power_embodiment bound_entity, or a character kit of kind bound_entity"),
    "CQ-G14": Query(
        "WITH v AS (SELECT unnest(?::VARCHAR[]) AS villain_type), h AS (SELECT c.villain_type, "
        "COUNT(DISTINCT c.title_id) AS n FROM characters c JOIN title_fields w ON w.title_id = c.title_id "
        "AND w.path = 'core.world_visibility' AND w.value = 'hidden' WHERE c.villain_type IS NOT NULL GROUP BY 1) "
        "SELECT v.villain_type, COALESCE(h.n, 0) AS n_hidden_world_titles FROM v LEFT JOIN h USING (villain_type)",
        ("enum:character.villain_type",), module="core", note="0 = a villain type no hidden-world title uses"),
    "CQ-G15": Query(
        "WITH s AS (SELECT unnest(?::VARCHAR[]) AS setting_type), w AS (SELECT unnest(?::VARCHAR[]) AS world_visibility), "
        "c AS (SELECT unnest(?::VARCHAR[]) AS conflict_scale), used AS (SELECT a.value AS setting_type, "
        "b.value AS world_visibility, d.value AS conflict_scale FROM v_incidence a JOIN v_incidence b "
        "ON b.title_id = a.title_id AND b.path = 'core.world_visibility' JOIN v_incidence d "
        "ON d.title_id = a.title_id AND d.path = 'core.conflict_scale' WHERE a.path = 'core.setting_type') "
        "SELECT s.setting_type, w.world_visibility, c.conflict_scale FROM s CROSS JOIN w CROSS JOIN c "
        "WHERE NOT EXISTS (SELECT 1 FROM used u WHERE u.setting_type = s.setting_type "
        "AND u.world_visibility = w.world_visibility AND u.conflict_scale = c.conflict_scale)",
        ("enum:core.setting_type", "enum:core.world_visibility", "enum:core.conflict_scale"), module="core"),
    "CQ-G16": Query(
        "WITH v AS (SELECT 'set_structure' AS field, unnest(?::VARCHAR[]) AS value UNION ALL "
        "SELECT 'story_engine', unnest(?::VARCHAR[]) UNION ALL SELECT 'mc_archetype', unnest(?::VARCHAR[])), "
        "n AS (SELECT 'set_structure' AS field, set_structure AS value, COUNT(*) AS n FROM census "
        "WHERE has_power_system AND set_structure IS NOT NULL GROUP BY 1, 2 UNION ALL "
        "SELECT 'story_engine', story_engine, COUNT(*) FROM census WHERE story_engine IS NOT NULL GROUP BY 1, 2 "
        "UNION ALL SELECT 'mc_archetype', mc_archetype, COUNT(*) FROM census WHERE mc_archetype IS NOT NULL "
        "GROUP BY 1, 2) SELECT v.field, v.value, COALESCE(n.n, 0) AS n_census_titles FROM v "
        "LEFT JOIN n USING (field, value)",
        ("enum:power_combat.set_structure", "enum:core.story_engine", "enum:core.mc_archetype"),
        note="census counts only (v1.6): 0 = no catalog title recorded with that value", census=True),
    "CQ-G17": Query(
        "WITH s AS (SELECT unnest(?::VARCHAR[]) AS set_structure), m AS (SELECT unnest(?::VARCHAR[]) AS subset_mechanic), "
        "used AS (SELECT DISTINCT a.value AS set_structure, b.value AS subset_mechanic FROM v_incidence a "
        "JOIN v_incidence b ON b.title_id = a.title_id AND b.path = 'power_combat.subset_mechanics' "
        "WHERE a.path = 'power_combat.set_structure') SELECT s.set_structure, m.subset_mechanic FROM s CROSS JOIN m "
        "WHERE s.set_structure <> 'none' AND m.subset_mechanic <> 'none' AND NOT EXISTS (SELECT 1 FROM used u "
        "WHERE u.set_structure = s.set_structure AND u.subset_mechanic = m.subset_mechanic)",
        ("enum:power_combat.set_structure", "enum:power_combat.subset_mechanics"), module="power_combat"),
    "CQ-I16": Query(
        f"WITH w AS ({_wide(['power_combat.set_structure', 'power_combat.mc_edge', 'core.mc_start'])}), "
        "mc AS (SELECT title_id, relationship_to_power, medium, creativity_level, n_creativity_moves FROM characters "
        "WHERE role = 'protagonist') SELECT w.title_id, w.mc_start, w.mc_edge, mc.relationship_to_power, mc.medium, "
        "mc.creativity_level, mc.n_creativity_moves FROM w LEFT JOIN mc USING (title_id) "
        "WHERE w.set_structure = 'open_variety' AND w.mc_start IN ('weakest', 'below_average') "
        "AND (w.mc_edge = 'creative_reinterpretation' OR mc.relationship_to_power = 'creative_reinterpretation' "
        "OR mc.creativity_level IN ('inventive', 'transcendent'))",
        note="a weak start in an open-variety system, won by reinterpreting the medium"),
    "CQ-I17": Query(
        f"WITH w AS ({_wide(['power_combat.set_structure', 'power_combat.member_depth', 'power_combat.set_scaffold'])}) "
        "SELECT set_structure, set_scaffold, title_id FROM w WHERE set_structure IN ('closed_set', 'hierarchical') "
        "AND member_depth = 'identity_with_history'"),
    "CQ-I18": Query(
        f"WITH {LABEL} SELECT c.drama_source, l.label, COUNT(*) AS n_characters, COUNT(DISTINCT c.title_id) AS n_titles "
        "FROM characters c JOIN label l USING (title_id) WHERE c.power_kind = 'stat_block' GROUP BY 1, 2"),
    "CQ-I19": Query(
        f"WITH {LABEL}, lb AS (SELECT title_id, COUNT(*) AS n FROM v_load_bearing GROUP BY 1), "
        "cites AS (SELECT c.character_id, COUNT(DISTINCT m.atom_id) AS n FROM characters c JOIN v_load_bearing m "
        "ON m.title_id = c.title_id AND m.evidence_refs LIKE '%\"' || c.character_id || '\"%' GROUP BY 1) "
        "SELECT c.origin_power_link, COUNT(DISTINCT c.title_id) AS n_hit_titles_with_load_bearing_atoms, "
        "COUNT(DISTINCT c.character_id) AS n_characters, COALESCE(SUM(ci.n), 0) AS n_atoms_citing_the_character "
        "FROM characters c JOIN label l USING (title_id) JOIN lb USING (title_id) LEFT JOIN cites ci USING (character_id) "
        "WHERE l.label = 'hit' AND c.origin_power_link IS NOT NULL GROUP BY 1",
        note="P2 may cite a character record as evidence (v1.8); title-level counts until it does"),
    "CQ-I20": Query(
        f"WITH {LABEL} SELECT cf.value AS core_fantasy, se.value AS story_engine, COUNT(DISTINCT cf.title_id) "
        "AS n_hit_titles FROM title_field_members cf JOIN title_fields se ON se.title_id = cf.title_id "
        "AND se.path = 'core.story_engine' AND se.value IS NOT NULL JOIN label l ON l.title_id = cf.title_id "
        "WHERE cf.path = 'core.core_fantasy' AND l.label = 'hit' GROUP BY 1, 2"),
    "CQ-I21": Query(
        f"WITH {LABEL}, w AS ({_wide(['core.audience_promise', 'core.promise_mechanism', 'core.promise_break'])}), "
        "fp AS (SELECT title_id, array_to_string(list_sort(list(pattern)), ', ') AS failure_patterns, "
        "bool_or(pattern = 'promise_broken') AS promise_broken FROM outcome_failure_patterns GROUP BY 1) "
        "SELECT w.title_id, l.label, w.audience_promise, w.promise_mechanism, w.promise_break, fp.failure_patterns "
        "FROM w JOIN label l USING (title_id) LEFT JOIN fp USING (title_id) WHERE l.label IN ('mixed', 'flop') "
        "AND (w.promise_break IS NOT NULL OR COALESCE(fp.promise_broken, false))"),
    "CQ-I22": Query(
        f"WITH {LABEL} SELECT f.value AS escalation_model, COUNT(DISTINCT f.title_id) AS n_titles_100_plus, "
        "COUNT(DISTINCT f.title_id) FILTER (WHERE l.label = 'hit') AS n_hits_100_plus FROM title_fields f "
        "JOIN coverage c USING (title_id) JOIN label l USING (title_id) WHERE f.path = 'core.escalation_model' "
        "AND f.value IS NOT NULL AND c.eps_in_scope >= 100 GROUP BY 1",
        note="episodes in scope arrive with M6 (coverage.episodes.in_scope)"),
    "CQ-I23": Query(
        "WITH s AS (SELECT unnest(?::VARCHAR[]) AS system), cn AS (SELECT borrowed_system AS system, COUNT(*) AS n "
        "FROM census WHERE has_power_system GROUP BY 1), k AS (SELECT s.system, COUNT(DISTINCT f.title_id) AS n "
        "FROM s JOIN title_fields f ON f.path = 'core.real_world_isomorphism' AND f.value IS NOT NULL "
        "AND lower(f.value) LIKE '%' || split_part(s.system, '_', 1) || '%' GROUP BY 1) "
        "SELECT s.system, COALESCE(cn.n, 0) AS n_census_powered_titles, COALESCE(k.n, 0) AS n_corpus_mentions "
        "FROM s LEFT JOIN cn USING (system) LEFT JOIN k USING (system) "
        "WHERE COALESCE(cn.n, 0) = 0 AND COALESCE(k.n, 0) = 0",
        ("borrowed_systems",),
        note="census counts plus a word match on the corpus's real_world_isomorphism phrases; M7 clusters map "
             "the phrases properly", census=True),
    "CQ-I24": Query(
        "WITH p AS (SELECT title_id, list_distinct(list_filter(string_split(lower(regexp_replace(value, '[^A-Za-z ]', "
        "' ', 'g')), ' '), x -> length(x) > 3)) AS w FROM title_fields WHERE path = 'core.premise_abstraction' "
        "AND value IS NOT NULL), pairs AS (SELECT a.title_id, len(list_intersect(a.w, b.w)) / "
        "GREATEST(len(list_distinct(list_concat(a.w, b.w))), 1) AS overlap FROM p a JOIN p b "
        "ON a.title_id <> b.title_id) SELECT p.title_id, ROUND(COALESCE(MAX(pairs.overlap), 0), 4) AS max_word_overlap "
        f"FROM p LEFT JOIN pairs USING (title_id) GROUP BY 1 HAVING COALESCE(MAX(pairs.overlap), 0) < {NEAR}",
        note=f"lexical proxy: content-word overlap (Jaccard) below {NEAR} with every other title; the IDEATE clone "
             "check (embeddings) is the real near-neighbor test"),
    "CQ-I25": Query(
        f"WITH {LABEL} SELECT a.value AS cost_of_power, b.value AS cost_of_power_secondary, "
        "COUNT(DISTINCT a.title_id) AS n_titles, COUNT(DISTINCT a.title_id) FILTER (WHERE l.label = 'hit') AS n_hits, "
        "COUNT(DISTINCT a.title_id) FILTER (WHERE l.label IN ('mixed', 'flop')) AS n_mixed_or_flop "
        "FROM title_fields a JOIN title_fields b ON b.title_id = a.title_id "
        "AND b.path = 'power_combat.cost_of_power_secondary' AND b.value IS NOT NULL JOIN label l "
        "ON l.title_id = a.title_id WHERE a.path = 'power_combat.cost_of_power' AND a.value IS NOT NULL GROUP BY 1, 2",
        note="the grid uses the primary cost only"),
    "CQ-I26": Query(
        f"WITH {LABEL}, w AS ({_wide(['power_combat.power_embodiment', 'power_combat.rarity', 'power_combat.world_integration'])}) "
        "SELECT w.power_embodiment, w.rarity, w.world_integration, l.label, COUNT(*) AS n_titles FROM w "
        "JOIN label l USING (title_id) WHERE w.power_embodiment IS NOT NULL OR w.rarity IS NOT NULL "
        "OR w.world_integration IS NOT NULL GROUP BY 1, 2, 3, 4"),
    "CQ-I27": Query(
        "SELECT m.value AS power_up_mode, g.value AS fight_logic, COUNT(DISTINCT m.title_id) AS n_titles, "
        "array_to_string(list_sort(list_distinct(list(c.value) FILTER (WHERE c.value IS NOT NULL))), '; ') "
        "AS power_up_costs FROM title_field_members m JOIN title_field_members g ON g.title_id = m.title_id "
        "AND g.path = 'power_combat.fight_logic' LEFT JOIN title_fields c ON c.title_id = m.title_id "
        "AND c.path = 'power_combat.power_up_cost' WHERE m.path = 'power_combat.power_up_mode' GROUP BY 1, 2"),
    "CQ-I28": Query(
        f"WITH {LABEL}, w AS ({_wide(['core.pilot_hook_type', 'core.ending_type'])}) SELECT w.pilot_hook_type, "
        "w.ending_type, l.label, COUNT(*) AS n_titles FROM w JOIN label l USING (title_id) "
        "WHERE w.pilot_hook_type IS NOT NULL OR w.ending_type IS NOT NULL GROUP BY 1, 2, 3"),
    "CQ-I29": Query(
        f"WITH i AS ({_parts('core.institutions', ['type', 'role'])}) SELECT i.type AS institution_type, "
        "s.value AS setting_type, COUNT(DISTINCT i.title_id) AS n_titles, "
        "array_to_string(list_sort(list_distinct(list(i.role))), '; ') AS roles FROM i LEFT JOIN title_fields s "
        "ON s.title_id = i.title_id AND s.path = 'core.setting_type' GROUP BY 1, 2",
        note="institution names stay in the title record (they join the name-leak list)"),
    "CQ-I30": Query(
        f"WITH {LABEL}, w AS ({_wide(['core.mc_archetype', 'core.mc_start', 'core.mc_goal_type'])}) "
        "SELECT w.mc_archetype, w.mc_start, w.mc_goal_type, COUNT(*) AS n_hit_titles FROM w JOIN label l "
        "USING (title_id) WHERE l.label = 'hit' AND w.mc_archetype IS NOT NULL GROUP BY 1, 2, 3"),
    "CQ-I31": Query(
        f"WITH {LABEL}, w AS ({_wide(['core.ensemble_size', 'core.rival_type', 'core.threat_structure'])}) "
        "SELECT w.ensemble_size, w.rival_type, w.threat_structure, l.label, COUNT(*) AS n_titles FROM w "
        "JOIN label l USING (title_id) WHERE w.ensemble_size IS NOT NULL OR w.rival_type IS NOT NULL "
        "OR w.threat_structure IS NOT NULL GROUP BY 1, 2, 3, 4"),
    "CQ-I32": Query(
        f"WITH {LABEL}, g AS ({_parts('core.thematic_argument', ['thesis_mc', 'antithesis_villain', 'resolution'], by_item=False)}) "
        "SELECT g.title_id, g.thesis_mc, g.antithesis_villain, g.resolution FROM g JOIN label l USING (title_id) "
        "WHERE l.label = 'hit'", note="free text; cross-title matching arrives with M7 clusters"),
    "CQ-I33": Query(
        f"WITH {LABEL}, h AS ({_parts('core.anticipation_hooks', ['type'])}) SELECT h.type AS hook_type, l.label, "
        "COUNT(*) AS n_hooks, COUNT(DISTINCT h.title_id) AS n_titles FROM h JOIN label l USING (title_id) "
        "GROUP BY 1, 2"),
    "CQ-I34": Query(
        f"WITH {LABEL} SELECT g.value AS genre_move, l.label, COUNT(DISTINCT g.title_id) AS n_titles, "
        "array_to_string(list_sort(list_distinct(list(r.value) FILTER (WHERE r.value IS NOT NULL))), '; ') "
        "AS reacts_against FROM title_fields g JOIN label l USING (title_id) LEFT JOIN title_fields r "
        "ON r.title_id = g.title_id AND r.path = 'core.reacts_against' WHERE g.path = 'core.genre_move' "
        "AND g.value IS NOT NULL GROUP BY 1, 2"),
    "CQ-I35": Query(
        "SELECT fp.pattern, o.label, o.failure_level, COUNT(DISTINCT fp.title_id) AS n_titles, "
        "array_to_string(list_sort(list_distinct(list(fp.source_ref))), ' ') AS sources "
        "FROM outcome_failure_patterns fp JOIN outcomes o USING (title_id) GROUP BY 1, 2, 3"),
    "CQ-I36": Query(
        f"WITH {LB} SELECT tb.concept, tr.transfer_id, tr.mechanism, tr.principle, tr.anti_pattern "
        "FROM transfer_bridge tb JOIN transfers tr USING (transfer_id) JOIN lb USING (transfer_id) "
        "WHERE tr.principle IS NOT NULL"),
    "CQ-I37": Query("SELECT p.pattern_id, p.statement, e.title_id AS held_out_title, e.atom_id FROM patterns p "
                    "JOIN pattern_predictive_evidence e USING (pattern_id) WHERE p.predictive", note="data from M7"),
    "CQ-I38": Query(
        "SELECT status, mc_edge, kit_kind, escalation_model, core_fantasy, COUNT(*) AS n_ideas, "
        "COUNT(*) FILTER (WHERE premise_abstraction IS NOT NULL) AS n_with_premise_abstraction, "
        "COUNT(*) FILTER (WHERE thesis_mc IS NOT NULL) AS n_with_thematic_argument, "
        "COUNT(*) FILTER (WHERE audience_promise IS NOT NULL) AS n_with_audience_promise "
        "FROM idea_concepts GROUP BY 1, 2, 3, 4, 5", note="idea cards gain these fields at M5"),
    "CQ-I39": Query("SELECT r.rule_id, r.result, i.status, COUNT(*) AS n_ideas FROM idea_rules r "
                    "JOIN ideas i USING (idea_id) GROUP BY 1, 2, 3", note="steering rules arrive with M5"),
    "CQ-C01": Query(
        "SELECT role, arc_type, backstory_reveal, COUNT(*) AS n_characters, "
        "array_to_string(list_sort(list(want) FILTER (WHERE want IS NOT NULL)), '; ') AS wants, "
        "array_to_string(list_sort(list(need) FILTER (WHERE need IS NOT NULL)), '; ') AS needs, "
        "array_to_string(list_sort(list(flaw || ' (when ' || flaw_condition || ')') FILTER (WHERE flaw IS NOT NULL)), "
        "'; ') AS flaws, array_to_string(list_sort(list(moral_line || ' (unless ' || moral_line_condition || ')') "
        "FILTER (WHERE moral_line IS NOT NULL)), '; ') AS moral_lines FROM characters GROUP BY 1, 2, 3"),
    "CQ-C02": Query(
        "WITH tp AS (SELECT character_id, idx, MAX(CASE WHEN key = 'season' THEN value END) AS season, "
        "MAX(CASE WHEN key = 'episode' THEN value END) AS episode FROM character_parts WHERE part = 'turning_points' "
        "GROUP BY 1, 2) SELECT c.role, TRY_CAST(tp.season AS INTEGER) AS season, TRY_CAST(tp.episode AS INTEGER) "
        "AS episode, COUNT(*) AS n_turning_points FROM tp JOIN characters c USING (character_id) GROUP BY 1, 2, 3"),
    "CQ-C03": Query(
        "SELECT c.title_id, c.origin, c.wound, c.origin_power_link, c.relationship_to_power, e.value AS mc_edge, "
        "c.power_kind, c.medium, c.n_functions, c.n_tools, c.n_limits, c.n_forms, c.evolution FROM characters c "
        "LEFT JOIN title_fields e ON e.title_id = c.title_id AND e.path = 'power_combat.mc_edge' "
        "WHERE c.role = 'protagonist'"),
    "CQ-C04": Query(
        f"WITH {LABEL} SELECT c.villain_type, c.villain_reveal, c.relation_to_mc, l.label, COUNT(*) AS n_antagonists "
        "FROM characters c JOIN label l USING (title_id) WHERE c.villain_type IS NOT NULL GROUP BY 1, 2, 3, 4"),
}


def adequacy(con: duckdb.DuckDBPyConnection, settings: Settings, modules: list[str]) -> dict[str, dict[str, Any]]:
    """Per module: is a zero there open? n = the titles with the module active and good field completion
    (`core`, which every title has, counts the titles with good completion). A zero is open only when the
    rule-of-three bound 3/n is below 0.02 (statistics as gates; it replaced the five-title minimum)."""
    completion = float(settings.coverage.get("min_field_completion", 0.8))
    out = {}
    for m in modules:
        pattern = "%" if m == "core" else f'%"{m}"%'
        n = int(con.execute("SELECT COUNT(*) FROM coverage WHERE modules_active LIKE ? AND field_completion >= ?",
                            [pattern, completion]).fetchone()[0])
        a = rule_of_three_adequacy(n)
        out[m] = {"n_adequate_titles": n, "rule_of_three": a["rule_of_three"], "min_needed": MIN_OPEN_N,
                  "adequate": a["open"]}
    return out


def census_adequacy(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Census-backed zeros: the rule of three over the census rows with a power system."""
    n = int(con.execute("SELECT COUNT(*) FROM census WHERE has_power_system").fetchone()[0])
    a = rule_of_three_adequacy(n)
    return {"n_powered_census_rows": n, "rule_of_three": a["rule_of_three"], "min_needed": MIN_OPEN_N,
            "adequate": a["open"]}


# The enum fields each gap question's zeros rest on: a field the agreement eval flagged unreliable takes its
# questions out of the gap reports (owner ruling, statistics as gates, item 1).
ZERO_DIMS: dict[str, tuple[str, ...]] = {
    "CQ-G01": ("power_combat.gate", "power_combat.cost_of_power"),
    "CQ-G04": ("power_combat.progression", "power_combat.fight_medium"),
    "CQ-G10": ("power_combat.gate", "power_combat.cost_of_power"),
    "CQ-G11": ("power_combat.gate", "power_combat.mc_edge"),
    "CQ-G13": ("core.story_engine", "power_combat.power_embodiment"),
    "CQ-G15": ("core.setting_type", "core.world_visibility", "core.conflict_scale"),
    "CQ-G16": ("power_combat.set_structure", "core.story_engine", "core.mc_archetype"),
    "CQ-G17": ("power_combat.set_structure", "power_combat.subset_mechanics"),
    "CQ-I07": ("relationships.power_is",),
    "CQ-N02": ("power_combat.gate", "power_combat.cost_of_power"),
    "CQ-N03": ("power_combat.progression", "power_combat.visible_counter"),
}
# Two-dimensional gap questions whose empty cells are ranked by expected count (item 3), and where their
# counts come from: corpus titles (v_incidence) or census rows with a power system.
GAP_RANK: dict[str, str] = {"CQ-G01": "corpus", "CQ-G04": "corpus", "CQ-G10": "census", "CQ-G17": "corpus",
                            "CQ-N02": "notes", "CQ-N03": "notes"}


def _gap_rows(con: duckdb.DuckDBPyConnection, px: str, py: str, source: str) -> list[tuple[str, str, str]]:
    """(row id, x value, y value) for every row that has both fields."""
    if source == "census":
        cx, cy = px.split(".")[-1], py.split(".")[-1]
        return con.execute(f'SELECT census_id, "{cx}", "{cy}" FROM census WHERE has_power_system '
                           f'AND "{cx}" IS NOT NULL AND "{cy}" IS NOT NULL').fetchall()
    if source == "notes":
        cx, cy = px.split(".")[-1], py.split(".")[-1]
        return con.execute(f'SELECT slug, "{cx}", "{cy}" FROM notes WHERE "{cx}" IS NOT NULL AND "{cy}" IS NOT NULL '
                           f'AND "{cx}" NOT LIKE \'other%\' AND "{cy}" NOT LIKE \'other%\'').fetchall()
    return con.execute("SELECT DISTINCT a.title_id, a.value, b.value FROM v_incidence a JOIN v_incidence b "
                       "ON a.title_id = b.title_id AND a.path = ? AND b.path = ?", [px, py]).fetchall()


def gap_ranking(con: duckdb.DuckDBPyConnection, vocab: Vocab, cq_id: str, cells: list[list[Any]]) -> dict[str, Any]:
    """The question's empty cells ranked by expected count under independence, n x p(x) x p(y), over the n rows
    with both fields known (`stats.rank_gaps`): expected >= 3 with none observed is a real gap, the rest are
    unsurprising. Ties by value, so the order is deterministic."""
    px, py = ZERO_DIMS[cq_id][:2]
    source = GAP_RANK[cq_id]
    rows = _gap_rows(con, px, py, source)
    xs: dict[str, set[str]] = {}
    ys: dict[str, set[str]] = {}
    joint: Counter = Counter()
    for rid, x, y in set(rows):
        xs.setdefault(x, set()).add(rid)
        ys.setdefault(y, set()).add(rid)
        joint[(x, y)] += 1
    n = len({r[0] for r in rows})

    def values(path: str) -> list[str]:
        return [v for v in vocab.enum(vocab.lens_field(path).vocab or path) if v != "other"]

    ranked = stats.rank_gaps(n, {v: len(xs.get(v, ())) for v in values(px)}, {v: len(ys.get(v, ())) for v in values(py)},
                             dict(joint))
    listed = {(c[0], c[1]) for c in cells}
    ranked = [g for g in ranked if (g["x"], g["y"]) in listed]
    return {"x": px, "y": py, "source": source, "n": n,
            "real_gaps": [[g["x"], g["y"], g["expected"]] for g in ranked if g["real"]],
            "unsurprising": [[g["x"], g["y"], g["expected"]] for g in ranked if not g["real"]]}


def _params(names: tuple[str, ...], vocab: Vocab, settings: Settings) -> list[Any]:
    out: list[Any] = []
    for name in names:
        if name.startswith("enum:"):
            out.append([v for v in vocab.enum(name[5:]) if v != "other"])
        elif name == "modules":
            out.append(list(vocab.module_names))
        elif name == "min_completion":
            out.append(float(settings.coverage.get("min_field_completion", 0.8)))
        elif name == "borrowed_systems":
            out.append([s for s in BORROWED_SYSTEMS if s not in ("none", "other")])
    return out


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def answer_all(con: duckdb.DuckDBPyConnection, vocab: Vocab, cqs: CQSet, settings: Settings,
               unreliable: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """`unreliable`: the fields the agreement eval flagged (statgates.unreliable_fields); their gap questions
    are excluded from the gap reports."""
    unreliable = unreliable or {}
    adequate = adequacy(con, settings, ["core", *vocab.module_names])
    census = census_adequacy(con)
    answers = {}
    for cq in cqs.questions:
        q = QUERIES[cq.id]
        if not q.sql:  # light path: the notes do not record what this question needs
            answers[cq.id] = {"id": cq.id, "text": cq.text, "columns": [], "rows": [], "note": q.note, "tracked": False}
            continue
        cur = con.execute(q.sql, _params(q.params, vocab, settings))
        columns = [d[0] for d in cur.description]
        rows = sorted((_clean(list(r)) for r in cur.fetchall()), key=stable_json)
        answer: dict[str, Any] = {"id": cq.id, "text": cq.text, "columns": columns, "rows": rows, "note": q.note}
        if q.module or q.census:
            cov = census if q.census else adequate[q.module]
            answer["coverage"] = cov
            answer["zeros_are"] = "open" if cov["adequate"] else "insufficient coverage"
        bad = sorted(d for d in ZERO_DIMS.get(cq.id, ()) if d in unreliable)
        if bad:
            answer["zeros_are"] = "excluded: unreliable field"
            answer["excluded_fields"] = [why_unreliable(d, unreliable[d]) for d in bad]
        elif cq.id in GAP_RANK:
            answer["gap_ranking"] = gap_ranking(con, vocab, cq.id, rows)
        if cq.id == "CQ-G07":
            answer["min_needed"] = MIN_OPEN_N
        answers[cq.id] = answer
    return answers


def save_answers(answers: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for cq_id, answer in sorted(answers.items()):
        text = json.dumps(answer, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        atomic_write_text(out_dir / f"{cq_id}.json", text)
        hashes[cq_id] = sha256_text(text)
    atomic_write_text(out_dir / "hashes.json", json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    return hashes
