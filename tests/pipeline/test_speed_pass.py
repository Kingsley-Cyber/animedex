"""Speed pass (v1.10, D-048): non-gold titles take the fast path (PROFILE, medium effort, the critic on
several titles per call, titles in parallel under one budget); gold titles keep the full path."""

from __future__ import annotations

import json
import threading
import time

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.budget import Budget, BudgetExceeded
from animedex.config import ModelSpec, load_settings
from animedex.guards import LiveRunRefused
from animedex.ontology import get_vocab
from animedex.pipeline.orchestrate import run_batch
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.canonical import CanonicalStore
from tests.pipeline.test_gather import WIKI, WIKIA
from tests.pipeline.test_m3 import LADDER, T1, T4, m3, p2_out, verdict  # noqa: F401  (fixture)
from tests.pipeline.test_p1 import ENTRY
from tests.pipeline.test_profile import REVIEW, TID, WebMock, merged_answer, reception

pytestmark = pytest.mark.pipeline


def speed_settings(repo, **over):
    settings = load_settings(repo)
    settings.model_extra["speed"] = {"merged_profile": True, "effort": "medium", "verify_only": ["core.outcome", "moments"],
                                     "check_batch_titles": 3, "parallel_titles": 4, **over}
    return settings


def mock_client(repo, responses, runlog, *, budget=None, default=None, web=False):
    provider = WebMock({WIKI, WIKIA, REVIEW}, responses=responses) if web \
        else MockProvider(responses=responses, default=default)
    return LLMClient(provider=provider, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                     prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                     cache=ResponseCache(repo.cache), runlog=runlog, budget=budget)


def test_non_gold_titles_take_profile_and_gold_titles_keep_gather(repo):
    gold = {**ENTRY, "title_id": "gold_harbor_2020", "title": "Gold Harbor", "year": 2020, "role_tags": ["gold"]}
    repo.corpus_file.write_text(yaml.safe_dump({"titles": [ENTRY, gold]}))
    keys: list[str] = []
    mocks: list = []

    def clients(key, runlog):
        keys.append(key)
        client = mock_client(repo, {("PROFILE", TID): [merged_answer()]}, runlog, web=True)
        mocks.append(client.provider)
        return client

    report = run_batch(repo, [TID, "gold_harbor_2020"], speed_settings(repo), {}, get_vocab(),
                       stages=("PROFILE", "GATHER"), clients=clients, reception=reception)
    assert report.stages["PROFILE"]["done"] == [TID] and "profile" in keys, report.stages   # the fast path
    assert "gather" not in keys or not report.stages.get("GATHER", {}).get("done")  # gold: GATHER, not PROFILE
    assert (repo.candidates / "title" / f"{TID}.jsonl").exists() or CanonicalStore(repo).read("title")
    profile_calls = [c for m in mocks for c in m.calls if c["pass"] == "PROFILE"]
    assert profile_calls and profile_calls[0]["params"].get("effort") == "medium" and "web" in profile_calls[0]["params"]


def test_the_fast_path_runs_titles_in_parallel_batches_the_critic_and_sends_medium_effort(m3):  # noqa: F811
    """T1 and T2 are canonical non-gold titles: P2 and P3 run for both at once, CHECK sees both in one call,
    every call carries effort medium, and each title's checks are written separately."""
    accept = {"verdicts": [verdict(f"{t}.m.{i:03d}", k) for t in (T1, T4) for i in (1, 2, 3) for k in ("mechanism", "proof")]}
    transfers = {"transfers": [
        {"source_atom_id": f"{T1}.m.00{i}", "pattern": "A helper pays for power with memory, one rescue at a time",
         "bridge": ["cost_of_advancement"], "essential_conditions": ["the cost is personal"],
         "variable_details": ["the setting"], "failure_conditions": ["the cost is reversible"], **LADDER} for i in (1, 2)]}
    active = {"n": 0, "peak": 0}
    lock = threading.Lock()

    def p2_for() -> dict:
        """p2_out without T1's moment references, so it fits any title with the default modules."""
        out = json.loads(json.dumps(p2_out()))
        out["engines"][0]["evidence_refs"] = ["power_combat.cost_of_power", "core.premise_engine"]
        out["effects"][1].update(element_field="core.premise_engine", element_moment_id=None,
                                 evidence_refs=["core.premise_engine"])
        return out

    def p3_for(atom_ids: list[str]) -> dict:
        """A proof per atom for whichever title the schema names, against that title's own partners."""
        from animedex.pipeline.common import canonical_titles, outcomes
        from animedex.pipeline.partners import select_partners

        tid = atom_ids[0].split(".m.")[0]
        titles = canonical_titles(m3)
        partners = select_partners(titles[tid], titles, outcomes(m3), get_vocab())
        contrast = [{"partner_title_id": pt["title_id"], "partner_role": pt["role"], "partner_has": "partial",
                     "difference": "The partner hides its meter from the audience as well."} for pt in partners]
        proofs = []
        for i, aid in enumerate(atom_ids):
            is_effect = i > 0
            proofs.append({"atom_id": aid, "contrast": contrast,
                           "explanation_test": ({"favors": "because", "via_partner": partners[0]["title_id"],
                                                 "note": "The partner has the meter but not the shared secret."}
                                                if is_effect else {"favors": None, "via_partner": None, "note": None}),
                           "ablation": {"if_removed": "The premise loses its engine and the feeling collapses.",
                                        "verdict": "load_bearing" if i < 2 else "decoration", "conf": 0.8}})
        return {"proofs": proofs}

    def answer(system, user, schema, params):
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        time.sleep(0.05)
        with lock:
            active["n"] -= 1
        props = schema.get("properties", {})
        if "effects" in props:
            return p2_for()
        if "proofs" in props:
            return p3_for(props["proofs"]["items"]["properties"]["atom_id"]["enum"])
        if "verdicts" in props:
            ids = props["verdicts"]["items"]["properties"]["target_id"]["enum"]
            return {"verdicts": [v for v in accept["verdicts"] if v["target_id"] in ids]}
        if "transfers" in props:
            ids = props["transfers"]["items"]["properties"]["source_atom_id"]["enum"]
            return {"transfers": [{**t, "source_atom_id": i} for t, i in zip(transfers["transfers"] * 5, ids, strict=False)]}
        raise AssertionError(f"unexpected schema {sorted(props)}")

    budget = Budget(None, None, None, 40, 20)
    mocks: list = []

    def clients(key, runlog):
        client = mock_client(m3, {}, runlog, budget=budget, default=answer)
        mocks.append(client.provider)
        return client

    accept = {"verdicts": [verdict(f"{t}.m.{i:03d}", k) for t in (T1, T4) for i in (1, 2, 3) for k in ("mechanism", "proof")]}
    report = run_batch(m3, [T1, T4], speed_settings(m3, parallel_titles=2), {}, get_vocab(),
                       stages=("P2", "P3", "CHECK", "P4"), clients=clients)
    assert not report.stopped, report.stopped
    assert sorted(report.stages["P2"]["done"]) == sorted([T1, T4]) and active["peak"] >= 2, report.stages   # two at once
    check_calls = [c for m in mocks for c in m.calls if c["pass"] == "CHECK" and not c["record_id"].endswith(".recheck")]
    assert len(check_calls) == 1 and f"=== title {T1}" in check_calls[0]["user"] and f"=== title {T4}" in check_calls[0]["user"]
    assert all(c["params"].get("effort") == "medium" for m in mocks for c in m.calls)
    state = CanonicalStore(m3).state()
    assert {c["target_id"].split(".m.")[0] for c in state["check"]} >= {T1, T4}
    assert sorted(report.stages["P4"]["done"]) == sorted([T1, T4]) and budget.calls_run == 0  # mocks are not live


