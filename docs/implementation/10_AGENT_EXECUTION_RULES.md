# 10 — Agent Execution Rules

Rules for the coding agent building ANIMEDEX.

## Read order
CHANGELOG → 00 → 02 → 03 → 04 → 05 → 06 → 07 (current milestone only) → 08 (its ACs) → 10 → 11.

## Rules
1. **One milestone at a time.** Do not start the next milestone until the current one's ACs pass and its completion report (12) is filed.
2. **Build only what the milestone lists.** Everything in 02's non-goals is off-limits.
3. **Contracts first.** Models and contract tests before pipeline logic.
4. **Never weaken, skip, or delete a test to make it pass.** If a test is wrong, say so in the report and propose the fix.
5. **Canonical data is written only by CANONICALIZE and ROLLUP.** Never hand-edit `data/canonical/`.
6. **No domain vocabulary in `src/`.** Enums, module definitions, operators, and prompt text live in `ontology/`, `config/`, and `prompts/`.
7. **Develop against the mock provider.** Live calls only for smoke tests and milestone runs, within the budget caps.
8. **Secrets via environment variables.** `.env` is gitignored. Never commit keys.
9. **Copyright.** No transcripts, subtitles, dialogue, or copied text in the repo, fixtures, or prompts. Paraphrase.
10. **Recall is not verification.** Never mark a field `web_confirmed` without a fetched source.
11. **Ontology changes go through proposals.** Never add enum values directly.
12. **Determinism.** Sort outputs by ID; fixed seeds; timestamps only in provenance, never in derived table contents.
13. **Prompts are versioned files.** Any edit bumps the version and is listed in the report.
14. **Stop and ask** when: specs conflict, an AC looks impossible, a change touches 02, a budget cap is hit, or data would be deleted.
15. **Boring dependencies.** Default stack: Python 3.11+, pydantic, duckdb, httpx, typer, pytest. Any new dependency is justified in the report.
16. **Local-first.** Every provider sits behind the interface; `openai_compatible` must work against a local endpoint.
17. **Small commits,** one concern each: `M<n>: <what>`. End each milestone with a tag `m<n>-complete`.
18. **Every milestone ends with a completion report** using 12.
19. **Episodes need a fetched source.** Never create an episode record from recall alone. Store a ≤60-word paraphrase and the URL; never the fetched text.
20. **Stay inside scope in every pass.** Treat a scope leak (another adaptation, unadapted source material) as a bug, not a nuance.
21. **Only status changes spend tokens in ROLLUP.** If a supporting episode triggers a re-run, that's a caching bug.
22. **MCP server (request A).** It never calls a model or the web. Only `add_commentary` writes, only to `data/commentary/`, and only Kingsley's own words when he asks for a note.
