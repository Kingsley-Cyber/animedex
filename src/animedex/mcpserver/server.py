"""`animedex mcp` (request A, D-033): the ANIMEDEX index as an MCP server over stdio.

The client's model does the chatting; this server only answers from the built index. It never calls a
model or the web. Index tools are read-only; `add_commentary` writes one file in the private data repo.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from mcp.types import ToolAnnotations

from animedex.mcpserver import jobs, tools
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
OPERATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)


def _answer(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """An index or job error (unknown id, hidden cards, a job already running) goes back to the client as
    its message, not as a crash."""
    try:
        return fn(*args, **kwargs)
    except (tools.ToolError, jobs.JobRunning, ValueError) as exc:
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

    # ---- operate (D-045): start the long commands in the background, one at a time
    @server.tool(annotations=OPERATE)
    def add_titles(titles: list[str], run: bool = True) -> dict[str, Any]:
        """Add shows to the corpus and index them in the background (about 12 minutes each, 4 per run; call
        again with the same lines to continue after a pause). Put the year in parentheses to pick a version,
        e.g. "Levius (2019)". run=false only shows which version would be picked, without starting anything."""
        return _answer(jobs.add_titles, paths, titles, run=run)

    @server.tool(annotations=OPERATE)
    def run_ideas(generations: int | None = None, arm: str = "animedex") -> dict[str, Any]:
        """Start one ideation run in the background (60 calls, about 40 minutes, one more generation of cards).
        Cards land in build/reports/ideas.md. arm: animedex (default) or baseline_loop."""
        argv = ["ideate", "--arm", arm, *(["--generations", str(generations)] if generations else [])]
        return _answer(jobs.start_job, paths, "ideas", argv, note=f"arm {arm}")

    @server.tool(annotations=OPERATE)
    def check_concept(text: str) -> dict[str, Any]:
        """Run Kingsley's own concept through the clone, novelty, graveyard and name checks, the judge and the
        ablation (3 calls, about a minute). Read the verdicts with job_status once it finishes."""
        return _answer(jobs.start_job, paths, "diagnose", ["diagnose", "--text", text], note=text[:80])

    @server.tool(annotations=READ)
    def job_status() -> dict[str, Any]:
        """The running job with the tail of its log, the last finished job, and every batch's status summary."""
        return _answer(jobs.job_status, paths)

    @server.tool(annotations=OPERATE)
    def stop_job() -> dict[str, Any] | None:
        """Stop the running job. Finished calls stay cached, so starting it again continues where it stopped."""
        return _answer(jobs.stop_job, paths)

    return server


def main() -> None:
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)  # the embedder's request log is noise on stderr
    build_server(Paths.discover()).run("stdio")
