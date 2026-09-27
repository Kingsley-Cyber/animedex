# Change plan v1.10: speed pass for non-gold titles

**Owner instruction (2026-09-27):** "Speed pass for non-gold titles (gold keeps full rigor): 1. Merge gather and interpret into one call. 2. Medium effort on every non-gold call. 3. VERIFY only the outcome and moment locators; everything else keeps its gathered source. 4. Run the critic on 3 titles per call instead of 1. 5. 4 titles in parallel. Target: under 6 minutes per show. Report time per stage before and after, and any drop in agreement on the grid fields."

**Status:** in progress on branch `speed/v1.10` (D-048). Gold titles (`role_tags: [gold]`) keep the full path unchanged.

## Before (14 titles, gather-first, sequential; `make timing`)
| Stage | Per title | Calls per title |
|---|---|---|
| GATHER (Haiku, web) | 1.7 min | 1 |
| INTERPRET (Opus, medium; profile + cast) | 2.4 min | 2 |
| VERIFY (Sonnet, web; documented fields + outcome) | 1.7 min | 1 |
| P2 (Opus, high) | 0.7 min | 1 |
| P3 (Opus, high) | 2.2 min | 1 |
| CHECK 1.3.0 (codex; check + re-check) | 2.8 min | 2 |
| P4 (Haiku) | 1.3 min | 1 |
| **Total** | **12.8 min** | **9** |

## What changes (non-gold only)
| Item | Change |
|---|---|
| 1. One call for gather + interpret | New `PROFILE` pass (`pipeline/profile.py`, prompt `profile.md` = the gather rules + the interpret rules): one Opus call with web tools returns the cited facts (with the model's own ids), the reception verdicts, the profile with evidence, the outcome, and the cast. The API reception numbers and the adaptation signal are fetched before the call and shown to it, so the outcome can cite them. Facts are admitted by the same rules as GATHER (only pages the call retrieved; MAL never); the profile is assembled by the same code as INTERPRET. Model slot `profile` (Opus 5.5, effort medium). |
| 2. Medium effort | Every non-gold call to P2, P3, CHECK, P4 and PROFILE carries `effort: medium` (`speed.effort`); gold calls keep their slot's effort. |
| 3. VERIFY outcome + moments | A non-gold title's verify list is the outcome (when reception didn't settle it) and the moment locators; every other field keeps its gathered source or is `not_required`. VERIFY asks non-gold titles about moments now (sensory stays gold-only). |
| 4. Critic on 3 titles per call | `run_check(batch_titles=3)`: one call carries three titles' profiles, moments, atoms, proofs and partner profiles; verdicts are split back per title; the re-check round runs per batch. Gold titles stay one per call. |
| 5. Four titles in parallel | The orchestrator's fast path runs each stage over up to `speed.parallel_titles` (4) titles at once (threads; one client and run log per worker; one thread-safe budget per run, so the 40-call cap still holds), then canonicalizes once. |

## Expected after
PROFILE ≈ 2.5 min, VERIFY ≈ 1.0, P2 ≈ 0.5, P3 ≈ 1.5, CHECK ≈ 1.0 (a third of a 3-title call, plus re-checks), P4 ≈ 1.0: about 7.5 min of machine time per title, and with 4 in parallel about 2 min of wall clock per title. Measured after the first fast batch.

## Acceptance
- AC-62: a non-gold title goes through PROFILE → VERIFY → P2 → P3 → CHECK → P4 with 5 calls (6 with a re-check) and every call carries `effort: medium`; a gold title still takes the full path (test with mocks).
- AC-63: CHECK with `batch_titles: 3` sends three titles in one call and writes each title's checks separately; a rejected atom of one title never touches another's (test).
- AC-64: the fast path runs 4 titles at once under one budget and stops at the cap (test with a slow mock).
- AC-65: the report (`reports/SPEED_PASS.md`) shows time per stage before and after on the first fast batch, and the grid-field agreement (raw and kappa) of a PROFILE rerun on those titles against the 14-title INTERPRET numbers.

## Order
1. Config, thread-safe budget, `params` on the analysis stages, VERIFY's non-gold rule (offline, tests).
2. PROFILE pass (INTERPRET's tail refactored into a shared function; `admit(keep_ids=True)`).
3. CHECK batching.
4. Orchestrator fast path with parallel stages.
5. `animedex profile` (with `--agreement`), docs (05, 08, 09, CHANGELOG, DECISIONS), USAGE.
6. Live: the next priority-1 batch on the fast path; agreement rerun on it; the report.
