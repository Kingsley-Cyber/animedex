"""Scene-test corrections cannot silently change the drafts or the blinded packet."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from animedex import cli
from tests.light.test_ideation_e2e import install_clients


def test_recheck_preserves_drafts_packet_and_previous_verdicts(repo, monkeypatch):
    mocks = install_clients(repo, monkeypatch)
    runner = CliRunner()
    first = runner.invoke(cli.app, ["ideate", "--n", "2", "--compare"])
    assert first.exit_code == 0, first.output
    path = next((repo.quick / "_ideation").glob("*.json"))
    before = json.loads(path.read_text())
    packet_before = (repo.root / before["packet_file"]).read_text()
    generated = len(mocks["generate"].calls)
    sources = len(mocks["ingest"].calls)
    original = mocks["check"].default

    def corrected(system, user, schema, params):
        out = original(system, user, schema, params)
        for item in out["tests"]:
            item["reason"] = "Corrected critique of the same visible draft."
        return out

    mocks["check"].default = corrected
    result = runner.invoke(cli.app, ["ideate", "--recheck", str(path)])
    assert result.exit_code == 0, result.output
    after = json.loads(path.read_text())
    assert after["ideas"] == before["ideas"]
    assert after["test_history"][0]["tests"] == before["tests"]
    assert after["tests"] != before["tests"]
    assert (repo.root / after["packet_file"]).read_text() == packet_before
    assert len(mocks["generate"].calls) == generated and len(mocks["ingest"].calls) == sources
