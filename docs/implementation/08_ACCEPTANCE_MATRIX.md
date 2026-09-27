# 08 — Acceptance Matrix

| AC | Requirement | Verification | Milestone |
|---|---|---|---|
| AC-01 | Pydantic models implement every contract in 04; JSON Schemas generate cleanly | Unit test + `make schemas` | M1 |
| AC-02 | An invalid record cannot enter canonical data | Contract test | M1 |
| AC-03 | Off-vocab enum is stored as `other` and writes a proposal file | Contract test | M1 |
| AC-04 | Every field, module, vocab field, and bridge concept has ≥1 `cq_refs`; coverage table has no orphans | `make validate` | M1 |
| AC-05 | Interrupted write leaves canonical files intact | Test simulating crash mid-write | M1 |
| AC-06 | Cache keys are stable; changing the P3 prompt does not invalidate P1/P2; support-count changes do not invalidate anything; status changes do | Unit test | M1 |
| AC-07 | `rm -rf build && make build` produces identical DuckDB table hashes | Determinism test | M1 |
| AC-08 | Every implemented stage runs offline on the mock provider (re-verified each milestone) | Pipeline test | M1 |
| AC-09 | Gold titles + partners have valid P1 profiles with scope; modules follow activation rules | `make validate` + rule test | M2 |
| AC-10 | Verify list always contains outcome, sensory fields, and moment locators; low-confidence fields carry `uncertainty_reason` | Unit test | M2 |
| AC-11 | No stored quotes, dialogue, or transcripts; text within length caps; no framing/blocking/editing claims in sensory fields | Test (length, quote, and keyword heuristics) | M2 |
| AC-12 | P1 enum agreement across two runs ≥ 0.80 on gold | `make eval` | M2 |
| AC-13 | Web correction rate reported per field | Report | M2 |
| AC-14 | Each title has ≥1 engine atom; total atoms ≤15 (fewer than 5 flagged, not failed); every atom has `evidence_refs`; every effect atom has `rival_because` | Contract test | M3 |
| AC-15 | Every anime gold title has ≥1 cross-medium partner; every effect-atom proof has an explanation test | Contract test | M3 |
| AC-16 | Load-bearing count per title is 3–8, or flagged; contested atoms are excluded from load-bearing | Report + contract test | M3 |
| AC-17 | Model load-bearing set recalls ≥ 0.60 of Kingsley's blind annotation | `make eval` | M3 |
| AC-18 | P4 patterns contain no names; every transfer atom has essential, variable, and failure conditions | Contract test | M3 |
| AC-19 | CHECK uses a different model family when configured; a scope-leak fixture is rejected | Config test + pipeline test | M3 |
| AC-20 | REJECTs quarantined with reasons; REVISEs re-checked once; CONTESTED sets `explanation: contested` | Pipeline test | M3 |
| AC-21 | Every CQ in scope for the milestone has a query and a saved answer | Test | M4 |
| AC-22 | Gap cells carry a coverage flag; thin-coverage zeros are labeled insufficient | Test | M4 |
| AC-23 | Graveyard index attaches `failure_reason` and `failure_level` to flop combinations; only premise-level failures warn (v1.3) | Test | M4 |
| AC-24 | CQ answers are identical after a clean rebuild | Determinism test | M4 |
| AC-25 | Every idea card has `closest_existing`, `why_not_a_clone`, and a complete engine | Contract test | M5 |
| AC-26 | Ideas use only load-bearing-eligible transfer atoms | Contract test | M5 |
| AC-27 | Every card records its operator and consequences; a surface-change fixture card fails the H1 test | Pipeline test | M5 |
| AC-28 | Clone, novelty, graveyard, failure-condition, and coherence gates are enforced; rejections logged with the gate | Pipeline test | M5 |
| AC-29 | Archive holds ≤1 idea per cell; per-cell fitness never decreases | Unit test | M5 |
| AC-30 | Blind review #1 completed and recorded | `eval/blind/` record | M5 |
| AC-31 | Episode records exist only for in-scope episodes with a fetched source; a recall-only fixture is refused | Contract + pipeline test | M6 |
| AC-32 | Key-episode selection follows the rule (pilot, moments, finale, control) within the cap | Unit test | M6 |
| AC-33 | ROLLUP is deterministic; status transitions follow the rules; supporting episodes trigger no re-runs; status changes trigger re-runs for affected atoms only | Pipeline test | M6 |
| AC-34 | Proposed atoms are promoted only when ≥2 distinct episodes support them, and then pass P3/CHECK/P4 | Pipeline test | M6 |
| AC-35 | Series-engine fields re-derived when ≥3 episodes (incl. control) are indexed; conflicts logged | Test | M6 |
| AC-36 | Links resolve to existing records; causal links carry evidence beyond order | Contract test | M6 |
| AC-37 | Blind review #2 recorded; lift vs. #1 and a compounding report included | `eval/blind/` record + report | M6 |
| AC-38 | Corpus ~40 with the target media mix; key episodes indexed per rule for series titles | Report | M7 |
| AC-39 | Gate and episode thresholds recalibrated; distributions documented | Report | M7 |
| AC-40 | Every pattern card records supporting titles, a counterexample search, boundary conditions, and scope | Contract test | M7 |
| AC-41 | ANIMEDEX beats the baseline on greenlights in blind review #3 | `eval/blind/` record | M7 |
| AC-42 | Cost per title (show passes + episodes) reported and within budget caps | Report | M7 |
| AC-43 | Every mixed/flop outcome carries a `failure_level`. A level other than `unknown` is web-sourced (evidence + URL) or Kingsley's override (v1.3) | Contract test | M3 |
