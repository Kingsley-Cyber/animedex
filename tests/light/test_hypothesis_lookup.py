"""The IDE hypothesis path and cross-record lookup are reachable from the product CLI."""

from __future__ import annotations

import csv
import json

from typer.testing import CliRunner

from animedex import cli
from animedex.store.runlog import RunLog
from tests.light.test_abduction import SHOWS, SOURCE, scan_answer
from tests.light.test_ingest import fake_numbers, fake_resolve
from tests.light.test_quick import card, clients_for, setup, verdict


def test_hypothesis_challenge_and_id_lookup_follow_a_card_to_its_sources(repo, monkeypatch):
    setup(repo, with_notes=SHOWS)
    scan_clients, scan_mocks = clients_for(repo, {}, [], [])
    scan_mocks["ingest"].urls = [SOURCE]
    scan_mocks["ingest"].default = lambda system, user, schema, params: scan_answer()
    research_clients, research_mocks = clients_for(repo, {}, [], [])

    def generate(system, user, schema, params):
        pass_ = params["_meta"]["pass"]
        note_id = SHOWS[0]
        if pass_.startswith("REASON_"):
            return {"hypothesis": f"{pass_} account of lost trust",
                    "steps": [{"claim": "Trust carries a cost after victory.", "premise_ids": [note_id]}]}
        if pass_ == "HYPOTHESIS_CHALLENGE":
            return {"hypotheses": [
                {"lens": lens, "claim": f"{lens} cause of lost trust",
                 "supporting_question": f"What would support the {lens} cause?",
                 "falsifying_question": f"What would disprove the {lens} cause?",
                 "premise_ids": [note_id]}
                for lens in ("abductive", "deductive", "inductive")]}
        if pass_ == "RESEARCH_FRAMES":
            return {"frames": [
                {"frame_sentence": "Victories pass danger to the allies who trusted the hero.",
                 "explanation": "Trust is the route by which danger moves.",
                 "new_concept": "transferred danger", "lens_refs": ["abductive"], "hypothesis_refs": ["H1"]},
                {"frame_sentence": "Every public win erases an ally's memory of the hero.",
                 "explanation": "Victories make allies forget their bond.",
                 "new_concept": "victory costs memory", "lens_refs": ["inductive"], "hypothesis_refs": ["H3"]}]}
        if pass_ == "SUSPEND":
            return {"comparisons": [{"left": "F1", "right": "F2", "relation": "independent",
                                     "reason": "The mechanisms differ."}], "syntheses": []}
        raise AssertionError(pass_)

    def gate(system, user, schema, params):
        assert "falsifying_question" in user
        refs = schema["properties"]["frames"]["items"]["properties"]["ref"]["enum"]
        examples = [{"slug": slug, "why_not": "This show does not transfer danger through trust."} for slug in SHOWS]
        return {"frames": [{"ref": ref, "explains_gap": True, "parent_independent": True,
                            "fusion": False, "anti_examples_valid": True, "anti_examples": examples,
                            "evidence_grounded": True, "reasoning_consistent": True,
                            "reason": "A distinct causal rule."} for ref in refs]}

    research_mocks["generate"].default = generate
    research_mocks["check"].default = gate
    idea = card(1, SHOWS[0])
    checked = verdict("C1", 3, closest=SHOWS[0])
    checked.update(keeps_frame=True, frame_reason="The trust cost stays central.")
    quick_clients, quick_mocks = clients_for(repo, {}, [idea], [checked])
    quick_mocks["generate"].default = lambda system, user, schema, params: {
        "seed_kind": "concept", "cards": [idea]}

    def clients(paths, settings, keys, calls_per_run=None):
        if keys == ("ingest",):
            return scan_clients, RunLog(repo.raw_runs, "scan_hypothesis")
        if keys == ("generate", "check"):
            return research_clients, RunLog(repo.raw_runs, "abduct_hypothesis")
        return quick_clients, RunLog(repo.raw_runs, "quick_hypothesis")

    monkeypatch.setattr(cli, "_paths", lambda: repo)
    monkeypatch.setattr(cli, "_clients", clients)
    monkeypatch.setattr(cli, "_catalog", lambda paths: (fake_resolve, fake_numbers))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["scan"]).exit_code == 0
    scan_file = next((repo.notes / "_scans").glob("*.json"))
    abducted = runner.invoke(cli.app, ["abduct", "--research", "--hypothesis-check", "--scan",
                                      str(scan_file.relative_to(repo.root)), "--gap", "G1", "--n", "2"])
    assert abducted.exit_code == 0, abducted.output
    frames_file = next((repo.quick / "_frames").glob("*.json"))
    frames = json.loads(frames_file.read_text())
    assert set(frames["hypotheses"]) == {"H1", "H2", "H3"}
    assert frames["hypotheses"]["H1"]["status"] == "untested"
    assert frames["frames"]["F1"]["hypothesis_refs"] == ["H1"]
    assert research_mocks["generate"].calls[3]["pass"] == "HYPOTHESIS_CHALLENGE"

    built = runner.invoke(cli.app, ["quick", "--frames-file", str(frames_file.relative_to(repo.root)),
                                   "--frame-id", "F1", "--shows", "Ironvale Circuit", "--n", "1"])
    assert built.exit_code == 0, built.output
    exported = runner.invoke(cli.app, ["export"])
    assert exported.exit_code == 0, exported.output
    with (repo.exports / "ideation_nodes.csv").open(newline="", encoding="utf-8") as file:
        nodes = list(csv.DictReader(file))
    with (repo.exports / "ideation_edges.csv").open(newline="", encoding="utf-8") as file:
        edges = list(csv.DictReader(file))
    card_id = next(node["id"] for node in nodes if node["kind"] == "card")
    frame_id = f"frame:{frames_file.stem}:F1"
    hypothesis_id = f"hypothesis:{frames_file.stem}:H1"
    assert {"from_id": hypothesis_id, "to_id": frame_id, "relation": "informs"} in edges
    assert any(edge["from_id"] == frame_id and edge["to_id"] == card_id for edge in edges)
    found = runner.invoke(cli.app, ["lookup", "--id", card_id])
    assert found.exit_code == 0, found.output
    lineage = {node["id"] for node in json.loads(found.output)["lineage"]}
    assert hypothesis_id in lineage
    assert f"gap:{scan_file.stem}:G1" in lineage
    assert f"note:{SHOWS[0]}" in lineage
