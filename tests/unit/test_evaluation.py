"""Coverage rows, web correction rates (AC-13), P1 enum agreement (AC-12)."""

from __future__ import annotations

import copy

import pytest

from animedex.evaluation import coverage_row, p1_agreement, verify_rates, verify_rates_markdown
from animedex.ontology import get_vocab
from tests.conftest import make_title

pytestmark = pytest.mark.unit


def verified(title, path, status, value=None):
    block, name = path.split(".")
    fv = title[block][name]
    fv["verification"] = status
    if status in ("web_confirmed", "web_corrected"):
        fv.update(source="web", source_ref="https://e.org")
    if value is not None:
        fv["value"] = value
    return title


def test_coverage_row_completion_verified_share_and_passes():
    t = make_title()
    for f in get_vocab().lens_fields():
        if f.block == "core" or f.block in t["modules_active"]:
            t[f.block][f.name]["verification"] = "not_required"
    t["core"]["central_mystery"] = {**t["core"]["central_mystery"], "value": None, "conf": 0.0}
    verified(t, "core.outcome", "web_confirmed")
    verified(t, "sensory.color_motif", "unverified")
    row = coverage_row(t, get_vocab())
    assert row["passes_done"] == ["P1"]  # a field still awaits VERIFY
    assert row["verified_share"] == 0.5 and 0 < row["field_completion"] < 1
    verified(t, "sensory.color_motif", "unresolved")
    assert coverage_row(t, get_vocab())["passes_done"] == ["P1", "VERIFY"]


def test_verify_rates_per_field():
    a, b = make_title(), make_title("zephyr_arc_2022", "Zephyr Arc")
    verified(a, "core.outcome", "web_corrected", "mixed")
    verified(b, "core.outcome", "web_confirmed")
    verified(a, "sensory.color_motif", "unresolved")
    rows = {r.path: r for r in verify_rates([a, b], get_vocab())}
    assert (rows["core.outcome"].corrected, rows["core.outcome"].confirmed, rows["core.outcome"].correction_rate) == (1, 1, 0.5)
    assert rows["sensory.color_motif"].unresolved == 1 and rows["sensory.color_motif"].correction_rate is None
    assert "film.closure" not in rows  # no title has the film module
    assert "| `core.outcome` |" in verify_rates_markdown(list(rows.values()))


def test_p1_agreement_counts_enum_fields_only():
    a = make_title()
    b = copy.deepcopy(a)
    assert p1_agreement([a], [b], get_vocab())["overall"] == 1.0
    b["power_combat"]["gate"]["value"] = "trained"
    b["core"]["tone"]["value"] = "entirely different"  # phrase field: ignored
    report = p1_agreement([a], [b], get_vocab())
    enum_active = [f for f in get_vocab().lens_fields() if f.kind == "enum" and (f.block == "core" or f.block in a["modules_active"])]
    assert report["comparisons"] == len(enum_active)
    assert report["per_field"]["power_combat.gate"] == 0.0
    assert report["overall"] == pytest.approx((len(enum_active) - 1) / len(enum_active), abs=1e-4)


def test_agreement_uses_the_newest_rerun_per_gold_title(tmp_path):
    import json

    from animedex.evaluation import latest_per_title

    def write(run, rows):
        f = tmp_path / run / "titles.jsonl"
        f.parent.mkdir()
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return f

    a = write("run_20260927_010000_000001", [{"title_id": "x", "v": 1}, {"title_id": "y", "v": 1}])
    b = write("run_20260927_020000_000001", [{"title_id": "x", "v": 2}, {"title_id": "z", "v": 2}])
    got, runs = latest_per_title([b, a], {"x", "y"})
    assert sorted((t["title_id"], t["v"]) for t in got) == [("x", 2), ("y", 1)]
    assert runs == [a.parent.name, b.parent.name]


def test_interpret_reliability_gates_the_grid_on_raw_agreement_and_kappa():
    import copy

    from animedex.evaluation import interpret_reliability
    from animedex.ontology import get_vocab
    from tests.conftest import make_title

    vocab = get_vocab()
    gates = [g for g in vocab.enum("power_combat.gate") if g != "other"]
    first, second = {}, {}
    for i in range(10):
        t = make_title(f"synthetic_title_{i}_2020", f"Synthetic Title {i}")
        t["power_combat"]["gate"]["value"] = gates[i % 3]
        first[t["title_id"]] = t
        u = copy.deepcopy(t)
        if i == 9:
            u["power_combat"]["gate"]["value"] = gates[(i + 1) % 3]  # one disagreement in ten
        second[u["title_id"]] = u
    report = interpret_reliability(first, second, vocab, ["power_combat.gate"])
    gate = report["fields"]["power_combat.gate"]
    assert gate["raw"] == 0.9 and gate["kappa"] is not None and gate["kappa"] >= 0.8 and report["grid_pass"]
    for u in second.values():
        u["power_combat"]["gate"]["value"] = gates[0]  # the second run always says the same thing
    assert not interpret_reliability(first, second, vocab, ["power_combat.gate"])["grid_pass"]

