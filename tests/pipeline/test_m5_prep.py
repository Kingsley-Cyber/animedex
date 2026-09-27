"""M5 prep, the owner's "before M5 live runs" rulings (2026-09-27), offline on the mock provider:

- item 4, the call brief: opaque atom aliases, the nearest 10 titles, region flops, cell facts,
  capped and logged (AC-50);
- item 5, census-backed novelty only with 200 powered census rows (AC-51);
- item 6, the judge weighs why_different on premise-level graveyard matches (AC-52);
- item 7 + controls decision 1, fair baselines: one standard, the same rules, no web while
  generating, baseline 1 = the same loop with an empty brief, kept out of the archive (AC-53);
- item 8, ideation runs get 60 calls, other runs keep 40 (AC-54);
- controls A8, contested-evidence flags in ideas.md, never in the packet (AC-55).
"""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest
import yaml

from animedex import SCHEMA_VERSION
from animedex.budget import Budget
from animedex.config import ModelSpec, load_settings
from animedex.embeddings.base import MockEmbedder
from animedex.ideate.brief import BriefOverCap, build_brief, redact_titles
from animedex.ideate.context import Context, build_context, cell_key
from animedex.ideate.flags import EvidenceFlags
from animedex.ideate.gates import Similarity, run_gates
from animedex.ideate.llm import judge_problems
from animedex.ideate.packet import build_packet, single_user
from animedex.ideate.report import write_report
from animedex.ideate.run import baseline_file, ideation_budget, run_ideate
from animedex.ideate.standard import render_prompt, taste_standard
from animedex.ideate.steering import SteeringError, load_rules, rule_lines
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.canonical import CanonicalStore
from animedex.store.jsonl import read_jsonl
from animedex.store.runlog import RunLog
from tests.conftest import make_census, make_title, prov, write_state
from tests.pipeline import test_ideate as base
from tests.pipeline.test_ideate import T1, T2, T3, responder, state

pytestmark = pytest.mark.pipeline


@pytest.fixture
def pool(repo):
    """The synthetic corpus of test_ideate.py (three titles, four eligible atoms, one execution-level flop)."""
    base._count["n"] = 0
    write_state(repo, state())
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope", "role_tags")}
              for t in state()["title"]]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    return repo

GENERATE_REF = re.compile(r"^(bl\.)?g\d+c\d+(\.rework)?$")
RULES = [{"id": "rule.001", "rule": "The hero is legibly the strongest without holding the biggest number.",
          "strength": "hard"},
         {"id": "rule.002", "rule": "Prefer costs that land on relationships.", "strength": "soft"}]


def kind(schema: dict) -> str:
    props = schema.get("properties", {})
    return ("single" if "premises" in props else "prior_art" if "checks" in props else
            "judge" if "cards" in props else "generate")


def make_clients(repo, answer, name="run_m5", budget=None, live=False, seen=None):
    def recording(system, user, schema, params):
        if seen is not None:
            seen.append({"kind": kind(schema), "params": dict(params), "user": user, "system": system})
        return answer(system, user, schema, params)

    def make(key):
        mock = MockProvider(default=recording)
        if live:
            mock.live = True
            mock.billing = "subscription"
        return LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                         prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                         cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, name), budget=budget,
                         title_guard=(lambda tid: None) if live else None)
    return {k: make(k) for k in ("ideate_generate", "ideate_judge", "prior_art")}


def generate_users(cs) -> list[str]:
    return [c["user"] for c in cs["ideate_generate"].provider.calls if GENERATE_REF.match(c["record_id"])]


def run(repo, name, *, index=True, generations=1, answer=responder, seen=None, settings=None):
    settings = settings or load_settings(repo)
    cs = make_clients(repo, answer, name, seen=seen)
    res = run_ideate(repo, settings, get_vocab(), clients=cs, embedder=MockEmbedder(), run_id=name,
                     generations=generations, index=index)
    return res, cs


