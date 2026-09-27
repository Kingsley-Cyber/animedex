"""Compact context (owner ruling v1.7 §3): every per-call model input is a compact structured slice of
`key: value` lines, never rendered Markdown (no bullets, headings, tables or blank-line layout), and it
carries the same information as before. Synthetic records only."""

from __future__ import annotations

import re

import pytest

from animedex.models import CorpusEntry
from animedex.ontology import get_vocab
from animedex.pipeline import check, p2, p3, p4
from animedex.pipeline.census import CensusItem
from animedex.pipeline.census import render_user as census_user
from animedex.pipeline.verify import Pending, render_user_native
from animedex.pipeline.verify import render_user as verify_web_user
from animedex.store.runlog import TransientText, redact
from tests.conftest import make_effect_atom, make_engine_atom, make_moment, make_proof, make_title

pytestmark = pytest.mark.contract

KEY_VALUE = re.compile(r"^[A-Za-z0-9_.:\-]+: \S")
T1, T2 = "ironvale_circuit_2021", "lantern_debt_2019"


def assert_compact(text: str) -> list[str]:
    lines = text.split("\n")
    bad = [line for line in lines if not KEY_VALUE.match(line)]
    assert not bad, f"not key: value lines: {bad[:5]}"
    assert not [line for line in lines if line.startswith(("- ", "#", "|", "===", "* "))]
    return lines


def profile_lines(record: dict, *, verification: bool) -> list[str]:
    vocab, out = get_vocab(), []
    for block in ["core", *record["modules_active"]]:
        for f in vocab.block_fields(block):
            fv = record[block][f.name]
            when = f"; when: {fv['condition']}" if fv.get("condition") else ""
            out.append(f"{f.path}: {fv['value']}{when}" + (f" [{fv['verification']}]" if verification else ""))
    return out


def test_p2_input_is_the_profile_and_moments_as_key_value_lines():
    record, moments = make_title(), [make_moment(n=1), make_moment(n=2, locator={"season": None, "episode": None,
                                                                              "timestamp": None, "episode_id": None})]
    lines = assert_compact(p2.render_user(record, moments, get_vocab()))
    for expected in ["title: Ironvale Circuit", "year: 2021", "medium: anime", "format: serialized",
                     "scope: synthetic TV series", "seasons: 1, 2", "numbering: broadcast",
                     "out_of_scope: nothing listed",
                     "modules_active: power_combat, sensory, anime_production, series_engine",
                     *profile_lines(record, verification=True), "moments: 2",
                     f"{T1}.mo.01: The courier reroutes the city grid to save a rival crew.; why_it_hit: A private "
                     "skill becomes a public sacrifice.; locator: S1E4 [unverified]",
                     f"{T1}.mo.02: The courier reroutes the city grid to save a rival crew.; why_it_hit: A private "
                     "skill becomes a public sacrifice.; locator: episode unknown [unverified]"]:
        assert expected in lines, expected
    assert any("; when: shows when the ledger is audited [unverified]" in line for line in lines)


def test_p3_input_keeps_atoms_partners_and_roles():
    record = make_title()
    partner = make_title(T2, "Lantern Debt", medium="western_animation", fmt="episodic",
                         modules=("relationships", "sensory", "series_engine", "comedy_satire"), role_tags=("mixed",))
    atoms = [make_effect_atom(), make_engine_atom()]
    text = p3.render_user(record, atoms, [{"title_id": T2, "role": "cross_medium"}], {T2: partner}, get_vocab())
    lines = assert_compact(text)
    e, g = atoms[0]["effect"], atoms[1]["engine"]
    assert "atoms: 2" in lines and f"partner: {T2}; role: cross_medium" in lines
    assert (f"{T1}.m.001: effect; element: {e['element']}; feeling: {e['feeling']}; because: {e['because']}; "
            f"rival: {e['rival_because']}") in lines
    assert (f"{T1}.m.002: engine; agent: {g['agent']}; goal: {g['goal']}; constraint: {g['constraint']}; "
            f"strategy: {g['strategy']}; benefit: {g['benefit']}; cost: {g['cost']}; dilemma: {g['dilemma']}") in lines
    partner_at = lines.index(f"partner: {T2}; role: cross_medium")
    assert lines[partner_at + 1] == "title: Lantern Debt"
    assert set(profile_lines(partner, verification=False)) <= set(lines[partner_at:])
    assert set(profile_lines(record, verification=False)) <= set(lines[:partner_at])
    assert not any(line.endswith("[unverified]") for line in lines)  # P3 reads values, not verification


