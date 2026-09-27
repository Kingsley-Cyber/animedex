"""M4 ANALYZE: every CQ has a query and a saved answer (AC-21); gap zeros carry a coverage flag
(AC-22); the graveyard attaches failure_reason + failure_level and warns on premise failures
only (AC-23, v1.3); CQ answers are identical after a clean rebuild (AC-24); gold stays masked."""

from __future__ import annotations

import json
import math

import pytest
import yaml
from typer.testing import CliRunner

from animedex.analyze import graveyard_index, run_analyze, verify_cq_determinism
from animedex.analyze.cq import QUERIES
from animedex.cli import app
from animedex.config import load_settings
from animedex.ontology import get_cqs
from tests.conftest import synthetic_state, write_state

pytestmark = pytest.mark.contract


def test_every_cq_has_a_query_and_a_saved_answer(repo):
    assert set(QUERIES) == get_cqs().ids  # AC-21: no question without a query, no orphan query
    write_state(repo, synthetic_state())
    result = run_analyze(repo, load_settings(repo))
    saved = {p.stem for p in (repo.build / "cq_answers").glob("CQ-*.json")}
    assert saved == get_cqs().ids and result.answered == len(saved)


def test_queries_run_on_an_empty_corpus(repo):
    result = run_analyze(repo, load_settings(repo))
    g01 = json.loads((repo.build / "cq_answers" / "CQ-G01.json").read_text())
    assert result.answered == len(get_cqs().ids)
    assert g01["zeros_are"] == "insufficient coverage" and g01["rows"]  # every cell empty, none trusted


def test_gap_zeros_carry_the_coverage_flag(repo):
    from tests.conftest import prov

    state = synthetic_state()
    state["coverage"] = [{"title_id": "ironvale_circuit_2021", "passes_done": ["P1", "VERIFY"], "field_completion": 0.9,
                          "verified_share": 0.5, "modules_active": ["power_combat", "sensory", "anime_production",
                                                                    "series_engine"],
                          "episodes": {"in_scope": 0, "indexed": 0, "unsourced": 0, "selection": {}},
                          "episode_backed_share": 0.0, "provenance": prov("CANONICALIZE", model=None)}]
    write_state(repo, state)
    run_analyze(repo, load_settings(repo))
    g01 = json.loads((repo.build / "cq_answers" / "CQ-G01.json").read_text())
    assert g01["coverage"]["adequate"] is False and g01["zeros_are"] == "insufficient coverage"  # AC-22
    g07 = json.loads((repo.build / "cq_answers" / "CQ-G07.json").read_text())
    assert dict(map(tuple, g07["rows"]))["power_combat"] == 1


def test_graveyard_warns_on_premise_failures_only():
    state = synthetic_state()
    rows = graveyard_index(state)
    [flop] = [r for r in rows if r["title_id"] == "glass_meridian_2016"]
    assert (flop["failure_level"], flop["warns"], flop["t5_evidence"]) == ("execution", False, True)  # AC-23
    assert flop["failure_reason"]
    state["outcome"][0]["failure_level"] = "premise"
    [flop] = [r for r in graveyard_index(state) if r["title_id"] == "glass_meridian_2016"]
    assert flop["warns"] is True and flop["t5_evidence"] is False


def test_cq_answers_are_deterministic(repo):
    write_state(repo, synthetic_state())
    ok, diffs = verify_cq_determinism(repo, load_settings(repo))
    assert ok and diffs == {}  # AC-24
    result = CliRunner().invoke(app, ["build", "--verify-determinism"])
    assert result.exit_code == 0 and "identical hashes and CQ answers" in result.output


def test_make_build_includes_the_cq_step(repo):
    write_state(repo, synthetic_state())
    result = CliRunner().invoke(app, ["build"])
    assert result.exit_code == 0 and "CQ answers" in result.output
    assert (repo.build / "cq_answers" / "hashes.json").is_file()


