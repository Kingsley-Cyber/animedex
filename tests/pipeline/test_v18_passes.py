"""v1.8 on the offline passes: P1 renders the grid tests from vocab, offers and checks the new kinds
(schema, draft checks, clean-up, the length repair on a part), sends a sourced field to VERIFY;
VERIFY checks corrected values of the new kinds and drops an unsourced promise_break; P4 requires the
abstraction ladder; the census asks for the three v1.8 fields."""

from __future__ import annotations

import json

import pytest
import yaml

from animedex.config import load_settings
from animedex.content_guards import GuardConfig
from animedex.models import CorpusEntry
from animedex.ontology import Vocab, get_vocab
from animedex.pipeline.canonicalize import canonicalize
from animedex.pipeline.p1 import draft_problems, normalize_draft, output_schema, render_prompt
from animedex.store.jsonl import read_jsonl
from tests.pipeline.test_p1 import ENTRY, KEY, fv, make_draft, run

pytestmark = pytest.mark.pipeline

GRID = ("power_combat.gate", "power_combat.cost_of_power", "power_combat.progression", "power_combat.visible_counter")
FLOP = {**ENTRY, "role_tags": ["flop"]}


def problems_for(draft: dict, entry: dict = ENTRY) -> list[str]:
    e = CorpusEntry.model_validate(entry)
    vocab = get_vocab()
    return draft_problems(normalize_draft(draft, e, vocab), e, vocab, 0.7, GuardConfig())


# ---------------------------------------------------------------- P1 prompt: tests from vocab
def test_p1_prompt_renders_the_discrimination_tests_from_vocab(repo):
    vocab, settings = get_vocab(), load_settings(repo)
    system = render_prompt(repo, vocab, settings).system
    for name in GRID:
        for value, text in vocab.tests(name).items():
            assert f"  - {value}: {text}" in system, (name, value)
    assert "- power_combat.cost_of_power_secondary: the values and tests of power_combat.cost_of_power" in system
    assert "- core.core_fantasy (one or more): secret_strength" in system and "- core.institutions.type: academy" in system
    fragment = (repo.prompts / "p1_modules" / "power_combat.md").read_text()
    assert not any(text in fragment for text in vocab.tests("power_combat.gate").values())  # one source: vocab.json
    data = json.loads(repo.vocab_file.read_text())
    data["fields"]["power_combat.gate"]["tests"]["innate"] = "Born with it, from nowhere; if it runs in a bloodline, choose inherited."
    edited = render_prompt(repo, Vocab(data), settings)
    assert "Born with it, from nowhere" in edited.system and edited.version != render_prompt(repo, vocab, settings).version


# ---------------------------------------------------------------- P1 schema and draft checks
def test_p1_schema_offers_each_kind_its_shape():
    core = output_schema(get_vocab(), CorpusEntry.model_validate(ENTRY))["properties"]["core"]["properties"]
    multi = core["core_fantasy"]["properties"]["value"]
    assert multi["type"] == ["array", "null"] and multi["items"] == {"type": "string"}
    inst = core["institutions"]["properties"]["value"]
    assert inst["type"] == ["array", "null"] and "up to 3 items" in inst["description"]
    assert inst["items"]["required"] == ["name", "type", "role"] and inst["items"]["additionalProperties"] is False
    group = core["thematic_argument"]["properties"]["value"]
    assert group["type"] == ["object", "null"] and group["required"] == ["thesis_mc", "antithesis_villain", "resolution"]
    assert group["properties"]["resolution"] == {"type": ["string", "null"], "description": "20 words or fewer"}
    assert core["premise_abstraction"]["properties"]["value"]["description"] == "a phrase of 20 words or fewer"


def test_a_complete_v18_draft_has_no_problems():
    assert problems_for(make_draft()) == []


@pytest.mark.parametrize("block, name, value, expected", [
    ("core", "core_fantasy", "mastery", "core.core_fantasy: must be a list"),
    ("core", "core_fantasy", ["mastery", "heist"], "core.core_fantasy.1: 'heist': use a listed value or other:<phrase>"),
    ("power_combat", "power_up_mode", ["none", "domain"], "none cannot be combined"),
    ("core", "institutions", [{"name": "a guild", "type": "academy", "role": "trains"}] * 4, "at most 3 items"),
    ("core", "institutions", [{"name": "a guild", "type": "academy"}], "core.institutions.0.role: is missing"),
    ("core", "institutions", [{"name": "a guild", "type": "union", "role": "trains"}], "core.institutions.0.type: 'union'"),
    ("core", "thematic_argument", {"thesis_mc": "x"}, "core.thematic_argument.antithesis_villain: is missing"),
    ("core", "premise_abstraction", "an anime where a courier keeps the grid alive", "no medium words (anime)"),
    ("core", "premise_abstraction", "a courier and her friend Marisol keep the grid alive", "no names (Marisol)"),
    ("core", "premise_abstraction", "the Ironvale Circuit courier keeps a city alive", "no names (it names the title)"),
    ("power_combat", "gate", "teleport", "power_combat.gate='teleport': use a listed value or other:<phrase>"),
])
def test_p1_checks_the_new_kinds(block, name, value, expected):
    draft = make_draft()
    draft[block][name] = fv(value)
    assert any(expected in p for p in problems_for(draft)), problems_for(draft)


