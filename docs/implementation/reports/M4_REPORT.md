# Completion Report — M4: ANALYZE with the statistics gates

- **Date:** 2026-09-27
- **Agent / model:** Claude Opus 5.5 (lead). ANALYZE makes no model calls.
- **Commit tag:** `m4-complete` (code and data repo)

## Summary
ANALYZE answered all 68 competency questions from the M3 index, ranked every empty cell by its expected count, attached failure levels to the graveyard, and scored every enum field's health. All four M4 ACs pass, and a clean rebuild gives identical answers. With 14 titles, no zero is trustworthy yet (the rule of three needs 151 rows), so the census is next.

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-21 | pass | 68 of 68 CQs have a query and a saved answer in `build/cq_answers/`; `test_analyze` checks that no question lacks a query and no query lacks a question. |
| AC-22 | pass | Every gap table carries its coverage flag. All four read "insufficient coverage": 14 titles give a rule-of-three bound of 0.214, and a zero is open only below 0.02. |
| AC-23 | pass | Graveyard: 4 titles (1 flop, 3 mixed), each with `failure_reason` and a sourced `failure_level`. All four are execution-level, so none warns. They become "retold better" (T5) lane evidence instead. |
| AC-24 | pass | `make clean-build`: identical hashes and CQ answers. |

## What the statistics say (14 titles)
- **Reliability.** Four fields are unreliable (kappa < 0.6) and are left out of the gap reports and novelty pairs: core.story_engine_secondary (0.42), core.threat_structure (0.58), power_combat.mc_edge (0.55) and power_combat.set_scaffold (0.38). The grid fields pass: gate 1.0, set_structure 0.89, progression 1.0.
- **Gaps.** Empty cells: gate × cost 77, progression × fight medium 16, gate × cost in the census 90 (no census rows yet), set structure × subset mechanic 19. None is a real gap: the highest expected count is 1.1, and a real gap needs 3. That is the right answer at n = 14.
- **Field health.** Five fields have low entropy (normalized < 0.5): escalation_model, member_depth, power_is, source_medium and demographic. The corpus is mostly individual powers and manga or light-novel sources, so these fields barely vary here. Mutual information with outcome is reported, but at 14 titles almost every value is unique to one title, so the MI values mostly measure sample size. They mean nothing until the backfill.
- **Lanes.** None yet. An imported lane needs 2 or more non-anime titles sharing a concept that no anime has, and there are 3 Western titles.
- **Coverage.** Field completion is 0.93–0.99 per title. Four titles show "P3" as not done because CHECK rejected 7 of their proofs; those atoms stay unproven and never feed ideation. All 14 are through P4.

## Tests
- `make test`: 546 passed; `test_analyze`: 12 passed (AC-21 to AC-24 and gold masking).
- `make clean-build`: identical.

## Next
The census: the top 500 anime and donghua roots from AniList (already fetched and cached), 10 titles per call, over two runs under the 40-call cap. Ideation needs 200 or more rows with a power system before census zeros count.