# ---------------------------------------------------------------- item 4: the call brief (AC-50)
def test_generate_calls_get_a_capped_brief_with_opaque_atom_ids(pool):
    res, cs = run(pool, "run_brief")
    st = CanonicalStore(pool).state()
    transfer_ids = {t["transfer_id"] for t in st["transfer"]}
    users = generate_users(cs)
    assert users and res.candidates
    for user in users:
        assert not any(t in user for t in transfer_ids)  # opaque aliases only, never a transfer id
        atom_lines = [line for line in user.splitlines() if line.startswith("atom ")]
        assert atom_lines and all(re.match(r"^atom A\d: ", line) for line in atom_lines)
        assert not any(tid in line for line in atom_lines for tid in (T1, T2, T3))  # no source title
        assert "#" not in user and "**" not in user  # key: value lines, not Markdown
        assert all(": " in line for line in user.splitlines())
        assert len(user.split()) <= 600
    for card in st["idea"]:  # the aliases map back to real transfer ids on the card
        assert card["transformation"]["source_transfer_ids"] and set(card["transformation"]["source_transfer_ids"]) \
            <= transfer_ids and card["atoms_used"] == card["transformation"]["source_transfer_ids"]
    logged = [json.loads(line) for line in (pool.raw_runs / "run_brief" / "calls.jsonl").read_text().splitlines()]
    briefs = [e["meta"]["brief"] for e in logged if GENERATE_REF.match(e["record_id"])]
    assert briefs and all(b["words"] <= 600 and b["est_tokens"] > 0 for b in briefs)  # size logged per call


def _synthetic_ctx(n_titles: int = 12) -> Context:
    vocab = get_vocab()
    gates = [g for g in vocab.enum("power_combat.gate") if g != "other"]
    titles, struct = {}, {}
    for i in range(n_titles):
        tid = f"synthetic_title_{i:02d}_20{10 + i}"
        titles[tid] = {"title_id": tid, "title": f"Synthetic {i}", "medium": "anime",
                       "core": {"logline_hook": {"value": f"a synthetic hook number {i}"}}}
        struct[tid] = {f"power_combat.gate={gates[i % len(gates)]}", f"bridge:concept_{i}"}
    graveyard = [
        {"title_id": "flop_in_region_2015", "label": "flop", "failure_level": "premise", "failure_reason": "r1",
         "structural": [f"power_combat.gate={gates[0]}"], "bridge": [], "warns": True},
        {"title_id": "flop_far_away_2016", "label": "mixed", "failure_level": "execution", "failure_reason": "r2",
         "structural": ["power_combat.gate=none_of_these"], "bridge": [], "warns": False},
    ]
    return Context(titles=titles, outcomes={}, pool=[], title_struct=struct, title_proc={}, graveyard=graveyard,
                   lanes={"imported": set(), "export": set()}, pair_counts=Counter(), concept_pairs=set(),
                   adequate=False, themes=[], names=(set(), set()))


def test_brief_lists_only_the_nearest_ten_titles_and_the_region_flops(repo):
    settings = load_settings(repo)
    ctx = _synthetic_ctx()
    gates = [g for g in get_vocab().enum("power_combat.gate") if g != "other"]
    target = {"gate": gates[0], "cost_of_power": "memory", "progression": "linear"}
    atom = {"transfer_id": "synthetic_title_03_2013.t.001", "title_id": "synthetic_title_03_2013", "medium": "anime",
            "pattern": "A synthetic pattern.", "bridge": ["concept_3"], "essential_conditions": ["e"],
            "variable_details": ["v"], "failure_conditions": ["f"]}
    brief = build_brief(ctx, settings, theme="t?", operator="change_rule", target=target, atoms=[atom])
    titles = [line.split(":")[0].removeprefix("title ") for line in brief.text.splitlines() if line.startswith("title ")]
    assert len(titles) == 10 == len(brief.title_ids)
    # same gate or the atom's bridge first (Jaccard), then ties by id
    assert titles[:3] == ["synthetic_title_00_2010", "synthetic_title_03_2013", "synthetic_title_09_2019"]
    assert titles[3:] == sorted(titles[3:])
    assert brief.flop_ids == ["flop_in_region_2015"] and "flop_far_away_2016" not in brief.text
    assert brief.aliases == {"A1": "synthetic_title_03_2013.t.001"} and "synthetic_title_03_2013.t.001" not in brief.text
    assert brief.meta["graveyard_region"] == "overlap" and brief.meta["titles"] == 10


