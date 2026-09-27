"""Retrodiction backtest (controls plan B1; statistics as gates, item 8) offline on mock providers.

AC-BT-1 held-out titles never enter the corpus or canonical data; AC-BT-2 the judge's inputs name no
title; AC-BT-3 the report shows both accuracies and their difference, with the exact McNemar p-value
and the sample size needed; AC-BT-4 a rerun is served from the cache. Synthetic titles only (09).
"""

from __future__ import annotations

import json
import re

import pytest
import yaml
from typer.testing import CliRunner

from animedex import SCHEMA_VERSION, stats
from animedex.backtest import BacktestPaths, add_titles, load_titles, run_backtest, score
from animedex.catalog.reception import Reception
from animedex.cli import app
from animedex.config import ModelSpec, load_settings
from animedex.guards import LiveRunRefused, check_live_title
from animedex.ontology import get_vocab
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.store.cache import ResponseCache
from animedex.store.runlog import RunLog
from tests.conftest import make_title, prov, write_state
from tests.pipeline.test_gather import WebMock
from tests.pipeline.test_ideate import T1, T2, T3, state
from tests.pipeline.test_p1 import make_draft

pytestmark = pytest.mark.pipeline

T4 = "hollow_ledger_2014"
WIKI = "https://en.wikipedia.org/wiki/Synthetic_Page"
FLOP_KIT = {"gate": "contract", "cost_of_power": "memory", "progression": "linear", "visible_counter": "gauge",
            "fight_medium": "energy"}
HIT_KIT = {"gate": "innate", "cost_of_power": "physical_toll", "progression": "lateral",
           "visible_counter": "numeric_level", "fight_medium": "unarmed"}   # T1 and T2's kit (both hits)
HELD = {  # title -> (kit, premise abstraction, outcome label or None)
    "Salt Bridge": (FLOP_KIT, "a debtor trades memories for strength and forgets the people she saves", "flop"),
    "Night Loom": (HIT_KIT, "a courier lends courage to strangers and collects it back with interest", "hit"),
    "Glass Harbor": (HIT_KIT, "a salvager bargains with tides of glass for one more year of life", None),
    # INTERPRET already refuses a premise abstraction that names its own title or a proper noun; these two pass
    # it but name another title (indexed, or held out), which the backtest's own check catches
    "Paper Crown": (HIT_KIT, "an heir rebuilds a hollow ledger of debts to win the throne", "hit"),
    "Tin Orchard": (HIT_KIT, "a keeper trades her voice for a storm over the night loom", "hit"),
}
YEARS = {"Salt Bridge": 2022, "Night Loom": 2021, "Glass Harbor": 2019, "Paper Crown": 2020, "Tin Orchard": 2023}


def _tid(title: str) -> str:
    return f"{title.lower().replace(' ', '_')}_{YEARS[title]}"


def corpus_state() -> dict:
    """The ideation corpus (two hits, a film flop) plus a premise-level flop that shares FLOP_KIT."""
    st = state()
    flop = make_title(T4, "Hollow Ledger", modules=("power_combat", "sensory", "anime_production", "series_engine"),
                      role_tags=("flop",))
    for name, value in FLOP_KIT.items():
        flop["power_combat"][name]["value"] = value
    st["title"].append(flop)
    st["outcome"].append({
        "title_id": T4, "label": "flop", "signals": [], "confounders": {
            "studio": "", "budget_signal": "", "source_popularity": "", "platform": "", "release_context": ""},
        "failure_reason": "Audiences rejected a hero who pays in memory for every win.", "failure_level": "premise",
        "failure_evidence": "Reviews blame the premise itself.", "failure_evidence_ref": "https://example.org/flop",
        "failure_level_source": "verify", "failure_patterns": [
            {"pattern": "promise_broken", "source_ref": "https://example.org/flop", "note": "the cost stops mattering"}],
        "provenance": prov("VERIFY")})
    return st


