"""The public scan -> frame gate -> selected-frame quick path uses fetched discourse evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from animedex import cli
from animedex.light.abduction import AbductionError, run_scan
from animedex.store.runlog import RunLog
from tests.light.test_ingest import fake_numbers, fake_resolve
from tests.light.test_quick import card, clients_for, setup, verdict

SOURCE = "https://anime.example/reviews/current-season"
SHOWS = ("ironvale_circuit_2021", "lantern_debt_2019", "copper_vow_2018")


def scan_answer():
    return {"gaps": [{"genre": "fantasy action", "expected_pattern": "victory builds trust",
                      "observation": "reviewers describe wins that isolate the hero",
                      "anomaly": "Why can winning make allies less willing to follow?",
                      "source_url": SOURCE, "source_date": datetime.now(UTC).date().isoformat()}]}


def test_public_workflow_gates_frames_before_card_scoring(repo, monkeypatch):
    setup(repo, with_notes=SHOWS)
    scan_clients, scan_mocks = clients_for(repo, {}, [], [])
    scan_mocks["ingest"].urls = [SOURCE]
    scan_mocks["ingest"].default = lambda system, user, schema, params: scan_answer()

    candidates = [
        {"frame_sentence": "Each victory transfers danger to the ally who trusted the hero most.",
         "explanation": "Allies withdraw because trust makes them bear the cost.",
         "new_concept": "trust transfers danger"},
        {"frame_sentence": "A familiar hero pilots a familiar robot in a familiar tournament.",
         "explanation": "It borrows recognizable parts instead of explaining the reaction.",
         "new_concept": "none"},
    ]
    examples = [{"slug": slug, "why_not": "Its wins do not transfer danger through trust."} for slug in SHOWS]
    gates = [
        {"ref": "F1", "explains_gap": True, "parent_independent": True, "fusion": False,
         "anti_examples_valid": True, "anti_examples": examples, "reason": "The cost follows trust."},
        {"ref": "F2", "explains_gap": False, "parent_independent": False, "fusion": True,
         "anti_examples_valid": False, "anti_examples": examples, "reason": "Only familiar parts are combined."},
    ]
    abduct_clients, abduct_mocks = clients_for(repo, {}, [], [])
    abduct_mocks["generate"].default = lambda system, user, schema, params: {"frames": candidates}
    abduct_mocks["check"].default = lambda system, user, schema, params: {"frames": gates}

    idea = card(1, SHOWS[0])
    check = verdict("C1", 3, closest=SHOWS[0])
    check.update(keeps_frame=True, frame_reason="The ally still bears the victory cost.")
    quick_clients, quick_mocks = clients_for(repo, {}, [idea], [check])
    quick_mocks["generate"].default = lambda system, user, schema, params: {
        "seed_kind": "concept", "cards": [idea]}

    def clients(paths, settings, keys, calls_per_run=None):
        if keys == ("ingest",):
            return scan_clients, RunLog(repo.raw_runs, "scan_run")
        if keys == ("generate", "check"):
            return abduct_clients, RunLog(repo.raw_runs, "abduct_run")
        return quick_clients, RunLog(repo.raw_runs, "quick_run")

    monkeypatch.setattr(cli, "_paths", lambda: repo)
    monkeypatch.setattr(cli, "_clients", clients)
    monkeypatch.setattr(cli, "_catalog", lambda paths: (fake_resolve, fake_numbers))
    runner = CliRunner()

    scanned = runner.invoke(cli.app, ["scan"])
    assert scanned.exit_code == 0, scanned.output
    scan_file = next((repo.notes / "_scans").glob("*.json"))
    scan_record = json.loads(scan_file.read_text())
    assert scan_record["web"]["fetched"] == [SOURCE]
    assert scan_record["gaps"][0]["id"] == "G1"
    assert scan_mocks["ingest"].calls[0]["pass"] == "ANOMALY_SCAN"

    abducted = runner.invoke(cli.app, ["abduct", "--scan", str(scan_file.relative_to(repo.root)),
                                      "--gap", "G1", "--n", "2"])
    assert abducted.exit_code == 0, abducted.output
    frames_file = next((repo.quick / "_frames").glob("*.json"))
    frames_record = json.loads(frames_file.read_text())
    assert frames_record["accepted_ids"] == ["F1"]
    assert abduct_mocks["generate"].calls[0]["pass"] == "ABDUCT"
    assert abduct_mocks["check"].calls[0]["pass"] == "FRAME_GATE"
    assert "score" not in frames_record["frames"]["F1"]["gate"]

    built = runner.invoke(cli.app, ["quick", "--frames-file", str(frames_file.relative_to(repo.root)),
                                   "--frame-id", "F1", "--shows", "Ironvale Circuit", "--n", "1"])
    assert built.exit_code == 0, built.output
    quick_record = json.loads(next(repo.quick.glob("*.json")).read_text())
    assert quick_record["source_frame"]["id"] == "F1"
    assert quick_record["survivors"] == ["C1"]
    assert "selected_frame:" in quick_mocks["generate"].calls[0]["user"]
    assert "selected_frame:" in quick_mocks["check"].calls[0]["user"]

    refused = runner.invoke(cli.app, ["quick", "--frames-file", str(frames_file.relative_to(repo.root)),
                                     "--frame-id", "F2"])
    assert refused.exit_code == 1
    assert "did not pass the frame gate" in refused.output
    assert len(quick_mocks["generate"].calls) == 1


def test_scan_rejects_a_gap_without_a_fetched_source(repo):
    clients, mocks = clients_for(repo, {}, [], [])
    mocks["ingest"].urls = ["https://anime.example/other-page"]
    mocks["ingest"].default = lambda system, user, schema, params: scan_answer()
    with pytest.raises(AbductionError, match="fetched"):
        run_scan(repo, cli.load_settings(repo), client=clients["ingest"], run_id="unfetched")
    assert not list((repo.notes / "_scans").glob("*.json"))
