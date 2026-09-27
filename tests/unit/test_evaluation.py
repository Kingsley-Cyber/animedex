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



# ---------------------------------------------------------------- calibration (statistics as gates, item 6)
def _draft_of(title, **confs):
    """A stored P1/INTERPRET answer: the title's fields with the model's own confidences."""
    draft = {b: {n: {"value": fv["value"], "conf": fv["conf"]} for n, fv in title[b].items()}
             for b in ["core", *title["modules_active"]]}
    for path, conf in confs.items():
        block, name = path.split("__")
        draft[block][name]["conf"] = conf
    return draft


def test_brier_per_field_uses_the_confidence_stored_before_verification():
    from animedex.evaluation import calibration, calibration_markdown

    a, b = make_title(), make_title("zephyr_arc_2022", "Zephyr Arc")
    verified(a, "core.outcome", "web_confirmed")        # right
    verified(b, "core.outcome", "web_corrected", "mixed")  # wrong
    verified(a, "power_combat.gate", "gathered")        # right (sourced at extraction)
    a["power_combat"]["gate"].update(source="web", source_ref="https://e.org")
    verified(b, "power_combat.gate", "unresolved")      # left out
    for t in (a, b):  # VERIFY raised the stored confidence of checked fields to the 0.7 threshold
        for path in ("core.outcome", "power_combat.gate"):
            block, name = path.split(".")
            t[block][name]["conf"] = max(t[block][name]["conf"], 0.7)
    drafts = {a["title_id"]: _draft_of(a, core__outcome=0.9, power_combat__gate=0.6),
              b["title_id"]: _draft_of(b, core__outcome=0.8)}
    rows = {r.path: r for r in calibration([a, b], get_vocab(), drafts)}
    out = rows["core.outcome"]  # (0.9, right), (0.8, wrong): ((0.1)^2 + (0.8)^2) / 2
    assert (out.n, out.brier, out.mean_conf, out.right_share, out.from_draft, out.floored) == \
        (2, round((0.01 + 0.64) / 2, 4), 0.85, 0.5, 2, 0)
    gate = rows["power_combat.gate"]  # gathered counts as right; unresolved stays out
    assert (gate.n, gate.brier) == (1, round(0.4 ** 2, 4))
    assert "core.tone" not in rows  # never checked
    no_draft = {r.path: r for r in calibration([a, b], get_vocab())}["core.outcome"]
    assert no_draft.floored == 2 and no_draft.from_draft == 0  # the stored, floored confidences stand in
    text = "\n".join(calibration_markdown(list(rows.values())))
    assert "| `core.outcome` | 2 | 0.325 | 0.85 | 0.50 | 0 |" in text and "Overall: Brier" in text
    assert "## Calibration" in verify_rates_markdown(verify_rates([a, b], get_vocab()), list(rows.values()))


def test_stored_drafts_come_from_the_response_cache_by_provenance_key(tmp_path):
    from animedex.evaluation import stored_drafts
    from animedex.store.cache import ResponseCache

    a, b, c = make_title(), make_title("zephyr_arc_2022", "Zephyr Arc"), make_title("quill_house_2018", "Quill House")
    a["provenance"]["cache_key"] = "sha256:" + "a" * 64
    b["provenance"]["cache_key"] = "sha256:" + "b" * 64
    cache = ResponseCache(tmp_path)
    cache.put("INTERPRET", a["provenance"]["cache_key"], {"json": {"core": {"outcome": {"value": "hit", "conf": 0.4}}}})
    cache.put("P1", b["provenance"]["cache_key"], {"json": {"core": {"outcome": {"value": "hit", "conf": 0.5}}}})
    drafts = stored_drafts(tmp_path, [a, b, c])
    assert set(drafts) == {a["title_id"], b["title_id"]}  # c has no cache key; nothing is called
    assert drafts[a["title_id"]]["core"]["outcome"]["conf"] == 0.4


def test_make_eval_writes_calibration_into_the_verify_report(repo):
    import json

    from typer.testing import CliRunner

    from animedex.cli import app
    from animedex.store.cache import ResponseCache
    from tests.conftest import write_state

    a = verified(make_title(), "core.outcome", "web_corrected", "mixed")
    a["provenance"]["cache_key"] = "sha256:" + "c" * 64
    ResponseCache(repo.cache).put("P1", a["provenance"]["cache_key"],
                                  {"json": {"core": {"outcome": {"value": "hit", "conf": 0.9}}}})
    write_state(repo, {"title": [a]})
    result = CliRunner().invoke(app, ["eval"])
    assert result.exit_code == 0 and "calibration (Brier, per field)" in result.output
    assert "core.outcome 0.810 over 1" in result.output  # the draft said 0.9; the web corrected it
    assert "## Calibration" in (repo.reports / "verify_rates.md").read_text()
    stored = json.loads((repo.build / "stats" / "calibration.json").read_text())
    assert stored["overall"] == {"checked": 1, "floored": 0, "brier": 0.81}
