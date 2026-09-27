# Completion Report — M3: P2 atoms, P3 proofs, CHECK, P4 transfers

- **Date:** 2026-09-27
- **Agent / model:** Claude Opus 5.5 (lead); P2 and P3 on Opus 5.5 at effort high, CHECK on gpt-5.6-terra (codex), P4 on Haiku 4.5
- **Commit tag:** `m3-complete` (code and data repo)

## Summary
All 14 titles went through P2, P3, CHECK and P4. Canonical now holds 159 mechanism atoms (33 engine), 152 proofs, 45 load-bearing-eligible atoms and 45 transfer patterns, and every title contributes at least 2 eligible atoms. Every M3 AC passes except AC-17, which stays deferred because the gold annotations were waived. The live run exposed four defects in CHECK's input. All four were fixed and CHECK was re-run on every title before anything was canonicalized.

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-14 | pass | 14 titles, 159 atoms (9–14 per title, none under 5), 33 engine atoms (every title ≥ 1); every atom cites evidence and every effect atom has `rival_because`. Contract tests plus a live count. |
| AC-15 | pass | Every anime title's proofs include a cross-medium partner; every effect-atom proof has an explanation test. |
| AC-16 | pass (1 flag) | Load-bearing per title: 3–4 for 13 titles; one title has 2 and is flagged for review. No contested atom is load-bearing-eligible (5 contested). |
| AC-17 | deferred | Owner: gold annotations waived 2026-09-27. |
| AC-18 | pass | 45 transfers across 14 titles; no names or medium words (integrity guard); every transfer has essential, variable and failure conditions. |
| AC-19 | pass | CHECK runs on codex_cli/gpt-5.6-terra, P2 on claude_cli/claude-opus-5-5; the scope-leak fixture test passes. |
| AC-20 | pass | Final verdicts: 308 ACCEPT, 98 REVISE, 5 CONTESTED. All 59 revised targets were re-checked once. 9 REJECTs were quarantined with reasons (7 proofs, 6 of them for contradicting a listed profile; 2 mechanisms). CONTESTED sets `explanation: contested`. |
| AC-43 | pass | All 4 mixed/flop outcomes carry a `failure_level` with evidence and a URL. |

## Tests
- `make test`: 546 passed. `make clean-build`: identical hashes and CQ answers. `animedex validate`: OK.
- New regression tests from the live run: length repair (client), CHECK re-check without the atom, CHECK moments/context/off-target verdicts, partner profiles in CHECK, explanation tests that favor both or neither, the resolved-proposal migration.

## What the live run found, and the fixes
| Defect | Effect | Fix |
|---|---|---|
| One text a word over its cap failed a whole P3 answer | 2 titles quarantined | D-030, D-036: shorten just the long texts, first before a full regeneration and again as the last resort |
| CHECK never saw the moments atoms cite | Atoms citing moments rejected as "unsupported" | D-034: CHECK 1.1.0 lists the title's moments |
| CHECK read partner comparisons as scope leaks | All 12 proofs of one title rejected | D-034: partner content is never a scope leak |
| CHECK couldn't see the partners a proof cites | All proofs of two titles rejected as "unsupported" | D-035: CHECK 1.2.0 lists each partner's profile |
| CHECK demanded that every partner detail appear in a profile | 9 of 12 proofs rejected with no stated reason | D-037: CHECK 1.3.0 judges proofs by their reasoning and by contradictions; canary: 1 reject, with a stated contradiction |
| A proof revised in the re-check round crashed CHECK | 1 title failed | Fixed; regression test |
| Off-target verdicts in the re-check round failed the answer | 1 title failed | Ignored instead (they change nothing) |
| "Neither" explanation test with no deciding partner | P3 answer rejected | D-036: `via_partner` may be null for both/neither |

Nothing reached canonical before CHECK 1.3.0. P2 and P3 were replayed from the response cache for each CHECK re-run, so the atoms and proofs are the ones P3 wrote, not new ones.

## Vocab 1.5.1: enum proposals (D-031; no title attribution)
- **7 M2 proposals** were closed. They were applied in 1.5.0 (D-002), and the re-profile chose listed values.
- **19 gather-first proposals** were resolved:
  - **New values (7 proposals):**
    - `power_combat.set_scaffold`: game_system (a game's classes, skills or item types organize the powers), 3 proposals; personal_desire (each power takes the shape of its holder's wish or obsession), 2 proposals.
    - `power_combat.power_up_mode`: absorption (power grows by taking it from others), 2 proposals.
  - **Merged into listed values (5):**
    - core_fantasy → being_chosen
    - mc_archetype → prodigy, and underdog
    - power_up_mode → temporary_boost
    - set_scaffold → none
  - **Kept as `other` (7):**
    - 6 values that only one title needs: a personality-typed scaffold, an emotion-triggered power-up, a self-improvement goal, a present-day remote setting, a sole-wielder edge and a public-rating counter.
    - 1 story engine whose nearest listed value is already that title's secondary engine.
- `animedex migrate --to 1.5.1` moved the resolved values onto 8 titles. 7 `other` values remain, one each in 7 fields: exactly the kept proposals.

## Metrics
| Metric | Value |
|---|---|
| Atoms / load-bearing / eligible / transfers | 159 / 49 / 45 / 45 |
| CHECK verdicts (final) | ACCEPT 308, REVISE 98, CONTESTED 5, REJECT 9 (quarantined) |
| P2 | 17 calls, 10 min (35 s a call, about 6.4k input tokens) |
| P3 | 31 calls, 31 min (1 min a call, about 11.7k input tokens), including 14 repairs and shortenings |
| CHECK | 101 calls over the four CHECK versions, 1h 52m; the final version alone took 36 calls and 39 min (about 15k input tokens per call) |
| P4 | 20 calls, 18 min (53 s a call, about 2.2k input tokens) |
| Cost | billed to the subscriptions; call caps 40 per run, 6 per title |

## Flags for review
- One title has 2 load-bearing atoms (below the 3–8 range). It still contributes 2 eligible atoms.
- 5 atoms are contested (because and rival explanations equally supported). They stay in the index and never feed ideation.

## Next
M4: ANALYZE with the statistics gates (coverage, gap ranking by expected count, graveyard with failure levels, field health), then the census.