def test_brief_carries_the_cells_lanes_and_prior_art_and_falls_back_for_flops(repo):
    settings = load_settings(repo)
    ctx = _synthetic_ctx()
    target = {"gate": "mutation", "cost_of_power": "moral", "progression": "hybrid"}  # no flop overlaps it
    key = cell_key(target, settings.ideate["grid_dims"])
    ctx.lanes = {"imported": {"concept_3"}, "export": set()}
    ctx.cell_titles[key], ctx.cell_census[key] = 2, 7
    ctx.prior_art_by_cell = {key: [{"claim_kind": "T1", "verdict": "counterexample", "counterexamples": [
        {"title": "Some Earlier Work", "url": "https://example.org/w", "match_note": "the same memory cost"}]}]}
    atom = {"transfer_id": "synthetic_title_03_2013.t.001", "title_id": "synthetic_title_03_2013", "medium": "anime",
            "pattern": "A synthetic pattern.", "bridge": ["concept_3"], "essential_conditions": ["e"],
            "variable_details": ["v"], "failure_conditions": ["f"]}
    lines = build_brief(ctx, settings, theme="t?", operator="change_rule", target=target, atoms=[atom]).text.splitlines()
    assert "lanes: imported concept_3; export none" in lines
    assert "prior_art: T1 counterexample; done before: Some Earlier Work (the same memory cost)" in lines
    assert any(line.startswith("cell: corpus titles 2; census titles 7; zeros untrusted") for line in lines)
    fallback = build_brief(ctx, settings, theme="t?", operator="change_rule", target=target, atoms=[atom])
    assert fallback.meta["graveyard_region"] == "fallback" and fallback.flop_ids == ["flop_far_away_2016",
                                                                                      "flop_in_region_2015"]


def test_brief_is_capped_optional_lines_go_first_and_an_oversized_core_is_refused(repo):
    settings = load_settings(repo)
    ctx = _synthetic_ctx()
    target = {"gate": "innate", "cost_of_power": "memory", "progression": "linear"}
    full = build_brief(ctx, settings, theme="t?", operator="change_rule", target=target, atoms=[])
    settings.ideate["brief_max_words"] = full.meta["words"] - 10
    trimmed = build_brief(ctx, settings, theme="t?", operator="change_rule", target=target, atoms=[])
    assert trimmed.meta["words"] <= settings.ideate["brief_max_words"] and trimmed.meta["trimmed_lines"] >= 1
    assert len(trimmed.title_ids) < len(full.title_ids) and trimmed.flop_ids == full.flop_ids  # titles trimmed first
    settings.ideate["brief_max_words"] = 5
    with pytest.raises(BriefOverCap):
        build_brief(ctx, settings, theme="a theme far too long for five words", operator="change_rule", target=target,
                    atoms=[])


def test_an_over_cap_brief_rejects_the_card_before_any_call(pool):
    settings = load_settings(pool)
    settings.ideate["brief_max_words"] = 5
    res, cs = run(pool, "run_cap5", settings=settings)
    assert not generate_users(cs) and res.rejected.get("brief", 0) == 12