def test_the_shared_budget_stops_parallel_workers_at_the_cap(m3):  # noqa: F811
    """Live-style accounting: every worker counts on one budget, so the run's cap holds across threads."""
    budget = Budget(None, None, None, 3, 20)
    for _ in range(3):
        budget.count_call()
    with pytest.raises(Exception, match="call cap reached"):
        budget.check_calls(T1)
    counts = []

    def bump():
        for _ in range(500):
            budget.count_call(T1)
        counts.append(budget.calls_title[T1])

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert budget.calls_title[T1] == 2000 and budget.calls_run == 2003


def test_fast_verify_list_is_the_outcome_and_the_moments(repo):
    """After PROFILE, the verify file holds only moment locators (the outcome was settled by reception)."""
    from animedex.models import CorpusEntry
    from animedex.pipeline.profile import run_profile
    from animedex.store.runlog import RunLog

    client = mock_client(repo, {("PROFILE", TID): [merged_answer()]}, RunLog(repo.raw_runs, "run_v"), web=True)
    run_profile(repo, [CorpusEntry.model_validate(ENTRY)], client, get_vocab(), speed_settings(repo), run_id="run_v",
                reception=reception)
    verify = json.loads((repo.candidates / "verify" / f"{TID}.json").read_text())["verify"]
    assert verify and all(p.startswith("moments.") for p in verify)


def test_a_stage_view_shares_the_run_cap_and_starts_its_own_title_count():
    """The run cap is one for the whole run; the per-title cap is per stage (each stage's client gets a view),
    so a title's 7 fast-path calls never trip a cap meant for one stage."""
    root = Budget(None, None, None, 40, 6)
    a, b = root.stage_view(), root.stage_view()
    for _ in range(6):
        a.count_call(T1)
    with pytest.raises(BudgetExceeded, match="call cap reached for"):
        a.check_calls(T1)
    b.check_calls(T1)   # a new stage: the title's count starts again
    assert root.calls_run == 6 and b.calls_title[T1] == 0 and a.root is root and b.root is root
    b.count_title(T1)   # a shared call: counted for the title, not again for the run
    assert root.calls_run == 6 and b.calls_title[T1] == 1
    root.calls_run = 40
    with pytest.raises(BudgetExceeded, match="this run"):
        b.check_calls(T4)


def test_a_check_group_is_guarded_and_charged_per_title_not_by_its_label():
    """The critic's batched call names `a+b`; the corpus guard and the per-title cap still see each title."""
    from types import SimpleNamespace

    from animedex.pipeline.check import _admit_group, _count_group
    from animedex.pipeline.common import StageResult

    seen: list[str] = []
    budget = Budget(None, None, None, 40, 6)
    client = SimpleNamespace(provider=SimpleNamespace(live=True), billing="subscription", budget=budget,
                             title_guard=seen.append)
    result = StageResult()
    assert _admit_group(client, [T1, T4], result, f"{T1}+{T4}") is None and seen == [T1, T4]
    _count_group(client, [T1, T4])
    assert budget.calls_title[T1] == 1 and budget.calls_title[T4] == 1 and budget.calls_run == 0

    def refuse(tid: str) -> None:
        raise LiveRunRefused(f"{tid} is not in corpus/titles.yaml")

    client.title_guard = refuse
    assert _admit_group(client, [T1, T4], result, "x") == "refused" and result.refused[0][0] == "x"
    client.title_guard = seen.append
    budget.calls_title[T4] = 6
    assert _admit_group(client, [T1, T4], result, "x") == "stopped" and "call cap reached for" in result.stopped
