# Audit: the light path only (2026-09-27)

Owner instruction: delete-only, no new features. Before = the tag `heavy-final` (commit c6ff602, the last commit with the heavy pipeline). After = this commit. Decisions D-056 to D-061.

## Numbers

| | Before | After | Change |
|---|---|---|---|
| Source lines (`src/animedex/**/*.py`) | 22,160 in 110 files | 5,019 in 39 files | -77% |
| Test lines (`tests/**/*.py`) | 10,134 in 61 files | 2,312 in 25 files | -77% |
| Tests | 604 | 114 | all pass |
| Prompt files | 35 (583 lines) | 4 (62 lines): ingest, generate, check, prior_art | -31 |
| Enums (`ontology/vocab.json`) | 62 fields (1,526 lines) | 6 (12 lines) | -56 |
| Competency questions | 74 | 5 (all run on notes) | -69 |
| Model slots (`config/settings.yaml`) | 19 (209 lines) | 4 (61 lines): ingest, generate, check, embeddings | -15 |
| Model adapters | 5 (claude CLI, codex CLI, Anthropic API, OpenAI-compatible API, mock) | 3 (claude CLI, codex CLI, mock) | -2 |
| Doc lines (`docs/**/*.md`) | 5,093 | 389 | -92% |
| Make targets | 29 | 11 | -18 |
| Runtime dependencies | 7 | 5 (`anthropic`, `mcp` dropped) | -2 |

## What went

| Owner item | Removed | Where it is now |
|---|---|---|
| 1. Heavy pipeline | GATHER, INTERPRET, VERIFY, PROFILE, P1, P2 atoms, P3 proofs, the CHECK critic, P4 patterns, IDEATE, census, backtest, audit, batch, timing, stats page, their 31 prompts and 490 tests, docs 00-12 and the milestone reports | tag `heavy-final`; `legacy/README.md` runs a gold title from a worktree at the tag |
| 2. One store | the canonical JSONL store and its DuckDB build, `make build`, `clean-build`, `validate`, `schemas` | notes/ is the store; `make analyze` reads notes/*.json in place; `make export` writes `build/exports/notes.csv` and `cards.csv` |
| 3. Dead weight | Anthropic and OpenAI-compatible adapters; pricing and dollar caps; per-title call caps; the client's title guard; the MAP-Elites archive and grid; the length-repair loop and every word-cap check (caps are prompt guidance now); the framing-term guard; the MCP server | the paraphrase guard stays (quotations, dialogue lines) |
| 4. Prompts, enums, CQs | 31 prompts; 56 enum fields; 69 questions | quick's research = the ingest prompt's `job: seed`; diagnose = `job: concept` + the check prompt (2 calls, was 3) |

Kept as they were: `make review` (the blind packet; its report now reads the packet cards' stored records directly), `make data-push` / `data-pull`, the steering rules, the call cap, the response cache, the run logs, the MAL block, the plan-limit pause.

## Runtime

Before (the light path on the heavy-era code, 2026-09-27, live):

| Run | Calls | Time | Per unit |
|---|---|---|---|
| `make ingest` priority_1 (40 shows) | 14 | 20.6 min | 30 s of call time per note |
| `make ingest` donghua (10 shows) | 4 | 14.2 min | 84 s per note (obscure titles: the model read pages) |
| `make ingest` print_first (2 shows) | 1 | 0.8 min | 23 s per note |
| `make quick` feral seed, first run | 4 (+1 hidden length repair) | 4.5 min | research 36 s, generate 159 s (incl. a 12 s `.shorten` call), check 37 s, prior art 28 s |
| `make quick` feral seed, second run | 3 (research skipped) | 3.6 min | generate 162 s, check 40 s, prior art 14 s |
| `make quick` MOLT concept | 4 (+1 hidden length repair) | 6.1 min | research 39 s, generate 244 s (incl. a 5 s `.shorten` call), check 55 s, prior art 25 s |

After: AFTER_RUNTIME
