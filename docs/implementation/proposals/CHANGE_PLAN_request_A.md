# Change plan: request A (MCP chat, commentary, search_atoms)

**Status:** merged into main on 2026-09-27, after the blind-review packet was built ("FINISH IT"); decided by the lead under the owner's standing rule (D-033). The original request A text was never pasted (CHANGE_PLAN_v1.3-v1.5, "pending A"), so this plan implements the three items named in the owner's instruction and the constraints the earlier plan already recorded.

## What it is
- **MCP chat.** An MCP server, `animedex mcp` (stdio), that lets Kingsley talk to the index from any MCP client (Claude Desktop, Claude Code). The client's model does the chatting. The server never calls a model, never uses the web, and reads only the built index (earlier plan: "the MCP server never calls a model").
- **search_atoms.** Ranked search over mechanism and transfer atoms by meaning, using the pipeline's embedder: Polymath's sidecar first, Ollama as the backup (D-008). If neither is reachable, a word-overlap ranker answers, and every response names the ranker that ran (silent-fallback rule).
- **Commentary.** Kingsley's own notes attached to a title, an atom, a gap or a champion card: added and read through the MCP server, stored only in the private data repo (`data/commentary/`). Commentary is owner voice, not evidence. No pipeline stage reads it until a later request says so.

## Tools (one server, two scopes)
| Tool | Scope | Returns |
|---|---|---|
| `search_atoms(query, kind, title_id, eligible_only, limit)` | index, read-only | atom id, kind, title, pattern or element/because, bridge concepts, support, eligibility, score, ranker |
| `get_title(title_id)` | index, read-only | the compact profile (enums and key phrases), outcome, cast summary, verification mix |
| `find_titles(filters, text)` | index, read-only | titles matching enum filters (path = value), optionally ranked by text |
| `get_atom(atom_id)` | index, read-only | the atom with its proof, checks and transfers |
| `list_cqs()`, `cq_answer(cq_id)` | index, read-only | saved CQ answers from the last ANALYZE build |
| `gaps(limit)` | index, read-only | ranked real gaps (expected ≥ 3, none observed), unreliable fields excluded |
| `commentary(target_id)` | commentary, read | the notes on a target, newest first |
| `add_commentary(target_id, text)` | commentary, write | appends one note (≤ 200 words, content guards); writes nowhere else |

## Rules
1. **Read-only index.** Index tools open canonical files and the DuckDB build read-only. A test proves no index tool writes a file.
2. **One write path.** `add_commentary` writes only `data/commentary/commentary.jsonl`, and only for a target id that exists. The data repo backs it up after each write batch (`make data-push`).
3. **Blind review stays blind.** Until the review is imported (`animedex review` has ratings for every packet card), no tool returns idea cards, arms or the answer key. Champions become visible after import.
4. **No model, no web.** The server imports no provider code. A test fails if it does.
5. **Accounting.** Every `search_atoms` response carries `ranker: embedding | word_overlap`, and the server log counts fallbacks.

## Build steps (after the packet)
1. `src/animedex/mcp/server.py` (the official `mcp` Python SDK, FastMCP), `mcp/tools.py` (pure functions over `Paths`), `mcp/search.py` (atom texts, embedding cache keyed by text hash + embedder id, word-overlap fallback).
2. `animedex mcp` CLI entry; `make mcp`; USAGE section with the Claude Desktop config snippet.
3. Tests: tool contracts, read-only proof, the blind guard, the fallback label, commentary caps and guards.
4. Docs: 02 (interface: CLI + MCP), 03 (MCP server), 04 (commentary record), 05 (tools), 06 (write scope), 10 (rules).
