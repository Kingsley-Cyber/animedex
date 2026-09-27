"""M3 offline: P2 WHY -> P3 PROOF -> CHECK -> CANONICALIZE -> P4 TRANSFER on the mock provider.

Covers AC-14 (atoms), AC-15 (cross-medium partner, explanation tests), AC-16 (load-bearing flags,
contested excluded), AC-18 (no names or medium words in patterns), AC-19 (critic family, scope
leak rejected), AC-20 (REJECT quarantined, REVISE re-checked once, CONTESTED marks the atom).
"""

from __future__ import annotations

import json

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.config import ModelSpec, load_settings
from animedex.eligibility import eligible_atom_ids
from animedex.ontology import get_vocab
from animedex.pipeline.canonicalize import canonicalize
from animedex.pipeline.check import run_check
from animedex.pipeline.common import canonical_titles, outcomes
from animedex.pipeline.p2 import run_p2
from animedex.pipeline.p3 import run_p3
from animedex.pipeline.p4 import run_p4
from animedex.pipeline.partners import select_partners
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.canonical import CanonicalStore
from animedex.store.jsonl import read_jsonl
from animedex.store.runlog import RunLog
from tests.conftest import make_moment, make_title, prov

pytestmark = pytest.mark.pipeline

T1, T2, T3, T4 = "ironvale_circuit_2021", "lantern_debt_2019", "glass_meridian_2016", "copper_vow_2018"
CREATED = "2026-09-27T12:00:00+00:00"


def outcome(tid: str, label: str) -> dict:
    base = {"title_id": tid, "label": label,
            "signals": [{"metric": "synthetic score", "value": "7.0", "source_ref": "https://example.org/s"}],
            "confounders": {"studio": "", "budget_signal": "", "source_popularity": "", "platform": "",
                            "release_context": ""},
            "failure_reason": None, "failure_level": None, "failure_evidence": None, "failure_evidence_ref": None,
            "failure_level_source": None, "provenance": prov("VERIFY")}
    if label != "hit":
        base.update(failure_reason="Pacing collapsed in the second half.", failure_level="unknown",
                    failure_level_source="verify")
    return base


@pytest.fixture
def m3(repo):
    titles = [make_title(),
              make_title(T2, "Lantern Debt", medium="western_animation", fmt="episodic",
                         modules=("relationships", "sensory", "series_engine", "comedy_satire"), role_tags=("mixed",)),
              make_title(T3, "Glass Meridian", medium="film", fmt="film", modules=("film",), role_tags=("flop",)),
              make_title(T4, "Copper Vow", role_tags=("hit",))]
    store = CanonicalStore(repo)
    store.write("title", titles, "run_setup")
    store.write("moment", [make_moment(T1, 1), make_moment(T1, 2)], "run_setup")
    store.write("outcome", [outcome(T1, "hit"), outcome(T2, "mixed"), outcome(T3, "flop"), outcome(T4, "hit")],
                "run_setup")
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope", "role_tags")} for t in titles]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    return repo


def client(repo, responses, name="run_m3") -> tuple[LLMClient, MockProvider]:
    mock = MockProvider(responses=responses)
    c = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                  prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                  cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, name))
    return c, mock


def p2_out(**over) -> dict:
    out = {
        "engines": [{"agent": "an unlicensed grid courier", "goal": "keep the district powered",
                     "constraint": "only she can read the grid and it burns her memory",
                     "strategy": "route power in secret at night", "benefit": "the district survives another week",
                     "cost": "she forgets the people she saves", "dilemma": "each rescue erases why she rescues",
                     "dramatic_question": "What will she remember when the grid is fixed?", "feeling": "tension",
                     "module": "power_combat", "conf": 0.8, "evidence_refs": ["power_combat.cost_of_power", f"{T1}.mo.01"]}],
        "effects": [
            {"element": "a power meter only the courier can see", "element_field": "power_combat.visible_counter",
             "element_moment_id": None, "feeling": "curiosity",
             "because": "the audience shares a secret the other characters cannot check",
             "rival_because": "visible numbers reward progress in the way games do",
             "module": "power_combat", "conf": 0.75, "evidence_refs": ["power_combat.visible_counter"]},
            {"element": "the reroute that saves a rival crew", "element_field": None, "element_moment_id": f"{T1}.mo.01",
             "feeling": "catharsis", "because": "sacrifice turns a private skill into a public bond",
             "rival_because": "the spectacle of the grid lighting up carries the scene",
             "module": "core", "conf": 0.7, "evidence_refs": [f"{T1}.mo.01"]},
        ]}
    out.update(over)
    return out


