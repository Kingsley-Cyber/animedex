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
| AC-12 | Enum agreement across two INTERPRET runs (gather-first, v1.7): every grid field raw ≥ 0.80 and Cohen's kappa ≥ 0.80; a field under kappa 0.60 is flagged unreliable. Recall-first P1 (M2) measured 0.73 on gold. | `make eval` → `eval/agreement/reliability.json` | M2 (passed after v1.7, D-028) |
| AC-13 | Web correction rate reported per field | Report | M2 |
| AC-14 | Each title has ≥1 engine atom; total atoms ≤15 (fewer than 5 flagged, not failed); every atom has `evidence_refs`; every effect atom has `rival_because` | Contract test | M3 |
| AC-15 | Every anime gold title has ≥1 cross-medium partner; every effect-atom proof has an explanation test | Contract test | M3 |
| AC-16 | Load-bearing count per title is 3–8, or flagged; contested atoms are excluded from load-bearing | Report + contract test | M3 |
| AC-17 | Model load-bearing set recalls ≥ 0.60 of Kingsley's blind annotation | `make eval` | M3 — **deferred (owner: Kingsley)**: gold annotations waived 2026-09-27 |
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
| AC-44 | Census titles come from a catalog and are counted in batches of ≤10; no atom, transfer, idea, or ideation prompt references a census entry (v1.6) | Contract test | M5 |
| AC-45 | Every T1/T4 claim on a champion carries a prior-art record; counterexample or inconclusive removes the claim (v1.6) | Pipeline test | M5 |
| AC-46 | Every judged card records the runway answer; revival cards name an execution-level flop with evidence; champions carry a pre-mortem (v1.6) | Pipeline test | M5 |
| AC-47 | The blind packet has three equal arms, shows logline + premise only, and keeps the answer key out of the repo (v1.6) | Pipeline test | M5 |
| AC-50 | Every generate call gets a capped `key: value` brief (`ideate.brief_max_words`, 600): atoms under opaque aliases (no transfer id, no source title), the nearest 10 titles, only the flops in the target region, the cell's counts, lanes and prior art, and the steering rules. Its words and estimated tokens are logged per call; an over-cap brief is refused before the call; cards map the aliases back to real transfer ids (M5 ruling, item 4) | Pipeline + unit test | M5 |
| AC-51 | Census-backed enum zero pairs make a card novel only with at least 200 powered census rows (199 do not, 200 do); until then novelty rests on bridge-concept pairs from 2+ titles (item 5) | Unit test | M5 |
| AC-52 | On a premise-level graveyard match the judge sees `why_different` and the matched flop's recorded failure (reason and level) and returns pass or fail with a reason; a fail gets one rework, then rejection; "not blank" is not a pass (item 6) | Pipeline test | M5 |
| AC-53 | Every blind-review arm uses the `ideate_generate` slot, the same taste standard text and the same steering rules; no arm sends web parameters while generating; every packet card gets the same prior-art check; baseline 1 is the same loop with an empty brief, and its cards never enter the canonical ideas, the archive or the champions (item 7; controls A5, decision 1) | Pipeline test | M5 |
| AC-54 | An ideation run stops at `ideate.calls_per_run` (60) calls shared by generate, judge and prior art; other runs keep `budget.calls_per_run` (40) (item 8) | Pipeline test | M5 |
| AC-55 | A card that leans on an atom now CONTESTED or REJECTed by its latest CHECK, with `explanation: contested`, gone from the index, or (M6) contradicted by episodes shows an evidence flag in `ideas.md`; the blind packet never shows it (controls A8) | Pipeline + unit test | M5 |
| AC-56 | `make audit` writes 10 date-seeded eligible atoms with evidence trails and a blank mark each to `eval/audit/`, never samples a gold title while the blind is pending, and never overwrites a sheet; `make audit-report` shows the wrong rate per audit date and the first-verdict disagreement per P2 run (controls A7) | Unit test | M5 |
| AC-57 | `make diagnose` structures a concept in one call, runs the clone, novelty, graveyard and name-leak gates, the judge and an ablation pass (3 calls), prints one line per check with a prescription from the fixed operator/rung table for each failure, and writes only to `data/diagnose/` (owner ruling 2026-09-27) | Pipeline test | M5 |
| AC-58 | A print corpus entry validates only with `numbering` chapters or volumes and `seasons: []`; its profile activates no animation-only module (v1.9) | Unit test | M5+ |
| AC-59 | A print title's moments and turning points carry a chapter or volume inside the scope's range; a screen title's still carry season and episode (v1.9) | Unit + integrity test | M5+ |
| AC-60 | `resolve("Jagaaan")` yields the print original with a chapter/volume scope; `resolve("Berserk (1997)")` still yields the anime; a `(manga)` hint forces the print version (v1.9) | Unit test with a fake catalog | M5+ |
| AC-61 | A print outcome and print census rows carry `adaptation` from the catalog; CQ-P01 answers from the census and survives a clean rebuild (v1.9) | Unit test + determinism | M5+ |
| AC-62 | A non-gold title goes PROFILE → VERIFY → P2 → P3 → CHECK → P4 and every call carries `effort: medium`; a gold title in the same batch still takes GATHER → INTERPRET (v1.10) | Pipeline test | M5+ |
| AC-63 | CHECK with `batch_titles: 3` sends several titles in one call (`=== title <id>` sections) and writes each title's checks separately (v1.10) | Pipeline test | M5+ |
| AC-64 | The fast path runs titles in parallel under one budget whose counters are locked, so the run cap holds across workers (v1.10) | Pipeline test | M5+ |
| AC-65 | `reports/SPEED_PASS.md` shows time per stage before and after on the first fast batch and the grid-field agreement (raw and kappa) of a PROFILE rerun against the INTERPRET numbers (v1.10) | Report | M5+ |
