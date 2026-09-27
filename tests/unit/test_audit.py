"""`make audit` / `make audit-report` (controls A7; AC-56), on synthetic canonical state.

The owner guard: while the gold blind is pending the audit never samples a gold title (partner titles
are fine). Sheets carry a blank mark per atom and are never overwritten; the report tracks the wrong
rate per audit date and the extractor-critic disagreement per P2 run."""

from __future__ import annotations

import json

import pytest
import yaml

from animedex.audit import (
    AuditError,
    disagreement_by_run,
    run_audit,
    sheet_rows,
    write_audit_report,
)
from animedex.store.canonical import CanonicalStore
from tests.conftest import prov, write_state
from tests.pipeline.test_ideate import T1, T2, state

pytestmark = pytest.mark.unit


@pytest.fixture
def audited(repo):
    write_state(repo, state())
    corpus = [{k: t[k] for k in ("title_id", "title", "year", "medium", "format", "scope", "role_tags")}
              for t in state()["title"]]
    corpus[0]["role_tags"] = ["gold", *corpus[0]["role_tags"]]  # T1 is gold, T2 a partner
    repo.corpus_file.write_text(yaml.safe_dump({"titles": corpus}))
    (repo.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "pending", "runs_without_annotations": True}))
    return repo


def test_audit_samples_non_gold_eligible_atoms_with_evidence_trails(audited):
    res = run_audit(audited, date="2026-09-27")
    assert res.path == "eval/audit/audit_2026-09-27.yaml" and res.eligible == 4 and res.gold_excluded == 2
    text = (audited.root / res.path).read_text()
    assert text.count("mark:   # true | plausible | wrong") == res.sampled == 2
    sheet = yaml.safe_load(text)
    assert {a["title_id"] for a in sheet["atoms"]} == {T2} and T1 not in text  # no gold title while pending
    for a in sheet["atoms"]:
        assert a["mark"] is None and a["text"] and a["p2_run"] == "run_test_001"
        assert a["checks"] == [{"target": "mechanism", "verdict": "ACCEPT", "reasons": [], "run_id": "run_test_001"}]
        [ev] = a["evidence"]  # the effect atom's element_ref names the same field: listed once
        assert ev["kind"] == "field" and ev["ref"] in ("power_combat.visible_counter", "core.premise_engine")
        assert ev["value"] and ev["verification"] == "unverified" and "source" in ev
    with pytest.raises(AuditError, match="never overwritten"):
        run_audit(audited, date="2026-09-27")  # it may hold marks


def test_once_the_blind_is_done_gold_atoms_can_be_sampled(audited):
    (audited.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "annotations_done"}))
    res = run_audit(audited, date="2026-09-28")
    assert res.sampled == 4 and res.gold_excluded == 0
    assert run_audit(audited, date="2026-09-29", size=2).sampled == 2  # the date seeds a fresh sample


def test_the_sample_is_seeded_by_the_date(audited):
    (audited.gold / "BLIND.yaml").write_text(yaml.safe_dump({"state": "waived"}))
    first = run_audit(audited, date="2026-10-01", size=2)
    ids = [a["atom_id"] for a in yaml.safe_load((audited.root / first.path).read_text())["atoms"]]
    (audited.root / first.path).unlink()
    again = run_audit(audited, date="2026-10-01", size=2)
    assert [a["atom_id"] for a in yaml.safe_load((audited.root / again.path).read_text())["atoms"]] == ids


def test_audit_report_tracks_the_wrong_rate_and_disagreement_per_run(audited):
    for date, marks in (("2026-09-27", ["wrong", True]), ("2026-10-04", ["plausible", "sure"])):
        path = audited.root / run_audit(audited, date=date, size=2).path
        sheet = yaml.safe_load(path.read_text())
        for atom, mark in zip(sheet["atoms"], marks, strict=True):
            atom["mark"] = mark
        path.write_text(yaml.safe_dump(sheet))
    rows = sheet_rows(audited)
    assert [(r["date"], r["marked"], r["wrong"], r["wrong_rate"]) for r in rows] == [
        ("2026-09-27", 2, 1, 0.5), ("2026-10-04", 1, 0, 0.0)]
    assert rows[1]["invalid"] == 1  # "sure" is not a mark
    store = CanonicalStore(audited)
    checks = store.read("check")
    first = dict(checks[0], verdict="REVISE", reasons=["overreach"], revision={"because": "x"},
                 provenance=prov("CHECK", run_id="run_check_000"))  # earlier than the ACCEPT
    store.write("check", [*checks, first])
    rejected = audited.quarantine / "CHECK" / "mechanism" / "orphan_title_2020.m.001.json"
    rejected.parent.mkdir(parents=True)
    rejected.write_text(json.dumps({"record_id": "orphan_title_2020.m.001", "reasons": ["REJECT: unsupported"],
                                    "record": {"atom_id": "orphan_title_2020.m.001",
                                               "provenance": prov("P2", run_id="run_p2_other")}}))
    runs = disagreement_by_run(audited)
    assert runs == {"run_p2_other": {"checked": 1, "disagreed": 1, "rejected": 1},
                    "run_test_001": {"checked": 4, "disagreed": 1, "rejected": 0}}
    out, _, _ = write_audit_report(audited)
    report = out.read_text()
    assert out == audited.reports / "audit.md" and "| 2026-09-27 | 2 | 2 | 1 | 0 | 1 | 50% |" in report
    assert "| run_test_001 | 4 | 1 | 0 | 25% |" in report and "| run_p2_other | 1 | 1 | 1 | 100% |" in report
    assert "orphan" not in report.replace("run_p2_other", "")  # counts only, never atom text or ids
