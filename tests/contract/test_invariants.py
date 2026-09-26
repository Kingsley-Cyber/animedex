"""04 invariants via `make validate` (AC-04 coverage lives here too)."""

from __future__ import annotations

import copy

import pytest
import yaml
from typer.testing import CliRunner

from animedex.cli import app
from animedex.integrity import integrity_errors
from animedex.ontology import get_vocab
from animedex.store.jsonl import dumps_jsonl
from animedex.validate import validate_repo
from tests.conftest import make_moment, make_transfer, synthetic_state, write_state

pytestmark = pytest.mark.contract


def test_validate_passes_on_synthetic_state(repo):
    write_state(repo, synthetic_state())
    report = validate_repo(repo)
    assert report.ok, report.errors
    assert (repo.reports / "cq_coverage.md").is_file()


def test_make_validate_fails_on_an_orphan_field(repo):
    data = yaml.safe_load(repo.cq_file.read_text())
    for q in data["questions"]:
        q["requires"] = [r for r in q["requires"] if r != "film.closure"]
    repo.cq_file.write_text(yaml.safe_dump(data, sort_keys=False))
    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "orphan lens_field film.closure" in result.output


def test_validate_catches_unsorted_duplicate_and_hand_edited_files(repo):
    write_state(repo, synthetic_state())
    path = repo.canonical / "titles.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[1], lines[0], lines[0], *lines[2:]]) + "\n")
    errors = "\n".join(validate_repo(repo).errors)
    assert "not sorted" in errors and "duplicate ids" in errors


def test_hand_edit_formatting_is_flagged(repo):
    write_state(repo, synthetic_state())
    path = repo.canonical / "moments.jsonl"
    path.write_text(path.read_text().replace('","', '", "', 1))
    assert any("not in canonical form" in w for w in validate_repo(repo).warnings)


def test_effect_atom_proof_needs_explanation_test():
    state = synthetic_state()
    state["proof"][0]["explanation_test"] = None
    assert any("explanation_test" in e for e in integrity_errors(state, get_vocab()))


def test_transfer_pattern_name_leaks_are_caught():
    state = synthetic_state()
    leaky = copy.deepcopy(state)
    leaky["transfer"] = [make_transfer(pattern="Like in Ironvale Circuit, the lead hides a private meter from others.")]
    assert any("contains names" in e for e in integrity_errors(leaky, get_vocab()))
    leaky["moment"] = [make_moment(description="The courier Marisol reroutes the grid to save a rival crew.")]
    leaky["transfer"] = [make_transfer(pattern="The lead, like Marisol, hides a private meter from everyone else.")]
    assert any("Marisol" in e for e in integrity_errors(leaky, get_vocab()))
    assert not integrity_errors(state, get_vocab())


def test_episode_outside_scope_and_unknown_refs_fail():
    state = synthetic_state()
    state["episode"] = [{
        "episode_id": "ironvale_circuit_2021.s03e01", "title_id": "ironvale_circuit_2021",
        "locator": {"season": 3, "episode": 1, "episode_title": "", "numbering": "broadcast"},
        "selection_reason": "pilot", "summary": "s", "function": "setup", "end_hook": "none",
        "info_shift": {"audience_learns": "", "characters_learn": "", "gap_change": "none"},
        "moment_refs": ["ironvale_circuit_2021.mo.99"], "atom_support": [], "source": "web",
        "source_ref": "https://example.org", "verification": "web_confirmed", "provenance": {}}]
    errors = "\n".join(integrity_errors(state, get_vocab()))
    assert "season outside" in errors and "unknown moment" in errors


def test_ideas_may_only_use_known_transfer_atoms():
    state = synthetic_state()
    state["idea"][0]["atoms_used"] = ["ironvale_circuit_2021.t.009"]
    assert any("unknown transfer" in e for e in integrity_errors(state, get_vocab()))


def test_corrupt_canonical_line_is_reported(repo):
    write_state(repo, synthetic_state())
    (repo.canonical / "links.jsonl").write_text(dumps_jsonl([]) + "{broken\n")
    assert any("invalid JSON" in e for e in validate_repo(repo).errors)