def test_p1_cleans_up_empty_values_equal_secondaries_and_outcome_bound_fields():
    e, vocab = CorpusEntry.model_validate(ENTRY), get_vocab()
    draft = make_draft()
    draft["core"]["core_fantasy"] = fv([])
    draft["core"]["thematic_argument"] = fv({"thesis_mc": None, "antithesis_villain": None, "resolution": None})
    draft["core"]["story_engine_secondary"] = fv(draft["core"]["story_engine"]["value"])
    draft["core"]["promise_break"] = fv("the promised climb stalls into a stalemate")  # the draft says hit
    out = normalize_draft(draft, e, vocab)
    for name in ("core_fantasy", "thematic_argument", "story_engine_secondary", "promise_break"):
        assert (out["core"][name]["value"], out["core"][name]["conf"]) == (None, 0), name
        assert out["core"][name]["uncertainty_reason"], name
    assert draft_problems(out, e, vocab, 0.7, GuardConfig()) == []


def test_a_long_list_part_gets_the_length_repair(repo):
    long = make_draft()
    long["core"]["institutions"] = fv([{"name": "the relay guild", "type": "guild_or_license",
                                        "role": "licenses every courier in the city and fines anyone who reroutes a district"}])  # 13 > 12
    short = {"items": [{"path": "core.institutions.0.role", "text": "licenses and fines the city's couriers"}]}
    result, mock = run(repo, {KEY: [long], ("P1", f"{KEY[1]}.shorten"): [short]})
    assert len(result.titles) == 1 and [c["record_id"] for c in mock.calls] == [KEY[1], f"{KEY[1]}.shorten"]
    assert "[max 12 words]" in mock.calls[1]["user"]
    assert result.titles[0]["core"]["institutions"]["value"][0]["role"] == "licenses and fines the city's couriers"


def test_off_vocab_members_reach_proposals_through_canonicalize(repo):
    repo.corpus_file.write_text(yaml.safe_dump({"titles": [ENTRY]}))
    draft = make_draft()
    draft["core"]["core_fantasy"] = fv(["other:quiet competence", "mastery"])
    result, _ = run(repo, {KEY: draft})
    assert result.titles[0]["core"]["core_fantasy"]["value"] == ["other:quiet competence", "mastery"]
    out = canonicalize(repo, "run_canon")
    assert out.written["title"] == ["ironvale_circuit_2021"]
    stored = read_jsonl(repo.canonical / "titles.jsonl")[0]
    assert stored["core"]["core_fantasy"]["value"] == ["other", "mastery"]
    assert stored["provenance"]["vocab_version"] == "1.5.0" and "story_engine" in stored["core"]
    assert any("quiet_competence" in p.name for p in out.proposals)


def test_a_promise_break_on_a_flop_is_always_sent_to_verify(repo):
    draft = make_draft()
    draft["core"]["outcome"] = fv("flop")
    draft["core"]["promise_break"] = fv("the promised climb stalls into a stalemate")
    result, _ = run(repo, {KEY: draft}, entry=FLOP)
    verify = json.loads((repo.candidates / "verify" / "ironvale_circuit_2021.json").read_text())["verify"]
    assert "core.promise_break" in verify
    assert result.titles[0]["core"]["promise_break"]["verification"] == "unverified"


# ---------------------------------------------------------------- VERIFY
def test_verify_checks_corrected_values_of_the_new_kinds():
    from animedex.pipeline.verify import _value_problems

    vocab, guards = get_vocab(), GuardConfig()
    good = [{"name": "the relay guild", "type": "guild_or_license", "role": "licenses couriers"}]
    assert _value_problems("core.institutions", good, vocab, guards) == []
    assert _value_problems("core.core_fantasy", ["mastery", "other:quiet competence"], vocab, guards) == []
    assert any("at most 3 items" in p for p in _value_problems("core.institutions", good * 4, vocab, guards))
    assert any("core.core_fantasy.0" in p for p in _value_problems("core.core_fantasy", ["heist"], vocab, guards))
    long = {"thesis_mc": "x", "antithesis_villain": None, "resolution": " ".join(["w"] * 21)}
    assert _value_problems("core.thematic_argument", long, vocab, guards) == [
        "core.thematic_argument.resolution: 20 words max"]
    assert _value_problems("core.institutions", [], vocab, guards) == ["corrected needs a value"]