# ---------------------------------------------------------------- item 5: novelty needs 200 powered census rows (AC-51)
def _one_title_card(ctx: Context) -> dict:
    atom = next(a for a in ctx.pool if a["title_id"] == T1)
    return {"logline": "A synthetic logline.", "premise": "A synthetic premise.", "why_different": None,
            "profile": {"gate": "contract", "cost_of_power": "lifespan", "progression": "linear",
                        "visible_counter": "collectible_count", "fight_medium": "energy", "power_is": "collective"},
            "bridge": sorted(atom["bridge"]), "_atoms": [atom]}


@pytest.mark.parametrize("rows, trusted", [(199, False), (200, True)])
def test_census_backed_zero_pairs_count_only_from_200_powered_rows(pool, rows, trusted):
    CanonicalStore(pool).write("census", make_census(rows))
    ctx = build_context(pool, load_settings(pool), get_vocab())
    assert ctx.powered_census == rows and ctx.census_zeros_trusted is trusted and ctx.adequate is trusted
    g = run_gates(_one_title_card(ctx), ctx, Similarity(MockEmbedder(), ctx), load_settings(pool).gates)
    assert g.novel_combo is trusted  # atoms from one title: only a census-backed enum zero could make it novel
    if trusted:
        assert g.novelty_basis.startswith("never together")
    else:
        assert g.fatal and "200 powered census rows (have 199)" in g.fatal[0]


def test_unpowered_census_rows_never_count_and_bridge_pairs_still_do(pool):
    CanonicalStore(pool).write("census", make_census(250, powered=False))
    ctx = build_context(pool, load_settings(pool), get_vocab())
    assert ctx.census_size == 250 and ctx.powered_census == 0 and not ctx.census_zeros_trusted
    card = _one_title_card(ctx)
    two = [next(a for a in ctx.pool if a["title_id"] == T1), next(a for a in ctx.pool if a["title_id"] == T2)]
    card.update(_atoms=two, bridge=sorted({b for a in two for b in a["bridge"]}))
    g = run_gates(card, ctx, Similarity(MockEmbedder(), ctx), load_settings(pool).gates)
    assert g.novel_combo and g.novelty_basis.startswith("patterns never combined")  # the bridge route stays open


# ---------------------------------------------------------------- item 6: the judge weighs why_different (AC-52)
T4 = "hollow_ledger_2014"


def _flop_state() -> dict:
    """A premise-level flop that generated cards match on gate + cost (graveyard), without cloning any title."""
    st = state()

    def set_enums(rec, values):
        for path, value in values.items():
            block, name = path.split(".")
            rec[block][name]["value"] = value

    others = {"power_combat.gate": "trained", "power_combat.cost_of_power": "lifespan",
              "power_combat.progression": "hybrid", "power_combat.visible_counter": "rank_tier",
              "power_combat.fight_medium": "weapon"}
    for t in st["title"][:2]:
        set_enums(t, others)
    flop = make_title(T4, "Hollow Ledger", modules=("power_combat", "relationships", "sensory", "anime_production",
                                                    "series_engine"), role_tags=("flop",))
    set_enums(flop, {"power_combat.gate": "contract", "power_combat.cost_of_power": "memory",
                     "power_combat.progression": "lateral", "power_combat.visible_counter": "numeric_level",
                     "power_combat.fight_medium": "energy", "relationships.power_is": "collective"})
    st["title"].append(flop)
    st["outcome"].append({"title_id": T4, "label": "flop", "signals": [], "confounders": {
        "studio": "", "budget_signal": "", "source_popularity": "", "platform": "", "release_context": ""},
        "failure_reason": "Audiences rejected a hero who pays in memory for every win.",
        "failure_level": "premise", "failure_evidence": "Reviews blame the premise itself.",
        "failure_evidence_ref": "https://example.org/flop", "failure_level_source": "verify",
        "provenance": prov("VERIFY")})
    for t in st["transfer"]:  # one bridge concept per pattern: cards stay close enough to the flop to match it
        t["bridge"] = t["bridge"][:1] if t["bridge"][0] != "cost_of_advancement" else t["bridge"][1:]
    return st


