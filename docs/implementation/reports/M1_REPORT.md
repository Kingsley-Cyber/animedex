# Completion Report — M1: Foundation

- **Date:** 2026-09-26
- **Agent / model:** Claude Code (claude-opus-5-5), under URCP (`harness` at `b645ea5`)
- **Commit tag:** `m1-complete`

## Summary
M1 built the foundation: pydantic contracts for every 04 record, the ontology with a clean CQ coverage table, an atomic canonical store, cache, redacted run logs, three provider adapters plus embeddings and search interfaces, the full CLI, and a deterministic DuckDB build. AC-01 to AC-08 pass: 129 tests, 0 skipped, `make validate` and the clean rebuild both green, and URCP `harness validate` PASS. Next is G1 (your config, gold picks, and blind annotations); M2's offline work starts now, and its live runs wait on G1.

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-01 | pass | `tests/contract/test_schemas.py` (5); `make schemas` writes 14 files; committed schemas match the models |
| AC-02 | pass | `test_canonical_store.py`: invalid titles, a mixed batch, and a dangling reference all leave canonical bytes unchanged |
| AC-03 | pass | `test_canonical_store.py`: `other:<phrase>` stored as `other` with a proposal file; alternate labels normalize with no proposal |
| AC-04 | pass | `make validate`: 89 coverage rows (50 lens fields, 7 modules, 23 vocab fields, 9 bridge concepts), 0 orphans; removing a CQ makes validate fail |
| AC-05 | pass | `test_atomic_crash.py`: a child process SIGKILLed before the rename and during fsync leaves `titles.jsonl` byte-identical and valid |
| AC-06 | pass | `test_cache.py` (10): stable keys; a P3 prompt bump spares P1/P2 and re-runs P3 and CHECK; support-count edits change nothing; status, explanation, and promotion edits invalidate |
| AC-07 | pass | `test_determinism.py` (5); `make clean-build`: identical hashes over 18 tables + 5 views; provenance timestamps never reach derived tables |
| AC-08 | pass | `test_offline_pipeline.py` (15) with sockets blocked: mock pass → repair → quarantine → CANONICALIZE → BUILD → VALIDATE; unbuilt stages exit 2 and name their milestone |

Beads: `animedex-b1o.3.1`–`.3.9`, each closed with the evidence above. The owner's G0 blind guard is `.3.9` (`test_blind_guard.py`, 6 tests).

## Tests
- `make test`: 129 passed / 0 failed / 0 skipped (80 unit, 49 contract and pipeline).
- `make validate`: pass (one warning: 19 config items block live runs; that is G1a).
- Clean-rebuild determinism: pass.
- URCP `harness validate`: PASS, proof `UNIT_PROVEN` (lint PASS, unit PASS, pyright skipped as optional and not installed).

## Metrics
No live model or web calls in M1: 0 tokens, $0. Metrics from P1 onward start in M2.

## Changes to prompts, vocab, or config
| File | Version | Why |
|---|---|---|
| `ontology/vocab.json` | new, 1.2.0 | 04 starter enums, plus a `lens` section declaring P1 fields and modules (spec v1.2: four fields deleted at G0) |
| `ontology/bridge.json` | new, 1.1.0 | 9 bridge concepts with definitions and `cq_refs` |
| `ontology/competency_questions.yaml` | new, 1.2.0 | 01's CQs with `requires:`; CQ-E04 extended, CQ-I13 added (G0 D4) |
| `config/settings.yaml` | new | 05 values, plus provider profiles, `pricing`, `models.eval_match`, `diversity_alarm.champion_share`, `p3.load_bearing_low_flag: 3` (AC-16), and an `eval` section |
| `prompts/` | none yet | P1 and VERIFY prompts arrive in M2 |

## Deviations from spec
1. **Lens in `vocab.json`:** P1 fields and modules are declared in the ontology, and the title-profile model is built from them, so module definitions stay out of `src/` (10 §6). Deleting a field is an ontology edit, not a code change.
2. **New dependencies (10 §15):**
   - `anthropic` 1.8.0: the official SDK for the Anthropic adapter (native structured outputs, typed errors, built-in retries, refusal fallbacks).
   - `PyYAML`: settings, corpus, and CQs are YAML.
