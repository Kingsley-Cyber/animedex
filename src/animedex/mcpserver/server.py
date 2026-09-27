"""`animedex mcp` (request A, D-033): the ANIMEDEX index as an MCP server over stdio.

The client's model does the chatting; this server only answers from the built index. It never calls a
model or the web. Index tools are read-only; `add_commentary` writes one file in the private data repo.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from mcp.types import ToolAnnotations

from animedex.mcpserver import tools
from animedex.mcpserver.search import AtomSearch
from animedex.paths import Paths

INSTRUCTIONS = (
    "ANIMEDEX indexes anime and other shows by how their power systems, engines and effects work. "
    "Use search_atoms to find mechanisms by meaning, get_atom for the evidence behind one, get_title for a "
    "show's profile, find_titles to filter by enum values (e.g. power_combat.gate = contract), list_cqs and "
    "cq_answer for the saved competency questions, and gaps for combinations nothing in the corpus uses. "
    "Commentary is Kingsley's own notes; add one only when he asks. Idea cards stay hidden until the blind "
    "review is fully rated.")
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)


def _answer(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """An index error (unknown id, hidden cards) goes back to the client as its message, not as a crash."""
    try:
        return fn(*args, **kwargs)
    except tools.ToolError as exc:
        raise McpToolError(str(exc)) from None


def default_embedder(paths: Paths):
    def make():
        from animedex.config import environment, load_settings
        from animedex.embeddings.base import build_embedder

        return build_embedder(load_settings(paths), environment(paths))
    return make


def build_server(paths: Paths, search: AtomSearch | None = None) -> MCPServer:
    search = search or AtomSearch(paths, default_embedder(paths))
    server = MCPServer(name="animedex", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ)
    def search_atoms(query: str, kind: str = "any", title_id: str | None = None, eligible_only: bool = False,
                     limit: int = 10) -> dict[str, Any]:
        """Mechanism and transfer atoms ranked by meaning. kind: any, mechanism or transfer. eligible_only keeps
        the load-bearing atoms ideation may use. The answer names the ranker (embedding or word_overlap)."""
        return _answer(search.search, query, kind=kind, title_id=title_id, eligible_only=eligible_only,
                       limit=limit)

    @server.tool(annotations=READ)
    def get_atom(atom_id: str) -> dict[str, Any]:
        """One atom (or transfer id) with its proof, CHECK verdicts, transfers and Kingsley's commentary."""
        return _answer(tools.get_atom, paths, atom_id)

    @server.tool(annotations=READ)
    def list_titles() -> list[dict[str, Any]]:
        """Every indexed title with its id, year, medium and outcome label."""
        return _answer(tools.list_titles, paths)

    @server.tool(annotations=READ)
    def get_title(title_id: str) -> dict[str, Any]:
        """A title's compact profile: every filled field, the outcome, the cast, its atom ids and commentary."""
        return _answer(tools.get_title, paths, title_id)

    @server.tool(annotations=READ)
    def find_titles(filters: dict[str, str]) -> list[dict[str, Any]]:
        """Titles whose fields hold the given values, e.g. {"power_combat.gate": "contract"}."""
        return _answer(tools.find_titles, paths, filters)

    @server.tool(annotations=READ)
    def list_cqs() -> list[dict[str, str]]:
        """The saved competency questions from the last analysis, with their row counts."""
        return _answer(tools.list_cqs, paths)

    @server.tool(annotations=READ)
    def cq_answer(cq_id: str, limit: int = 50) -> dict[str, Any]:
        """One saved competency-question answer (its columns and up to `limit` rows)."""
        return _answer(tools.cq_answer, paths, cq_id, limit)

    @server.tool(annotations=READ)
    def gaps(limit: int = 20) -> dict[str, Any]:
        """Real gaps: combinations expected at least 3 times by chance that no title uses."""
        return _answer(tools.gaps, paths, limit)

    @server.tool(annotations=READ)
    def champions() -> list[dict[str, Any]]:
        """The best idea card in each grid cell, only after the blind review is fully rated."""
        return _answer(tools.champions, paths)

    @server.tool(annotations=READ)
    def commentary(target_id: str) -> list[dict[str, Any]]:
        """Kingsley's notes on a title, atom, transfer, idea or CQ, newest first."""
        return _answer(tools.commentary, paths, target_id)

    @server.tool(annotations=WRITE)
    def add_commentary(target_id: str, text: str) -> dict[str, Any]:
        """Save one of Kingsley's notes (200 words or fewer, his own words, no quotes) on an existing target."""
        return _answer(tools.add_commentary, paths, target_id, text)

    return server


def main() -> None:
    build_server(Paths.discover()).run("stdio")
