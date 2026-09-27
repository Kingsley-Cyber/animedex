"""v1.8 record shapes (schema 1.4.0): the three new lens kinds, `since` fields on older records, the
cross-field lens rules, characters, failure patterns, the P4 ladder, predictive pattern cards, idea-card
concept fields, census fields, and the steering library."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from animedex.models import (
    CensusEntry,
    CharacterRecord,
    IdeaCard,
    Outcome,
    PatternCard,
    SteeringRule,
    TransferAtom,
    load_steering,
    load_steering_rules,
    title_profile_model,
)
from animedex.ontology import get_vocab
from tests.conftest import (
    REPO,
    field_value,
    make_character,
    make_idea,
    make_title,
    make_transfer,
    prov,
    synthetic_state,
)

pytestmark = pytest.mark.unit


def validate(rec: dict) -> dict:
    return title_profile_model().model_validate(rec).to_record()


def with_value(path: str, value, **over) -> dict:
    rec = make_title()
    block, name = path.split(".")
    rec[block][name] = {**field_value(value), **over}
    return rec


# ---------------------------------------------------------------- field kinds
def test_every_kind_keeps_the_same_envelope():
    out = validate(make_title())
    for path in ("core.institutions", "core.thematic_argument", "core.core_fantasy", "power_combat.mc_edge"):
        block, name = path.split(".")
        assert set(out[block][name]) == {"value", "condition", "conf", "uncertainty_reason", "source",
                                         "verification", "source_ref", "epistemic"}, path


@pytest.mark.parametrize("value", [["mastery"], ["mastery", "found_family"], ["other"]])
def test_enum_multi_accepts_one_or_more_listed_values(value):
    assert validate(with_value("core.core_fantasy", value))["core"]["core_fantasy"]["value"] == value


@pytest.mark.parametrize("value, message", [
    ([], "one or more"),
    (["mastery", "mastery"], "twice"),
    (["heist"], "one or more"),
    (["none", "bloodline"], "none cannot be combined"),
    ("mastery", "list"),
])
def test_enum_multi_rejects_bad_values(value, message):
    path = "power_combat.subset_mechanics" if "none" in str(value) else "core.core_fantasy"
    with pytest.raises(ValidationError, match=message):
        validate(with_value(path, value))


def test_enum_multi_null_is_unknown_with_conf_zero():
    validate(with_value("core.core_fantasy", None, conf=0.0))
    with pytest.raises(ValidationError, match="conf 0"):
        validate(with_value("core.core_fantasy", None, conf=0.6))


def test_list_items_have_typed_parts_and_a_limit():
    item = {"name": "the relay guild", "type": "guild_or_license", "role": "licenses every courier in the city"}
    assert validate(with_value("core.institutions", [item] * 3))["core"]["institutions"]["value"] == [item] * 3
    assert validate(with_value("core.institutions", []))["core"]["institutions"]["value"] == []  # known: none
    for bad, message in [([item] * 4, "at most 3 items"),
                         ([{**item, "type": "labor_union"}], "not one of"),
                         ([{k: v for k, v in item.items() if k != "role"}], "role"),
                         ([{**item, "role": None}], "role"),
                         ([{**item, "name": "the very long official name of the relay guild"}], "6-word limit"),
                         ([{**item, "extra": "x"}], "extra")]:
        with pytest.raises(ValidationError, match=message):
            validate(with_value("core.institutions", bad))


def test_group_parts_may_be_unknown_but_not_all():
    group = {"thesis_mc": "help shared is strength", "antithesis_villain": "only control keeps the lights on",
             "resolution": None}  # an unfinished story: the ending's argument is unknown
    assert validate(with_value("core.thematic_argument", group))["core"]["thematic_argument"]["value"] == group
    with pytest.raises(ValidationError, match="no known part"):
        validate(with_value("core.thematic_argument", dict.fromkeys(group)))
    with pytest.raises(ValidationError, match="thesis_mc"):
        validate(with_value("core.thematic_argument", {"antithesis_villain": "x", "resolution": "y"}))
    with pytest.raises(ValidationError, match="20-word limit"):
        validate(with_value("core.thematic_argument", {**group, "resolution": " ".join(["w"] * 21)}))


# ---------------------------------------------------------------- since (older records stay valid)
def v14_record() -> dict:
    rec = make_title()
    for f in get_vocab().lens_fields():
        if f.since and f.block in rec:
            rec[f.block].pop(f.name, None)
    rec["provenance"]["vocab_version"] = "1.4.0"
    return rec


def test_a_record_made_under_an_older_vocab_may_omit_newer_fields():
    rec = v14_record()
    out = validate(rec)
    assert "story_engine" not in out["core"] and "mc_edge" not in out["power_combat"]  # omitted, not null-filled
    assert out == validate(out)


def test_a_record_made_under_vocab_1_5_0_needs_every_field():
    rec = v14_record()
    rec["provenance"]["vocab_version"] = "1.5.0"
    with pytest.raises(ValidationError, match="core.story_engine is missing"):
        validate(rec)


# ---------------------------------------------------------------- cross-field lens rules
def test_a_secondary_differs_from_its_primary_and_needs_one():
    rec = make_title()
    rec["power_combat"]["cost_of_power_secondary"] = field_value(rec["power_combat"]["cost_of_power"]["value"])
    with pytest.raises(ValidationError, match="must differ"):
        validate(rec)
    rec = make_title()
    rec["core"]["story_engine"] = field_value(None, uncertainty_reason="no reliable recall")
    with pytest.raises(ValidationError, match="needs core.story_engine"):
        validate(rec)
    rec = make_title()
    rec["power_combat"]["cost_of_power_secondary"] = field_value(None, uncertainty_reason="no second cost")
    validate(rec)  # optional


def test_promise_break_is_for_mixed_and_flop_titles_and_needs_a_source():
    text = "the promised underdog climb stalls into a static stalemate"
    web = {"source": "web", "verification": "web_confirmed", "source_ref": "https://example.org/review"}
    rec = with_value("core.promise_break", text, **web)
    with pytest.raises(ValidationError, match="only for mixed/flop titles"):
        validate(rec)  # synthetic titles are hits
    rec["core"]["outcome"]["value"] = "flop"
    validate(rec)
    rec["core"]["promise_break"].update(source="recall", verification="unresolved", source_ref=None)
    with pytest.raises(ValidationError, match="needs a cited source"):
        validate(rec)
    rec["core"]["promise_break"]["verification"] = "unverified"
    validate(rec)  # a P1 candidate waiting for VERIFY


def test_premise_abstraction_has_no_medium_words():
    validate(with_value("core.premise_abstraction", "a debt collector who can see what every life owes"))
    with pytest.raises(ValidationError, match="medium words"):
        validate(with_value("core.premise_abstraction", "an anime about a debt collector"))


# ---------------------------------------------------------------- characters
def test_character_record_validates_and_roundtrips():
    for c in synthetic_state()["character"]:
        once = CharacterRecord.model_validate(c).to_record()
        assert CharacterRecord.model_validate(once).to_record() == once


def kit(**over) -> dict:
    return {**make_character()["power_kit"], **over}


@pytest.mark.parametrize("over, message", [
    ({"character_id": "lantern_debt_2019.c.01"}, "start with its title_id"),
    ({"character_id": "ironvale_circuit_2021.c.1"}, "does not match"),
    ({"role": "sidekick"}, "not in vocab"),
    ({"villain": {"villain_type": "ideological", "villain_reveal": "gradual", "relation_to_mc": "mirror"}},
     "villain fields are only for main_antagonist"),
    ({"turning_points": [{"event": "e", "locator": {"episode": 1}}] * 4}, "at most 3"),
    ({"flaw": {"value": "refuses help"}}, "condition"),
    ({"source_refs": ["recall"]}, "must be URLs"),
    ({"power_kit": kit(functions=["reroute current", "read load"])}, "3-6 core functions"),
    ({"power_kit": kit(tools=[{"tool": "blackout feint", "function": "fly"}])}, "not one of the kit's functions"),
    ({"power_kit": kit(creativity_moves=[])}, "needs at least one sourced creativity move"),
    ({"power_kit": kit(creativity_moves=[{"move": "cages a rival", "source_ref": "a wiki"}])}, "source URL"),
    ({"power_kit": kit(drama_source="restraint")}, "only for stat_block"),
    ({"power_kit": kit(power_kind="stat_block")}, "drama_source instead of creativity"),
    ({"power_kit": kit(power_kind="stat_block", creativity_level=None, creativity_moves=[])}, "needs a drama_source"),
    ({"power_kit": kit(power_kind="none")}, "kind none"),
    ({"power_kit": kit(tools=[{"tool": "t", "function": "reroute current"}] * 6)}, "at most 5"),
])
def test_character_rules(over, message):
    with pytest.raises(ValidationError, match=message):
        CharacterRecord.model_validate(make_character(**over))


def test_stat_block_kits_take_drama_and_antagonists_take_villain_fields():
    CharacterRecord.model_validate(make_character(power_kit=kit(power_kind="stat_block", creativity_level=None,
                                                                creativity_moves=[], drama_source="restraint")))
    with pytest.raises(ValidationError, match="needs villain fields"):
        CharacterRecord.model_validate(make_character(n=2, role="main_antagonist", villain=None))
    unknown = make_character(origin=None, wound=None, want=None, need=None, flaw=None, moral_line=None,
                             relationship_to_power=None, origin_power_link=None, arc_type=None, backstory_reveal=None)
    CharacterRecord.model_validate(unknown)  # null is unknown
    missing = make_character()
    del missing["want"]
    with pytest.raises(ValidationError, match="want"):
        CharacterRecord.model_validate(missing)  # base fields are written out


# ---------------------------------------------------------------- outcomes, transfers, pattern cards
def flop(**over) -> dict:
    o = copy.deepcopy(synthetic_state()["outcome"][0])
    o.update(over)
    return o


def test_failure_patterns_are_mixed_or_flop_only_sourced_and_listed_once():
    out = Outcome.model_validate(flop()).to_record()
    assert out["failure_patterns"][0]["pattern"] == "pacing_collapse"
    assert "failure_patterns" not in Outcome.model_validate(flop(failure_patterns=[])).to_record()  # earlier form
    pattern = flop()["failure_patterns"][0]
    for bad, message in [([{**pattern, "source_ref": "recall"}], "source URL"),
                         ([pattern, pattern], "twice"),
                         ([{**pattern, "pattern": "bad_vibes"}], "not in vocab"),
                         ([{**pattern, "note": " ".join(["w"] * 13)}], "12-word limit")]:
        with pytest.raises(ValidationError, match=message):
            Outcome.model_validate(flop(failure_patterns=bad))


def test_transfer_ladder_is_optional_but_checked():
    TransferAtom.model_validate(make_transfer())  # earlier transfers stay valid
    ladder = {"mechanism": "a private measure turns every fight into a shared secret",
              "principle": "When growth is visible only to the audience, hide it from rivals, because the secret "
                           "carries the tension",
              "anti_pattern": "everyone can read the measure"}
    TransferAtom.model_validate(make_transfer(**ladder))
    for key, bad, message in [("principle", "Hide the measure from rivals because secrets create tension",
                               "when X, do Y, because Z"),
                              ("principle", "Because it works, when in doubt hide the measure", "when X, do Y"),
                              ("mechanism", " ".join(["w"] * 21), "20-word limit"),
                              ("anti_pattern", " ".join(["w"] * 13), "12-word limit")]:
        with pytest.raises(ValidationError, match=message):
            TransferAtom.model_validate(make_transfer(**{**ladder, key: bad}))


def card(**over) -> dict:
    rec = {"pattern_id": "pattern.001", "statement": "A private measure of growth shared only with the audience.",
           "transfer_ids": ["ironvale_circuit_2021.t.001"], "supporting_titles": ["ironvale_circuit_2021"],
           "scope": "corpus_subset", "provenance": prov("PATTERNS", model=None)}
    rec.update(over)
    return rec


def test_a_predictive_principle_needs_held_out_evidence():
    assert PatternCard.model_validate(card()).predictive is False
    held_out = {"title_id": "lantern_debt_2019", "atom_id": "lantern_debt_2019.m.004"}
    PatternCard.model_validate(card(predictive=True, predictive_evidence=[held_out]))
    with pytest.raises(ValidationError, match="held-out title"):
        PatternCard.model_validate(card(predictive=True))
    with pytest.raises(ValidationError, match="held-out title"):
        PatternCard.model_validate(card(predictive=True, predictive_evidence=[
            {"title_id": "ironvale_circuit_2021", "atom_id": "ironvale_circuit_2021.m.001"}]))  # a supporting title
    with pytest.raises(ValidationError, match="belong to its title_id"):
        PatternCard.model_validate(card(predictive_evidence=[{"title_id": "lantern_debt_2019",
                                                              "atom_id": "ironvale_circuit_2021.m.001"}]))


# ---------------------------------------------------------------- idea cards and census
IDEA_V18 = {
    "mc": {"edge": "unique_cost", "origin": "a lighthouse keeper's daughter raised on the harbor ledger",
           "wound": "watched the sea take her father", "origin_power_link": "origin_sets_cost"},
    "power_kit": {"kind": "medium", "medium": "debts owed to the sea",
                  "functions": ["read a debt", "move a debt", "call a debt due"],
                  "tools": [{"tool": "storm tithe", "function": "call a debt due"}],
                  "limits": ["cannot erase a debt"], "creativity_path": "from reading debts to rewriting the harbor's"},
    "thematic_argument": {"thesis_mc": "a debt can be carried together", "antithesis_villain": "every debt is paid alone",
                          "resolution": "the town pays its debt as one"},
    "audience_promise": "a quiet keeper outwits the sea itself", "escalation_model": "cost_scaled",
    "core_fantasy": ["protection", "secret_strength"],
    "premise_abstraction": "a keeper who can move what the living owe must choose who pays",
    "rules": {"version": "1.0.0", "satisfied": ["rule.001"], "failed": ["rule.002"]},
}


def test_idea_cards_take_the_v18_concept_fields_and_stay_valid_without_them():
    IdeaCard.model_validate(make_idea())
    out = IdeaCard.model_validate(make_idea(**IDEA_V18)).to_record()
    assert out["mc"]["edge"] == "unique_cost" and out["rules"]["failed"] == ["rule.002"]


@pytest.mark.parametrize("key, bad, message", [
    ("power_kit", {**IDEA_V18["power_kit"], "functions": ["read a debt"]}, "at least 3"),
    ("power_kit", {**IDEA_V18["power_kit"], "tools": [{"tool": "t", "function": "sing"}]}, "not one of the kit's"),
    ("power_kit", {**IDEA_V18["power_kit"], "tools": [{"tool": "t", "function": "read a debt"}] * 4}, "at most 3"),
    ("mc", {**IDEA_V18["mc"], "edge": "sheer_luck"}, "not in vocab"),
    ("core_fantasy", ["protection", "protection"], "twice"),
    ("premise_abstraction", "a keeper anime about who pays the sea", "medium words"),
    ("rules", {"version": "1.0.0", "satisfied": ["rule.001"], "failed": ["rule.001"]}, "once"),
    ("rules", {"version": "1.0.0", "satisfied": ["no-caps"], "failed": []}, "does not match"),
    ("thematic_argument", {"thesis_mc": "x", "antithesis_villain": "y"}, "resolution"),
])
def test_idea_card_concept_rules(key, bad, message):
    with pytest.raises(ValidationError, match=message):
        IdeaCard.model_validate(make_idea(**{**IDEA_V18, key: bad}))


def test_census_entries_take_the_three_v18_fields():
    entry = {"census_id": "anilist:1", "title": "Synthetic", "medium": "anime", "format": "TV", "batch_id": "b",
             "set_structure": "open_variety", "story_engine": "tournament", "mc_archetype": "underdog",
             "provenance": prov("CENSUS")}
    assert CensusEntry.model_validate(entry).story_engine == "tournament"
    with pytest.raises(ValidationError, match="not in vocab"):
        CensusEntry.model_validate({**entry, "mc_archetype": "hero"})


# ---------------------------------------------------------------- steering library
def rule(**over) -> dict:
    rec = {"id": "rule.001", "rule": "The MC is legibly the strongest without holding the biggest number.",
           "strength": "hard", "examples": ["A courier who wins by rerouting the arena's power."],
           "check": {"field": "mc.edge", "op": "not_in", "values": ["biggest_number", "not_strongest"]}}
    rec.update(over)
    return rec


def test_the_committed_example_library_loads():
    lib = load_steering(REPO / "config" / "steering.example.yaml")
    assert lib.version and [r.id for r in lib.rules] == ["rule.001", "rule.002", "rule.003"]
    assert {r.strength for r in lib.rules} == {"hard", "soft"} and any(r.check is None for r in lib.rules)


def test_a_missing_library_is_empty(tmp_path: Path):
    assert load_steering_rules(tmp_path / "steering" / "rules.yaml") == []


@pytest.mark.parametrize("over, message", [
    ({"id": "rule.1"}, "does not match"),
    ({"strength": "firm"}, "hard"),
    ({"examples": []}, "at least 1"),
    ({"examples": ["a", "b", "c"]}, "at most 2"),
    ({"rule": " ".join(["w"] * 31)}, "30-word limit"),
    ({"check": {"field": "mc.aura", "op": "in", "values": ["x"]}}, "not an idea-card field"),
    ({"check": {"field": "mc.edge", "op": "in", "values": ["sheer_luck"]}}, "not values of mc.edge"),
    ({"check": {"field": "mc.edge", "op": "about", "values": ["unique_cost"]}}, "in"),
])
def test_steering_rule_rules(over, message):
    with pytest.raises(ValidationError, match=message):
        SteeringRule.model_validate(rule(**over))


def test_steering_checks_test_idea_cards(tmp_path: Path):
    card_ = make_idea(**IDEA_V18)
    r = SteeringRule.model_validate(rule())
    assert r.check.passes(card_) is True
    assert r.check.passes({**card_, "mc": {**IDEA_V18["mc"], "edge": "biggest_number"}}) is False
    assert r.check.passes(make_idea()) is None  # the card leaves the field empty
    fantasy = SteeringRule.model_validate(rule(check={"field": "core_fantasy", "op": "in", "values": ["protection"]}))
    assert fantasy.check.passes(card_) is True  # a list field: any member listed
    dupes = tmp_path / "rules.yaml"
    dupes.write_text("version: '1'\nrules:\n" + "".join(
        "  - {id: rule.001, rule: r, strength: soft, examples: [e]}\n" for _ in range(2)))
    with pytest.raises(ValidationError, match="duplicate rule ids"):
        load_steering(dupes)
    unversioned = tmp_path / "unversioned.yaml"
    unversioned.write_text("rules:\n  - {id: rule.001, rule: r, strength: soft, examples: [e]}\n")
    with pytest.raises(ValidationError, match="needs a version"):
        load_steering(unversioned)
