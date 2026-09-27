"""M5 IDEATE offline (mock generator, judge, prior art; mock embeddings).

AC-25 complete cards (closest_existing, why_not_a_clone, engine); AC-26 eligible atoms only;
AC-27 operator + consequences recorded, a surface change fails H1; AC-28 gates enforced and
rejections logged by gate; AC-29 <=1 idea per cell, a cell's fitness never decreases. Plus the
v1.6 runway question, taste evidence filtering, prior-art checks, the call-cap stop, the masked
ideas.md, and the three-arm blind packet.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.budget import Budget
from animedex.config import ModelSpec, load_settings
from animedex.embeddings.base import MockEmbedder
from animedex.ideate.packet import build_packet
from animedex.ideate.report import write_report
from animedex.ideate.run import run_ideate
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.canonical import CanonicalStore
from animedex.store.runlog import RunLog
from tests.conftest import (
    make_effect_atom,
    make_engine_atom,
    make_proof,
    make_title,
    make_transfer,
    prov,
    write_state,
)

pytestmark = pytest.mark.pipeline

T1, T2, T3 = "ironvale_circuit_2021", "lantern_debt_2019", "glass_meridian_2016"


def state() -> dict:
    titles = [make_title(), make_title(T2, "Lantern Debt", medium="western_animation", fmt="episodic",
                                       modules=("power_combat", "relationships", "sensory", "series_engine"),
                                       role_tags=("hit",)),
              make_title(T3, "Glass Meridian", medium="film", fmt="film", modules=("film",), role_tags=("flop",))]
    mech = [make_effect_atom(), make_engine_atom(), make_effect_atom(T2, 1), make_engine_atom(T2, 2)]
    for m in mech:
        m["evidence_refs"] = ["core.premise_engine"] if m["atom_kind"] == "engine" else ["power_combat.visible_counter"]
    proofs = [make_proof(m["atom_id"], partner=T3 if m["title_id"] == T1 else T1,
                         explanation_test=None if m["atom_kind"] == "engine" else
                         {"favors": "because", "via_partner": T3 if m["title_id"] == T1 else T1,
                          "note": "The partner has the element but not the feeling."}) for m in mech]
    for p in proofs:
        p["ablation"]["verdict"] = "load_bearing"
    checks = [{"target_id": m["atom_id"], "target_type": "mechanism", "verdict": "ACCEPT", "reasons": [],
               "revision": None, "provenance": prov("CHECK")} for m in mech]
    transfers = [
        make_transfer(T1, 1, 1),
        make_transfer(T1, 2, 2, atom_kind="engine", pattern="A helper pays for power with memory, one rescue at a time.",
                      bridge=["cost_of_advancement", "core_tension"]),
        make_transfer(T2, 1, 1, pattern="A debt ledger decides who may fight, and every win adds interest.",
                      bridge=["access_gate", "borrowed_system"]),
        make_transfer(T2, 2, 2, atom_kind="engine", pattern="A crew shares one power that weakens whoever uses it most.",
                      bridge=["bond_as_power", "cost_of_advancement"]),
    ]
    outcome = {"title_id": T3, "label": "flop",
               "signals": [{"metric": "score", "value": "4.1", "source_ref": "https://example.org/s"}],
               "confounders": {"studio": "", "budget_signal": "", "source_popularity": "", "platform": "",
                               "release_context": ""},
               "failure_reason": "Execution buried a clear premise.", "failure_level": "execution",
               "failure_evidence": "Reviews fault pacing, not the idea.", "failure_evidence_ref": "https://example.org/r",
               "failure_level_source": "verify", "provenance": prov("VERIFY")}
    return {"title": titles, "outcome": [outcome], "mechanism": mech, "proof": proofs, "check": checks,
            "transfer": transfers}


_count = {"n": 0}


def responder(system, user, schema, params):
    props = schema.get("properties", {})
    if "premises" in props:  # baselines
        n = int(re.search(r"Write (\d+) premises", user).group(1))
        return {"premises": [{"logline": f"Baseline hero number {i} bargains with a tide of glass.",
                              "premise": "A salvager trades years of her life for tides that obey her, until the "
                                         "town wants more."} for i in range(n)]}
    if "checks" in props:  # prior art
        refs = props["checks"]["items"]["properties"]["ref"]["enum"]
        return {"checks": [{"ref": r, "verdict": "clear", "counterexamples": []} for r in refs]}
    if "cards" in props:  # judge
        refs = props["cards"]["items"]["properties"]["ref"]["enum"]
        out = []
        for r in refs:
            surface = r.endswith("c01")
            out.append({"ref": r, **{f"{d}_differs": not surface for d in ("choices", "relationships", "outcomes")},
                        **{f"{d}_reason": "The new cost changes who acts and why." for d in
                           ("choices", "relationships", "outcomes")},
                        "failure_conditions_triggered": [], "coherence": "pass",
                        "coherence_reason": "The dilemma grows from the cost.", "runway_hurts_by_arc5": True,
                        "runway_reason": "The cost compounds with every win.",
                        "taste": [{"criterion": "T3", "evidence": "Patterns from two media combine coherently."},
                                  {"criterion": "T5", "evidence": "Claims a retelling without a revival source."}]})
        return {"cards": out}
    # generate
    _count["n"] += 1
    k = _count["n"]
    ids = props["source_transfer_ids"]["items"]["enum"]
    vocab = get_vocab()
    gates = [g for g in vocab.enum("power_combat.gate") if g != "other"]
    costs = [c for c in vocab.enum("power_combat.cost_of_power") if c != "other"]
    out = {"logline": f"A tollkeeper numbered {k} lends strangers borrowed courage and collects it back with interest.",
           "premise": f"In harbor city number {k}, a quiet tollkeeper can lend courage to anyone, but every loan returns "
                      "doubled and heavier, so each rescue deepens a debt the whole district must one day repay.",
           "engine": {"goal": "save the harbor district", "constraint": "every loan comes back doubled",
                      "strategy": "lend courage only to strangers", "benefit": "strangers become heroes overnight",
                      "cost": "the district inherits the debt", "dilemma": "each rescue mortgages the neighbors",
                      "dramatic_question": "Who pays when the debts come due?"},
           "what_changed": "The cost of power lands on the neighbors, not the hero.",
           "source_transfer_ids": ids,
           "consequences": {"choices": "She refuses rescues she cannot afford.",
                            "relationships": "Neighbors become creditors of her kindness.",
                            "outcomes": "Victory bankrupts the people it protects."},
           "profile": {"gate": gates[k % len(gates)], "cost_of_power": costs[(k * 3) % len(costs)],
                       "progression": "linear", "visible_counter": "numeric_level", "fight_medium": "energy",
                       "power_is": "collective"},
           "broken_rule": "power is always paid for by its user", "appetite": "stories about shared debts",
           "closest_existing": props["closest_existing"]["enum"][0],
           "why_not_a_clone": "The debt falls on bystanders, which changes every choice the lead makes.",
           "why_different": None, "revival_improvement": "Pacing fixed by a single escalating debt clock."
           if "FLOP TO REVIVE" in user else None}
    if "premortem" in props:
        src = props["premortem"]["items"]["properties"]["source_title_id"]["enum"][0]
        out["premortem"] = [{"risk": "The debt rule could feel arbitrary.", "source_title_id": src,
                             "mitigation": "Show the ledger on screen every episode."},
                            {"risk": "Pacing could stall between loans.", "source_title_id": src,
                             "mitigation": "One loan per arc, each larger than the last."}]
    return out


def clients(repo, name="run_i", budget=None, live=False):
    def make(key):
        mock = MockProvider(default=responder)
        if live:
            mock.live = True
            mock.billing = "subscription"
        return LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                         prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                         cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, name), budget=budget,
                         title_guard=(lambda tid: None) if live else None)
    return {k: make(k) for k in ("ideate_generate", "ideate_judge", "prior_art")}


@pytest.fixture
def pool(repo):
    _count["n"] = 0
    write_state(repo, state())
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope", "role_tags")}
              for t in state()["title"]]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    return repo


def test_ideate_produces_complete_gated_cards_and_a_sound_archive(pool):
    settings = load_settings(pool)
    res = run_ideate(pool, settings, get_vocab(), clients=clients(pool), embedder=MockEmbedder(), run_id="run_i",
                     generations=1)
    assert res.generations == [0] and res.candidates >= 10 and not res.stopped
    st = CanonicalStore(pool).state()
    eligible = {t["transfer_id"] for t in st["transfer"]}
    ideas, archive = st["idea"], st["archive"]
    assert ideas and archive
    for card in ideas:
        assert card["closest_existing"] and card["why_not_a_clone"] and all(card["engine"].values())  # AC-25
        assert set(card["atoms_used"]) <= eligible  # AC-26
        assert card["transformation"]["operator"] and all(card["consequences"].values())  # AC-27
    surface = [c for c in ideas if c["status"] == "rejected" and not c["gates"]["consequence_test"]["h1_pass"]]
    assert surface and res.rejected.get("H1", 0) >= 1  # AC-27/28: a surface change fails H1, logged by gate
    cells = [a["cell_key"] for a in archive]
    assert len(cells) == len(set(cells))  # AC-29
    champions = [c for c in ideas if c["status"] == "champion"]
    assert {c["idea_id"] for c in champions} == {a["idea_id"] for a in archive}
    for c in champions:
        assert "T5" not in c["taste"]["criteria_met"]  # no revival source -> claim dropped
        assert c["runway"]["hurts_by_arc5"] is True and c["premortem"]


def test_a_cells_fitness_never_decreases(pool):
    settings = load_settings(pool)
    run_ideate(pool, settings, get_vocab(), clients=clients(pool), embedder=MockEmbedder(), run_id="run_a",
               generations=1)
    before = {a["cell_key"]: a["fitness"] for a in CanonicalStore(pool).state()["archive"]}
    run_ideate(pool, settings, get_vocab(), clients=clients(pool, "run_b"), embedder=MockEmbedder(), run_id="run_b",
               generations=1)
    after = {a["cell_key"]: a["fitness"] for a in CanonicalStore(pool).state()["archive"]}
    assert set(before) <= set(after)
    assert all(after[k] >= before[k] for k in before)  # AC-29
    gens = {i["generation"] for i in CanonicalStore(pool).state()["idea"]}
    assert gens == {0, 1}  # the second run continued the archive


def test_the_call_cap_stops_ideation_cleanly(pool):
    settings = load_settings(pool)
    budget = Budget(None, None, None, calls_per_run=3, calls_per_title=3)
    res = run_ideate(pool, settings, get_vocab(), clients=clients(pool, budget=budget, live=True),
                     embedder=MockEmbedder(), run_id="run_cap", generations=2)
    assert res.stopped and "call cap" in res.stopped and res.generations == []


def test_ideas_report_hides_gold_titles(pool):
    settings = load_settings(pool)
    run_ideate(pool, settings, get_vocab(), clients=clients(pool), embedder=MockEmbedder(), run_id="run_r",
               generations=1)
    data = yaml.safe_load(pool.corpus_file.read_text())
    for t in data["titles"]:
        t["role_tags"] = ["gold", *t["role_tags"]]
    pool.corpus_file.write_text(yaml.safe_dump(data))
    (pool.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "pending", "runs_without_annotations": True}))
    text = write_report(pool)
    assert "# ANIMEDEX idea cards" in text and "[gold title]" in text
    assert "Ironvale Circuit" not in text and "Lantern Debt" not in text


def test_blind_packet_has_three_equal_arms_and_hides_the_key(pool):
    settings = load_settings(pool)
    run_ideate(pool, settings, get_vocab(), clients=clients(pool), embedder=MockEmbedder(), run_id="run_p",
               generations=1)
    cs = clients(pool, "run_pk")
    res = build_packet(pool, settings, get_vocab(), plain=cs["ideate_generate"], web=cs["ideate_generate"],
                       date="2026-09-27")
    n = res.per_arm
    text = (pool.root / res.packet).read_text()
    assert text.count("## C") == 3 * n and "idea." not in text and "T1 never done" in text
    key = json.loads((pool.root / res.key).read_text())
    assert sorted({v["arm"] for v in key.values()}) == ["animedex", "plain", "web"]
    assert res.key.startswith("data/blind/") and (pool.root / res.ratings).is_file()


def test_prior_art_counterexamples_cite_retrieved_pages_never_blocked_ones():
    from animedex.ideate.llm import prior_art_problems
    from animedex.pipeline.common import url_set

    urls = url_set(["https://example.com/show", "https://myanimelist.net/anime/9"])

    def out(url):
        return {"checks": [{"ref": "c1", "verdict": "counterexample",
                            "counterexamples": [{"title": "Show", "url": url, "match_note": "same system"}]}]}

    assert prior_art_problems(out("https://www.example.com/show/"), ["c1"], urls) == []  # same page, other spelling
    [blocked] = prior_art_problems(out("https://myanimelist.net/anime/9"), ["c1"], urls)
    assert "myanimelist.net pages are not an allowed source" in blocked
    assert "cite a URL" in prior_art_problems(out("https://elsewhere.example/x"), ["c1"], urls)[0]
