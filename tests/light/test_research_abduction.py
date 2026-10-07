"""The migrated IDE path reaches a sourced, gated frame through the public CLI."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from animedex import cli
from animedex.light.premises import retrieve_premises
from animedex.store.runlog import RunLog
from tests.light.test_abduction import SHOWS, SOURCE, scan_answer
from tests.light.test_ingest import fake_numbers, fake_resolve
from tests.light.test_quick import card, clients_for, setup, verdict


def test_research_path_preserves_human_frame_gate_and_old_card_contract(repo, monkeypatch):
    setup(repo, with_notes=SHOWS)
    scan_clients, scan_mocks = clients_for(repo, {}, [], [])
    scan_mocks["ingest"].urls = [SOURCE]
    scan_mocks["ingest"].default = lambda system, user, schema, params: scan_answer()

    research_clients, research_mocks = clients_for(repo, {}, [], [])

    def generate(system, user, schema, params):
        pass_ = params["_meta"]["pass"]
        if pass_.startswith("REASON_"):
            note_id = schema["properties"]["steps"]["items"]["properties"]["premise_ids"]["items"]["enum"][0]
            return {"hypothesis": f"{pass_} explanation of trust costs",
                    "steps": [{"claim": "Trust can transfer danger after a win.", "premise_ids": [note_id]}]}
        if pass_ == "RESEARCH_FRAMES":
            return {"frames": [
                {"frame_sentence": "Each win transfers danger to the ally who trusted the hero most.",
                 "explanation": "Allies withdraw because trusting the hero incurs the cost.",
                 "new_concept": "trust transfers danger", "lens_refs": ["abductive", "deductive"]},
                {"frame_sentence": "A famous robot hero joins a familiar tournament.",
                 "explanation": "It combines existing elements.", "new_concept": "none",
                 "lens_refs": ["inductive"]},
            ]}
        if pass_ == "SUSPEND":
            return {"comparisons": [{"left": "F1", "right": "F2", "relation": "tension",
                                     "reason": "One changes a causal rule; the other borrows motifs."}],
                    "syntheses": [{"frame_sentence": "A public victory creates a private obligation for every witness.",
                                    "explanation": "Witnesses stop celebrating because the win binds them.",
                                    "new_concept": "witness obligation", "parents": ["F1", "F2"]}]}
        if pass_ == "ADAPT_FRAMES":
            return {"frames": [{"frame_sentence": "A champion's victories erase allies' memories of their trust.",
                                "explanation": "Allies withdraw because the bond that made them follow disappears.",
                                "new_concept": "victory erases trust", "lens_refs": ["abductive", "inductive"]}]}
        raise AssertionError(pass_)

    def gate(system, user, schema, params):
        refs = schema["properties"]["frames"]["items"]["properties"]["ref"]["enum"]
        examples = [{"slug": slug, "why_not": "Its victories do not transfer trust costs."} for slug in SHOWS]
        return {"frames": [{"ref": ref, "explains_gap": ref != "F2", "parent_independent": ref != "F2",
                            "fusion": ref == "F2", "anti_examples_valid": ref != "F2",
                            "anti_examples": examples, "evidence_grounded": True,
                            "reasoning_consistent": True,
                            "reason": "Borrowed motifs" if ref == "F2" else "A distinct causal rule"}
                           for ref in refs]}

    research_mocks["generate"].default = generate
    research_mocks["check"].default = gate
    idea = card(1, SHOWS[0])
    checked = verdict("C1", 3, closest=SHOWS[0])
    checked.update(keeps_frame=True, frame_reason="The trust cost remains central.")
    quick_clients, quick_mocks = clients_for(repo, {}, [idea], [checked])
    quick_mocks["generate"].default = lambda system, user, schema, params: {
        "seed_kind": "concept", "cards": [idea]}

    def clients(paths, settings, keys, calls_per_run=None):
        if keys == ("ingest",):
            return scan_clients, RunLog(repo.raw_runs, "scan_research")
        if keys == ("generate", "check"):
            return research_clients, RunLog(repo.raw_runs, "abduct_research")
        return quick_clients, RunLog(repo.raw_runs, "quick_research")

    monkeypatch.setattr(cli, "_paths", lambda: repo)
    monkeypatch.setattr(cli, "_clients", clients)
    monkeypatch.setattr(cli, "_catalog", lambda paths: (fake_resolve, fake_numbers))
    runner = CliRunner()
    scanned = runner.invoke(cli.app, ["scan"])
    assert scanned.exit_code == 0, scanned.output
    scan_file = next((repo.notes / "_scans").glob("*.json"))
    abducted = runner.invoke(cli.app, ["abduct", "--research", "--scan", str(scan_file.relative_to(repo.root)),
                                      "--gap", "G1", "--n", "2"])
    assert abducted.exit_code == 0, abducted.output
    frames_file = next((repo.quick / "_frames").glob("*.json"))
    record = json.loads(frames_file.read_text())
    assert record["workflow"] == "research_v1"
    assert record["accepted_ids"] == ["F1", "S1", "R1"]
    assert set(record["reasoning_graphs"]) == {"abductive", "deductive", "inductive"}
    assert record["premise_retrieval"]["method"] == "metropolis_hastings"
    assert set(record["premise_retrieval"]["selected_note_ids"]) <= set(SHOWS)
    assert record["controller"]["revised_from"] == {"R1": "F2"}
    assert any(edge == {"from": "frame:F2", "to": "frame:R1", "relation": "revises"}
               for edge in record["state_graph"]["edges"])
    assert {call["pass"] for call in research_mocks["generate"].calls} == {
        "REASON_ABDUCTIVE", "REASON_DEDUCTIVE", "REASON_INDUCTIVE", "RESEARCH_FRAMES",
        "SUSPEND", "ADAPT_FRAMES"}
    assert len(research_mocks["check"].calls) == 2

    built = runner.invoke(cli.app, ["quick", "--frames-file", str(frames_file.relative_to(repo.root)),
                                   "--frame-id", "F1", "--shows", "Ironvale Circuit", "--n", "1"])
    assert built.exit_code == 0, built.output
    refused = runner.invoke(cli.app, ["quick", "--frames-file", str(frames_file.relative_to(repo.root)),
                                     "--frame-id", "F2"])
    assert refused.exit_code == 1
    assert len(quick_mocks["generate"].calls) == 1


def test_premise_chain_is_reproducible_and_only_visits_indexed_notes():
    notes = {"a": {"premise": "victory costs trust", "engine": {}, "elements": []},
             "b": {"premise": "victory gains status", "engine": {}, "elements": []},
             "c": {"premise": "loss costs memory", "engine": {}, "elements": []}}
    gap = {"anomaly": "victory costs trust", "expected_pattern": "victory builds trust",
           "observation": "allies leave after victory"}
    first = retrieve_premises(gap, notes, count=2, seed="sourced-gap")
    assert first == retrieve_premises(gap, notes, count=2, seed="sourced-gap")
    assert set(first["selected_note_ids"]) <= set(notes)
    assert {step["state"] for step in first["chain"]} <= set(notes)