def p3_out(repo, verdicts=("load_bearing", "load_bearing", "decoration"), favors=("because", "because")) -> dict:
    partners = select_partners(canonical_titles(repo)[T1], canonical_titles(repo), outcomes(repo), get_vocab())
    contrast = [{"partner_title_id": p["title_id"], "partner_role": p["role"], "partner_has": "partial",
                 "difference": "The partner hides its meter from the audience as well."} for p in partners]
    proofs = []
    for i, verdict in enumerate(verdicts, start=1):
        is_effect = i > 1
        proofs.append({"atom_id": f"{T1}.m.{i:03d}", "contrast": contrast,
                       "explanation_test": ({"favors": favors[i - 2], "via_partner": partners[0]["title_id"],
                                             "note": "The partner has the meter but not the shared secret."}
                                            if is_effect else {"favors": None, "via_partner": None, "note": None}),
                       "ablation": {"if_removed": "The premise loses its engine and the feeling collapses.",
                                    "verdict": verdict, "conf": 0.8}})
    return {"proofs": proofs}


def blank_revision() -> dict:
    keys = ("element", "because", "rival_because", "goal", "constraint", "strategy", "benefit", "cost", "dilemma",
            "dramatic_question", "feeling", "ablation_verdict", "favors")
    return {k: None for k in keys}


def verdict(aid, ttype, v="ACCEPT", reasons=(), **rev) -> dict:
    return {"target_id": aid, "target_type": ttype, "verdict": v, "reasons": list(reasons),
            "revision": {**blank_revision(), **rev}, "note": None}


def run_through_check(repo, check_rounds, p3=None):
    settings, vocab = load_settings(repo), get_vocab()
    c, _ = client(repo, {("P2", T1): [p2_out()]}, "run_p2")
    assert run_p2(repo, [T1], c, vocab, settings, run_id="run_p2", created_at=CREATED).done == [T1]
    c, _ = client(repo, {("P3", T1): [p3 or p3_out(repo)]}, "run_p3")
    r3 = run_p3(repo, [T1], c, vocab, settings, run_id="run_p3", created_at=CREATED)
    assert r3.done == [T1]
    c, mock = client(repo, check_rounds, "run_check")
    rc = run_check(repo, [T1], c, vocab, settings, run_id="run_check", created_at=CREATED)
    return rc, mock