def _flop_answer(judge_passes_rework: bool):
    def answer(system, user, schema, params):
        out = responder(system, user, schema, params)
        k = kind(schema)
        if k == "generate":
            out["profile"] = {"gate": "contract", "cost_of_power": "memory", "progression": "linear",
                              "visible_counter": "numeric_level", "fight_medium": "energy", "power_is": "collective"}
            out["why_different"] = ("The memory cost resets each arc, so the loss the flop dwelt on never piles up."
                                    if "rework: why_different" in user else "This time it is better.")
        if k == "judge":
            for card in out["cards"]:
                block = user.split(f"=== CARD {card['ref']}")[1].split("=== CARD")[0]
                if "graveyard match " in block:
                    reworked = "never piles up" in block
                    ok = reworked and judge_passes_rework
                    card.update(why_different_verdict="pass" if ok else "fail",
                                why_different_reason="It answers the recorded failure." if ok else
                                "It restates the premise; the recorded failure stays.")
        return out
    return answer


def _flop_pool(pool):
    for name in ("titles.jsonl", "outcomes.jsonl"):
        (pool.canonical / name).unlink(missing_ok=True)
    write_state(pool, _flop_state())
    corpus = yaml.safe_load(pool.corpus_file.read_text())
    corpus["titles"].append({k: _flop_state()["title"][-1][k] for k in ("title_id", "title", "year", "medium",
                                                                         "format", "scope", "role_tags")})
    pool.corpus_file.write_text(yaml.safe_dump(corpus))
    return pool


@pytest.mark.parametrize("passes", [False, True])
def test_why_different_is_judged_against_the_flops_recorded_failure(pool, passes):
    _flop_pool(pool)
    seen: list[dict] = []
    res, _ = run(pool, f"run_wd{int(passes)}", answer=_flop_answer(passes), seen=seen)
    judged = [c["user"] for c in seen if c["kind"] == "judge" and "graveyard match " in c["user"]]
    assert judged, "no card reached the judge with a premise-level match"
    assert f"graveyard match {T4}: flop; recorded failure (premise): Audiences rejected a hero" in judged[0]
    assert "why_different: This time it is better." in judged[0]  # the card's own text, not just "present"
    ideas = [i for i in CanonicalStore(pool).state()["idea"] if T4 in i["gates"]["graveyard_hits"]
             and i["gates"]["consequence_test"]["h1_pass"]]  # matched cards the judge weighed
    assert ideas and res.reworks >= len(ideas)  # a fail earns one rework
    if passes:
        assert all(i["status"] != "rejected" for i in ideas)
        assert all("never piles up" in i["why_different"] for i in ideas)
    else:  # not blank is no longer a pass: a second fail rejects
        assert all(i["status"] == "rejected" for i in ideas) and res.rejected.get("judge", 0) == len(ideas)


def test_the_judge_must_answer_why_different_on_a_match():
    card = {"ref": "g0c01", "why_different_verdict": "not_applicable", "why_different_reason": ""}
    assert any("why_different pass or fail" in p for p in judge_problems({"cards": [card]}, ["g0c01"], ["g0c01"]))
    assert not [p for p in judge_problems({"cards": [card]}, ["g0c01"], []) if "why_different" in p]


# ---------------------------------------------------------------- item 7: fair baselines (AC-53)
def test_every_arm_reads_the_same_taste_standard(repo):
    standard = taste_standard(repo)
    generate = render_prompt(repo, "ideate_generate.md").system
    single = render_prompt(repo, "baseline_single.md", n=15).system
    assert "T1 Never done before." in standard and "Hard fail" in standard
    assert generate.count(standard) == 1 and single.count(standard) == 1  # one text, word for word
    assert "{taste_standard}" not in generate + single and not (repo.prompts / "baseline_web.md").exists()


