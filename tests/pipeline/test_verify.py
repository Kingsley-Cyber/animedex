"""VERIFY on mock search + mock model: citations required, corrections logged, caps enforced,
fetched text never stored, outcome recorded with sourced metrics."""

from __future__ import annotations

import json

import httpx
import pytest

from animedex import SCHEMA_VERSION
from animedex.config import ModelSpec, load_settings
from animedex.models import CorpusEntry
from animedex.ontology import get_vocab
from animedex.pipeline.canonicalize import canonicalize
from animedex.pipeline.verify import run_verify
from animedex.providers.client import LLMClient
from animedex.providers.mock import MockProvider
from animedex.search.base import MockSearch, SearchResult
from animedex.search.web import BraveSearch, SearchBudget, html_to_text
from animedex.store.cache import ResponseCache
from animedex.store.jsonl import read_jsonl
from animedex.store.runlog import RunLog
from tests.pipeline.test_p1 import ENTRY, KEY, make_draft, run

pytestmark = pytest.mark.pipeline

TID = "ironvale_circuit_2021"
FACTS, EPISODES = "https://ref.example/ironvale", "https://ref.example/ironvale-episodes"
REVIEW, RATINGS = "https://reviews.example/ironvale", "https://ratings.example/ironvale"
PAGE = {FACTS: "Synthetic reference page describing the power look as violet circuitry lines on the skin. " * 3,
        EPISODES: "Synthetic episode list: episode 1 pilot, episode 2 grid, episode 3 rival, episode 7 reroute. " * 3,
        REVIEW: "Synthetic review: strong reception, praised pacing and animation, rated highly by critics. " * 3,
        RATINGS: "Synthetic ratings page: average score 8.4 from 300k users. " * 3}


def search() -> MockSearch:
    results = {
        "Ironvale Circuit 2021 anime": [SearchResult(FACTS, "ref", "")],
        "Ironvale Circuit anime episode list": [SearchResult(EPISODES, "eps", "")],
        "Ironvale Circuit 2021 anime reception ratings": [SearchResult(RATINGS, "ratings", "")],
        "Ironvale Circuit anime review": [SearchResult(REVIEW, "review", "")],
    }
    return MockSearch(results, PAGE)


def verify_out(**over) -> dict:
    out = {
        "fields": [
            {"path": "core.outcome", "status": "confirmed", "value": None, "source_url": RATINGS, "note": None},
            {"path": "sensory.power_visual_signature", "status": "corrected", "value": "violet circuitry lines on skin",
             "source_url": FACTS, "note": "page describes the look"},
            {"path": "sensory.color_motif", "status": "confirmed", "value": None, "source_url": "https://not-fetched.example", "note": None},
        ],
        "moments": [
            {"moment_id": f"{TID}.mo.01", "status": "confirmed", "season": 1, "episode": 1, "source_url": EPISODES},
            {"moment_id": f"{TID}.mo.02", "status": "corrected", "season": 1, "episode": 7, "source_url": EPISODES},
            {"moment_id": f"{TID}.mo.03", "status": "not_found", "season": None, "episode": None, "source_url": EPISODES},
        ],
        "outcome": {"label": "hit", "signals": [{"metric": "average user score", "value": "8.4", "source_url": RATINGS}],
                    "confounders": {"studio": "synthetic studio", "budget_signal": "", "source_popularity": "high",
                                    "platform": "", "release_context": ""}, "failure_reason": None},
    }
    out.update(over)
    return out


def verify(repo, responses, search_backend=None, settings=None):
    run(repo, {KEY: make_draft()})  # P1 candidates first
    settings = settings or load_settings(repo)
    mock = MockProvider(responses=responses)
    client = LLMClient(provider=mock, provider_name="mock", spec=ModelSpec(provider="mock", model="v"),
                       prompt_version="unset", schema_version=SCHEMA_VERSION, vocab_version=get_vocab().version,
                       cache=ResponseCache(repo.cache), runlog=RunLog(repo.raw_runs, "run_v"))
    backend = search_backend or search()
    result = run_verify(repo, [CorpusEntry.model_validate(ENTRY)], client, backend, get_vocab(), settings,
                        run_id="run_v", created_at="2026-09-26T13:00:00+00:00")
    return result, mock, backend


