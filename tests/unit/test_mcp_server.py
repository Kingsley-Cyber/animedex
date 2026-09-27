"""Request A (D-033): the MCP server's tools read the index only, search names its ranker, commentary is the
one write, idea cards stay hidden until the blind review is rated, and nothing reaches a model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from animedex.embeddings.base import EmbedderUnavailable, MockEmbedder
from animedex.mcpserver import tools
from animedex.mcpserver.search import AtomSearch, word_overlap
from animedex.mcpserver.server import build_server
from tests.pipeline.test_ideate import T1, T2, state, write_state

pytestmark = pytest.mark.unit


@pytest.fixture
def index(repo):
    write_state(repo, state())
    return repo


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_index_tools_answer_from_the_index_and_write_nothing(index):
    before = snapshot(index.root)
    titles = tools.list_titles(index)
    assert [t["title_id"] for t in titles] == sorted(t["title_id"] for t in state()["title"])
    t1 = tools.get_title(index, T1)
    assert t1["fields"]["power_combat.gate"] and t1["atoms"] and t1["commentary"] == []
    gate = t1["fields"]["power_combat.gate"]
    assert T1 in [r["title_id"] for r in tools.find_titles(index, {"power_combat.gate": gate})]
    atom = tools.get_atom(index, t1["atoms"][0])
    assert atom["proof"] and atom["checks"] and atom["eligible"] is True
    found = AtomSearch(index, lambda: MockEmbedder()).search("a helper pays for power with memory")
    assert found["ranker"] == "embedding" and found["results"]
    with pytest.raises(tools.ToolError, match="list_titles"):
        tools.get_title(index, "no_such_title_2000")
    assert snapshot(index.root) == before


def test_search_falls_back_to_word_overlap_and_says_so(index):
    def down():
        raise EmbedderUnavailable("Polymath's embedder isn't ready and Ollama is not running")

    search = AtomSearch(index, down)
    res = search.search("pays for power with memory", kind="transfer")
    assert res["ranker"] == "word_overlap" and "Ollama is not running" in res["note"]
    assert res["results"][0]["text"].startswith("A helper pays for power with memory")
    assert res["session_rankers"] == {"embedding": 0, "word_overlap": 1}
    assert word_overlap("memory power", "") == 0.0
    with pytest.raises(tools.ToolError):
        search.search("   ")


def test_commentary_is_the_one_write_and_it_is_guarded(index):
    row = tools.add_commentary(index, T1, "The cost only lands because the lead chooses it every time.",
                               now="2026-09-28T10:00:00+00:00")
    assert row["target_type"] == "title" and row["author"] == "owner"
    assert tools.commentary(index, T1)[0]["text"].startswith("The cost only lands")
    assert (index.root / "data" / "commentary" / "commentary.jsonl").is_file()
    with pytest.raises(tools.ToolError, match="200 words"):
        tools.add_commentary(index, T1, "word " * 201)
    with pytest.raises(tools.ToolError, match="no title, atom"):
        tools.add_commentary(index, "nothing_here", "a note")
    with pytest.raises(tools.ToolError):
        tools.add_commentary(index, T2, 'He said "never give up on your friends" and it worked.')


def test_idea_cards_stay_hidden_until_the_blind_packet_is_rated(index):
    with pytest.raises(tools.ToolError, match="stay hidden"):
        tools.champions(index)
    blind = index.root / "eval" / "blind"
    blind.mkdir(parents=True)
    (blind / "packet_2026-09-29.json").write_text(json.dumps({"date": "2026-09-29", "cards": [{"id": "c1"},
                                                                                             {"id": "c2"}]}))
    (blind / "ratings_2026-09-29.yaml").write_text(yaml.safe_dump({"cards": {"c1": {"rating": 4}}}))
    assert not tools.review_complete(index)
    (blind / "ratings_2026-09-29.yaml").write_text(yaml.safe_dump({"cards": {"c1": {"rating": 4},
                                                                             "c2": {"rating": 2}}}))
    assert tools.review_complete(index) and tools.champions(index) == []


def test_the_server_lists_its_tools_and_answers_a_call(index):
    server = build_server(index, AtomSearch(index, lambda: MockEmbedder()))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"search_atoms", "get_atom", "list_titles", "get_title", "find_titles", "list_cqs", "cq_answer",
                     "gaps", "champions", "commentary", "add_commentary",
                     "add_titles", "run_ideas", "check_concept", "job_status", "stop_job"}   # operate (D-045)
    read_only = {t.name for t in asyncio.run(server.list_tools()) if t.annotations and t.annotations.read_only_hint}
    assert read_only == names - {"add_commentary", "add_titles", "run_ideas", "check_concept", "stop_job"}
    result = asyncio.run(server.call_tool("list_titles", {}))
    assert T1 in json.dumps(result.model_dump() if hasattr(result, "model_dump") else result, default=str)


def test_the_server_imports_no_model_provider():
    code = ("import sys, animedex.mcpserver.server; "
            "print(sorted(m for m in sys.modules if m.startswith(('animedex.providers', 'anthropic'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"