def test_full_m3_flow_reject_revise_recheck_and_transfer(m3):
    first = {"verdicts": [
        verdict(f"{T1}.m.001", "mechanism"), verdict(f"{T1}.m.001", "proof"),
        verdict(f"{T1}.m.002", "mechanism", "REVISE", ["overreach"],
                because="the audience alone can verify a secret the cast cannot"),
        verdict(f"{T1}.m.002", "proof"),
        verdict(f"{T1}.m.003", "mechanism", "REJECT", ["scope_leak"]), verdict(f"{T1}.m.003", "proof")]}
    recheck = {"verdicts": [verdict(f"{T1}.m.002", "mechanism"), verdict(f"{T1}.m.002", "proof")]}
    rc, mock = run_through_check(m3, {("CHECK", T1): [first], ("CHECK", f"{T1}.recheck"): [recheck]})
    assert rc.done == [T1] and [c["record_id"] for c in mock.calls] == [T1, f"{T1}.recheck"]
    assert list((m3.quarantine / "CHECK").rglob(f"{T1}.m.003*"))  # AC-19/20: scope leak quarantined
    res = canonicalize(m3, "run_canon")
    assert sorted(res.written["mechanism"]) == [f"{T1}.m.001", f"{T1}.m.002"]
    state = CanonicalStore(m3).state()
    m2 = next(m for m in state["mechanism"] if m["atom_id"] == f"{T1}.m.002")
    assert m2["effect"]["because"] == "the audience alone can verify a secret the cast cannot"
    assert [c["verdict"] for c in state["check"] if c["target_id"] == f"{T1}.m.002" and c["target_type"] == "mechanism"
            ] == ["REVISE", "ACCEPT"]
    assert eligible_atom_ids(state) == {f"{T1}.m.001", f"{T1}.m.002"}
    cov = next(c for c in state["coverage"] if c["title_id"] == T1)
    assert {"P2", "P3", "CHECK"} <= set(cov["passes_done"]) and "P4" not in cov["passes_done"]

    leaky = {"transfers": [
        {"source_atom_id": f"{T1}.m.001", "pattern": "An Ironvale courier trades memory for anime power each episode",
         "bridge": ["cost_of_advancement"], "essential_conditions": ["the cost is personal and cumulative"],
         "variable_details": ["what is forgotten"], "failure_conditions": ["the cost can be undone"]},
        {"source_atom_id": f"{T1}.m.002", "pattern": "Only the lead can read the measure of growth",
         "bridge": ["visible_progress_counter", "information_asymmetry"],
         "essential_conditions": ["the measure stays private"], "variable_details": ["the measure's form"],
         "failure_conditions": ["others can read the measure"]}]}
    clean = json.loads(json.dumps(leaky))
    clean["transfers"][0]["pattern"] = "A helper trades memories for power, and every rescue costs a memory"
    c, mock = client(m3, {("P4", T1): [leaky, clean]}, "run_p4")
    r4 = run_p4(m3, [T1], c, get_vocab(), load_settings(m3), run_id="run_p4", created_at=CREATED)
    assert r4.done == [T1] and len(mock.calls) == 2
    repair = mock.calls[1]["user"]
    assert "medium words" in repair and "ironvale" in repair.lower()  # AC-18
    canonicalize(m3, "run_canon2")
    state = CanonicalStore(m3).state()
    assert sorted(t["source_atom_id"] for t in state["transfer"]) == [f"{T1}.m.001", f"{T1}.m.002"]
    cov = next(c for c in state["coverage"] if c["title_id"] == T1)
    assert "P4" in cov["passes_done"]


def test_rival_favoring_explanation_forces_revise_or_contested(m3):
    p3 = p3_out(m3, favors=("rival", "because"))
    accept_all = {"verdicts": [verdict(f"{T1}.m.{i:03d}", t) for i in (1, 2, 3) for t in ("mechanism", "proof")]}
    contested = json.loads(json.dumps(accept_all))
    contested["verdicts"][2] = verdict(f"{T1}.m.002", "mechanism", "CONTESTED", ["contradiction"])
    rc, mock = run_through_check(m3, {("CHECK", T1): [accept_all, contested]}, p3=p3)
    assert "favors the rival" in mock.calls[1]["user"]
    canonicalize(m3, "run_canon")
    state = CanonicalStore(m3).state()
    m2 = next(m for m in state["mechanism"] if m["atom_id"] == f"{T1}.m.002")
    assert m2["explanation"] == "contested" and f"{T1}.m.002" not in eligible_atom_ids(state)  # AC-16, AC-20


def test_adjudication_is_queued_without_blocking(m3):
    rounds = {"verdicts": [verdict(f"{T1}.m.{i:03d}", t) for i in (1, 2, 3) for t in ("mechanism", "proof")]}
    rounds["verdicts"][0] = verdict(f"{T1}.m.001", "mechanism", "NEEDS_ADJUDICATION", ["contradiction"])
    rc, _ = run_through_check(m3, {("CHECK", T1): [rounds]})
    assert rc.done == [T1] and any("needs adjudication" in f for _, f in rc.flags)
    assert (m3.root / "data" / "adjudication" / f"{T1}.json").is_file()
    canonicalize(m3, "run_canon")
    assert f"{T1}.m.001" not in eligible_atom_ids(CanonicalStore(m3).state())