3. **Off-vocab value on a P1 enum without `other`** (for example `progression`): stored as `value: null`, `conf: 0`, with an `uncertainty_reason`, and a proposal is written. Storing `other` there would put a non-vocab value in canonical data, which P-04 forbids.
4. **Anthropic refusal fallbacks are on by default** (`fallbacks: default`), per current Claude API guidance. Provenance records the model that actually served the call. Set it to `null` in `config/settings.yaml` to turn it off.
5. **CANONICALIZE archives applied candidates** to `data/candidates/<type>/applied/<run_id>/`, so a rerun cannot revert a later canonical update.
6. **`integration` marker:** contract and pipeline tests also carry it, because URCP's validator runs `pytest -m integration` with a hardcoded command.
7. **Python pinned to 3.12** for URCP parity; `requires-python` stays at `>=3.11` per the spec.
8. **`make build`** is BUILD only for now. ANALYZE's CQ-answer step joins it in M4 (accepted default G-10).

## Ontology proposals pending review
None.

## NEEDS_ADJUDICATION and unsettled CONTESTED items
None (no atoms exist yet).

## Decisions needed from Kingsley (G1)
**G1a: live-run config.** `uv run animedex smoke` prints the live list; it is 19 items today.
1. **Models per pass.** Recommended:
   - `claude-opus-5` (Anthropic) for p2, p3, and ideate_generate;
   - `claude-haiku-4-5` (Anthropic) for the cheap passes (p1, verify, p4, ep, rollup_match, eval_match);
   - for check and ideate_judge, a strong non-Claude model you name, on an OpenAI-compatible API such as OpenRouter.
2. **API keys:** paste into `.env` (already created, gitignored): `ANTHROPIC_API_KEY`, `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_API_KEY`. Never paste keys in chat.
3. **Search backend:** Brave Search API recommended (free tier; put the key in `SEARCH_API_KEY`). Alternatives: Tavily, or a local SearXNG.
4. **Budget caps:** recommended run $25, per title $3, per episode $0.25.
5. **Pricing:** I fill in Claude prices from the official table once you confirm models; give the per-million-token price for the non-Claude model.
- *Later (M5):* an embedding model for local Ollama, e.g. `ollama pull nomic-embed-text` (a download I'll ask about then).

**G1b: gold picks and scopes.** See `eval/gold/G1B_PROPOSAL.md`.
- Approve the label rule.
- Mixed: Sword Art Online (2012); backup Guilty Crown.
- Flop: Big Order (2016); backup Platinum End.
- Approve the five scopes (Solo Leveling S1 + S2).

**G1c: blind annotations.**
- Fill the three templates in `eval/gold/` (Solo Leveling, FMA: Brotherhood, Hunter x Hunter).
- The mixed and flop templates are created the moment you approve G1b.
- Tell me when they're done; I'll check and commit them. Live gold runs refuse until then (G2, enforced in code).

## Known issues and risks
1. **URCP portability gaps** (hardcoded `planning/` path, no `--project-id`, `python`-only environment probe on macOS, 2 environment-dependent tests) are in their own task; they don't block ANIMEDEX.
2. **Anthropic structured outputs accept a subset of JSON Schema.** The pass schemas built in M2 get checked by `make smoke` against the real API before any gold run.
3. **The P4 name-leak list is a heuristic** (full titles plus capitalized mid-sentence words). Expect false positives, to be tuned in M3.
4. **The MAL API (Jikan) was down** during G1b research, so values come from live MAL pages. Scores get re-fetched when the gold set is frozen.
5. **VERIFY's cap of 3 searches** (+2 for outcomes) will leave many sensory fields and moment locators `unresolved`.

## Next milestone readiness
- [x] All ACs pass (AC-01 to AC-08)
- [x] Report filed
- [x] Tagged `m1-complete`; pushed to `Kingsley-Cyber/animedex` right after tagging
