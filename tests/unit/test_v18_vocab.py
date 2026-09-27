"""v1.8 vocab 1.5.0: discrimination tests for the grid (owner ruling), the lead's enum decisions, the
new lens fields with their kinds and caps, and the loader's checks on malformed lens specs."""

from __future__ import annotations

import copy
import json

import pytest

from animedex.ontology import OntologyError, Vocab, get_vocab
from tests.conftest import REPO

pytestmark = pytest.mark.unit

GRID = ("power_combat.gate", "power_combat.cost_of_power", "power_combat.progression", "power_combat.visible_counter")

# The request's enums, value for value (v1.8_request.md §1-7).
V18_ENUMS = {
    "power_combat.mc_edge": ["biggest_number", "creative_reinterpretation", "partnership_with_power", "unique_cost",
                             "relentless_training", "hidden_advantage", "not_strongest", "other"],
    "power_combat.power_embodiment": ["energy_or_technique", "bound_entity", "object_or_artifact", "system_interface",
                                      "body_transformation", "other"],
    "power_combat.set_structure": ["closed_set", "hierarchical", "open_variety", "pantheon", "universal_energy",
                                   "unique_to_few", "none", "other"],
    "power_combat.subset_mechanics": ["specialization", "combination", "forbidden_art", "bloodline", "legendary_unlock",
                                      "none"],
    "power_combat.set_scaffold": ["arbitrary", "cultural_reference", "semantic_domain", "elemental",
                                  "game_system", "personal_desire", "none", "other"],   # + D-031 (1.5.1)
    "power_combat.member_depth": ["label_only", "ability_only", "identity_with_history"],
    "power_combat.world_integration": ["decorative", "social_structure", "economic", "political_geography",
                                       "cosmological", "other"],
    "power_combat.rarity": ["universal", "common", "rare", "unique_to_mc"],
    "power_combat.power_up_mode": ["none", "staged_forms", "temporary_boost", "awakening", "partnership_mode", "domain",
                                   "absorption", "other"],   # + D-031 (1.5.1)
    "power_combat.fight_logic": ["power_level", "type_counters", "rules_exploitation", "strategy_information",
                                 "emotional_surge", "sacrifice", "other"],
    "core.story_engine": ["tournament", "journey_quest", "ladder_climb", "investigation", "war_campaign",
                          "death_game_rounds", "monster_of_the_week", "survival", "political_intrigue", "revenge",
                          "slice_of_life", "other"],
    "core.pilot_hook_type": ["cold_open_action", "mystery_hook", "tragedy_inciting", "power_awakening", "transported",
                             "status_quo_disruption", "other"],
    "core.ending_type": ["triumphant", "bittersweet", "tragic", "open", "unfinished", "other"],
    "core.setting_type": ["modern_urban", "historical", "secondary_fantasy", "isekai", "future_scifi",
                          "post_apocalyptic", "other"],
    "core.world_visibility": ["hidden", "open", "contained"],
    "core.conflict_scale": ["personal", "local", "national", "world", "cosmic"],
    "core.institution_type": ["academy", "military", "guild_or_license", "government", "criminal_org", "religious",
                              "other"],
    "core.mc_archetype": ["underdog", "chosen_one", "prodigy", "villain_protagonist", "everyman", "already_overpowered",
                          "veteran", "other"],
    "core.mc_start": ["weakest", "below_average", "average", "strong", "overpowered"],
    "core.mc_goal_type": ["find_someone", "revenge", "become_the_best", "protect", "escape_or_survive",
                          "change_the_world", "restore_what_was_lost", "other"],
    "core.ensemble_size": ["solo", "duo", "trio", "team", "large_ensemble"],
    "core.rival_type": ["friend_rival", "antagonist_rival", "mirror_rival", "none"],
    "core.threat_structure": ["single_final_boss", "escalating_ladder", "rotating_threats", "society_itself", "other"],
    "core.escalation_model": ["vertical_power", "horizontal_tools", "stakes_over_power", "structural_reset",
                              "cost_scaled", "none", "other"],
    "core.anticipation_hook_type": ["promised_payoff", "countdown", "rematch", "reunion", "long_mystery", "next_form"],
    "core.core_fantasy": ["secret_strength", "underestimated_then_vindicated", "mastery", "found_family", "revenge",
                          "transgression", "being_chosen", "protection", "freedom", "competence", "other"],
    "core.genre_move": ["subversion", "synthesis", "escalation", "purification", "inversion", "return_to_basics",
                        "other"],
    "character.role": ["protagonist", "main_rival", "main_antagonist", "mentor", "deuteragonist"],
    "character.origin_power_link": ["origin_creates_power", "origin_shapes_use", "origin_sets_cost", "unrelated",
                                    "other"],
    "character.arc_type": ["positive_change", "flat", "fall", "corruption", "disillusionment", "redemption", "other"],
    "character.backstory_reveal": ["upfront", "gradual", "late_twist", "never"],
    "character.power_kind": ["medium", "stat_block", "technique_system", "bound_entity", "object", "system_interface",
                             "skill_or_trait", "none"],
    "character.creativity_level": ["literal", "inventive", "transcendent"],
    "character.drama_source": ["restraint", "vulnerability", "corruption", "isolation", "other"],
    "character.villain_type": ["ideological", "predator", "mirror_of_mc", "system_or_institution", "tragic",
                               "hidden_manipulator", "nihilist", "force_of_nature", "other"],
    "character.villain_reveal": ["upfront", "gradual", "betrayal_twist", "never_fully"],
    "character.relation_to_mc": ["mirror", "opposing_ideology", "obstacle", "personal_betrayal", "other"],
    "outcome.failure_pattern": ["promise_broken", "power_scaling_collapse", "villain_deflation", "cast_bloat",
                                "pacing_collapse", "adaptation_compression", "tone_whiplash", "protagonist_passivity",
                                "ending_failure", "production_quality", "other"],
}


