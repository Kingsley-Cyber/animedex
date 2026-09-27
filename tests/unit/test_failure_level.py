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
                                failure_level_source=None, failure_reason=None))
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

