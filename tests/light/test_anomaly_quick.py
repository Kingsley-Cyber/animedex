"""The public quick command keeps an anomaly attached through research, generation, check, and report."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from animedex import cli
from animedex.store.runlog import RunLog
from tests.light.test_ingest import fake_numbers, fake_resolve
from tests.light.test_quick import card, clients_for, setup, verdict

OBSERVATION = "I expected a stronger hero to remove tension, but each win costs an ally's trust"
SHOWS = ("ironvale_circuit_2021", "lantern_debt_2019", "copper_vow_2018")


def test_quick_anomaly_explains_or_drops_cards_via_cli(repo, monkeypatch):
    setup(repo, with_notes=SHOWS)
    research = {"picks": [
        {"show": "Ironvale Circuit", "year": 2021, "in_index": True,
         "index_slug": SHOWS[0], "why": "strong hero"},
        {"show": "Lantern Debt", "year": 2019, "in_index": True,
         "index_slug": SHOWS[1], "why": "trust cost"},
        {"show": "Copper Vow", "year": 2018, "in_index": True,
         "index_slug": SHOWS[2], "why": "victory cost"},
    ], "notes": []}
    cards = [card(1, SHOWS[0]), card(2, SHOWS[1])]
    cards[0]["hypothesis"] = "Winning transfers the battle's risk to a teammate."
    cards[1]["hypothesis"] = "The hero needs a new costume."
    checks = [verdict("C1", 3, closest=SHOWS[0]), verdict("C2", 3, closest=SHOWS[1])]
    checks[0].update(explains_anomaly=True, explanation_reason="The ally bears the cost of each win.")
    checks[1].update(explains_anomaly=False, explanation_reason="A costume does not explain lost trust.")
    clients, mocks = clients_for(repo, research, cards, checks)
    mocks["generate"].default = lambda system, user, schema, params: {"seed_kind": "anomaly", "cards": cards}

    monkeypatch.setattr(cli, "_paths", lambda: repo)
    monkeypatch.setattr(cli, "_catalog", lambda paths: (fake_resolve, fake_numbers))
    monkeypatch.setattr(cli, "_clients", lambda paths, settings, keys, calls_per_run: (
        clients, RunLog(repo.raw_runs, "cli_anomaly")))
    runner = CliRunner()
    result = runner.invoke(cli.app, ["quick", "--anomaly", OBSERVATION, "--n", "2"])
    assert result.exit_code == 0, result.output

    for slot in ("ingest", "generate", "check"):
        assert OBSERVATION in mocks[slot].calls[0]["user"]
    assert "hypothesis: Winning transfers" in mocks["check"].calls[0]["user"]
    record = json.loads(next(repo.quick.glob("*.json")).read_text())
    assert record["input_kind"] == "anomaly" and record["seed_kind"] == "anomaly"
    assert record["survivors"] == ["C1"]
    assert "C2: hypothesis does not explain" in record["dropped"][0]
    report = next(repo.quick.glob("*.md")).read_text()
    assert "Anomaly (user observation, unverified)" in report
    assert "**Hypothesis.** Winning transfers" in report
    assert "**Anomaly check.** Explains" in report
    assert "C2: hypothesis does not explain" in report

    invalid = runner.invoke(cli.app, ["quick", "--seed", "a fight", "--anomaly", OBSERVATION])
    assert invalid.exit_code == 2
    assert "give either --seed" in invalid.output
