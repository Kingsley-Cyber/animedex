"""Unsupported source rows do not become mechanisms; supported rows can seed distinct hypotheses."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from animedex import cli
from tests.light.test_ideation_e2e import install_clients


def test_partial_source_pool_keeps_only_opened_records_and_logs_rejections(repo, monkeypatch):
    mocks = install_clients(repo, monkeypatch)
    scan_original = mocks["ingest"].default
    generate_original = mocks["generate"].default

    def scan(system, user, schema, params):
        out = scan_original(system, user, schema, params)
        if params["_meta"]["pass"] == "IDEATION_MATERIALS":
            out["materials"][1]["source_url"] = "https://research.example/never-opened"
        return out

    def generate(system, user, schema, params):
        if params["_meta"]["pass"] == "IDEATION_HYPOTHESES":
            ids = schema["properties"]["hypotheses"]["items"]["properties"]["material_ids"]["items"]["enum"]
            return {"hypotheses": [{"surprise": f"Surprise {i}", "claim": f"Causal transformation {i}",
                "forced_choice": "Choose who carries the delay.", "supporting_question": "Who must wait?",
                "falsifying_question": "Can the cost disappear?", "material_ids": ids} for i in (1, 2)]}
        return generate_original(system, user, schema, params)

    mocks["ingest"].default = scan
    mocks["generate"].default = generate
    result = CliRunner().invoke(cli.app, ["ideate", "--n", "2"])
    assert result.exit_code == 0, result.output
    record = json.loads(next((repo.quick / "_ideation").glob("*.json")).read_text())
    assert len(record["materials"]) == 1 and len(record["ideas"]) == 2
    assert len(record["rejected_materials"]) == 1
    assert "opened" in record["rejected_materials"][0]["problems"][0]
    assert len(list((repo.notes / "_materials").glob("*.json"))) == 1