def raw_vocab() -> dict:
    return copy.deepcopy(json.loads((REPO / "ontology" / "vocab.json").read_text()))


def test_every_grid_value_has_a_one_sentence_discrimination_test():
    vocab = get_vocab()
    for name in GRID:
        tests = vocab.tests(name)
        assert list(tests) == list(vocab.enum(name)), name  # every value, nothing else
        for value, text in tests.items():
            assert 1 <= len(text.split()) <= 30, (name, value)
            assert text.endswith(".") and ". " not in text, (name, value)  # one sentence
            assert "; if " in text, (name, value)  # ...that says when the nearest neighbour is right instead


def test_the_leads_enum_decisions_are_applied_exactly():
    vocab = get_vocab()
    assert vocab.version == "1.6.0"  # 1.5.1 (D-031) and 1.6.0 (D-046, print media) only added enum values
    assert vocab.enum("power_combat.cost_of_power") == (
        "physical_toll", "lifespan", "memory", "identity_or_humanity", "relationships", "resource", "moral",
        "self_imposed_restriction", "imposed_penalty", "none", "other")
    assert vocab.enum("power_combat.visible_counter") == (
        "numeric_level", "rank_tier", "collectible_count", "transformation_stage", "gauge", "none", "other")
    assert vocab.enum("anime_production.demographic") == (
        "shonen", "seinen", "shojo", "josei", "kodomo", "no_magazine_demographic", "other")
    assert vocab.enum("power_combat.gate") == ("innate", "trained", "inherited", "contract", "system_granted",
                                               "artifact", "death_or_ritual", "mutation", "none", "other")
    assert vocab.enum("power_combat.progression") == ("lateral", "linear", "hybrid", "none")
    contract = vocab.tests("power_combat.gate")["contract"]
    assert "wish" in contract and "catastrophe" in contract  # a wish granted in a catastrophe is contract
    assert "a category label is not a counter" in vocab.tests("power_combat.visible_counter")["none"]


def test_v18_enums_match_the_request():
    vocab = get_vocab()
    for name, values in V18_ENUMS.items():
        assert list(vocab.enum(name)) == values, name
        assert vocab.cq_refs(name), name


