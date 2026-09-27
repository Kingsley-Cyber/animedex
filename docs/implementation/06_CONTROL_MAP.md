# 06 — Control Map

## Controls by stage
| Stage | Control | Type | Threshold (config) | On failure |
|---|---|---|---|---|
| P1 | JSON schema validation | Preventive | — | 1 repair attempt → quarantine |
| P1 | Enum check | Preventive | `vocab.json` | Store `other`, write proposal |
| P1 | Scope declared | Preventive | Every title has scope | Stage blocked |
| P1 | Confidence floor | Detective | `conf < 0.7` | Added to verify list; `uncertainty_reason` required |
| VERIFY | Mandatory verify set | Preventive | Outcome, sensory, moment locators | Mark `unresolved` if not settled |
| VERIFY | Search cap | Budget | 3/title (+2 for outcome). Native: also a hard turn limit; searches counted | Stop; mark `unresolved`. Native: flag a cap overrun in the verify notes |
| VERIFY | Retrieved-source citation | Preventive | A confirm/correct must cite a URL this call retrieved (native: from its own tool traffic) | One repair, then `unresolved` |
| VERIFY | Recall–web conflict | Detective | — | Web wins if credible, else `unresolved`; logged |
| P2 | Evidence required | Preventive | ≥1 `evidence_ref` | Atom rejected |
| P2 | Engine present | Preventive | ≥1 engine atom per title | Re-run P2 once, then flag |
| P2 | Rival explanation present | Preventive | Every effect atom | Atom rejected |
| P2 | Soft atom limits | Detective | ≤15 total; <5 flagged | Truncate by conf; flag low counts |
| P2 | Circularity | Detective | `because` restates element | CHECK rejects |
| P3 | Partner availability | Preventive | Partners have P1 | Stage blocked |
| P3 | Cross-medium partner | Preventive | Anime titles need ≥1 | Stage blocked |
| P3 | Explanation test present | Preventive | Every effect atom | Re-run P3 for title |
| P3 | Leniency alarm | Detective | >8 load-bearing per title | Flag; re-run with strict prompt |
| CHECK | Independent critic | Detective | Different model family when available | — |
| CHECK | Scope leak | Detective | Events outside scope | REJECT or REVISE |
| CHECK | Contested explanations | Detective | Because and rival equally supported | `explanation: contested`; excluded from load-bearing |
| CHECK | Reject-rate alarm | Detective | >30% rejected for a title | Stop title; inspect P2 prompt |
| P4 | Name-leak test | Preventive | No title/character names | Reject; re-run atom |
| P4 | Conditions present | Preventive | Essential, variable, failure non-empty | Re-run atom |
| CANON | Atomic write | Preventive | Temp file + rename | Abort; no partial write |
| CANON | Referential integrity | Preventive | All refs resolve | Abort |
| EP | Fetched source required | Preventive | `episodes.require_fetched_source` | Skip; count `unsourced` |
| EP | In-scope episode | Preventive | Season/episode inside scope | Reject |
| EP | Episode identity | Detective | Title + number (+ name) match | `unresolved`; skip |
| EP | Selection cap | Budget | 6 per title | Stop selection |
| ROLLUP | Promotion threshold | Preventive | ≥2 distinct episodes | Proposal stays pending |
| ROLLUP | Re-run only on status change | Budget | Support increments excluded from cache hash | — |
| ROLLUP | Contradiction storm | Detective | >30% of a title's atoms contradicted | Stop; suspect scope or P2 contamination (see 11) |
| ROLLUP | Derived-field conflict | Detective | Episode-derived ≠ P1 value | Derived wins; conflict logged |
| ROLLUP | Causal link evidence | Preventive | `enables`/`prevents` need more than order | Link dropped |
| BUILD | Determinism | Detective | Hash of tables + CQ answers | Fail build |
| ANALYZE | Coverage gate on gaps | Preventive | ≥5 titles with module, completion ≥0.8 | Label "insufficient coverage" |
| ANALYZE | Graveyard lookup | Detective | Combination matches a flop | Attach `failure_reason` + `failure_level`; only premise-level failures warn (v1.3) |
| PATTERNS | Counterexample search | Preventive | Search run and recorded | Card invalid |
| IDEATE | Eligible atoms only | Preventive | Load-bearing, settled, not mixed/contradicted | Atom excluded |
| IDEATE | Engine complete | Preventive | All engine parts + dramatic question | Rework once → reject |
| IDEATE | Clone gate | Preventive | Structural J ≥ .70, procedural J ≥ .75, or (cosine ≥ .90 and structural J ≥ .55) | Rework once → reject |
| IDEATE | Novelty gate | Preventive | No novel pair/triple/inversion | Reject |
| IDEATE | Graveyard gate | Detective | Premise-level flop combination match (v1.3) | Require "why this time is different," else reject |
| IDEATE | H1 consequence test | Preventive | <2 of choices/relationships/outcomes differ from closest title | Reject (surface change) |
| IDEATE | Failure-condition check | Preventive | Idea triggers an atom's failure condition | Rework once → reject |
| IDEATE | Coherence gate | Preventive | Theme ↔ mechanic; dilemma follows from cost | Reject |
| IDEATE | Diversity alarm | Detective | >40% of champions in 10% of cells | Target empty cells; vary operators |
| ALL | Budget cap | Budget | Subscription CLIs: calls per run and per title. API-billed: per-run, per-title, per-episode dollar caps | Stop cleanly after current unit; report |
| ALL (live) | Plan usage limit | Budget | CLI reports a usage/rate limit | Stop the run cleanly, no retries; finished calls stay cached; resume later |
| ALL (live) | CLI isolation | Preventive | Allowlisted env (no `ANTHROPIC_*`/`OPENAI_*`/`CLAUDE*`/`CODEX_*`), empty scratch dir, tools off, no user settings/skills/MCP/memory | Refuse an API-key login; log each call's init metadata; report user-level leaks |
| ALL (live) | Gold blind guard | Preventive | Live run on a gold title needs filled, committed `eval/gold/<title_id>/` annotations | Refuse to start |
| ALL | Raw-log redaction | Preventive | Fetched web text never written to logs | Replace with URL + sha256 + length |

## Decision rights
| Decision | Agent | Kingsley |
|---|---|---|
| Run pipeline, fix bugs, add tests | Yes | — |
| Choose key episodes by the selection rule | Yes | — |
| Override episode selection or raise the per-title cap | Propose | Approves |
| Accept/reject ontology proposals | Propose | Approves |
| Change taste criteria or the H1 test | No | Yes |
| Change gate or episode thresholds | Propose with calibration data | Approves |
| Add a field, module, operator, or pass | Propose with idea-card failure evidence | Approves |
| Hand-edit canonical data | Never | Never (use the pipeline) |
| Select gold-set mixed/flop titles | Propose with verified reception data | Approves |
| Set title scope | Propose | Approves for gold titles |
| Raise budget caps | No | Yes |
| Mark an idea final "elite" | No | Yes |
| Scope changes (02) | No | Yes |

## Human review points
1. Title scope and gold-set annotation, done blind before seeing model output (M2, M3).
2. Ontology proposal queue (every milestone).
3. `NEEDS_ADJUDICATION` atoms, and `CONTESTED` atoms that episodes haven't settled.
4. Blind idea review (M5, M6, M7).