def test_report_masks_gold_titles_while_the_blind_is_pending(repo):
    state = synthetic_state()
    write_state(repo, state)
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope")}
              | {"role_tags": ["gold", "flop"] if t["title_id"] == "glass_meridian_2016" else t["role_tags"]}
              for t in state["title"]]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    (repo.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "pending", "runs_without_annotations": True}))
    run_analyze(repo, load_settings(repo))
    report = (repo.reports / "analysis.md").read_text()
    assert "glass_meridian_2016 | (gold: hidden)" in report and "Execution problems" not in report
    (repo.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "waived", "runs_without_annotations": True}))
    run_analyze(repo, load_settings(repo))
    assert "Execution problems" in (repo.reports / "analysis.md").read_text()


# ---------------------------------------------------------------- statistics as gates (owner ruling 2026-09-27)
def _coverage_db(n_titles: int, n_census: int):
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE TABLE coverage (title_id VARCHAR, modules_active VARCHAR, field_completion DOUBLE)")
    con.executemany("INSERT INTO coverage VALUES (?, ?, ?)",
                    [(f"t{i:03d}_2020", '["power_combat"]', 0.9) for i in range(n_titles)])
    con.execute("CREATE TABLE census (census_id VARCHAR, has_power_system BOOLEAN)")
    con.executemany("INSERT INTO census VALUES (?, ?)", [(f"anilist:{i}", True) for i in range(n_census)])
    return con


@pytest.mark.parametrize("n, open_", [(150, False), (151, True)])
def test_a_zero_is_open_only_by_the_rule_of_three(repo, n, open_):
    from animedex.analyze.cq import adequacy, census_adequacy

    con = _coverage_db(n, n)
    [cov] = adequacy(con, load_settings(repo), ["power_combat"]).values()
    assert (cov["n_adequate_titles"], cov["adequate"], cov["min_needed"]) == (n, open_, 151)
    assert cov["rule_of_three"] == round(3 / n, 4)  # 150 titles: 3/150 = 0.02 is not below 0.02
    census = census_adequacy(con)
    assert (census["n_powered_census_rows"], census["adequate"]) == (n, open_)


def _incidence(pairs: list[tuple[str, str, int]]):
    """An in-memory v_incidence with `n` titles for each (gate, cost_of_power) pair."""
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE TABLE v_incidence (title_id VARCHAR, path VARCHAR, value VARCHAR)")
    rows, i = [], 0
    for gate, cost, n in pairs:
        for _ in range(n):
            rows += [(f"t{i:03d}_2020", "power_combat.gate", gate), (f"t{i:03d}_2020", "power_combat.cost_of_power", cost)]
            i += 1
    con.executemany("INSERT INTO v_incidence VALUES (?, ?, ?)", rows)
    return con


def test_empty_cells_rank_by_expected_count_real_gaps_first():
    from animedex.analyze.cq import gap_ranking
    from animedex.ontology import get_vocab

    vocab = get_vocab()
    gates = [g for g in vocab.enum("power_combat.gate") if g != "other"]
    costs = [c for c in vocab.enum("power_combat.cost_of_power") if c != "other"]

    def cells(used):
        return [[g, c] for g in gates for c in costs if (g, c) not in used]

    used = {("innate", "physical_toll"), ("trained", "lifespan"), ("trained", "physical_toll")}
    # 20 titles: innate 10, trained 10; physical_toll 14, lifespan 6 -> innate x lifespan: 20 x .5 x .3 = 3.0, real
    g = gap_ranking(_incidence([("innate", "physical_toll", 10), ("trained", "lifespan", 6),
                                ("trained", "physical_toll", 4)]), vocab, "CQ-G01", cells(used))
    assert g["n"] == 20 and g["real_gaps"] == [["innate", "lifespan", 3.0]]
    assert len(g["unsurprising"]) == len(cells(used)) - 1 and {e for _, _, e in g["unsurprising"]} == {0.0}
    # 8 titles: innate 4, trained 4; physical_toll 6, lifespan 2 -> innate x lifespan: 8 x .5 x .25 = 1.0, unsurprising
    g = gap_ranking(_incidence([("innate", "physical_toll", 4), ("trained", "lifespan", 2),
                                ("trained", "physical_toll", 2)]), vocab, "CQ-G01", cells(used))
    assert g["real_gaps"] == [] and g["unsurprising"][0] == ["innate", "lifespan", 1.0]
    assert g["unsurprising"] == sorted(g["unsurprising"], key=lambda r: (-r[2], r[0], r[1]))  # deterministic order


