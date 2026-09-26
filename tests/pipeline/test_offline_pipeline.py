"""AC-08: every implemented stage runs offline on the mock provider (no network at all).

M1's implemented stages: the model-call path (LLMClient + mock fixtures + repair + quarantine),
CANONICALIZE, BUILD, and VALIDATE. Stage commands built later exit 2 and name their milestone.
"""

from __future__ import annotations

import json
import socket

import pytest
from typer.testing import CliRunner

from animedex import SCHEMA_VERSION
from animedex.cli import app
from animedex.config import ModelSpec
from animedex.models import title_profile_model
from animedex.pipeline import STAGE_MILESTONE
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache, upstream_hash
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.store.quarantine import quarantine
from animedex.store.runlog import RunLog
from tests.conftest import FIXTURES

pytestmark = pytest.mark.pipeline


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network access attempted in an offline test")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def mock_p1_pass(paths, title_ids):
    """A stand-in P1 pass: prompt -> mock -> validated profile -> candidates (quarantine on failure)."""
    model = title_profile_model()
    client = LLMClient(provider=MockProvider(fixtures_dir=FIXTURES), provider_name="mock",
                       spec=ModelSpec(provider="mock", model="m"), prompt_version="0.0.0-test",
                       schema_version=SCHEMA_VERSION, vocab_version="1.2.0",
                       cache=ResponseCache(paths.cache), runlog=RunLog(paths.raw_runs, "run_offline"))
    schema = model.model_json_schema(by_alias=True)
    good = []
    for tid in title_ids:
        ctx = CallContext(pass_="P1", record_id=tid, upstream=upstream_hash([{"title_id": tid}]), title_id=tid)
        try:
            data, _ = client.complete("P1 system prompt (synthetic)", f"Profile {tid}", schema, ctx=ctx,
                                      validate=model.model_validate)
            good.append(data)
        except InvalidOutput as exc:
            quarantine(paths.quarantine, "P1", "title", tid, exc.raw, exc.errors)
    folder = paths.candidates / "title"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p1_run_offline.jsonl").write_text(dumps_jsonl(good))
    return good


def test_committed_fixtures_are_valid_or_deliberately_broken():
    model = title_profile_model()
    model.model_validate(json.loads((FIXTURES / "P1" / "ironvale_circuit_2021.json").read_text()))
    model.model_validate(json.loads((FIXTURES / "P1" / "lantern_debt_2019.repair.json").read_text()))
    assert not (FIXTURES / "P1" / "lantern_debt_2019.txt").read_text().lstrip().startswith("{\"title_id\"")


def test_offline_pass_repair_quarantine_canonicalize_build_validate(repo):
    produced = mock_p1_pass(repo, ["ironvale_circuit_2021", "lantern_debt_2019", "quill_house_2018"])
    assert [p["title_id"] for p in produced] == ["ironvale_circuit_2021", "lantern_debt_2019"]  # 2nd needed a repair
    q = json.loads((repo.quarantine / "P1" / "title" / "quill_house_2018.json").read_text())
    assert len(q["reasons"]) == 2  # failed, repaired, failed again

    runner = CliRunner()
    r = runner.invoke(app, ["canonicalize"])
    assert r.exit_code == 0 and "wrote 2 title record(s)" in r.output, r.output
    assert [t["title_id"] for t in read_jsonl(repo.canonical / "titles.jsonl")] == ["ironvale_circuit_2021", "lantern_debt_2019"]
    assert runner.invoke(app, ["build"]).exit_code == 0
    r = runner.invoke(app, ["validate"])
    assert r.exit_code == 0, r.output

    calls = [json.loads(line) for line in (repo.raw_runs / "run_offline" / "calls.jsonl").read_text().splitlines()]
    assert {c["attempt"] for c in calls if c["record_id"] == "lantern_debt_2019"} == {0, 1}


def test_rerun_is_served_from_cache(repo):
    mock_p1_pass(repo, ["ironvale_circuit_2021"])
    mock_p1_pass(repo, ["ironvale_circuit_2021"])
    calls = [json.loads(line) for line in (repo.raw_runs / "run_offline" / "calls.jsonl").read_text().splitlines()]
    assert [c["cache_hit"] for c in calls] == [False, True]


@pytest.mark.parametrize("stage", sorted(STAGE_MILESTONE))
def test_unbuilt_stages_exit_2_and_name_their_milestone(repo, stage):
    result = CliRunner().invoke(app, [stage])
    assert result.exit_code == 2
    assert STAGE_MILESTONE[stage] in result.output
