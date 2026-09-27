"""v1.8 contracts across records: character integrity (roles, kits, turning points), the name-leak list
with character names, character evidence for atoms, predictive evidence, CANONICALIZE on the new kinds,
the BUILD tables, the new CQ answers, and older records under the new vocab (coverage, AC-12)."""

from __future__ import annotations

import copy
import json

import duckdb
import pytest
import yaml

from animedex.analyze import run_analyze
from animedex.build.duckdb_build import build
from animedex.config import load_settings
from animedex.evaluation import coverage_row, p1_agreement
from animedex.integrity import integrity_errors, name_list
from animedex.ontology import get_vocab
from animedex.pipeline.canonicalize import canonicalize
from animedex.store.canonical import CanonicalStore, normalize_record
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from tests.conftest import (
    make_character,
    make_title,
    make_transfer,
    prov,
    synthetic_state,
    write_state,
)

pytestmark = pytest.mark.contract


def errors_with(**changes) -> str:
    state = synthetic_state()
    state.update(changes)
    return "\n".join(integrity_errors(state, get_vocab()))


def test_synthetic_state_with_characters_is_clean():
    assert integrity_errors(synthetic_state(), get_vocab()) == []


@pytest.mark.parametrize("cast, message", [
    ([make_character(title_id="quill_house_2018")], "unknown title"),
    ([make_character(), make_character(n=2)], "2 protagonist records"),
    ([make_character(n=1, role="main_rival")], "needs its protagonist"),
    ([make_character(), make_character(n=2, role="mentor", power_kit=None),
      make_character(n=3, role="deuteragonist", power_kit=None)], "one mentor or deuteragonist"),
    ([make_character(), *(make_character(n=i, role=r) for i, r in ((2, "main_rival"), (3, "mentor"),
                                                                     (4, "main_rival")))], "at most 3"),
    ([make_character(power_kit=None), make_character(n=2, role="main_rival")], "start with the protagonist's"),
    ([make_character(turning_points=[{"event": "a reroute", "locator": {"season": 1, "episode": None}}])],
     "needs its episode"),
    ([make_character(turning_points=[{"event": "a reroute", "locator": {"season": 7, "episode": 2}}])],
     "outside the title's scope"),
])
def test_character_integrity(cast, message):
    assert message in errors_with(character=cast)


def test_more_than_four_characters_fail():
    cast = [make_character(), make_character(n=2, role="main_rival", power_kit=None),
            make_character(n=3, role="main_antagonist"), make_character(n=4, role="mentor", power_kit=None),
            make_character(n=5, role="deuteragonist", power_kit=None)]
    errors = errors_with(character=cast)
    assert "5 records; at most 4" in errors


def test_film_turning_points_need_no_episode():
    film = make_character(title_id="glass_meridian_2016",
                          turning_points=[{"event": "a reroute", "locator": {"season": None, "episode": None}}])
    assert "glass_meridian_2016" not in errors_with(character=[*synthetic_state()["character"], film])


def test_character_names_join_the_name_leak_list():
    state = synthetic_state()
    _, tokens = name_list(state, get_vocab())
    assert {"Wren", "Halloway", "Sable", "Morrow"} <= tokens  # every word of a name, the first one too
    assert "Overload" not in tokens  # other texts give only their mid-sentence capitals, as before
    leaky = make_transfer(pattern="A courier like Wren hides a private meter from everyone else.")
    assert "contains names ['Wren']" in errors_with(transfer=[leaky])
    ladder = make_transfer(principle="When Sable holds the grid, starve it, because control needs supply")
    assert "principle contains names ['Sable']" in errors_with(transfer=[ladder])


def test_list_and_group_phrases_feed_the_name_list():
    state = synthetic_state()
    state["title"][0]["core"]["institutions"]["value"] = [
        {"name": "the Meridian Relay Guild", "type": "guild_or_license", "role": "answers to the Grid Council"}]
    _, tokens = name_list(state, get_vocab())
    assert {"Meridian", "Relay", "Guild", "Grid", "Council"} <= tokens


def test_premise_abstraction_names_are_caught_within_their_own_title():
    state = synthetic_state()
    state["title"][0]["core"]["premise_abstraction"]["value"] = "Wren keeps a failing city lit at any cost"
    state["title"][1]["core"]["premise_abstraction"]["value"] = "Wren songs guide a debt collector through the Harbor"
    errors = integrity_errors(state, get_vocab())
    assert "title ironvale_circuit_2021: core.premise_abstraction contains names ['Wren']" in errors  # its own cast
    assert "title lantern_debt_2019: core.premise_abstraction contains names ['Harbor']" in errors  # a capital
    # another title's cast never counts, so adding a title cannot change this title's result


