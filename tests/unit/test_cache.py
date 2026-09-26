"""AC-06: stable cache keys; P3 prompt change does not invalidate P1/P2; support-count changes
invalidate nothing; status changes do."""

from __future__ import annotations

import copy

import pytest

from animedex.store.cache import ResponseCache, cache_key, upstream_hash
from tests.conftest import make_effect_atom, make_proof, make_title

pytestmark = pytest.mark.unit


def key(pass_: str, prompt_version: str, upstream: str, params: dict | None = None, record_id: str = "t_2020") -> str:
    return cache_key(record_id=record_id, pass_=pass_, prompt_version=prompt_version, schema_version="1.2.0",
                     vocab_version="1.2.0", model="anthropic/strong", params=params or {}, upstream=upstream)


def pipeline_keys(prompts: dict[str, str], atom: dict, proof: dict) -> dict[str, str]:
    title = make_title()
    up_p1 = upstream_hash([{"corpus_entry": title["title_id"]}])
    up_p2 = upstream_hash([title])
    up_p3 = upstream_hash([title, atom])
    up_check = upstream_hash([atom, proof])
    return {
        "P1": key("P1", prompts["P1"], up_p1),
        "P2": key("P2", prompts["P2"], up_p2),
        "P3": key("P3", prompts["P3"], up_p3),
        "CHECK": key("CHECK", prompts["CHECK"], up_check),
    }


PROMPTS = {"P1": "1.0.0", "P2": "1.0.0", "P3": "1.0.0", "CHECK": "1.0.0"}


def test_keys_are_stable_and_prefixed():
    a, b = key("P1", "1.0.0", "sha256:x"), key("P1", "1.0.0", "sha256:x")
    assert a == b and a.startswith("sha256:") and len(a) == len("sha256:") + 64


def test_p3_prompt_change_leaves_p1_p2_but_invalidates_p3_and_check():
    atom, proof = make_effect_atom(), make_proof()
    before = pipeline_keys(PROMPTS, atom, proof)
    bumped = pipeline_keys({**PROMPTS, "P3": "1.1.0"}, atom, proof)
    assert bumped["P1"] == before["P1"] and bumped["P2"] == before["P2"]
    assert bumped["P3"] != before["P3"]
    # the re-run P3 writes proofs stamped with the new prompt version -> CHECK re-runs
    new_proof = copy.deepcopy(proof)
    new_proof["provenance"]["prompt_version"] = "1.1.0"
    assert pipeline_keys({**PROMPTS, "P3": "1.1.0"}, atom, new_proof)["CHECK"] != before["CHECK"]


def test_support_count_change_invalidates_nothing():
    atom, proof = make_effect_atom(), make_proof()
    before = pipeline_keys(PROMPTS, atom, proof)
    more_support = copy.deepcopy(atom)
    more_support["support"]["supporting_episodes"] = ["ironvale_circuit_2021.s01e01", "ironvale_circuit_2021.s01e05"]
    more_support["support"]["reframing_episodes"] = ["ironvale_circuit_2021.s02e01"]
    assert pipeline_keys(PROMPTS, more_support, proof) == before


@pytest.mark.parametrize("field, value", [
    (("support", "status"), "mixed"),
    (("support", "status"), "contradicted"),
    (("explanation",), "contested"),
    (("origin",), "promoted_from_episodes"),
])
def test_status_explanation_and_promotion_changes_invalidate(field, value):
    atom, proof = make_effect_atom(), make_proof()
    before = pipeline_keys(PROMPTS, atom, proof)
    changed = copy.deepcopy(atom)
    target = changed
    for part in field[:-1]:
        target = target[part]
    target[field[-1]] = value
    after = pipeline_keys(PROMPTS, changed, proof)
    assert after["P3"] != before["P3"] and after["CHECK"] != before["CHECK"]
    assert after["P1"] == before["P1"] and after["P2"] == before["P2"]


def test_provenance_run_id_and_timestamp_do_not_invalidate():
    atom = make_effect_atom()
    same = copy.deepcopy(atom)
    same["provenance"].update(run_id="run_other", created_at="2030-01-01T00:00:00+00:00", cache_key="sha256:" + "0" * 64)
    assert upstream_hash([atom]) == upstream_hash([same])


def test_transport_params_ignored_real_params_count():
    base = key("P1", "1.0.0", "sha256:x", {"max_tokens": 100})
    assert key("P1", "1.0.0", "sha256:x", {"max_tokens": 100, "_meta": {"attempt": 1}}) == base
    assert key("P1", "1.0.0", "sha256:x", {"max_tokens": 200}) != base
    assert key("P1", "1.0.0", "sha256:x", {"max_tokens": 100, "rerun": 2}) != base  # agreement reruns


def test_response_cache_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path)
    k = key("P1", "1.0.0", "sha256:x")
    assert cache.get("P1", k) is None
    cache.put("P1", k, {"json": {"a": 1}, "model": "m"})
    assert cache.get("P1", k) == {"json": {"a": 1}, "model": "m"}
