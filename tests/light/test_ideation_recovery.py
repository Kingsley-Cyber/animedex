"""Actual opened Wikipedia titles survive URI encoding; unsupported pages still fail."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from animedex import cli
from tests.light.test_ideation_e2e import install_clients

ENCODED = "https://en.wikipedia.org/wiki/Example_%282026_series%29"
DECODED = "https://en.wikipedia.org/wiki/Example_(2026_series)"


def prior_answer(schema, url):
    refs = schema["properties"]["checks"]["items"]["properties"]["ref"]["enum"]
    return {"checks": [{"ref": ref, "overlap": "partial", "title": "Synthetic example",
                       "url": url, "difference": "The working story mechanism differs."} for ref in refs]}


def test_opened_wikipedia_article_matches_decoded_citation_via_public_cli(repo, monkeypatch):
    mocks = install_clients(repo, monkeypatch)
    original = mocks["ingest"].default

    def scan(system, user, schema, params):
        if params["_meta"]["pass"] == "IDEATION_PRIOR_ART":
            mocks["ingest"].urls = [ENCODED]
            return prior_answer(schema, DECODED)
        return original(system, user, schema, params)

    mocks["ingest"].default = scan
    result = CliRunner().invoke(cli.app, ["ideate", "--n", "2"])
    assert result.exit_code == 0, result.output
    record = json.loads(next((repo.quick / "_ideation").glob("*.json")).read_text())
    assert record["status"] == "complete"
    assert record["provenance"]["prior_art"]["web"]["fetched"] == [ENCODED]


def test_retry_prior_art_preserves_saved_drafts_and_comparison(repo, monkeypatch):
    mocks = install_clients(repo, monkeypatch)
    original = mocks["ingest"].default

    def unsupported(system, user, schema, params):
        if params["_meta"]["pass"] == "IDEATION_PRIOR_ART":
            return prior_answer(schema, "https://en.wikipedia.org/wiki/Unopened_example")
        return original(system, user, schema, params)

    mocks["ingest"].default = unsupported
    runner = CliRunner()
    failed = runner.invoke(cli.app, ["ideate", "--n", "2", "--compare"])
    assert failed.exit_code == 1
    run_file = next((repo.quick / "_ideation").glob("*.json"))
    before = json.loads(run_file.read_text())
    assert before["status"] == "failed" and before["stage"] == "prior_art"
    generated = len(mocks["generate"].calls)
    judged = len(mocks["check"].calls)

    def opened(system, user, schema, params):
        mocks["ingest"].urls = [ENCODED]
        return prior_answer(schema, DECODED)

    mocks["ingest"].default = opened
    resumed = runner.invoke(cli.app, ["ideate", "--resume", str(run_file)])
    assert resumed.exit_code == 0, resumed.output
    after = json.loads(run_file.read_text())
    assert after["ideas"] == before["ideas"] and after["tests"] == before["tests"]
    assert after["status"] == "complete" and after["packet_file"]
    assert len(mocks["generate"].calls) == generated and len(mocks["check"].calls) == judged