def _write_rules(paths):
    (paths.root / "steering").mkdir(exist_ok=True)
    (paths.root / "steering" / "rules.yaml").write_text(yaml.safe_dump(RULES))


def test_steering_rules_reach_every_arm_and_no_arm_searches_while_generating(pool):
    _write_rules(pool)
    CanonicalStore(pool).write("census", make_census(200))
    lines = rule_lines(load_rules(pool))
    assert lines == [f"rule rule.001 (hard): {RULES[0]['rule']}", f"rule rule.002 (soft): {RULES[1]['rule']}"]
    seen: list[dict] = []
    run(pool, "run_sa", seen=seen)
    run(pool, "run_sb", index=False, seen=seen)
    cs = make_clients(pool, responder, "run_sp", seen=seen)
    build_packet(pool, load_settings(pool), get_vocab(), single=cs["ideate_generate"], prior_art=cs["prior_art"],
                 date="2026-09-28")
    arms = {"animedex": [c for c in seen if c["kind"] == "generate" and "patterns: none given" not in c["user"]],
            "baseline_loop": [c for c in seen if c["kind"] == "generate" and "patterns: none given" in c["user"]],
            "baseline_single": [c for c in seen if c["kind"] == "single"]}
    assert all(arms.values())
    for calls in arms.values():
        for c in calls:
            assert all(line in c["user"].splitlines() for line in lines)  # the same rules, the same words
            assert "web" not in c["params"]  # no arm searches the web while generating
    single = arms["baseline_single"][0]["user"]
    assert single == single_user(int(re.search(r"Write (\d+) premises", single).group(1)), lines)
    assert all("web" in c["params"] for c in seen if c["kind"] == "prior_art")  # the one web step, the same for all


def test_a_malformed_rules_file_stops_the_run(repo):
    (repo.root / "steering").mkdir()
    (repo.root / "steering" / "rules.yaml").write_text(yaml.safe_dump([{"id": "rule.001", "rule": "x",
                                                                         "strength": "maybe"}]))
    with pytest.raises(SteeringError):
        load_rules(repo)


def test_baseline_loop_cards_never_enter_the_archive(pool):
    CanonicalStore(pool).write("census", make_census(200))
    run(pool, "run_arch")
    before = CanonicalStore(pool).state()
    res, cs = run(pool, "run_bl", index=False, generations=2)
    after = CanonicalStore(pool).state()
    assert after["idea"] == before["idea"] and after["archive"] == before["archive"]  # canonical untouched
    cards = read_jsonl(baseline_file(pool, "ideas"))
    assert cards and res.passed and res.placed == 0 and res.champions == 0
    assert all(c["arm"] == "baseline_loop" and c["status"] != "champion" and c["atoms_used"] == [] for c in cards)
    assert {c["closest_existing"] for c in cards} <= {t["title_id"] for t in before["title"]}  # measured, real ids
    ids = {c["idea_id"] for c in cards}
    assert not ids & {a["idea_id"] for a in after["archive"]}
    for user in generate_users(cs):  # an empty brief: no index material at all
        assert "patterns: none given" in user
        assert not any(tid in user for tid in (T1, T2, T3))
        assert not any(line.startswith(("atom ", "title ", "flop ", "cell:", "lanes:", "prior_art:"))
                       for line in user.splitlines())
    write_report(pool)
    assert not any(i in (pool.reports / "ideas.md").read_text() for i in ids)  # ideas.md lists ANIMEDEX cards only


def test_a_card_triggers_only_its_own_atoms_failure_conditions(pool):
    CanonicalStore(pool).write("census", make_census(200))

    def inventive(system, user, schema, params):
        out = responder(system, user, schema, params)
        for card in out.get("cards") or []:
            card["failure_conditions_triggered"] = ["a condition no pattern of this card has"]
        return out

    res, _ = run(pool, "run_fc", index=False, answer=inventive)  # baseline 1: no atoms, so nothing to trigger
    assert res.passed and not res.rejected.get("judge") and res.reworks == 0