def test_check_input_keeps_every_atom_and_proof_field():
    atoms = [make_effect_atom(), make_engine_atom()]
    proofs = [make_proof(), make_proof(f"{T1}.m.002", explanation_test=None)]
    lines = assert_compact(check.render_user(make_title(), atoms, proofs, get_vocab()))
    e, g = atoms[0]["effect"], atoms[1]["engine"]
    assert lines.index("atoms: 2") < lines.index("proofs: 2")
    assert (f"{T1}.m.001: mechanism; kind: effect; module: power_combat; element: {e['element']}; feeling: "
            f"{e['feeling']}; because: {e['because']}; rival_because: {e['rival_because']}; "
            "evidence: power_combat.visible_counter") in lines
    engine = next(line for line in lines if line.startswith(f"{T1}.m.002: mechanism"))
    for k in ("agent", "goal", "constraint", "strategy", "benefit", "cost", "dilemma", "dramatic_question"):
        assert f"{k}: {g[k]}" in engine
    proof = next(line for line in lines if line.startswith(f"{T1}.m.001: proof"))
    c, t, ab = proofs[0]["contrast"][0], proofs[0]["explanation_test"], proofs[0]["ablation"]
    for part in (c["partner_title_id"], c["partner_role"], f"has {c['partner_has']}", c["difference"],
                 f"favors {t['favors']} via {t['via_partner']}", t["note"], f"ablation: {ab['verdict']}",
                 f"conf {ab['conf']}", ab["if_removed"]):
        assert part in proof, part
    assert "explanation_test" not in next(line for line in lines if line.startswith(f"{T1}.m.002: proof"))
    assert set(profile_lines(make_title(), verification=True)) <= set(lines)


def test_p4_input_lists_each_atom_on_one_line():
    atoms = {a["atom_id"]: a for a in (make_effect_atom(), make_engine_atom())}
    lines = assert_compact(p4.render_user(atoms))
    e, g = atoms[f"{T1}.m.001"]["effect"], atoms[f"{T1}.m.002"]["engine"]
    assert lines[0] == "atoms: 2"
    assert lines[1] == f"{T1}.m.001: effect; element: {e['element']}; feeling: {e['feeling']}; because: {e['because']}"
    for k in ("agent", "goal", "constraint", "strategy", "benefit", "cost", "dilemma", "dramatic_question"):
        assert f"{k}: {g[k]}" in lines[2]


def test_census_input_lists_each_title_on_one_line():
    batch = [CensusItem("anilist:1", "Show One", 2001, "anime", "TV"), CensusItem("anilist:2", "Show Two", None,
                                                                                 "donghua", "ONA")]
    assert assert_compact(census_user(batch)) == [
        "titles: 2", "anilist:1: Show One; year: 2001; format: TV; medium: anime",
        "anilist:2: Show Two; year: unknown; format: ONA; medium: donghua"]


def verify_case():
    record = make_title()
    entry = CorpusEntry.model_validate({k: record[k] for k in ("title_id", "title", "year", "medium", "format",
                                                               "scope", "role_tags")})
    moment = make_moment()
    pending = Pending(record, [moment], ["core.outcome", "core.logline_hook", f"moments.{moment['moment_id']}.locator"])
    return entry, pending


def test_verify_brief_lists_fields_moments_and_limits():
    entry, pending = verify_case()
    vocab = get_vocab()
    limits = {"max_searches": 5, "outcome_extra": 2, "max_fetches": 10, "max_turns": 17}
    lines = assert_compact(render_user_native(entry, pending, vocab, limits))
    outcome, hook = pending.record["core"]["outcome"]["value"], pending.record["core"]["logline_hook"]["value"]
    for expected in ["title: Ironvale Circuit", "seasons: 1, 2", "fields_to_check: 2 (path: recalled value)",
                     f"core.outcome: {outcome!r} [allowed: {' | '.join(vocab.enum('core.outcome'))}]",
                     f"core.logline_hook: {hook!r} [max 20 words]",
                     "moments_to_locate: 1 (moment_id: description; recalled season/episode)",
                     f"{T1}.mo.01: The courier reroutes the city grid to save a rival crew.; recalled: S1 E4",
                     "limits: at most 5 web searches (2 of them only for the outcome) and 10 page fetches"]:
        assert expected in lines, expected


def test_verify_web_pages_stay_raw_so_the_run_log_can_redact_them():
    entry, pending = verify_case()
    page = TransientText("https://example.org/a", "Synthetic page line one about the series.\n"
                                                  'A second line with "quotes" and a colon: here.')
    text = verify_web_user(entry, pending, get_vocab(), {page.url: page})
    brief, _, rest = text.partition("\npages: 1\n")
    assert_compact(brief) and rest.startswith(f"page: {page.url}\n{page.text}")
    logged = redact(text, [page])
    assert page.text not in logged and f"[[web url={page.url} " in logged
