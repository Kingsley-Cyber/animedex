"""BUILD (05): canonical JSONL -> build/animedex.duckdb + CSV exports + content hashes.

Determinism (10 §12, AC-07): rows are sorted, threads = 1, no timestamps or run ids in derived
tables, and hashes cover sorted table contents (DuckDB files are not byte-stable).
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from animedex.models import RECORD_TYPES
from animedex.ontology import Vocab, get_vocab
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.store.jsonl import read_jsonl
from animedex.textutil import sha256_text, stable_json

State = dict[str, list[dict[str, Any]]]
Row = tuple[Any, ...]


def _j(value: Any) -> str:
    return stable_json(value)


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[tuple[str, str], ...]
    rows: Callable[[State, Vocab], list[Row]]


def _titles(s: State, v: Vocab) -> list[Row]:
    out = []
    for t in s.get("title", []):
        sc, p = t["scope"], t["provenance"]
        out.append((t["title_id"], t["title"], t["year"], t["medium"], t["format"], sc["version"],
                    _j(sc.get("seasons", [])), sc.get("numbering"), _j(sc.get("exclude", [])),
                    _j(t.get("role_tags", [])), _j(t.get("modules_active", [])), p["pass"], p.get("model"),
                    p.get("prompt_version")))
    return out


def _title_fields(s: State, v: Vocab) -> list[Row]:
    out = []
    for t in s.get("title", []):
        for f in v.lens_fields():
            block = t.get(f.block)
            if block is None:
                continue
            fv = block[f.name]
            out.append((t["title_id"], f.block, f.name, f.path, f.kind, fv.get("value"), fv.get("condition"),
                        fv["conf"], fv.get("uncertainty_reason"), fv["source"], fv["verification"],
                        fv.get("source_ref"), fv["epistemic"]))
    return out


def _moments(s: State, v: Vocab) -> list[Row]:
    return [(m["moment_id"], m["title_id"], m["description"], m["locator"].get("season"), m["locator"].get("episode"),
             m["locator"].get("timestamp"), m["locator"].get("episode_id"), m["moment_type"], m["why_it_hit"],
             m["conf"], m["verification"], m.get("source_ref")) for m in s.get("moment", [])]


def _outcomes(s: State, v: Vocab) -> list[Row]:
    return [(o["title_id"], o["label"], o.get("failure_reason"), *(o["confounders"][k] for k in
            ("studio", "budget_signal", "source_popularity", "platform", "release_context")),
             o.get("failure_level"), o.get("failure_evidence"), o.get("failure_level_source"))
            for o in s.get("outcome", [])]


def _outcome_signals(s: State, v: Vocab) -> list[Row]:
    return [(o["title_id"], i, sg["metric"], sg["value"], sg["source_ref"])
            for o in s.get("outcome", []) for i, sg in enumerate(o.get("signals", []))]


_ENGINE = ("agent", "goal", "constraint", "strategy", "benefit", "cost", "dilemma", "dramatic_question", "feeling")


def _mechanisms(s: State, v: Vocab) -> list[Row]:
    out = []
    for m in s.get("mechanism", []):
        e, g, sup = m.get("effect") or {}, m.get("engine") or {}, m["support"]
        ref = e.get("element_ref") or {}
        out.append((m["atom_id"], m["title_id"], m["atom_kind"], m["module"], m["conf"], m["explanation"],
                    sup["status"], len(sup["supporting_episodes"]), len(sup["contradicting_episodes"]),
                    len(sup["reframing_episodes"]), m["origin"], e.get("element"), ref.get("field"),
                    ref.get("moment_id"), e.get("feeling"), e.get("because"), e.get("rival_because"),
                    *(g.get(k) for k in _ENGINE), _j(m["evidence_refs"])))
    return out


def _proofs(s: State, v: Vocab) -> list[Row]:
    out = []
    for p in s.get("proof", []):
        et, ab = p.get("explanation_test") or {}, p["ablation"]
        out.append((p["atom_id"], et.get("favors"), et.get("via_partner"), et.get("note"),
                    ab["if_removed"], ab["verdict"], ab["conf"]))
    return out


def _proof_contrasts(s: State, v: Vocab) -> list[Row]:
    return [(p["atom_id"], i, c["partner_title_id"], c["partner_role"], c["partner_has"], c["difference"])
            for p in s.get("proof", []) for i, c in enumerate(p["contrast"])]


def _checks(s: State, v: Vocab) -> list[Row]:
    seq: dict[tuple[str, str], int] = defaultdict(int)
    out = []
    for c in s.get("check", []):  # canonical order = target|run|created -> seq per target
        k = (c["target_type"], c["target_id"])
        out.append((c["target_id"], c["target_type"], seq[k], c["verdict"], _j(c.get("reasons", [])),
                    c.get("revision") is not None))
        seq[k] += 1
    return out


def _transfers(s: State, v: Vocab) -> list[Row]:
    return [(t["transfer_id"], t["source_atom_id"], t["atom_kind"], t["pattern"], _j(t["essential_conditions"]),
             _j(t["variable_details"]), _j(t["failure_conditions"])) for t in s.get("transfer", [])]


def _transfer_bridge(s: State, v: Vocab) -> list[Row]:
    return [(t["transfer_id"], b) for t in s.get("transfer", []) for b in t["bridge"]]


def _episodes(s: State, v: Vocab) -> list[Row]:
    out = []
    for e in s.get("episode", []):
        loc, beat = e["locator"], e.get("engine_beat") or {}
        out.append((e["episode_id"], e["title_id"], loc["season"], loc["episode"], loc.get("episode_title"),
                    loc["numbering"], e["selection_reason"], e["summary"], e["function"], e["end_hook"],
                    beat.get("engine_atom_id"), beat.get("advances"), e["info_shift"]["gap_change"],
                    len(e.get("decisions", [])), e["source_ref"], e["verification"]))
    return out


def _episode_support(s: State, v: Vocab) -> list[Row]:
    return [(e["episode_id"], a["atom_id"], a["relation"], a["note"])
            for e in s.get("episode", []) for a in e.get("atom_support", [])]


def _links(s: State, v: Vocab) -> list[Row]:
    return [(link["link_id"], link["title_id"], link["from_id"], link["to_id"], link["type"], link["evidence"])
            for link in s.get("link", [])]


def _patterns(s: State, v: Vocab) -> list[Row]:
    return [(p["pattern_id"], p["statement"], p["scope"], _j(p["transfer_ids"]), _j(p["supporting_titles"]),
             len(p.get("counterexamples", []))) for p in s.get("pattern", [])]


def _coverage(s: State, v: Vocab) -> list[Row]:
    return [(c["title_id"], _j(c.get("passes_done", [])), c["field_completion"], c["verified_share"],
             _j(c.get("modules_active", [])), c["episodes"]["in_scope"], c["episodes"]["indexed"],
             c["episodes"]["unsourced"], c.get("episode_backed_share", 0.0)) for c in s.get("coverage", [])]


_PROFILE = ("gate", "cost_of_power", "progression", "visible_counter", "fight_medium", "power_is")


def _ideas(s: State, v: Vocab) -> list[Row]:
    out = []
    for i in s.get("idea", []):
        g, hr = i["gates"], i.get("human_rating") or {}
        out.append((i["idea_id"], i["target_domain"], i["logline"], i["premise"], i["theme_root"],
                    i["transformation"]["operator"], i["transformation"]["what_changed"], i["grid_cell"],
                    i["closest_existing"], i["status"], i["generation"], *(i["profile"][k] for k in _PROFILE),
                    g["structural_jaccard_max"], g["procedural_jaccard_max"], g["premise_cosine_max"],
                    g["novel_combo"], g["consequence_test"]["h1_pass"], g["coherence"],
                    _j(i["taste"]["criteria_met"]), i["taste"]["hard_fail"], hr.get("rating"), hr.get("greenlight"),
                    _j(g.get("graveyard_hits", []))))
    return out


def _archive(s: State, v: Vocab) -> list[Row]:
    return [(a["cell_key"], a["idea_id"], _j(a["fitness"]), a.get("replaced_idea_id"), a["generation"])
            for a in s.get("archive", [])]


SQL_TYPES = {"": "VARCHAR", "d": "DOUBLE", "i": "INTEGER", "b": "BOOLEAN"}


def _cols(spec: str) -> tuple[tuple[str, str], ...]:
    out = []
    for part in spec.split():
        name, _, typ = part.partition(":")
        out.append((name, SQL_TYPES[typ]))
    return tuple(out)


TABLES: tuple[Table, ...] = (
    Table("titles", _cols("title_id title year:i medium format scope_version scope_seasons scope_numbering "
                          "scope_exclude role_tags modules_active prov_pass prov_model prov_prompt_version"), _titles),
    Table("title_fields", _cols("title_id block field path kind value condition conf:d uncertainty_reason source "
                                "verification source_ref epistemic"), _title_fields),
    Table("moments", _cols("moment_id title_id description season:i episode:i timestamp episode_id moment_type "
                           "why_it_hit conf:d verification source_ref"), _moments),
    Table("outcomes", _cols("title_id label failure_reason studio budget_signal source_popularity platform "
                            "release_context failure_level failure_evidence failure_level_source"), _outcomes),
    Table("outcome_signals", _cols("title_id idx:i metric value source_ref"), _outcome_signals),
    Table("mechanisms", _cols("atom_id title_id atom_kind module conf:d explanation support_status n_supporting:i "
                              "n_contradicting:i n_reframing:i origin element element_field element_moment_id "
                              "effect_feeling because rival_because engine_agent engine_goal engine_constraint "
                              "engine_strategy engine_benefit engine_cost engine_dilemma engine_dramatic_question "
                              "engine_feeling evidence_refs"), _mechanisms),
    Table("proofs", _cols("atom_id favors via_partner et_note if_removed verdict ablation_conf:d"), _proofs),
    Table("proof_contrasts", _cols("atom_id idx:i partner_title_id partner_role partner_has difference"), _proof_contrasts),
    Table("checks", _cols("target_id target_type seq:i verdict reasons has_revision:b"), _checks),
    Table("transfers", _cols("transfer_id source_atom_id atom_kind pattern essential_conditions variable_details "
                             "failure_conditions"), _transfers),
    Table("transfer_bridge", _cols("transfer_id concept"), _transfer_bridge),
    Table("episodes", _cols("episode_id title_id season:i episode:i episode_title numbering selection_reason summary "
                            "function end_hook engine_atom_id engine_advances gap_change n_decisions:i source_ref "
                            "verification"), _episodes),
    Table("episode_atom_support", _cols("episode_id atom_id relation note"), _episode_support),
    Table("links", _cols("link_id title_id from_id to_id type evidence"), _links),
    Table("patterns", _cols("pattern_id statement scope transfer_ids supporting_titles n_counterexamples:i"), _patterns),
    Table("coverage", _cols("title_id passes_done field_completion:d verified_share:d modules_active "
                            "eps_in_scope:i eps_indexed:i eps_unsourced:i episode_backed_share:d"), _coverage),
    Table("ideas", _cols("idea_id target_domain logline premise theme_root operator what_changed grid_cell "
                         "closest_existing status generation:i gate cost_of_power progression visible_counter "
                         "fight_medium power_is structural_jaccard_max:d procedural_jaccard_max:d "
                         "premise_cosine_max:d novel_combo:b h1_pass:b coherence criteria_met hard_fail:b "
                         "human_rating:i greenlight:b graveyard_hits"), _ideas),
    Table("archive", _cols("cell_key idea_id fitness replaced_idea_id generation:i"), _archive),
)

VIEWS: tuple[tuple[str, str], ...] = (
    ("v_incidence", "SELECT title_id, path, value FROM title_fields WHERE kind = 'enum' AND value IS NOT NULL"),
    ("v_pair_cooccurrence",
     "SELECT a.path AS path_a, a.value AS value_a, b.path AS path_b, b.value AS value_b, "
     "COUNT(DISTINCT a.title_id) AS n_titles FROM v_incidence a JOIN v_incidence b "
     "ON a.title_id = b.title_id AND (a.path < b.path OR (a.path = b.path AND a.value < b.value)) "
     "GROUP BY a.path, a.value, b.path, b.value"),
    ("v_latest_check",
     "SELECT target_id, target_type, verdict FROM checks "
     "QUALIFY row_number() OVER (PARTITION BY target_type, target_id ORDER BY seq DESC) = 1"),
    ("v_load_bearing",
     "SELECT m.* FROM mechanisms m JOIN proofs p USING (atom_id) "
     "JOIN v_latest_check c ON c.target_type = 'mechanism' AND c.target_id = m.atom_id "
     "WHERE p.verdict = 'load_bearing' AND c.verdict = 'ACCEPT' AND m.explanation = 'settled' "
     "AND m.support_status IN ('profile_only', 'episode_backed')"),
    ("v_outcomes",
     "SELECT t.title_id, t.medium, t.format, o.label, o.failure_reason, o.studio, o.budget_signal, "
     "o.source_popularity, o.platform, o.release_context, o.failure_level FROM titles t "
     "LEFT JOIN outcomes o USING (title_id)"),
)


def load_state(canonical: Path) -> State:
    return {name: read_jsonl(canonical / rt.file) for name, rt in RECORD_TYPES.items()}


def _hash_relation(con: duckdb.DuckDBPyConnection, name: str) -> str:
    cur = con.execute(f"SELECT * FROM {name} ORDER BY ALL")
    cols = [d[0] for d in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    return sha256_text(json.dumps({"columns": cols, "rows": rows}, sort_keys=True, default=str, ensure_ascii=False))


def _csv(con: duckdb.DuckDBPyConnection, name: str) -> str:
    cur = con.execute(f"SELECT * FROM {name} ORDER BY ALL")
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([d[0] for d in cur.description])
    writer.writerows(cur.fetchall())
    return buf.getvalue()


def build_into(out_dir: Path, canonical: Path, vocab: Vocab) -> dict[str, str]:
    """Build the database, exports, and hashes into `out_dir`; return the hashes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "animedex.duckdb"
    for stale in (db_path, out_dir / "animedex.duckdb.wal"):
        stale.unlink(missing_ok=True)
    state = load_state(canonical)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("SET threads = 1")
        for table in TABLES:
            cols = ", ".join(f'"{n}" {t}' for n, t in table.columns)
            con.execute(f"CREATE TABLE {table.name} ({cols})")
            rows = sorted(table.rows(state, vocab), key=lambda r: stable_json(list(r)))
            if rows:
                marks = ", ".join("?" for _ in table.columns)
                con.executemany(f"INSERT INTO {table.name} VALUES ({marks})", rows)
        for name, sql in VIEWS:
            con.execute(f"CREATE VIEW {name} AS {sql}")
        names = [t.name for t in TABLES] + [n for n, _ in VIEWS]
        hashes = {name: _hash_relation(con, name) for name in names}
        exports = out_dir / "exports"
        exports.mkdir(exist_ok=True)
        for table in TABLES:
            atomic_write_text(exports / f"{table.name}.csv", _csv(con, table.name))
    finally:
        con.close()
    atomic_write_text(out_dir / "hashes.json", json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    return hashes


def build(paths: Paths) -> dict[str, str]:
    return build_into(paths.build, paths.canonical, get_vocab(paths))


def verify_determinism(paths: Paths) -> tuple[bool, dict[str, tuple[str, str]]]:
    """Build twice from the same canonical data and compare every table/view hash."""
    first = build(paths)
    tmp = Path(tempfile.mkdtemp(prefix="animedex-rebuild-"))
    try:
        second = build_into(tmp, paths.canonical, get_vocab(paths))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    diffs = {k: (first.get(k, ""), second.get(k, "")) for k in sorted(set(first) | set(second))
             if first.get(k) != second.get(k)}
    return not diffs, diffs
