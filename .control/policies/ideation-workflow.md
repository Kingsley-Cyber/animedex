# IDE agent ideation workflow

Owner correction, 2026-10-07: ANIMEDEX needs repo-owned instructions and tools usable from Claude,
Codex, or another IDE. The research methods below remain in scope; none is silently discarded.

## Contract

The public product CLI in `src/animedex/cli.py` owns all model calls and private writes.
`scripts/animedex_agent.py` is the host-neutral agent entrypoint. Its `tools` and `status`
commands are read-only JSON. `scan`, `abduct`, and `quick` call the existing product CLI.
Run them in that order. A human chooses the sourced gap and then the passing frame. The agent
may show candidates and verdicts, but must not silently make either creative choice.

The scan is evidence of discussion on a fetched page, not proof of a genre-wide gap. The frame
gate can reject a fusion before card scoring. A gate result is a model judgment, not proof of
originality. A live source and a human reading are needed before calling a premise fresh.

## Research methods in scope

These are proposed mechanisms from the owner's supplied research notes. They are design inputs,
not implemented capabilities or independently verified scientific findings.

| Method | Contribution to test in ANIMEDEX | Current boundary |
|---|---|---|
| GS-3 | Alternate broad frame exploration, criticism, and a controller that changes the search direction | Generation and gate exist; adaptive control does not |
| Graph of States | Track which sourced observation and causal explanation led to each frame, so drift can be caught | Scan-to-frame provenance exists; a causal state graph does not |
| Theorem-of-Thought | Let abductive, deductive, and inductive readings challenge a candidate frame | One generation pass and one gate exist; parallel reasoning graphs do not |
| Quantum abduction | Hold conflicting frames open long enough to compare or synthesize them | Multiple candidates are saved; there is no quantum computation or synthesis operator |
| MCMC premise retrieval | Explore a large evidence store for relevant premises without relying on one nearest neighbor | The current small notes index is read directly; no MCMC retrieval exists |

Each method needs an owner-approved behavior contract and a verifier before being wired into a
production command. The method names alone must never make a run appear more creative or proven.