def test_atoms_wait_for_their_checks(m3):
    c, _ = client(m3, {("P2", T1): [p2_out()]})
    run_p2(m3, [T1], c, get_vocab(), load_settings(m3), run_id="run_p2")
    res = canonicalize(m3, "run_canon")
    assert "mechanism" not in res.written and res.held
    assert read_jsonl(m3.candidates / "mechanism" / f"{T1}.jsonl")


def test_p2_repairs_unknown_evidence_and_circular_because(m3):
    bad = p2_out()
    bad["effects"][0]["evidence_refs"] = ["core.not_a_field"]
    bad["effects"][1]["because"] = "the reroute that saves the rival crew"
    c, mock = client(m3, {("P2", T1): [bad, p2_out()]})
    r = run_p2(m3, [T1], c, get_vocab(), load_settings(m3), run_id="run_p2")
    assert r.done == [T1] and len(mock.calls) == 2
    assert "not listed field paths" in mock.calls[1]["user"] and "restates the element" in mock.calls[1]["user"]
    atoms = read_jsonl(m3.candidates / "mechanism" / f"{T1}.jsonl")
    assert [a["atom_kind"] for a in atoms] == ["engine", "effect", "effect"]  # AC-14
    assert all(a["evidence_refs"] for a in atoms) and all(a["effect"]["rival_because"] for a in atoms[1:])


def test_p3_partners_include_cross_medium_and_flag_low_load_bearing(m3):
    titles = canonical_titles(m3)
    partners = select_partners(titles[T1], titles, outcomes(m3), get_vocab())
    roles = {p["role"]: p["title_id"] for p in partners}
    assert roles["nearest_neighbor"] == T4 and roles["flop"] == T2 and roles["cross_medium"] == T3  # AC-15
    c, _ = client(m3, {("P2", T1): [p2_out()]})
    run_p2(m3, [T1], c, get_vocab(), load_settings(m3), run_id="run_p2")
    c, _ = client(m3, {("P3", T1): [p3_out(m3, verdicts=("load_bearing", "decoration", "decoration"))]})
    r = run_p3(m3, [T1], c, get_vocab(), load_settings(m3), run_id="run_p3")
    assert any("1 load-bearing atoms" in f for _, f in r.flags)  # AC-16


def test_critic_is_a_different_model_family():
    settings = load_settings()
    fam = {name: prof.type for name, prof in settings.providers.items()}
    assert fam[settings.models["check"].provider] != fam[settings.models["p2"].provider]  # AC-19
    assert settings.models["check"].strict_model


def test_orchestrator_runs_m3_stages_with_mocks(m3):
    from animedex.pipeline.orchestrate import run_batch

    accept = {"verdicts": [verdict(f"{T1}.m.{i:03d}", t) for i in (1, 2, 3) for t in ("mechanism", "proof")]}
    transfers = {"transfers": [
        {"source_atom_id": f"{T1}.m.00{i}", "pattern": "A helper pays for power with memory, one rescue at a time",
         "bridge": ["cost_of_advancement"], "essential_conditions": ["the cost is personal"],
         "variable_details": ["the setting"], "failure_conditions": ["the cost is reversible"]} for i in (1, 2)]}
    responses = {("P2", T1): [p2_out()], ("P3", T1): [p3_out(m3)], ("CHECK", T1): [accept], ("P4", T1): [transfers]}

    def clients(key, runlog):
        mock = MockProvider(responses=responses)
        return LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                         prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                         cache=ResponseCache(m3.cache), runlog=runlog)

    report = run_batch(m3, [T1], load_settings(m3), {}, get_vocab(), stages=("P2", "P3", "CHECK", "P4"),
                       clients=clients)
    assert not report.stopped and report.stages["P4"]["done"] == [T1]
    state = CanonicalStore(m3).state()
    assert len(state["transfer"]) == 2 and report.canonical.get("check", 0) >= 6