def test_baseline_rework_notes_carry_no_title_ids(pool):
    ctx = build_context(pool, load_settings(pool), get_vocab())
    note = f"clone: structural overlap 0.81 with {T1} (limit 0.7); graveyard: matches premise-level flop(s) ['{T3}']"
    assert T1 not in redact_titles(note, ctx) and T3 not in redact_titles(note, ctx)


# ---------------------------------------------------------------- item 8: 60 calls per ideation run (AC-54)
def test_ideation_runs_get_60_calls_other_runs_keep_40(pool):
    settings = load_settings(pool)
    assert Budget.from_settings(settings).calls_per_run == 40 and ideation_budget(settings).calls_per_run == 60
    budget = ideation_budget(settings)
    cs = make_clients(pool, responder, "run_60", budget=budget, live=True)
    res = run_ideate(pool, settings, get_vocab(), clients=cs, embedder=MockEmbedder(), run_id="run_60",
                     generations=6)
    made = sum(len(c.provider.calls) for c in cs.values())
    assert res.stopped and "60/60" in res.stopped and made == budget.calls_run == 60  # shared by all three slots
    assert len(res.generations) >= 3  # one capped run covers three generations


# ---------------------------------------------------------------- controls A8: contested-evidence flags (AC-55)
def test_cards_on_contested_atoms_carry_a_flag_in_ideas_md_but_never_in_the_packet(pool):
    CanonicalStore(pool).write("census", make_census(200))
    run(pool, "run_fl")
    run(pool, "run_flb", index=False)
    store = CanonicalStore(pool)
    st = store.state()
    champion = next(i for i in st["idea"] if i["status"] == "champion")
    source = next(t["source_atom_id"] for t in st["transfer"] if t["transfer_id"] == champion["atoms_used"][0])
    contested = {"target_id": source, "target_type": "mechanism", "verdict": "CONTESTED", "reasons": ["overreach"],
                 "revision": None, "provenance": prov("CHECK", run_id="run_zz_recheck")}
    store.write("check", [*st["check"], contested])
    text = write_report(pool)
    assert "**Evidence flag.**" in text and f"{source} (latest CHECK CONTESTED)" in text
    cs = make_clients(pool, responder, "run_flp")
    res = build_packet(pool, load_settings(pool), get_vocab(), single=cs["ideate_generate"], prior_art=cs["prior_art"],
                       date="2026-09-29")
    packet = (pool.root / res.packet).read_text()
    assert "Evidence flag" not in packet and source not in packet and "CONTESTED" not in packet


def test_flags_cover_contested_explanations_missing_atoms_and_the_m6_hook():
    atom = {"atom_id": "ironvale_circuit_2021.m.001", "explanation": "settled", "support": {"status": "profile_only"}}
    st = {"transfer": [{"transfer_id": "ironvale_circuit_2021.t.001", "source_atom_id": atom["atom_id"]}],
          "mechanism": [atom], "check": []}
    card = {"atoms_used": ["ironvale_circuit_2021.t.001", "ironvale_circuit_2021.t.002"]}
    assert EvidenceFlags(st).for_card(card) == ["ironvale_circuit_2021.t.002 (no longer in the index)"]
    atom.update(explanation="contested", support={"status": "contradicted"})
    [flag, _] = EvidenceFlags(st).for_card(card)
    assert "explanation contested" in flag and "contradicted by episodes" in flag


def test_cell_key_and_census_cell_counts(pool):
    CanonicalStore(pool).write("census", make_census(3))
    ctx = build_context(pool, load_settings(pool), get_vocab())
    dims = load_settings(pool).ideate["grid_dims"]
    key = cell_key({"gate": "artifact", "cost_of_power": "resource", "progression": "hybrid"}, dims)
    assert ctx.cell_census[key] == 3 and sum(ctx.cell_titles.values()) >= 1
