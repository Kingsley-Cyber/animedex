# Abductive ideation migration

Owner request, 2026-10-07: use Graphify and Graft, implement the research methods previously left as design inputs, and migrate the IDE agent path.

## Contract

Given one sourced scan gap and the private show notes, the IDE agent's `abduct` tool must produce a private frame record that:

- retrieves relevant note premises through an inspectable MCMC chain;
- keeps independent abductive, deductive, and inductive reasoning traces with explicit source and dependency links;
- holds conflicting candidate frames through a comparison and synthesis step before the frame gate;
- uses the gate's criticism to direct a further generation step when candidates fail;
- records a causal state graph from sourced observation through premises, hypotheses, criticism, and frames;
- still requires the owner to choose a passing frame before `quick` can build cards.

These are testable software adaptations of GS-3, Graph of States, Theorem-of-Thought, quantum abduction, and MCMC premise retrieval. They do not claim learned critics, calibrated Bayesian probabilities, or quantum computation without those implementations and evidence. No new taste threshold is introduced.

Research mode needs two candidate frames because a comparison requires distinct sides. The existing owner gate needs three indexed shows for its contrasts. The premise chain takes one corpus-sized sweep per requested premise slot, so its work scales with the measured note count and the requested frame count. A single feedback transition is the smallest generator → critic → controller → generator cycle; it is not a claim that later candidates have converged.

## Migration

`animedex abduct --research` writes the new record under the existing private `build/quick/_frames/` path. The `make abduct` and `scripts/animedex_agent.py abduct` entrypoints pass `--research`. Plain `animedex abduct` and old frame records remain readable so the original tests and saved owner selections keep working. `quick` continues to use the existing frame gate loader, not a new card path. No private file is rewritten or deleted.

Graphify's local AST graph and Graft's local wiring graph identify the public `abduct` handler, `run_abduct`, and `load_selected_frame` as the migration seam. Their generated indexes stay out of the public repository. Graft setup that would write global IDE configuration is outside this change.

## Ordered work and proof

1. Add deterministic MCMC premise retrieval with trace and citeable note IDs. Prove that the returned premise set comes from the current notes and is reproducible for the same gap.
2. Add independent reasoning lenses, hypothesis suspension/synthesis, gate feedback, and a validated causal state graph to the research mode. Prove through the public CLI that fetched scan evidence reaches a passing frame and a rejected fusion cannot reach `quick`.
3. Move the repo's IDE entrypoints to research mode while retaining the old CLI and record contract. Prove a prior frame record still loads, no existing test or evaluation file changes, and the original suite passes.
4. Refresh Graphify and Graft indexes, run `make lint`, `make test`, `harness validate`, and `harness proof status`; then update the draft PR with exact limits of the evidence.

The scan now uses Codex Terra for live web retrieval because the Claude subscription reached its plan limit. Mock-backed CLI tests prove wiring and validation; human review determines whether the resulting premises are fresh and worth building.
