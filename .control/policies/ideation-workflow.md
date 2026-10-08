# IDE agent ideation workflow

Owner correction, 2026-10-07: ANIMEDEX needs repo-owned instructions and tools usable from Claude,
Codex, or another IDE. The research methods below remain in scope; none is silently discarded.

## Contract

The public product CLI in `src/animedex/cli.py` owns all model calls and private writes.
`scripts/animedex_agent.py` is the host-neutral agent entrypoint. Its `tools`, `status`, and `lookup`
commands are read-only JSON. `scan`, `abduct`, and `quick` call the existing product CLI.
Run them in that order. A human chooses the sourced gap and then the passing frame. The agent
may show candidates and verdicts, but must not silently make either creative choice.

The scan is evidence of discussion on a fetched page, not proof of a genre-wide gap. The frame
gate can reject a fusion before card scoring. A gate result is a model judgment, not proof of
originality. A live source and a human reading are needed before calling a premise fresh.
The IDE entrypoint challenges the three reasoning hypotheses with unanswered supporting and
falsifying questions before frames are drafted. `make export` derives node and edge CSVs from
private records; `lookup --id` traces an ID to its sources without creating another store.

## Research methods in scope

These are testable software adaptations of mechanisms from the owner's supplied research notes.
The links identify the primary research; ANIMEDEX does not claim to reproduce each paper's full
method or its reported results.

| Method | Wired behavior in `make abduct` | Current boundary |
|---|---|---|
| [GS-3](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1654716/full) | The gate critiques frames; its failure reasons direct a further generation pass | No learned critic or adaptive sampling entropy |
| [Graph of States](https://arxiv.org/abs/2603.21250) | A validated graph links the sourced gap, indexed premises, reasoning steps, frames, comparisons, gate verdicts, and revisions | Links encode recorded dependencies, not proven causation |
| [Theorem-of-Thought](https://arxiv.org/abs/2506.07106) | Three independent abductive, deductive, and inductive calls write cited reasoning traces | No NLI-calibrated Bayesian propagation or graph winner selection |
| [Quantum abduction](https://arxiv.org/abs/2509.16958) | Candidate frames stay open through explicit comparison and possible synthesis before the gate | No quantum formalism or hardware |
| [MCMC premise retrieval](https://www.jstage.jst.go.jp/article/pjsai/JSAI2025/0/JSAI2025_1Win439/_pdf/-char/en) | A seeded Metropolis-Hastings chain samples private note premises and records every transition | The small local index does not establish a retrieval gain over exact ranking |

The private record permits inspection of each stage. The method names alone must never make a
run appear more creative or proven. The owner still makes the jump from candidate to selected frame.
