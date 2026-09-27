"""v1.3: outcome failure_level (premise | execution | external | unknown) and the 1.3.0 migration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animedex.models import Outcome
from tests.conftest import synthetic_state

pytestmark = pytest.mark.unit


def base(**over):
    o = synthetic_state()["outcome"][0]
    o.update(over)
    return o


def test_hits_carry_no_level_and_non_hits_need_one():
    Outcome.model_validate(base(label="hit", failure_level=None, failure_evidence=None, failure_evidence_ref=None,
                                failure_level_source=None, failure_reason=None, failure_patterns=[]))
    with pytest.raises(ValidationError, match="hit carries failure_level null"):
        Outcome.model_validate(base(label="hit"))
    with pytest.raises(ValidationError, match="needs failure_level"):
        Outcome.model_validate(base(failure_level=None))


def test_web_sourced_levels_need_evidence_but_unknown_and_owner_do_not():
    with pytest.raises(ValidationError, match="needs failure_evidence"):
        Outcome.model_validate(base(failure_evidence=None))
    Outcome.model_validate(base(failure_level="unknown", failure_evidence=None, failure_evidence_ref=None))
    Outcome.model_validate(base(failure_level="premise", failure_level_source="owner", failure_evidence=None,
                                failure_evidence_ref=None))


def test_migration_defaults_old_non_hit_outcomes_to_unknown(repo):
    import json

    from animedex.migrations import migrate_1_3_0

    state = synthetic_state()
    old = {k: v for k, v in state["outcome"][0].items() if not k.startswith("failure_level")
           and k not in ("failure_evidence", "failure_evidence_ref")}
    title = next(t for t in state["title"] if t["title_id"] == old["title_id"])
    (repo.canonical / "titles.jsonl").write_text(json.dumps(title, sort_keys=True) + "\n")
    (repo.canonical / "outcomes.jsonl").write_text(json.dumps(old, sort_keys=True) + "\n")
    assert migrate_1_3_0(repo, "run_m") == [old["title_id"]]
    [row] = [json.loads(line) for line in (repo.canonical / "outcomes.jsonl").read_text().splitlines()]
    assert (row["failure_level"], row["failure_level_source"]) == ("unknown", "migration")
    assert migrate_1_3_0(repo, "run_m2") == []  # idempotent


def test_migration_also_fixes_waiting_candidates(repo):
    import json

    from animedex.migrations import migrate_1_3_0

    old = {k: v for k, v in synthetic_state()["outcome"][0].items() if not k.startswith("failure_level")
           and k not in ("failure_evidence", "failure_evidence_ref")}
    (repo.candidates / "outcome").mkdir(parents=True, exist_ok=True)
    (repo.candidates / "outcome" / "glass_meridian_2016.jsonl").write_text(json.dumps(old) + "\n")
    assert migrate_1_3_0(repo, "run_m") == ["glass_meridian_2016"]
    [row] = [json.loads(x) for x in (repo.candidates / "outcome" / "glass_meridian_2016.jsonl").read_text().splitlines()]
    assert row["failure_level"] == "unknown" and row["failure_level_source"] == "migration"



def test_resolved_proposals_replace_only_a_still_open_other(repo):
    """1.5.1 (D-031): accepted or merged proposals land where the title still holds `other`."""
    import json

    from animedex.migrations import migrate_1_5_1

    title = synthetic_state()["title"][0]
    tid = title["title_id"]
    title["power_combat"]["set_scaffold"]["value"] = "other"
    title["power_combat"]["power_up_mode"]["value"] = ["temporary_boost", "other"]
    title["core"]["mc_archetype"]["value"] = "prodigy"  # a later run already answered: left alone
    (repo.canonical / "titles.jsonl").write_text(json.dumps(title, sort_keys=True) + "\n")

    def proposal(field, proposed, status, resolution, path):
        folder = repo.proposals / field
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{proposed}.json").write_text(json.dumps({
            "field": field, "proposed": proposed, "status": status, "resolution": resolution,
            "examples": [{"record_type": "title", "record_id": tid, "path": path, "run_id": "run_x"}]}))

    proposal("power_combat.set_scaffold", "game classes", "accepted", "game_system", "power_combat.set_scaffold.value")
    proposal("power_combat.power_up_mode", "a vow", "merged", "temporary_boost", "power_combat.power_up_mode.value.1")
    proposal("core.mc_archetype", "wild child", "merged", "underdog", "core.mc_archetype.value")
    proposal("core.setting_type", "an island", "kept_other", None, "core.setting_type.value")
    assert migrate_1_5_1(repo, "run_m") == [tid]
    [row] = [json.loads(line) for line in (repo.canonical / "titles.jsonl").read_text().splitlines()]
    assert row["power_combat"]["set_scaffold"]["value"] == "game_system"
    assert row["power_combat"]["power_up_mode"]["value"] == ["temporary_boost"]  # already listed: other dropped
    assert row["core"]["mc_archetype"]["value"] == "prodigy"
    assert migrate_1_5_1(repo, "run_m2") == []  # idempotent