def test_atoms_may_cite_a_character_record():
    state = synthetic_state()
    state["mechanism"][0]["evidence_refs"] = ["ironvale_circuit_2021.c.01"]
    assert integrity_errors(state, get_vocab()) == []
    state["mechanism"][0]["evidence_refs"] = ["ironvale_circuit_2021.c.09"]
    assert any("not a field path, moment, episode, or character" in e for e in integrity_errors(state, get_vocab()))


def test_predictive_evidence_must_be_a_load_bearing_atom():
    card = {"pattern_id": "pattern.001", "statement": "A private measure shared only with the audience.",
            "transfer_ids": ["ironvale_circuit_2021.t.001"], "supporting_titles": ["lantern_debt_2019"],
            "scope": "corpus_subset", "predictive": True,
            "predictive_evidence": [{"title_id": "ironvale_circuit_2021", "atom_id": "ironvale_circuit_2021.m.001"}],
            "provenance": prov("PATTERNS", model=None)}
    assert "pattern.001" not in errors_with(pattern=[card])  # m.001 is load-bearing-eligible
    other = copy.deepcopy(card)
    other["predictive_evidence"][0]["atom_id"] = "ironvale_circuit_2021.m.002"  # no CHECK: not eligible
    assert "not a load-bearing-eligible atom" in errors_with(pattern=[other])
    named = {**card, "statement": "Like Wren, the lead hides a private meter."}
    assert "statement contains names" in errors_with(pattern=[named])


# ---------------------------------------------------------------- CANONICALIZE on the new kinds
def test_off_vocab_members_become_other_or_drop_out():
    rec = make_title()
    rec["core"]["core_fantasy"]["value"] = ["other:heist thrill", "Mastery", "other:rule bending"]
    rec["power_combat"]["subset_mechanics"]["value"] = ["other:grafting"]   # no `other` in this vocab
    rec["core"]["anticipation_hooks"]["value"] = [{"hook": "the rematch at the tower", "type": "rematch"},
                                                  {"hook": "a vow to return", "type": "oath"}]
    rec["core"]["institutions"]["value"] = [{"name": "the relay guild", "type": "labor union", "role": "licenses"}]
    out, proposals = normalize_record("title", rec, get_vocab(), "run_x")
    assert out["core"]["core_fantasy"]["value"] == ["other", "mastery"]  # mapped, then de-duplicated
    sub = out["power_combat"]["subset_mechanics"]
    assert sub["value"] is None and sub["conf"] == 0.0 and sub["uncertainty_reason"]
    assert out["core"]["anticipation_hooks"]["value"] == [{"hook": "the rematch at the tower", "type": "rematch"}]
    assert out["core"]["institutions"]["value"][0]["type"] == "other"
    assert {(p.field, p.proposed) for p in proposals} == {
        ("core.core_fantasy", "heist thrill"), ("core.core_fantasy", "rule bending"),
        ("power_combat.subset_mechanics", "grafting"), ("core.anticipation_hook_type", "oath"),
        ("core.institution_type", "labor union")}
    from animedex.models import title_profile_model

    title_profile_model().model_validate(out)


def test_characters_canonicalize_with_their_title(repo):
    state = synthetic_state()
    write_state(repo, {k: v for k, v in state.items() if k != "character"})
    folder = repo.candidates / "character"
    folder.mkdir(parents=True)
    (folder / "ironvale_circuit_2021.jsonl").write_text(dumps_jsonl(state["character"]))
    (folder / "lantern_debt_2019.jsonl").write_text(dumps_jsonl([make_character("lantern_debt_2019", role="main_rival")]))
    result = canonicalize(repo, "run_chars")
    assert result.written["character"] == ["ironvale_circuit_2021.c.01", "ironvale_circuit_2021.c.02"]
    assert "lantern_debt_2019" in result.held_titles  # a cast without its protagonist waits
    assert [c["character_id"] for c in CanonicalStore(repo).read("character")] == result.written["character"]


def test_an_older_canonical_title_keeps_its_exact_form(repo):
    state = synthetic_state()
    old = state["title"][0]
    for f in get_vocab().lens_fields():
        if f.since and f.block in old:
            old[f.block].pop(f.name)
    old["provenance"]["vocab_version"] = "1.4.0"
    state["outcome"][0].pop("failure_patterns")
    write_state(repo, state)
    from animedex.validate import validate_repo

    report = validate_repo(repo)
    assert report.ok, report.errors
    assert not [w for w in report.warnings if "titles.jsonl" in w or "outcomes.jsonl" in w]  # nothing rewritten