def test_v18_lens_fields_kinds_and_caps():
    vocab = get_vocab()
    new = {f.path: f for f in vocab.lens_fields() if f.since == "1.5.0"}
    assert len(new) == 37 and sum(f.block == "core" for f in new.values()) == 25
    kinds = {k: {p for p, f in new.items() if f.kind == k} for k in ("enum_multi", "list", "group")}
    assert kinds == {"enum_multi": {"power_combat.subset_mechanics", "power_combat.power_up_mode",
                                    "power_combat.fight_logic", "core.core_fantasy"},
                     "list": {"core.institutions", "core.anticipation_hooks"}, "group": {"core.thematic_argument"}}
    inst, hooks = vocab.lens_field("core.institutions"), vocab.lens_field("core.anticipation_hooks")
    assert inst.max_items == 3 and [(p.name, p.max_words or p.vocab) for p in inst.parts] == [
        ("name", 6), ("type", "core.institution_type"), ("role", 12)]
    assert hooks.max_items == 3 and [(p.name, p.max_words or p.vocab) for p in hooks.parts] == [
        ("hook", 12), ("type", "core.anticipation_hook_type")]
    assert [(p.name, p.max_words) for p in vocab.lens_field("core.thematic_argument").parts] == [
        ("thesis_mc", 15), ("antithesis_villain", 15), ("resolution", 20)]
    secondary = vocab.lens_field("power_combat.cost_of_power_secondary")
    assert (secondary.vocab, secondary.differs_from) == ("power_combat.cost_of_power", "cost_of_power")
    assert vocab.lens_field("core.story_engine_secondary").differs_from == "story_engine"
    promise_break = vocab.lens_field("core.promise_break")
    assert promise_break.outcome_in == ("mixed", "flop") and promise_break.needs_source
    assert [f.path for f in vocab.lens_fields() if f.abstract] == ["core.premise_abstraction"]
    assert vocab.lens_field("power_combat.power_up_cost").max_words == 15


@pytest.mark.parametrize("spec, message", [
    ({"kind": "wordcloud"}, "kind must be"),
    ({"kind": "enum_multi", "vocab": "no.such_field"}, "unknown vocab"),
    ({"kind": "phrase", "vocab": "feeling"}, "only enum kinds take a vocab"),
    ({"kind": "list", "item": {"x": {"kind": "phrase"}}}, "max_items"),
    ({"kind": "list", "max_items": 2}, "needs `item`"),
    ({"kind": "group", "fields": {"x": {"kind": "number"}}}, "sub-field kind"),
    ({"kind": "group", "fields": {"x": {"kind": "enum", "vocab": "nope"}}}, "unknown vocab"),
    ({"kind": "group", "fields": {"x": {"kind": "phrase"}}, "max_items": 2}, "only list fields take max_items"),
    ({"kind": "enum", "vocab": "feeling", "item": {"x": {"kind": "phrase"}}}, "only a list field"),
    ({"kind": "enum", "vocab": "feeling", "since": "soon"}, "since"),
    ({"kind": "enum", "vocab": "feeling", "differs_from": "tone"}, "differs_from"),
    ({"kind": "enum", "vocab": "feeling", "differs_from": "extra_field"}, "differs_from"),
    ({"kind": "phrase", "outcome_in": ["cult_classic"]}, "outcome_in"),
    ({"kind": "enum", "vocab": "feeling", "abstract": True}, "abstract"),
])
def test_malformed_lens_specs_are_rejected(spec, message):
    data = raw_vocab()
    data["lens"]["core"]["fields"]["extra_field"] = spec
    with pytest.raises(OntologyError, match=message):
        Vocab(data)


@pytest.mark.parametrize("value, text, message", [
    ("teleport", "A route nobody lists; if it is listed, choose it.", "not in the enum"),
    ("innate", " ".join(["word"] * 31), "1-30 words"),
    ("innate", "  ", "1-30 words"),
])
def test_discrimination_tests_must_name_real_values_and_stay_short(value, text, message):
    data = raw_vocab()
    data["fields"]["power_combat.gate"]["tests"][value] = text
    with pytest.raises(OntologyError, match=message):
        Vocab(data)
