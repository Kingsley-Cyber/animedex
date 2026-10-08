"""The new public suggestion path preserves sources, rejects weak drafts, and blinds taste testing."""

from __future__ import annotations

import csv
import json

from typer.testing import CliRunner

from animedex import cli
from animedex.ideate.review import Store
from animedex.store.runlog import RunLog
from tests.light.test_quick import clients_for

SOURCE = "https://research.example/primary-mechanisms"


def install_clients(repo, monkeypatch, *, fetched=True):
    old, mocks = clients_for(repo, {}, [], [])
    clients = {"scan": old["ingest"], "generate": old["generate"], "check": old["check"]}
    mocks["ingest"].urls = [SOURCE] if fetched else []

    def scan(system, user, schema, params):
        pass_ = params["_meta"]["pass"]
        if pass_ == "IDEATION_MATERIALS":
            return {"materials": [{"domain": domain, "causal_rule": f"{domain} transfers a delay to a different person.",
                "surprise": "The delay travels opposite the work.", "shape": f"{domain}-backward-propagation",
                "forced_choice": "choose-who-waits", "cost": "time", "source_url": SOURCE}
                for domain in ("science", "craft")]}
        if pass_ == "IDEATION_PRIOR_ART":
            refs = schema["properties"]["checks"]["items"]["properties"]["ref"]["enum"]
            return {"checks": [{"ref": ref, "overlap": "partial", "title": "Synthetic comparison",
                "url": SOURCE, "difference": "Its delays do not transfer obligations."} for ref in refs]}
        raise AssertionError(pass_)

    def generate(system, user, schema, params):
        pass_ = params["_meta"]["pass"]
        assert "comparison index" not in user
        if pass_ == "IDEATION_HYPOTHESES":
            ids = schema["properties"]["hypotheses"]["items"]["properties"]["material_ids"]["items"]["enum"]
            return {"hypotheses": [{"surprise": f"Delay surprise {i}", "claim": f"Obligation rule {i}",
                "forced_choice": "Choose who waits.", "supporting_question": "Who absorbs the delay?",
                "falsifying_question": "Can the delay vanish without a cost?", "material_ids": [id_]}
                for i, id_ in enumerate(ids, start=1)]}
        if pass_ in ("IDEATION_DRAFTS", "IDEATION_BASELINE"):
            ref_schema = schema["properties"]["ideas"]["items"]["properties"]["hypothesis_ref"]
            refs = ref_schema.get("enum") or [None, None]
            return {"ideas": [{"logline": f"A courier moves somebody else's wait {i}.",
                "premise": f"A courier negotiates who bears delayed obligations {i}.",
                "story_rule": f"Waiting obligation {i}", "protagonist_advantage": "Negotiates the route.",
                "cold_open": f"A delayed delivery freezes a household {i}.",
                "engine": {field: f"{field} for obligation {i}" for field in
                           ("goal", "constraint", "strategy", "cost", "dilemma")}, "hypothesis_ref": ref}
                for i, ref in enumerate(refs, start=1)]}
        raise AssertionError(pass_)

    def check(system, user, schema, params):
        assert '"arm"' not in user and '"hypothesis_ref"' not in user
        refs = schema["properties"]["tests"]["items"]["properties"]["ref"]["enum"]
        return {"tests": [{"ref": ref, "rule_drives_choices": True, "engine_has_runway": True,
            "specific_not_cosmetic": i != 0, "fits_brief": True, "distinct_from_notes": True,
            "pressure_scene": "The courier must delay a friend or the school opening.",
            "escalation_scene": "A rival refuses to accept any reassigned delay.",
            "removal_test": "Without transferred waits the negotiation disappears.",
            "same_engine_as": None, "closest_note": None,
            "reason": "Cosmetic rule" if i == 0 else "The rule creates an incompatible choice."}
            for i, ref in enumerate(refs)]}

    mocks["ingest"].default = scan
    mocks["generate"].default = generate
    mocks["check"].default = check
    monkeypatch.setattr(cli, "_paths", lambda: repo)
    monkeypatch.setattr(cli, "_clients", lambda paths, settings, keys, calls_per_run=None:
        (clients, RunLog(repo.raw_runs, "ideation_test")))
    return mocks


def test_public_generic_ideation_reaches_suggestions_and_source_id_lookup(repo, monkeypatch):
    mocks = install_clients(repo, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["ideate", "--brief", "a workplace comedy", "--medium", "sitcom", "--n", "2"])
    assert result.exit_code == 0, result.output
    run_file = next((repo.quick / "_ideation").glob("*.json"))
    record = json.loads(run_file.read_text())
    assert record["medium"] == "sitcom" and record["status"] == "complete"
    assert len(record["suggested"]) == 1
    assert all("power_kit" not in item for item in record["ideas"].values())
    assert set(record["materials"]) == {path.stem for path in (repo.notes / "_materials").glob("*.json")}
    assert {call["pass"] for call in mocks["generate"].calls} == {"IDEATION_HYPOTHESES", "IDEATION_DRAFTS"}
    assert runner.invoke(cli.app, ["export"]).exit_code == 0
    with (repo.exports / "ideation_nodes.csv").open(newline="", encoding="utf-8") as file:
        nodes = list(csv.DictReader(file))
    mechanisms = [node for node in nodes if node["kind"] == "mechanism"]
    assert {node["domain"] for node in mechanisms} == {"science", "craft"}
    assert all(node["source_url"] == SOURCE and node["shape"] and node["force"] for node in mechanisms)
    id_ = f"idea:{run_file.stem}:{record['suggested'][0]}"
    found = runner.invoke(cli.app, ["lookup", "--id", id_])
    assert found.exit_code == 0, found.output
    assert {node["kind"] for node in json.loads(found.output)["lineage"]} == {"mechanism", "hypothesis"}


def test_unfetched_material_fails_and_persists_no_success(repo, monkeypatch):
    install_clients(repo, monkeypatch, fetched=False)
    result = CliRunner().invoke(cli.app, ["ideate", "--n", "2"])
    assert result.exit_code == 1 and "opened" in result.output
    record = json.loads(next((repo.quick / "_ideation").glob("*.json")).read_text())
    assert record["status"] == "failed" and record["stage"] == "materials"
    assert not record["ideas"]
    assert not list((repo.notes / "_materials").glob("*.json"))


def test_comparison_keeps_arms_hidden_until_every_card_is_rated(repo, monkeypatch):
    install_clients(repo, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["ideate", "--brief", "a comedy", "--medium", "television", "--n", "2", "--compare"])
    assert result.exit_code == 0, result.output
    run_file = next((repo.quick / "_ideation").glob("*.json"))
    record = json.loads(run_file.read_text())
    packet_file = repo.root / record["packet_file"]
    packet = json.loads(packet_file.read_text())
    assert len(packet["cards"]) == 4
    assert all(set(card) == {"id", "logline", "premise"} for card in packet["cards"])
    args = ["ideate-results", "--run", str(run_file)]
    before = json.loads(runner.invoke(cli.app, args).output)
    assert not before["complete"] and "arms" not in before and "provenance" not in before
    store = Store(packet_file)
    for card in packet["cards"]:
        store.update(card["id"], {"rating": 3, "greenlight": True})
    after = json.loads(runner.invoke(cli.app, args).output)
    assert after["complete"] and set(after["arms"]) == {"hypothesis", "direct"}
    assert all(len(arm["ratings"]) == 2 for arm in after["arms"].values())