def answer(system, user, schema, params):
    props = schema.get("properties", {})
    if "characters" in props:  # GATHER: one cited character, so its name joins the name-leak list
        return {"facts": [], "reception": [], "characters": [{"role": "protagonist", "name": "Marisol Vey", "facts": [
            {"field": "origin", "value": "grew up in a flooded orchard", "season": None, "episode": None,
             "source_url": WIKI, "scope": "in_scope"}]}]}
    if "evidence" in props:  # INTERPRET
        title = re.search(r"^Title: (.+?) \(", user, re.M).group(1)
        kit, premise, label = HELD[title]
        draft = make_draft()
        for name, value in kit.items():
            draft["power_combat"][name]["value"] = value
        draft["core"]["premise_abstraction"]["value"] = premise
        draft["evidence"] = []
        draft["outcome"] = None if label is None else {
            "label": label, "signals": [{"metric": "AniList average", "value": "61", "fact_id": "A01"}],
            "failure_reason": None if label == "hit" else "The premise wore thin fast.",
            "failure_level": None if label == "hit" else "premise", "failure_evidence": None,
            "failure_evidence_fact": None, "confounders": {k: "" for k in ("studio", "budget_signal",
                                                                           "source_popularity", "platform",
                                                                           "release_context")}}
        return draft
    if "predictions" in props:  # the judge: always "hit" blind; with the index, follow the nearest neighbour
        refs = props["predictions"]["items"]["properties"]["ref"]["enum"]
        index = "condition: index" in user
        out = []
        for ref in refs:
            first = re.search(rf"^{ref}\.N1: outcome (\w+)", user, re.M)
            out.append({"ref": ref, "label": first.group(1) if index and first else "hit",
                        "reason": "Premises like this one landed this way."})
        return {"predictions": out}
    raise AssertionError(f"unexpected schema {sorted(props)}")


def clients(repo, name="run_bt"):
    def make(provider):
        return LLMClient(provider=provider, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                         prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                         cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, name))
    return {"gather": make(WebMock({WIKI}, default=answer)), "interpret": make(MockProvider(default=answer)),
            "ideate_judge": make(MockProvider(default=answer))}


def reception(entry):
    return [Reception(source="anilist", mal_id=None, anilist_id=1, score=61.0, scorers=None, rank=None, popularity=900,
                      url=f"https://anilist.co/anime/{entry.year}", fetched_at="2026-09-27T00:00:00+00:00")], []


@pytest.fixture
def held(repo):
    write_state(repo, corpus_state())
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope", "role_tags")}
              for t in corpus_state()["title"]]
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    entries = [{"title_id": _tid(t), "title": t, "year": YEARS[t], "medium": "anime", "format": "serialized",
                "scope": {"version": "synthetic TV", "seasons": [1], "numbering": "broadcast"}, "role_tags": []}
               for t in HELD]
    home = BacktestPaths(repo.root).home
    home.mkdir(parents=True)
    (home / "titles.yaml").write_text(yaml.safe_dump({"titles": entries}))
    return repo


def run(repo, name="run_bt"):
    cs = clients(repo, name)
    res = run_backtest(repo, load_settings(repo), get_vocab(), clients=cs, run_id=name, reception=reception,
                       created_at="2026-09-27T12:00:00+00:00")
    return res, cs


def test_backtest_scores_both_briefs_and_reports_the_binomial_test(held):
    corpus_before = held.corpus_file.read_text()
    canonical_before = (held.canonical / "titles.jsonl").read_text()
    res, cs = run(held)
    assert res.titles == 5 and res.gathered == 5 and res.interpreted == 5
    # scored: the flop (blank says hit, the index's nearest neighbour is the premise-level flop) and a hit
    assert res.predictions == {_tid("Salt Bridge"): {"label": "flop", "blank": "hit", "index": "flop"},
                               _tid("Night Loom"): {"label": "hit", "blank": "hit", "index": "hit"}}
    why = dict(res.excluded)
    assert why[_tid("Glass Harbor")].startswith("no reception-backed outcome label")
    assert why[_tid("Paper Crown")].startswith("name leak") and "hollow ledger" in why[_tid("Paper Crown")]
    assert why[_tid("Tin Orchard")].startswith("name leak") and "night loom" in why[_tid("Tin Orchard")]
    s = res.summary  # AC-BT-3
    assert (s["n"], s["accuracy_blank"], s["accuracy_index"], s["difference"]) == (2, 0.5, 1.0, 0.5)
    assert (s["only_index"], s["only_blank"], s["p_value"]) == (1, 0, stats.mcnemar(1, 0))
    assert s["sample_size_needed"] == stats.sample_size_needed(1, 0, 2) and s["sample_size_needed"] > 2
    report = (held.reports / "backtest.md").read_text()
    assert "| Accuracy | 0.50 | 1.00 |" in report and "Difference (index minus blank): +0.50." in report
    assert "McNemar p-value" in report and f"{s['sample_size_needed']} titles." in report
    stored = json.loads((held.build / "stats" / "backtest.json").read_text())
    assert stored["n"] == 2 and stored["judge_calls"] == {"blank": 1, "index": 1}
    # AC-BT-1: nothing reached the corpus, the canonical data or the pipeline's candidates
    assert held.corpus_file.read_text() == corpus_before
    assert (held.canonical / "titles.jsonl").read_text() == canonical_before
    assert not held.candidates.exists()
    assert (BacktestPaths(held.root).home / "gathered" / f"{_tid('Salt Bridge')}.json").is_file()
    # AC-BT-2: the judge's inputs name no title, held out or indexed, and no character
    judged = [c["user"] for c in cs["ideate_judge"].provider.calls]
    assert len(judged) == 2 and "condition: blank" in judged[0] and "condition: index" in judged[1]
    names = [*HELD, *(_tid(t) for t in HELD), "Hollow Ledger", "Ironvale", "Lantern", "Glass Meridian", T1, T2, T3, T4,
             "Marisol"]
    for user in judged:
        assert not [n for n in names if n.lower() in user.lower()]
    index = judged[1]
    assert "B1.N1: outcome hit; shares" in index  # titles in id order: night_loom_2021, then salt_bridge_2022
    assert "B2.N1: outcome flop; shares" in index and "failure premise; patterns promise_broken" in index
    assert "reason Audiences rejected a hero" in index and "premise a debtor trades memories" in index


