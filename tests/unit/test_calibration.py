"""Calibration per field (statistics as gates, item 6): the Brier score of the extraction's own confidence,
read from its stored draft (D-022), against verified correctness; `make eval` writes it into the VERIFY report."""

from __future__ import annotations

import pytest

from animedex.evaluation import verify_rates, verify_rates_markdown
from animedex.ontology import get_vocab
from tests.conftest import make_title
from tests.unit.test_evaluation import verified

pytestmark = pytest.mark.unit


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