def _reliability(repo, fields):
    f = repo.root / "eval" / "agreement" / "reliability.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"fields": fields}))


def test_unreliable_fields_leave_the_gap_reports(repo):
    write_state(repo, synthetic_state())
    run_analyze(repo, load_settings(repo))  # no reliability file: nothing excluded
    g01 = json.loads((repo.build / "cq_answers" / "CQ-G01.json").read_text())
    assert "gap_ranking" in g01 and "No reliability report yet" in (repo.reports / "analysis.md").read_text()
    _reliability(repo, {"power_combat.gate": {"n": 14, "raw": 0.64, "kappa": 0.41, "unreliable": True, "pass": False},
                        "power_combat.progression": {"n": 14, "raw": 0.93, "kappa": 0.85, "unreliable": False,
                                                     "pass": True}})
    result = run_analyze(repo, load_settings(repo))
    g01 = json.loads((repo.build / "cq_answers" / "CQ-G01.json").read_text())
    g04 = json.loads((repo.build / "cq_answers" / "CQ-G04.json").read_text())
    assert g01["zeros_are"] == "excluded: unreliable field" and "gap_ranking" not in g01
    assert g01["excluded_fields"] == ["power_combat.gate (kappa 0.41, raw agreement 0.64)"]
    assert "gap_ranking" in g04 and g04["zeros_are"] != "excluded: unreliable field"  # a reliable field stays
    report = (repo.reports / "analysis.md").read_text()
    assert "Excluded from the gap reports: unreliable field power_combat.gate" in report
    assert result.unreliable == ["power_combat.gate"]
    stats_ = json.loads((repo.build / "stats" / "analysis.json").read_text())
    assert stats_["gaps"]["CQ-G01"] == {"excluded": g01["excluded_fields"]}
    ok, diffs = verify_cq_determinism(repo, load_settings(repo))  # the rebuild reads the same verdicts
    assert ok and diffs == {}


def test_field_health_reports_entropy_and_mutual_information_with_outcome(repo):
    state = synthetic_state()
    for t, setting, world in zip(state["title"], ("modern_urban", "historical", "historical"),
                                 ("hidden", "open", "contained"), strict=True):
        t["core"]["setting_type"]["value"] = setting
        t["core"]["world_visibility"]["value"] = world
    write_state(repo, state)
    result = run_analyze(repo, load_settings(repo))
    health = {h["path"]: h for h in json.loads((repo.build / "stats" / "analysis.json").read_text())["field_health"]}
    # labels: hit, hit, flop (the flop has an outcome record; the others' core.outcome is hit)
    h = health["core.setting_type"]  # values A, B, B out of 7 allowed
    assert (h["n"], h["k"], h["entropy"]) == (3, 7, 0.9183)  # H(1/3, 2/3)
    assert h["normalized_entropy"] == round(0.9183 / math.log2(7), 4) and h["low_entropy"] is True  # 0.33 < 0.5
    assert h["mi_outcome"] == 0.2516 and h["n_with_outcome"] == 3  # 0.9183 - (2/3 x 1 bit)
    w = health["core.world_visibility"]  # three different values out of 3 allowed: uniform
    assert (w["entropy"], w["normalized_entropy"], w["low_entropy"]) == (1.585, 1.0, False)
    assert w["mi_outcome"] == 0.9183  # each value names its title's label: MI = H(label)
    assert health["core.story_engine"]["entropy"] == 0.0 and health["core.story_engine"]["low_entropy"] is True
    assert health["core.outcome"]["mi_outcome"] is None and "core.story_engine" in result.low_entropy
    report = (repo.reports / "analysis.md").read_text()
    assert "## Field health" in report and "| `core.world_visibility` | 3 | 1.585 | 1.000 |  | 0.918 (3 titles) |" in report
