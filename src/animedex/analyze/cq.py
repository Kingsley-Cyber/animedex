"""A query and a saved answer for every competency question (AC-21), deterministic (AC-24).

Answers go to build/cq_answers/<CQ-ID>.json with sorted rows. Gap questions carry a
coverage-adequacy flag (AC-22): a zero is "open" only when enough titles have the module active
with good field completion (`coverage.min_titles_with_module`, `coverage.min_field_completion`).
Questions whose data arrives later (ideas at M5, episodes at M6) have real queries that return no
rows until then.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from animedex.config import Settings
from animedex.ontology import CQSet, Vocab
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


@dataclass(frozen=True)
class Query:
    sql: str
    params: tuple[str, ...] = ()   # names resolved by `_params`
    note: str = ""
    module: str | None = None      # adequacy flag for this module's zeros


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
        ("modules", "min_completion"), note="a zero is trustworthy only where n_adequate_titles >= the minimum"),
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
}


def adequacy(con: duckdb.DuckDBPyConnection, settings: Settings, modules: list[str]) -> dict[str, dict[str, Any]]:
    cov = settings.coverage
    need, completion = int(cov.get("min_titles_with_module", 5)), float(cov.get("min_field_completion", 0.8))
    out = {}
    for m in modules:
        n = con.execute("SELECT COUNT(*) FROM coverage WHERE modules_active LIKE ? AND field_completion >= ?",
                        [f'%"{m}"%', completion]).fetchone()[0]
        out[m] = {"n_adequate_titles": int(n), "min_needed": need, "adequate": int(n) >= need}
    return out


def _params(names: tuple[str, ...], vocab: Vocab, settings: Settings) -> list[Any]:
    out: list[Any] = []
    for name in names:
        if name.startswith("enum:"):
            out.append([v for v in vocab.enum(name[5:]) if v != "other"])
        elif name == "modules":
            out.append(list(vocab.module_names))
        elif name == "min_completion":
            out.append(float(settings.coverage.get("min_field_completion", 0.8)))
    return out


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def answer_all(con: duckdb.DuckDBPyConnection, vocab: Vocab, cqs: CQSet, settings: Settings) -> dict[str, dict[str, Any]]:
    adequate = adequacy(con, settings, list(vocab.module_names))
    answers = {}
    for cq in cqs.questions:
        q = QUERIES[cq.id]
        cur = con.execute(q.sql, _params(q.params, vocab, settings))
        columns = [d[0] for d in cur.description]
        rows = sorted((_clean(list(r)) for r in cur.fetchall()), key=stable_json)
        answer: dict[str, Any] = {"id": cq.id, "text": cq.text, "columns": columns, "rows": rows, "note": q.note}
        if q.module:
            answer["coverage"] = adequate[q.module]
            answer["zeros_are"] = "open" if adequate[q.module]["adequate"] else "insufficient coverage"
        if cq.id == "CQ-G07":
            answer["min_needed"] = int(settings.coverage.get("min_titles_with_module", 5))
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
