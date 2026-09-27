"""Shared fixtures. Every title and text here is synthetic (09: no copied or real-title text)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from animedex import SCHEMA_VERSION
from animedex.ontology import get_vocab
from animedex.paths import ROOT_ENV, Paths

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
CREATED = "2026-09-26T12:00:00+00:00"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """A throwaway ANIMEDEX repo (real ontology + config) with ANIMEDEX_ROOT pointing at it."""
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("ontology", "config", "corpus", "schemas", "prompts"):
        shutil.copytree(REPO / name, root / name)
    for d in ("data/canonical", "eval/gold"):
        (root / d).mkdir(parents=True)
    monkeypatch.setenv(ROOT_ENV, str(root))
    return Paths(root)


def git(root: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


@pytest.fixture
def git_repo(repo: Paths) -> Paths:
    git(repo.root, "init", "-q", "-b", "main")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "init")
    return repo


# ---------------------------------------------------------------- record factories
def prov(pass_: str = "P1", **over: Any) -> dict[str, Any]:
    vocab = get_vocab()
    base = {"run_id": "run_test_001", "pass": pass_, "model": "mock/test", "prompt_version": "1.0.0",
            "schema_version": SCHEMA_VERSION, "vocab_version": vocab.version, "cache_key": None,
            "created_at": CREATED}
    base.update(over)
    return base


def field_value(value: Any, **over: Any) -> dict[str, Any]:
    base = {"value": value, "conf": 0.8 if value is not None else 0.0, "source": "recall",
            "verification": "unverified", "source_ref": None, "epistemic": "interpretive"}
    base.update(over)
    return base


def _block(block: str) -> dict[str, Any]:
    vocab = get_vocab()
    out = {}
    for f in vocab.block_fields(block):
        if f.kind == "enum":
            fv = field_value(vocab.enum(f.vocab)[0], epistemic="observed")
        else:
            fv = field_value(f"synthetic {f.name.replace('_', ' ')} phrase")
        if f.conditional:
            fv["condition"] = "shows when the ledger is audited"
        out[f.name] = fv
    return out


def make_title(title_id: str = "ironvale_circuit_2021", title: str = "Ironvale Circuit", *,
               medium: str = "anime", fmt: str = "serialized",
               modules: tuple[str, ...] = ("power_combat", "sensory", "anime_production", "series_engine"),
               role_tags: tuple[str, ...] = ("hit",), **over: Any) -> dict[str, Any]:
    year = int(title_id.rsplit("_", 1)[1])
    scope = ({"version": "feature film (synthetic)", "seasons": [], "numbering": None, "exclude": []}
             if fmt == "film" else
             {"version": "synthetic TV series", "seasons": [1, 2], "numbering": "broadcast", "exclude": []})
    rec: dict[str, Any] = {"title_id": title_id, "title": title, "year": year, "medium": medium, "format": fmt,
                           "scope": scope, "role_tags": list(role_tags), "modules_active": list(modules),
                           "core": _block("core"), "provenance": prov("P1")}
    for m in modules:
        rec[m] = _block(m)
    rec.update(over)
    return rec


def make_moment(title_id: str = "ironvale_circuit_2021", n: int = 1, **over: Any) -> dict[str, Any]:
    rec = {"moment_id": f"{title_id}.mo.{n:02d}", "title_id": title_id,
           "description": "The courier reroutes the city grid to save a rival crew.",
           "locator": {"season": 1, "episode": 4, "timestamp": None, "episode_id": None},
           "moment_type": "reversal", "why_it_hit": "A private skill becomes a public sacrifice.",
           "conf": 0.7, "verification": "unverified", "source_ref": None, "provenance": prov("P1")}
    rec.update(over)
    return rec


def make_effect_atom(title_id: str = "ironvale_circuit_2021", n: int = 1, **over: Any) -> dict[str, Any]:
    rec = {"atom_id": f"{title_id}.m.{n:03d}", "title_id": title_id, "atom_kind": "effect",
           "effect": {"element": "grid access that only the courier can read",
                      "element_ref": {"field": "power_combat.visible_counter", "moment_id": None},
                      "feeling": "superiority", "because": "The audience shares a secret that reframes every fight.",
                      "rival_because": "The spectacle of the grid alone carries the thrill."},
           "engine": None, "module": "power_combat", "epistemic": "interpretive", "conf": 0.7,
           "evidence_refs": ["power_combat.visible_counter"], "explanation": "settled",
           "support": {"status": "profile_only", "supporting_episodes": [], "contradicting_episodes": [],
                       "reframing_episodes": []},
           "origin": "p2", "provenance": prov("P2")}
    rec.update(over)
    return rec


def make_engine_atom(title_id: str = "ironvale_circuit_2021", n: int = 2, **over: Any) -> dict[str, Any]:
    rec = make_effect_atom(title_id, n)
    rec.update({"atom_kind": "engine", "effect": None, "module": "core", "evidence_refs": ["core.premise_engine"],
                "engine": {"agent": "the courier", "goal": "keep the district's power on",
                           "constraint": "every reroute burns part of her memory",
                           "strategy": "trade memories for grid access in secret",
                           "benefit": "the district survives each blackout",
                           "cost": "she forgets the people she saves",
                           "dilemma": "each rescue erases a reason to keep rescuing",
                           "dramatic_question": "What will be left of her when the grid holds?",
                           "feeling": "tension"}})
    rec.update(over)
    return rec


def make_transfer(title_id: str = "ironvale_circuit_2021", n: int = 1, atom_n: int = 1, **over: Any) -> dict[str, Any]:
    rec = {"transfer_id": f"{title_id}.t.{n:03d}", "source_atom_id": f"{title_id}.m.{atom_n:03d}",
           "atom_kind": "effect", "pattern": "Only the lead can read the measure of their own power, so the audience shares a secret.",
           "bridge": ["visible_progress_counter", "information_asymmetry"],
           "essential_conditions": ["measure visible to the audience"],
           "variable_details": ["form of the interface"],
           "failure_conditions": ["other characters can read the measure"], "provenance": prov("P4")}
    rec.update(over)
    return rec


def make_proof(atom_id: str = "ironvale_circuit_2021.m.001", partner: str = "lantern_debt_2019", **over: Any) -> dict[str, Any]:
    rec = {"atom_id": atom_id,
           "contrast": [{"partner_title_id": partner, "partner_role": "cross_medium", "partner_has": "no",
                         "difference": "The partner shows its meter to everyone, so no shared secret forms."}],
           "explanation_test": {"favors": "because", "via_partner": partner,
                                "note": "Without the secret the same spectacle lands flat."},
           "ablation": {"if_removed": "The fights become ordinary brawls.", "verdict": "load_bearing", "conf": 0.7},
           "provenance": prov("P3")}
    rec.update(over)
    return rec


def make_idea(n: int = 1, *, transfer_ids: tuple[str, ...] = ("ironvale_circuit_2021.t.001",),
              closest: str = "ironvale_circuit_2021", **over: Any) -> dict[str, Any]:
    rec = {"idea_id": f"idea.run_test_001.{n:03d}", "target_domain": "anime",
           "logline": "A lighthouse keeper can see the debts every sailor owes the sea, and must choose who pays.",
           "premise": "A synthetic premise used only for contract tests.", "theme_root": "What does survival cost others?",
           "engine": {"goal": "keep the harbor alive", "constraint": "debts must be paid", "strategy": "reassign debts",
                      "benefit": "ships return", "cost": "someone else drowns", "dilemma": "whose life balances the ledger",
                      "dramatic_question": "Who does she let the sea take?"},
           "transformation": {"operator": "transfer_cost", "source_transfer_ids": list(transfer_ids),
                              "what_changed": "The cost of power lands on strangers instead of the wielder."},
           "consequences": {"choices": "She must pick a victim each storm.", "relationships": "The town fears her mercy.",
                            "outcomes": "Harbor survives while families vanish."},
           "profile": {"gate": "inherited", "cost_of_power": "relationships", "progression": "none",
                       "visible_counter": "none", "fight_medium": "summon", "power_is": "individual"},
           "bridge": ["cost_of_advancement"], "grid_cell": "inherited|relationships|none",
           "atoms_used": list(transfer_ids), "borrowed_from": [closest], "broken_rule": "", "appetite": "",
           "closest_existing": closest, "why_not_a_clone": "The cost moves to others, which changes every choice.",
           "gates": {"structural_jaccard_max": 0.3, "procedural_jaccard_max": 0.25, "premise_cosine_max": 0.4,
                     "novel_combo": True, "graveyard_hits": [], "failure_conditions_triggered": [],
                     "consequence_test": {"choices": True, "relationships": True, "outcomes": False, "h1_pass": True},
                     "coherence": "pass"},
           "taste": {"criteria_met": ["T2"], "evidence": {"T2": "Nearest title shares the concept; the cost atom differs."},
                     "hard_fail": False},
           "status": "champion", "generation": 1, "parent_ids": [], "human_rating": None, "provenance": prov("IDEATE")}
    rec.update(over)
    return rec


def make_census(n: int, *, powered: bool = True, **over: Any) -> list[dict[str, Any]]:
    """`n` synthetic census rows (counts only), all in one cell that the test cards avoid."""
    rows = []
    for i in range(1, n + 1):
        rec = {"census_id": f"anilist:{900000 + i}", "title": f"Census title {i}", "year": 2010, "medium": "anime",
               "format": "serialized", "popularity": 1000, "has_power_system": powered, "gate": "artifact",
               "cost_of_power": "resource", "progression": "hybrid", "visible_counter": "rank_tier",
               "fight_medium": "weapon", "power_is": "paired", "borrowed_system": "none", "trust": "recall",
               "batch_id": "census_test", "provenance": prov("CENSUS")}
        rec.update(over)
        rows.append(rec)
    return rows


def synthetic_state() -> dict[str, list[dict[str, Any]]]:
    """A small, fully linked canonical state across the V1 record types."""
    t1 = make_title()
    t2 = make_title("lantern_debt_2019", "Lantern Debt", medium="western_animation", fmt="episodic",
                    modules=("relationships", "sensory", "series_engine", "comedy_satire"), role_tags=("mixed",))
    t3 = make_title("glass_meridian_2016", "Glass Meridian", medium="film", fmt="film", modules=("film",),
                    role_tags=("flop",))
    atom1, atom2 = make_effect_atom(), make_engine_atom()
    proof1 = make_proof()
    proof2 = make_proof("ironvale_circuit_2021.m.002", explanation_test=None)
    check1 = {"target_id": atom1["atom_id"], "target_type": "mechanism", "verdict": "ACCEPT", "reasons": [],
              "revision": None, "provenance": prov("CHECK")}
    transfer = make_transfer()
    outcome = {"title_id": "glass_meridian_2016", "label": "flop",
               "signals": [{"metric": "synthetic score", "value": "4.1", "source_ref": "https://example.org/score"}],
               "confounders": {"studio": "synthetic studio", "budget_signal": "low", "source_popularity": "low",
                               "platform": "theatrical", "release_context": "crowded season"},
               "failure_reason": "Execution problems buried a clear premise.",
               "failure_level": "execution", "failure_evidence": "Reviews blame pacing and production, not the premise.",
               "failure_evidence_ref": "https://example.org/review", "failure_level_source": "verify",
               "provenance": prov("VERIFY")}
    idea = make_idea()
    archive = {"cell_key": idea["grid_cell"], "idea_id": idea["idea_id"], "fitness": [1.0, 1.0, 0.0, -0.3],
               "replaced_idea_id": None, "generation": 1, "provenance": prov("IDEATE")}
    return {"title": [t1, t2, t3], "moment": [make_moment()], "outcome": [outcome], "mechanism": [atom1, atom2],
            "proof": [proof1, proof2], "check": [check1], "transfer": [transfer], "idea": [idea], "archive": [archive]}


def write_state(paths: Paths, state: dict[str, list[dict[str, Any]]]) -> None:
    from animedex.pipeline.canonicalize import ORDER
    from animedex.store.canonical import CanonicalStore

    store = CanonicalStore(paths)
    for record_type in ORDER:
        if state.get(record_type):
            store.write(record_type, state[record_type])


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """URCP's validator runs `pytest -m integration`: contract + pipeline tests carry that mark too."""
    for item in items:
        parts = set(Path(str(item.fspath)).parts)
        if parts & {"contract", "pipeline"}:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Only fake CLIs under pytest's temp dir may run. A real `claude`/`codex` call would spend
    Kingsley's subscription, so every test refuses it."""
    from animedex.providers import cli_common

    base = str(tmp_path_factory.getbasetemp().resolve())
    monkeypatch.setattr(cli_common, "BINARY_GUARD", lambda binary: str(Path(binary).resolve()).startswith(base))