def test_statuses_require_fetched_citations(repo):
    # the uncited "confirmed" is rejected once, then the repaired answer drops it to unresolved
    bad = verify_out()
    good = verify_out(fields=[f for f in bad["fields"] if f["path"] != "sensory.color_motif"])
    result, mock, _ = verify(repo, {("VERIFY", TID): [bad, good]})
    assert "cite one of the provided page URLs" in mock.calls[1]["user"]
    [r] = result.titles
    assert r.statuses["core.outcome"] == "confirmed"
    assert r.statuses["sensory.power_visual_signature"] == "corrected"
    assert r.statuses["sensory.color_motif"] == "unresolved"
    [title] = read_jsonl(repo.candidates / "title" / f"{TID}.jsonl")
    sig = title["sensory"]["power_visual_signature"]
    assert (sig["value"], sig["verification"], sig["source"], sig["source_ref"]) == (
        "violet circuitry lines on skin", "web_corrected", "web", FACTS)
    assert title["sensory"]["color_motif"]["verification"] == "unresolved"
    assert title["core"]["logline_hook"]["verification"] == "not_required"
    assert r.conflicts[0]["path"] == "sensory.power_visual_signature"


def test_moments_located_corrected_or_dropped_and_outcome_recorded(repo):
    good = verify_out(fields=[f for f in verify_out()["fields"] if f["path"] != "sensory.color_motif"])
    result, _, _ = verify(repo, {("VERIFY", TID): good})
    moments = {m["moment_id"]: m for m in read_jsonl(repo.candidates / "moment" / f"{TID}.jsonl")}
    assert f"{TID}.mo.03" not in moments and result.titles[0].dropped_moments == [f"{TID}.mo.03"]
    assert moments[f"{TID}.mo.02"]["locator"]["episode"] == 7 and moments[f"{TID}.mo.02"]["verification"] == "web_corrected"
    [outcome] = read_jsonl(repo.candidates / "outcome" / f"{TID}.jsonl")
    assert outcome["label"] == "hit" and outcome["signals"][0]["source_ref"] == RATINGS
    assert outcome["provenance"]["pass"] == "VERIFY"


def test_fetched_text_is_never_stored(repo):
    good = verify_out(fields=[f for f in verify_out()["fields"] if f["path"] != "sensory.color_motif"])
    verify(repo, {("VERIFY", TID): good})
    for path in repo.root.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for page in PAGE.values():
                assert page[:60] not in text, path


def test_search_caps_leave_the_rest_unresolved(repo):
    settings = load_settings(repo)
    settings.verify["max_searches_per_title"] = 1
    settings.verify["outcome_extra_searches"] = 1
    out = verify_out(fields=[{"path": "core.outcome", "status": "unresolved", "value": None, "source_url": None, "note": None}],
                     moments=[], outcome=None)
    result, _, backend = verify(repo, {("VERIFY", TID): out}, settings=settings)
    [r] = result.titles
    assert backend.search_calls == 2  # 1 facts + 1 outcome; episodes and the second outcome query were capped
    assert any("search cap reached" in n for n in r.notes)
    assert set(r.statuses.values()) == {"unresolved"}


def test_no_pages_means_no_model_call_and_everything_unresolved(repo):
    result, mock, _ = verify(repo, {}, search_backend=MockSearch())
    assert mock.calls == [] and set(result.titles[0].statuses.values()) == {"unresolved"}


def test_verified_candidates_canonicalize(repo):
    import yaml

    repo.corpus_file.write_text(yaml.safe_dump({"titles": [ENTRY]}))
    good = verify_out(fields=[f for f in verify_out()["fields"] if f["path"] != "sensory.color_motif"])
    verify(repo, {("VERIFY", TID): good})
    out = canonicalize(repo, "run_c")
    assert out.written["title"] == [TID] and out.written["outcome"] == [TID] and len(out.written["moment"]) == 2


def test_search_budget_and_html_extraction():
    b = SearchBudget(max_searches=1, outcome_extra=1)
    b.take("a")
    b.take("o", outcome=True)
    with pytest.raises(Exception, match="search cap"):
        b.take("b")
    html = "<html><head><script>var x=1</script></head><body><nav>menu</nav><p>Real text here.</p></body></html>"
    assert html_to_text(html) == "Real text here."


def test_brave_adapter_request_shape():
    seen = {}

    def handler(request):
        seen["url"], seen["token"] = str(request.url), request.headers.get("x-subscription-token")
        return httpx.Response(200, json={"web": {"results": [{"url": "https://a.example", "title": "A", "description": "d"}]}})

    results = BraveSearch("key123", transport=httpx.MockTransport(handler)).search("q text")
    assert results[0].url == "https://a.example" and seen["token"] == "key123" and "q=q+text" in seen["url"]


def test_verify_json_summary_has_no_page_text(repo):
    good = verify_out(fields=[f for f in verify_out()["fields"] if f["path"] != "sensory.color_motif"])
    verify(repo, {("VERIFY", TID): good})
    summary = json.loads((repo.candidates / "verify" / f"{TID}.result.json").read_text())
    assert summary["sources"] == sorted(PAGE)
    assert all(page[:40] not in json.dumps(summary) for page in PAGE.values())
