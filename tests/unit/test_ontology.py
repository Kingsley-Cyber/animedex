"""Enum normalization and the field -> CQ coverage table (AC-04)."""

from __future__ import annotations

import copy
import json

import pytest

from animedex.models import record_paths
from animedex.ontology import (
    CQSet,
    Vocab,
    coverage_report,
    get_bridge,
    get_cqs,
    get_vocab,
    normalize_enum,
)
from tests.conftest import REPO

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw, value, proposal", [
    ("system_granted", "system_granted", None),
    ("status window", "system_granted", None),        # alternate label
    ("System Granted", "system_granted", None),       # case / spacing
    ("other:crystal lattice", "other", "crystal lattice"),
    ("crystal lattice", "other", "crystal lattice"),
])
def test_normalize_gate(raw, value, proposal):
    n = normalize_enum(get_vocab(), "power_combat.gate", raw)
    assert (n.value, n.proposal) == (value, proposal)


def test_normalize_enum_without_other_returns_none_and_proposal():
    n = normalize_enum(get_vocab(), "power_combat.progression", "spiral")
    assert n.value is None and n.proposal == "spiral"


def test_real_ontology_has_no_orphans():
    report = coverage_report(get_vocab(), get_bridge(), get_cqs(), record_paths())
    assert report.errors == []
    assert report.orphans == []
    kinds = {r.kind for r in report.rows}
    assert kinds == {"lens_field", "module", "vocab_field", "bridge_concept"}
    assert len([r for r in report.rows if r.kind == "lens_field"]) == 50


def test_lens_matches_spec_v1_2():
    vocab = get_vocab()
    paths = {f.path for f in vocab.lens_fields()}
    for deleted in ("sensory.sound_motif", "comedy_satire.satire_target", "comedy_satire.comic_roles",
                    "comedy_satire.running_gag_system"):
        assert deleted not in paths
    assert "series_engine.episode_template" in paths
    assert {f.path for f in vocab.lens_fields() if f.conditional} == {"core.flaw", "core.moral_line"}


def test_orphan_detected_when_a_cq_is_removed():
    data = json.loads((REPO / "ontology" / "vocab.json").read_text())
    vocab = Vocab(data)
    cqs = get_cqs()
    trimmed = CQSet({"version": cqs.version, "questions": [
        {"id": q.id, "text": q.text, "requires": [r for r in q.requires if r != "series_engine.episode_template"]}
        for q in cqs.questions]})
    report = coverage_report(vocab, get_bridge(), trimmed, record_paths())
    assert [r.name for r in report.orphans] == ["series_engine.episode_template"]
    assert not report.ok


def test_unknown_requires_and_unknown_cq_refs_are_errors():
    data = json.loads((REPO / "ontology" / "vocab.json").read_text())
    data = copy.deepcopy(data)
    data["fields"]["feeling"]["cq_refs"] = ["CQ-X99"]
    cqs = get_cqs()
    bad = CQSet({"version": "t", "questions": [
        *({"id": q.id, "text": q.text, "requires": list(q.requires)} for q in cqs.questions),
        {"id": "CQ-Z01", "text": "?", "requires": ["core.no_such_field"]}]})
    report = coverage_report(Vocab(data), get_bridge(), bad, record_paths())
    assert any("CQ-X99" in e for e in report.errors)
    assert any("core.no_such_field" in e for e in report.errors)
