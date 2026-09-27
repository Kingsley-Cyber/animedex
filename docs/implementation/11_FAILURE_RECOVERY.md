# 11 — Failure Recovery

**Rollback principle:** canonical data lives in git; every milestone ends with a tagged commit (`m<n>-complete`). Derived data is always rebuildable.

| Failure | Detection | Immediate response | Prevention |
|---|---|---|---|
| Malformed JSON from model | Parse error | One repair call with the error; then quarantine | Native JSON-schema mode; length caps |
| Schema violation | Validation | Same as above | Schema in prompt |
| Off-vocab value | Enum check | Store `other`; write proposal | Enum lists in prompt |
| Provider 429 / 5xx (API adapters) | HTTP status | Exponential backoff (max 5); resume from cache | Rate-limit config |
| Subscription usage or rate limit (CLI) | CLI error text: usage limit, 429, overloaded | Stop the run cleanly, no retries; finished calls stay cached; resume later from cache | Call caps per run and per title; pacing; keep headroom for Kingsley's coding sessions |
| CLI not logged in or session expired | CLI auth error; `animedex smoke --providers` preflight | Stop; Kingsley runs `claude auth login` or `codex login` (subscription, not API key) | Preflight before every live run |
| CLI loads user-level config | Init metadata / `codex debug prompt-input` | Report it; strip it if a flag exists | Isolation flags; allowlisted env |
| Timeout | Client timeout | Retry once; split P3 batch | Smaller batches |
| Budget cap hit | Cost ledger | Stop after current title/episode; report | Cheap models for P1/P4/EP |
| Native search runs long or over cap | Turn limit hit (CLI error) / counted searches | Skip the title (`unresolved`), log; over-cap is flagged | Limits in the prompt; hard `--max-turns` |
| Web verification inconclusive | No credible source | Mark `unresolved`; block P2 only if a gold title's outcome is unresolved | Better query templates |
| Recall–web conflict | Verify diff | Web wins if credible; log | Track per-field correction rate |
| Scope leak (other adaptation or unadapted source) | CHECK `scope_leak` / EP scope check | Reject or revise; tighten the title's scope `exclude` list | Scope in every prompt |
| Hallucinated moment or episode | Verify can't confirm | Drop moment; remove from `evidence_refs`; re-run P2 for atoms that depended only on it | Always verify locators |
| No engine atom produced | P2 control | Re-run P2 once with the engine template emphasized; then flag | Worked example in prompt |
| Critic reject spike (>30%) | CHECK stats | Stop title; inspect P2 prompt; bump version | Tune against gold |
| Too many load-bearing atoms (>8) | P3 stats | Re-run P3 with strict prompt | Add worked examples |
| Contested atoms pile up | CHECK stats | Leave excluded; list in report; M6 episodes may settle them | Better contrast partners |
| Episode summary unavailable | Fetch fails | Skip; count `unsourced`; take next candidate by the selection rule | Multiple search backends |
| Episode numbering mismatch (broadcast vs. streaming order, recaps, split cours) | Identity check fails | Mark `unresolved`; skip | `scope.numbering`; match by episode name |
| Contradiction storm (>30% of a title's atoms contradicted) | ROLLUP alarm | Stop; likely scope contamination or a weak P2. Re-run VERIFY/P2 for that title with scope tightened | Scope discipline |
| Promotion flood | ROLLUP stats | Raise `match_similarity` or `promote_threshold`; review matcher prompt | Calibrate in M7 |
| Highlight bias (engine absent from control episode) | Compounding eval | Flag the engine atom; consider a second control episode | Control episode in selection |
| Supporting episode triggered a re-run | Cost log | Treat as caching bug; fix `upstream_hash` | AC-06, AC-33 |
| Low agreement | Eval | Tighten definitions; add examples | — |
| Nondeterministic build or ROLLUP | Hash mismatch | Fail; find the unsorted query or unseeded step | Sorted outputs, fixed seeds |
| Regression diff after prompt/vocab change | Snapshot diff | Revert, or accept with Kingsley's approval and a new snapshot | Versioning |
| Corrupted canonical file | Validation / git diff | Restore from git; rebuild | Atomic writes |
| Partial run crash | Missing records | Re-run; cache skips completed calls | Idempotent stages |
| Vocab migration (rename/merge) | Version bump | Migration script in `ontology/migrations/`; re-canonicalize, no re-extraction | Alternate labels |
| Generator keeps producing surface changes | H1 failure rate | Inspect operator stats; strengthen the operator prompt with a failing and a passing example | H1 test in judge |
| Ideation mode collapse | Diversity alarm | Target empty cells; rotate operators | Cell-targeted generation |
| Clone-gate false positive | Kingsley flags | Log; recalibrate in M7 | Calibration |
| Catalog unavailable or rate-limited (v1.6) | HTTP error / 429 | Wait for Retry-After; list unresolved lines; never guess titles from recall | Paced calls |
| Prior art finds a counterexample (v1.6) | Prior-art record | Drop the claim (T1 may stand as T2 with its own evidence) | Census before M5 |
| A backfill pick is the wrong version | Backfill report | Kingsley corrects the line or `corpus/titles.yaml`; rerun | Versions in parentheses |
| Name leak in P4 | Name-leak test | Re-run P4 for that atom | Name list check |
| Thinking model rejects multi-turn call | Provider 400 | Keep pass calls single-turn; preserve reasoning content in the adapter for any multi-turn step | Adapter tests |
| ANIMEDEX loses blind review | M5/M6/M7 eval | Diagnose in order: (1) load-bearing atoms weak? check AC-17; (2) engines weak? check engine match vs. gold; (3) H1 or gates too loose/tight? inspect gate stats; (4) grid dims wrong? try cluster dims; (5) judge rewarding the wrong thing? compare judge tags to Kingsley's | Do not scale until resolved |
| M6 shows no lift over M5 | Blind review #2 | Check whether episodes changed any load-bearing atoms; if not, episodes are confirming, not extending. Report it; don't add episodes just to add them | Compounding report |
