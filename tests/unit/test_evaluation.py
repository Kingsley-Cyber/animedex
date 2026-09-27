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