def test_verify_brief_shows_each_kind_its_shape_and_drops_an_unsourced_promise_break():
    from animedex.pipeline.verify import Pending, _brief, apply

    entry = CorpusEntry.model_validate(FLOP)
    draft = normalize_draft(make_draft(), entry, get_vocab())
    record = {"title_id": entry.title_id, "core": draft["core"]}
    record["core"]["outcome"] = {**fv("flop"), "verification": "unverified", "source": "recall", "source_ref": None}
    record["core"]["promise_break"] = {**fv("the promised climb stalls"), "verification": "unverified",
                                       "source": "recall", "source_ref": None}
    pending = Pending(record, [], ["core.institutions", "core.promise_break", "core.outcome"])
    brief = "\n".join(_brief(entry, pending, get_vocab()))
    assert "core.institutions: [{\"name\": " in brief and "[up to 3 items, each with name (6 words or fewer)" in brief
    out = {"fields": [{"path": "core.promise_break", "status": "unresolved", "value": None, "source_url": None,
                       "note": None}], "moments": [], "outcome": None}
    stored, _, _, res = apply(pending, out, set(), prov={}, threshold=0.7, vocab=get_vocab())
    kept = stored["core"]["promise_break"]
    assert res.statuses["core.promise_break"] == "unresolved" and kept["value"] is None and kept["conf"] == 0.0


def test_verify_clears_a_promise_break_when_the_outcome_is_a_hit():
    from animedex.pipeline.verify import Pending, apply

    url = "https://reviews.example/ironvale"
    record = {"title_id": "ironvale_circuit_2021",
              "core": {"outcome": {**fv("flop"), "verification": "unverified", "source": "recall", "source_ref": None},
                       "promise_break": {**fv("the climb stalls"), "verification": "unverified", "source": "recall",
                                         "source_ref": None}}}
    out = {"fields": [{"path": "core.outcome", "status": "corrected", "value": "hit", "source_url": url, "note": None},
                      {"path": "core.promise_break", "status": "confirmed", "value": None, "source_url": url,
                       "note": None}], "moments": [], "outcome": None}
    stored, _, _, _ = apply(Pending(record, [], ["core.outcome", "core.promise_break"]), out, {url}, prov={},
                            threshold=0.7, vocab=get_vocab())
    assert stored["core"]["outcome"]["value"] == "hit" and stored["core"]["promise_break"]["value"] is None


# ---------------------------------------------------------------- P4 and census
def test_p4_requires_the_abstraction_ladder():
    from animedex.pipeline.p4 import output_problems, output_schema
    from tests.conftest import make_effect_atom

    atom = make_effect_atom()
    schema = output_schema([atom["atom_id"]], ["cost_of_advancement"])
    assert {"mechanism", "principle", "anti_pattern"} <= set(schema["properties"]["transfers"]["items"]["required"])
    base = {"source_atom_id": atom["atom_id"], "pattern": "A helper pays for power with memory, one rescue at a time",
            "bridge": ["cost_of_advancement"], "essential_conditions": ["the cost is personal"],
            "variable_details": ["the setting"], "failure_conditions": ["the cost is reversible"],
            "mechanism": "each use of power spends something the helper cannot get back",
            "principle": "When power has a personal price, make every use a choice, because the price drives drama",
            "anti_pattern": "power that costs nothing"}

    def problems(**over) -> list[str]:
        return output_problems({"transfers": [{**base, **over}]}, {atom["atom_id"]: atom}, (set(), {"Wren"}),
                               GuardConfig(), get_vocab())

    assert problems() == []
    assert any("give mechanism, principle" in p for p in problems(mechanism=None, principle=""))
    assert any("when X, do Y, because Z" in p for p in problems(principle="Make every use a choice so it hurts"))
    assert any("anti_pattern uses medium words ['anime']" in p for p in problems(anti_pattern="an anime with no cost"))
    assert any("principle names ['Wren']" in p for p in problems(
        principle="When Wren pays for power, show it, because the price drives drama"))


def test_the_census_asks_for_the_three_v18_fields():
    from animedex.pipeline.census import output_schema

    vocab = get_vocab()
    item = output_schema(vocab, ["anilist:1"])["properties"]["titles"]["items"]
    for key, path in (("set_structure", "power_combat.set_structure"), ("story_engine", "core.story_engine"),
                      ("mc_archetype", "core.mc_archetype")):
        assert key in item["required"]
        assert item["properties"][key]["enum"] == [*(v for v in vocab.enum(path) if v != "other"), None]