# ---------------------------------------------------------------- older records under the new vocab
def test_coverage_counts_an_absent_field_as_not_filled_and_ac12_skips_it():
    vocab = get_vocab()
    new, old = make_title(), make_title()
    for f in vocab.lens_fields():
        if f.since and f.block in old:
            old[f.block].pop(f.name)
    assert coverage_row(new, vocab)["field_completion"] > coverage_row(old, vocab)["field_completion"]
    agreement = p1_agreement([new], [old], vocab)
    assert "power_combat.mc_edge" not in agreement["per_field"] and agreement["overall"] == 1.0


# ---------------------------------------------------------------- BUILD and CQ answers
def test_build_unpacks_the_new_kinds_and_records(repo):
    write_state(repo, synthetic_state())
    build(repo)
    con = duckdb.connect(str(repo.build_db), read_only=True)
    try:
        q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
        assert q("SELECT value FROM title_field_members WHERE title_id = 'ironvale_circuit_2021' "
                 "AND path = 'core.core_fantasy'") == [("secret_strength",)]
        assert ("core.institutions.type", "academy") in q(
            "SELECT path, value FROM v_incidence WHERE title_id = 'ironvale_circuit_2021'")
        assert q("SELECT part, value FROM title_field_parts WHERE title_id = 'ironvale_circuit_2021' "
                 "AND path = 'core.thematic_argument' ORDER BY part")[0] == ("antithesis_villain",
                                                                           "synthetic antithesis villain phrase")
        assert q("SELECT kind, value FROM title_fields WHERE title_id = 'ironvale_circuit_2021' "
                 "AND path = 'core.core_fantasy'") == [("enum_multi", '["secret_strength"]')]
        assert q("SELECT role, power_kind, villain_type FROM characters ORDER BY character_id") == [
            ("protagonist", "medium", None), ("main_antagonist", None, "ideological")]
        assert q("SELECT count(*) FROM character_parts WHERE part = 'tools'") == [(2,)]
        assert q("SELECT pattern FROM outcome_failure_patterns") == [("pacing_collapse",)]
    finally:
        con.close()


def test_new_cq_answers_read_the_new_fields(repo):
    state = synthetic_state()
    state["title"][1]["core"]["premise_abstraction"]["value"] = "a courier keeps a failing grid alive for strangers"
    write_state(repo, state)
    run_analyze(repo, load_settings(repo))
    answers = repo.build / "cq_answers"

    def rows(cq: str) -> list:
        return json.loads((answers / f"{cq}.json").read_text())["rows"]

    g11 = {(r[0], r[1]): (r[2], r[3]) for r in rows("CQ-G11")}
    vocab = get_vocab()
    assert len(g11) == (len(vocab.enum("power_combat.gate")) - 1) * (len(vocab.enum("power_combat.mc_edge")) - 1)
    assert g11[("innate", "biggest_number")] == (1, 1)  # the synthetic hit
    assert [r[0] for r in rows("CQ-C04")] == ["ideological"]
    assert rows("CQ-C03")[0][:2] == ["ironvale_circuit_2021", "a courier raised in the grid's maintenance tunnels"]
    assert [r[0] for r in rows("CQ-I35")] == ["pacing_collapse"]
    # the two titles with the default synthetic abstraction are each other's near-neighbors; the rewritten one has none
    assert {r[0] for r in rows("CQ-I24")} == {"lantern_debt_2019"}
    g14 = dict(rows("CQ-G14"))
    assert set(g14) == set(vocab.enum("character.villain_type")) - {"other"}
    assert (g14["ideological"], g14["predator"]) == (1, 0)  # the synthetic world is hidden (its first value)


def test_census_fields_reach_the_census_table(repo):
    entry = {"census_id": "anilist:1", "title": "Synthetic", "year": 2020, "medium": "anime", "format": "TV",
             "popularity": 1, "has_power_system": True, "set_structure": "open_variety", "story_engine": "tournament",
             "mc_archetype": "underdog", "batch_id": "b", "provenance": prov("CENSUS")}
    write_state(repo, {**synthetic_state(), "census": [entry]})
    run_analyze(repo, load_settings(repo))
    g16 = {(r[0], r[1]): r[2] for r in json.loads((repo.build / "cq_answers" / "CQ-G16.json").read_text())["rows"]}
    assert g16[("set_structure", "open_variety")] == 1 and g16[("story_engine", "tournament")] == 1
    assert g16[("mc_archetype", "prodigy")] == 0


def test_corpus_and_canonical_files_stay_readable(repo):
    repo.corpus_file.write_text(yaml.safe_dump({"titles": []}))
    write_state(repo, synthetic_state())
    assert read_jsonl(repo.canonical / "characters.jsonl")[0]["name"] == "Wren Halloway"
