# IDE agent control plane

Owner request, 2026-10-07: make the ideation workflow usable by LLMs in Claude, Codex, and other
IDEs, and keep GS-3, Graph of States, Theorem-of-Thought, quantum abduction, and MCMC premise
retrieval in the design scope.

## Contract and acceptance

- One repo-owned entrypoint lists its tools and reports local state as JSON, from any working
  directory, without a model call or private write.
- The entrypoint can invoke the existing scan, abduct, and selected-frame quick commands from
  any working directory. Existing CLI validation, plan-limit behavior, and private data paths
  remain the authority.
- Claude and Codex read the same human gate: the owner selects a sourced gap and a passing frame.
- The five research methods have an explicit disposition and are not described as implemented.

## Change boundary

`scripts/animedex_agent.py` is the shared tool entrypoint. `AGENTS.md` routes IDE agents to it;
`CLAUDE.md` already routes Claude to `AGENTS.md`. `.control/policies/ideation-workflow.md` owns
the human gate and method disposition. No provider, model slot, test, or evaluation code changes.

Verification: run the read-only commands from outside the repo; exercise a command dispatch with
the existing CLI's validation; run `make test`, `make lint`, and `harness validate`. Live discourse
quality remains unproven while the subscription plan limit blocks live scan.
