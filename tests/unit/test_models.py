"""Contract shapes (04, v1.2) on synthetic records."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from animedex.models import (
    CorpusEntry,
    Episode,
    IdeaCard,
    MechanismAtom,
    Moment,
    Provenance,
    TransferAtom,
    title_profile_model,
)
from tests.conftest import (
    field_value,
    make_effect_atom,
    make_engine_atom,
    make_idea,
    make_moment,
    make_title,
    make_transfer,
    prov,
)

pytestmark = pytest.mark.unit


def test_title_profile_valid_and_inactive_modules_omitted():
    model = title_profile_model()
    rec = make_title()
    out = model.model_validate(rec).to_record()
    assert "film" not in out and "comedy_satire" not in out
    assert out["power_combat"]["gate"]["value"] == rec["power_combat"]["gate"]["value"]
    assert out["provenance"]["pass"] == "P1"


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.update(modules_active=["power_combat"]), "present but not in modules_active"),
    (lambda r: r.update(modules_active=[*r["modules_active"], "film"]), "active but missing"),
    (lambda r: r.update(modules_active=[*r["modules_active"], "astrology"]), "unknown modules"),
])
def test_title_module_rules(mutate, message):
    rec = make_title()
    mutate(rec)
    with pytest.raises(ValidationError, match=message):
        title_profile_model().model_validate(rec)


def test_deleted_fields_are_gone_after_g0():
    rec = make_title(modules=("sensory", "comedy_satire"))
    rec["sensory"]["sound_motif"] = field_value("a humming synth")
    with pytest.raises(ValidationError, match="sound_motif"):
        title_profile_model().model_validate(rec)
    rec = make_title(modules=("sensory", "comedy_satire"))
    rec["comedy_satire"]["satire_target"] = field_value("corporate heroes")
    with pytest.raises(ValidationError, match="satire_target"):
        title_profile_model().model_validate(rec)


def test_film_scope_allows_empty_seasons_and_null_numbering():
    rec = make_title("glass_meridian_2016", "Glass Meridian", medium="film", fmt="film", modules=("film",))
    assert title_profile_model().model_validate(rec).scope.numbering is None


def test_non_film_scope_needs_seasons_and_numbering():
    rec = make_title()
    rec["scope"]["numbering"] = None
    with pytest.raises(ValidationError, match="numbering is required"):
        title_profile_model().model_validate(rec)
    rec = make_title()
    rec["scope"]["seasons"] = []
    with pytest.raises(ValidationError, match="at least one season"):
        title_profile_model().model_validate(rec)


def test_scope_version_always_required_even_for_films():
    rec = make_title("glass_meridian_2016", "Glass Meridian", medium="film", fmt="film", modules=("film",))
    rec["scope"]["version"] = ""
    with pytest.raises(ValidationError):
        title_profile_model().model_validate(rec)


@pytest.mark.parametrize("path, value, message", [
    (("power_combat", "gate"), field_value("teleport_permit"), "not in vocab"),
    (("core", "logline_hook"), field_value(" ".join(["word"] * 21)), "1-20 words"),  # a two-part field
    (("core", "tone"), field_value(" ".join(["word"] * 16)), "1-15 words"),
    (("core", "flaw"), {**field_value("proud"), "condition": " ".join(["word"] * 16)}, "15-word limit"),
    (("core", "tone"), field_value(None, conf=0.5), "conf 0"),
    (("core", "tone"), {**field_value("wry"), "condition": "when cornered"}, "does not take a condition"),
    (("core", "tone"), field_value("wry", verification="web_confirmed"), "recall is not verification"),
])
def test_field_value_rules(path, value, message):
    rec = make_title()
    rec[path[0]][path[1]] = value
    with pytest.raises(ValidationError, match=message):
        title_profile_model().model_validate(rec)


def test_conditional_character_fields_accept_condition():
    rec = make_title()
    assert rec["core"]["flaw"]["condition"]
    title_profile_model().model_validate(rec)


def test_corpus_entry_title_id_must_end_with_year():
    entry = {"title_id": "ironvale_circuit_2021", "title": "Ironvale Circuit", "year": 2020, "medium": "anime",
             "format": "serialized", "scope": {"version": "tv", "seasons": [1], "numbering": "broadcast"}}
    with pytest.raises(ValidationError, match="first-airing year"):
        CorpusEntry.model_validate(entry)
    entry["year"] = 2021
    CorpusEntry.model_validate(entry)


def test_mechanism_exactly_one_kind_matching_atom_kind():
    MechanismAtom.model_validate(make_effect_atom())
    MechanismAtom.model_validate(make_engine_atom())
    bad = make_effect_atom()
    bad["engine"] = copy.deepcopy(make_engine_atom()["engine"])
    with pytest.raises(ValidationError, match="exactly one"):
        MechanismAtom.model_validate(bad)
    bad = make_effect_atom(atom_kind="engine")
    with pytest.raises(ValidationError, match="exactly one"):
        MechanismAtom.model_validate(bad)


def test_effect_atom_requires_rival_because_and_evidence():
    bad = make_effect_atom()
    del bad["effect"]["rival_because"]
    with pytest.raises(ValidationError, match="rival_because"):
        MechanismAtom.model_validate(bad)
    with pytest.raises(ValidationError, match="evidence_refs"):
        MechanismAtom.model_validate(make_effect_atom(evidence_refs=[]))


def test_atom_id_must_belong_to_title():
    with pytest.raises(ValidationError, match="start with its title_id"):
        MechanismAtom.model_validate(make_effect_atom(title_id="ironvale_circuit_2021", atom_id="lantern_debt_2019.m.001"))


def test_transfer_needs_all_three_condition_lists_and_known_bridge():
    for key in ("essential_conditions", "variable_details", "failure_conditions"):
        with pytest.raises(ValidationError):
            TransferAtom.model_validate(make_transfer(**{key: []}))
    with pytest.raises(ValidationError, match="bridge concept"):
        TransferAtom.model_validate(make_transfer(bridge=["vibes"]))


def test_idea_status_is_champion_not_elite():
    IdeaCard.model_validate(make_idea())
    with pytest.raises(ValidationError):
        IdeaCard.model_validate(make_idea(status="elite"))


def test_idea_taste_criteria_need_evidence_and_engine_is_complete():
    bad = make_idea()
    bad["taste"] = {"criteria_met": ["T1"], "evidence": {}, "hard_fail": False}
    with pytest.raises(ValidationError, match="lack required evidence"):
        IdeaCard.model_validate(bad)
    bad = make_idea()
    bad["engine"]["dilemma"] = ""
    with pytest.raises(ValidationError):
        IdeaCard.model_validate(bad)


def test_moment_word_limit():
    with pytest.raises(ValidationError, match="26 words"):
        Moment.model_validate(make_moment(description=" ".join(["beat"] * 26)))


def test_episode_needs_fetched_url_and_matching_locator():
    ep = {"episode_id": "ironvale_circuit_2021.s01e01", "title_id": "ironvale_circuit_2021",
          "locator": {"season": 1, "episode": 1, "episode_title": "", "numbering": "broadcast"},
          "selection_reason": "pilot", "summary": "A courier discovers the grid answers only to her.",
          "function": "pilot_hook", "end_hook": "open_question",
          "info_shift": {"audience_learns": "", "characters_learn": "", "gap_change": "widens"},
          "source": "web", "source_ref": "https://example.org/ep1", "verification": "web_confirmed",
          "provenance": prov("EP")}
    Episode.model_validate(ep)
    with pytest.raises(ValidationError, match="fetched URL"):
        Episode.model_validate({**ep, "source_ref": "recall"})
    with pytest.raises(ValidationError, match="must match the locator"):
        Episode.model_validate({**ep, "episode_id": "ironvale_circuit_2021.s01e02"})


def test_provenance_pass_values_include_canonicalize_and_patterns():
    for p in ("CANONICALIZE", "PATTERNS", "IDEATE"):
        Provenance.model_validate(prov(p))
    with pytest.raises(ValidationError):
        Provenance.model_validate(prov("SMOKE"))
    with pytest.raises(ValidationError, match="sha256"):
        Provenance.model_validate(prov("P1", cache_key="md5:abc"))


def test_each_phrase_field_takes_its_own_cap():
    rec = make_title()
    rec["core"]["logline_hook"] = field_value(" ".join(["word"] * 20))
    rec["core"]["tone"] = field_value(" ".join(["word"] * 15))
    title_profile_model().model_validate(rec)  # both exactly at their caps


def test_an_explanation_test_names_its_deciding_partner_unless_none_decides():
    """D-036: favors because/rival needs the deciding partner; both/neither may have none."""
    from pydantic import ValidationError

    from animedex.models.atoms import ExplanationTest

    ExplanationTest(favors="neither", via_partner=None, note="The partner lacks both, so it decides nothing.")
    ExplanationTest(favors="both", note="Both explanations survive the comparison.")
    ExplanationTest(favors="because", via_partner="glass_meridian_2016", note="The partner has the element only.")
    with pytest.raises(ValidationError, match="needs the partner"):
        ExplanationTest(favors="rival", via_partner=None, note="The partner shows the rival cause.")