def test_a_rerun_is_served_from_the_cache(held):
    run(held)
    again, cs = run(held, "run_bt2")  # outputs exist: nothing runs again; the judge answers come from the cache
    assert sum(len(c.provider.calls) for c in cs.values()) == 0 and again.summary["n"] == 2
    home = BacktestPaths(held.root).home
    for sub in ("gathered", "interpret"):  # even rebuilt from scratch, every call is a cache hit (AC-BT-4)
        for f in (home / sub).glob("*.json"):
            f.unlink()
    third, cs = run(held, "run_bt3")
    assert sum(len(c.provider.calls) for c in cs.values()) == 0 and third.summary == again.summary


def test_held_out_titles_get_their_own_scoped_list_and_guard(held):
    from animedex.catalog.backfill import plan_backfill
    from animedex.guards import load_corpus
    from tests.unit.test_catalog import fake_anilist

    settings, vocab = load_settings(held), get_vocab()
    bp = BacktestPaths(held.root)
    check_live_title(bp, settings, vocab, _tid("Salt Bridge"))  # a declared scope, in the backtest list
    with pytest.raises(LiveRunRefused):
        check_live_title(bp, settings, vocab, T4)  # an indexed title is not a backtest title
    iron = {"title_id": "iron_tide_2015", "title": "Iron Tide", "year": 2015, "medium": "anime",
            "format": "serialized", "scope": {"version": "TV", "seasons": [1, 2], "numbering": "broadcast"},
            "role_tags": [], "catalog_ref": "anilist:1"}
    corpus = [e.model_dump(mode="json", exclude_none=True) for e in load_corpus(held).values()]
    held.corpus_file.write_text(yaml.safe_dump({"titles": [*corpus, iron]}))
    corpus_text = held.corpus_file.read_text()
    plan = plan_backfill(fake_anilist(), ["Iron Tide (2015)", "Glass Harbor", "Iron Tide (2024)"], load_corpus(held),
                         suggest=False)
    added, refused = add_titles(held, plan)
    assert added == ["iron_tide_2024"] and "iron_tide_2024" in load_titles(held)
    assert [r[0] for r in refused] == ["Iron Tide (2015)", "Glass Harbor"]
    assert "held out titles cannot be in the corpus" in refused[0][1]  # the 2015 version is indexed (AC-BT-1)
    assert "already in the backtest list" in refused[1][1]
    assert held.corpus_file.read_text() == corpus_text and "iron_tide_2024" not in load_corpus(held)


def test_score_counts_only_titles_both_briefs_predicted():
    got = score({"a_2020": {"label": "hit", "blank": "flop", "index": "hit"},
                 "b_2020": {"label": "flop", "blank": "flop", "index": "hit"},
                 "c_2020": {"label": "hit", "blank": "hit", "index": None}})
    assert (got["n"], got["only_index"], got["only_blank"], got["difference"]) == (2, 1, 1, 0.0)
    assert got["sample_size_needed"] is None and got["p_value"] == stats.mcnemar(1, 1)


def test_the_cli_needs_backtest_titles(repo):
    result = CliRunner().invoke(app, ["backtest"])
    assert result.exit_code == 1 and "no backtest titles yet" in result.output
