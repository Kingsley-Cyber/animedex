"""AC-01: pydantic models implement every 04 contract; JSON Schemas generate cleanly."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from animedex.cli import app
from animedex.models import RECORD_TYPES
from animedex.paths import Paths
from animedex.schemas import schema_documents, stale_schemas
from tests.conftest import REPO, synthetic_state

pytestmark = pytest.mark.contract

CONTRACTS_04 = {"title", "moment", "outcome", "mechanism", "proof", "check", "transfer", "episode", "link",
                "pattern", "coverage", "idea", "archive", "prior_art", "census",  # v1.6 adds the last two
                "character"}  # v1.8


def test_every_04_record_type_has_a_model():
    assert set(RECORD_TYPES) == CONTRACTS_04
    for rt in RECORD_TYPES.values():
        schema = rt.model.model_json_schema(by_alias=True)
        assert "provenance" in schema["properties"], rt.name
        assert schema.get("additionalProperties") is False, rt.name


def test_schema_documents_are_valid_json_and_carry_vocab_enums():
    docs = schema_documents()
    assert len(docs) == len(RECORD_TYPES) + 1
    for text in docs.values():
        json.loads(text)
    title = json.loads(docs["title.schema.json"])
    gate_value = title["$defs"]["PowerCombatBlock"]["properties"]["gate"]
    ref = gate_value["$ref"].split("/")[-1]
    assert "system_granted" in title["$defs"][ref]["properties"]["value"]["enum"]


def test_committed_schemas_match_models():
    assert stale_schemas(Paths(REPO)) == [], "run `make schemas`"


def test_make_schemas_writes_files(repo):
    for f in repo.schemas.glob("*.json"):
        f.unlink()
    result = CliRunner().invoke(app, ["schemas"])
    assert result.exit_code == 0, result.output
    assert stale_schemas(repo) == []


def test_synthetic_records_roundtrip_through_every_model():
    for record_type, records in synthetic_state().items():
        model = RECORD_TYPES[record_type].model
        for r in records:
            once = model.model_validate(r).to_record()
            assert model.model_validate(once).to_record() == once
