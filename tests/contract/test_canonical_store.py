"""AC-02 (invalid records never enter canonical data) and AC-03 (off-vocab -> `other` + proposal)."""

from __future__ import annotations

import json

import pytest

from animedex.pipeline.canonicalize import canonicalize
from animedex.store.canonical import CanonicalStore, IntegrityError, InvalidRecords
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from tests.conftest import make_moment, make_title, synthetic_state, write_state

pytestmark = pytest.mark.contract


def snapshot(paths):
    return {p.name: p.read_bytes() for p in sorted(paths.canonical.glob("*.jsonl"))}


@pytest.fixture
def seeded(repo):
    write_state(repo, synthetic_state())
    return repo


@pytest.mark.parametrize("breaker", [
    lambda r: r.pop("core"),                                                    # missing required block
    lambda r: r["core"]["tone"].update(value=" ".join(["long"] * 16)),         # phrase over its 15-word cap
    lambda r: r.update(medium="radio"),                                         # record-level enum off-vocab
])
def test_invalid_title_never_enters_canonical(seeded, breaker):
    store = CanonicalStore(seeded)
    before = snapshot(seeded)
    rec = make_title("zephyr_arc_2022", "Zephyr Arc")
    breaker(rec)
    with pytest.raises(InvalidRecords):
        store.write("title", [rec])
    assert snapshot(seeded) == before


def test_one_bad_record_blocks_the_whole_batch(seeded):
    store = CanonicalStore(seeded)
    before = snapshot(seeded)
    good = make_title("zephyr_arc_2022", "Zephyr Arc")
    bad = make_title("quill_house_2018", "Quill House", medium="radio")
    with pytest.raises(InvalidRecords):
        store.write("title", [good, bad])
    assert snapshot(seeded) == before


def test_dangling_reference_is_refused(seeded):
    before = snapshot(seeded)
    with pytest.raises(IntegrityError, match="unknown title"):
        CanonicalStore(seeded).write("moment", [make_moment("nobody_2000")])
    assert snapshot(seeded) == before


def test_off_vocab_with_other_is_stored_as_other_and_writes_proposal(seeded):
    rec = make_title("zephyr_arc_2022", "Zephyr Arc")
    rec["power_combat"]["gate"]["value"] = "other:crystal lattice"
    result = CanonicalStore(seeded).write("title", [rec], run_id="run_ac03")
    stored = {r["title_id"]: r for r in read_jsonl(seeded.canonical / "titles.jsonl")}["zephyr_arc_2022"]
    assert stored["power_combat"]["gate"]["value"] == "other"
    [proposal] = result.proposals
    data = json.loads(proposal.read_text())
    assert data["field"] == "power_combat.gate" and data["proposed"] == "crystal lattice" and data["status"] == "pending"
    assert data["examples"][0]["record_id"] == "zephyr_arc_2022" and data["examples"][0]["run_id"] == "run_ac03"


def test_p1_enum_without_other_becomes_null_with_proposal(seeded):
    rec = make_title("zephyr_arc_2022", "Zephyr Arc")
    rec["power_combat"]["progression"]["value"] = "spiral"
    result = CanonicalStore(seeded).write("title", [rec])
    stored = {r["title_id"]: r for r in read_jsonl(seeded.canonical / "titles.jsonl")}["zephyr_arc_2022"]
    fv = stored["power_combat"]["progression"]
    assert fv["value"] is None and fv["conf"] == 0.0 and "off-vocab" in fv["uncertainty_reason"]
    assert json.loads(result.proposals[0].read_text())["proposed"] == "spiral"


def test_alternate_label_normalized_without_proposal(seeded):
    rec = make_title("zephyr_arc_2022", "Zephyr Arc")
    rec["power_combat"]["gate"]["value"] = "status window"
    result = CanonicalStore(seeded).write("title", [rec])
    stored = {r["title_id"]: r for r in read_jsonl(seeded.canonical / "titles.jsonl")}["zephyr_arc_2022"]
    assert stored["power_combat"]["gate"]["value"] == "system_granted" and result.proposals == []


def test_record_level_off_vocab_with_other_uses_other(seeded):
    result = CanonicalStore(seeded).write("moment", [make_moment(n=2, moment_type="other:heist")])
    stored = {r["moment_id"]: r for r in read_jsonl(seeded.canonical / "moments.jsonl")}
    assert stored["ironvale_circuit_2021.mo.02"]["moment_type"] == "other"
    assert json.loads(result.proposals[0].read_text())["field"] == "moment_type"


def test_upsert_sorted_and_canonical_form(seeded):
    store = CanonicalStore(seeded)
    store.write("title", [make_title("aaron_gate_2015", "Aaron Gate")])
    records = read_jsonl(seeded.canonical / "titles.jsonl")
    ids = [r["title_id"] for r in records]
    assert ids == sorted(ids) and "aaron_gate_2015" in ids
    assert (seeded.canonical / "titles.jsonl").read_text() == dumps_jsonl(records)
    store.write("title", [make_title("aaron_gate_2015", "Aaron Gate Revised")])
    records = read_jsonl(seeded.canonical / "titles.jsonl")
    assert [r["title"] for r in records if r["title_id"] == "aaron_gate_2015"] == ["Aaron Gate Revised"]


def test_canonicalize_stage_quarantines_bad_and_applies_good(seeded):
    folder = seeded.candidates / "moment"
    folder.mkdir(parents=True)
    good = make_moment(n=3)
    bad = make_moment(n=4, description=" ".join(["beat"] * 30))
    (folder / "p1_run.jsonl").write_text(dumps_jsonl([good, bad]))
    result = canonicalize(seeded, "run_canon")
    assert result.written["moment"] == ["ironvale_circuit_2021.mo.03"]
    assert [q[1] for q in result.quarantined] == ["ironvale_circuit_2021.mo.04"]
    qfile = seeded.quarantine / "CANONICALIZE" / "moment" / "ironvale_circuit_2021.mo.04.json"
    assert "30 words" in json.loads(qfile.read_text())["reasons"][0]
    assert not list(folder.glob("*.jsonl")) and (folder / "applied" / "run_canon" / "p1_run.jsonl").is_file()
