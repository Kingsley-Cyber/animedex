# Completion Report — M2: P1 profiles + VERIFY (recall-first baseline)

- **Date:** 2026-09-27
- **Agent / model:** Claude Code (Opus 5.5) orchestrating. Pipeline calls ran on the subscription CLIs (G1a): P1 and VERIFY on Sonnet 5 through `claude_cli` 2.1.251, effort high.
- **Commit tag:** `m2-complete`

## Summary
All 14 corpus titles have canonical P1 profiles (14 titles, 65 moments, 14 outcomes), web-checked by VERIFY under the owner's rules. `validate` passes and a clean rebuild is identical. AC-12 (P1 enum agreement on gold) is **0.73, below the 0.80 bar**. The misses are three power-system enums, and v1.7 gather-first must bring it over the bar before M3 uses P1 output. These numbers are the recall-first baseline that v1.7 is measured against.

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-09 | pass | `animedex validate`: OK. 14 titles carry scopes, and module activation rules pass (P1 schema, `normalize_draft`, model validation). |
| AC-10 | pass | `test_p1_writes_candidates_and_mandatory_verify_list`. The verify list still holds outcome, sensory and moment locators. Under the owner rule (2026-09-27), VERIFY checks sensory and moment locators for gold titles only. |
| AC-11 | pass | Quote, dialogue, length and framing guards run at P1, VERIFY and the canonical boundary (tests in `test_p1`, `test_verify`, `test_content_guards`, `test_canonical_store`). The dialogue heuristic was refined after 3 false positives (v1.6.4). |
| AC-12 | **fail (0.7333 < 0.80)** | `animedex eval`: 45 comparisons across 5 of 5 gold titles. Per field: cost_of_power 0.2, progression 0.4, visible_counter 0.4, gate 0.8, demographic 0.8; source_medium, outcome, fight_medium and power_is are all 1.0. Setting the 2 web-corrected fields back to recall gives the same 0.7333, so VERIFY is not the cause. Gate: M3 does not use P1 output until AC-12 ≥ 0.80 (decision 1). |
| AC-13 | pass (reported) | `build/reports/verify_rates.md`. Correction rate among checked fields, top: arc_cour_structure, signature_technique, core_bond and rival are 1/1 each; demographic 2/4; central_mystery 1/4; animation_signature 1/4; outcome 1/12. |

## Tests
- `make test`: 292 passed, 0 failed, 0 skipped.
- `make validate`: pass (90 CQ rows, 0 orphans).
- Clean-rebuild determinism: pass (identical hashes and CQ answers).

## Metrics
| Metric | Value | Bar |
|---|---|---|
| Output tokens per title | P1 about 31.8k, VERIFY about 22.7k, including thinking at effort high | — |
| Input tokens per title | not measurable yet: the run log stores uncached input only (known issue 1) | — |
| Cost per title | plan's own estimate $0.40 P1 + $0.79 VERIFY, billed to the subscriptions, not charged | call caps 40/run, 6/title |
| P1 enum agreement | 0.7333 | ≥ 0.80 |
| Web correction rate (top 5 fields) | see AC-13 | tracked |
| P3/CHECK/M5+ metrics | n/a (M3+) | — |

### Where the time goes (owner request; `make timing`)
| Stage | Calls | Total | Per call | Retries |
|---|---|---|---|---|
| P1 | 62 | 1h 12m | 1m 10s | 34 calls, 27m 35s (38% of P1 time) |
| VERIFY | 23 | 1h 13m | 3m 12s | 5 calls, 16m 00s |

- **Per-stage split** (the 18 calls made since per-stage timing landed): P1 is about 99% model time; VERIFY is about 80% model and 20% web. CLI startup is under 1 second per call; pacing is negligible. Older calls have totals only, estimated from log timestamps.
- **Model time is mostly thinking plus the structured answer.** At effort high, P1 writes about 2.5 times the tokens of its final answer (decision 2).
- **Retries were the biggest avoidable cost.** Owner decisions already remove most of them: per-field word caps, and VERIFY no longer retries for evidence.
- **Speed at the end of M2:** the final batch (9 steps, 3 titles at once) finished in 9 minutes. Non-gold VERIFY took about 2 minutes, down from 3.5, because it skips visual and moment checks.

**Time spent per title across M2** (every attempt, including retries on old code; gold titles include their AC-12 second run):

| Title | P1 | VERIFY | Retries | Total |
|---|---|---|---|---|
| btooom_2012 | 10m 05s | 7m 56s | 6 (7m 27s) | 18m 01s |
| the_boys_2019 | 3m 15s | 12m 13s | 3 (6m 55s) | 15m 27s |
| hunter_x_hunter_2011 | 6m 50s | 7m 05s | 5 (1m 23s) | 13m 55s |
| big_order_2016 | 2m 35s | 10m 27s | 2 (4m 37s) | 13m 02s |
| avatar_the_last_airbender_2005 | 9m 22s | 3m 11s | 3 (3m 50s) | 12m 33s |
| platinum_end_2021 | 6m 03s | 5m 44s | 4 (5m 57s) | 11m 47s |
| solo_leveling_2024 | 7m 30s | 3m 16s | 5 (2m 37s) | 10m 47s |
| future_diary_2011 | 4m 10s | 5m 19s | 2 (1m 54s) | 9m 29s |
| demon_slayer_kimetsu_no_yaiba_2019 | 5m 50s | 2m 54s | 2 (1m 58s) | 8m 44s |
| fullmetal_alchemist_brotherhood_2009 | 4m 04s | 3m 48s | 2 (1m 04s) | 7m 52s |
| mob_psycho_100_2016 | 3m 15s | 3m 42s | 1 (1m 35s) | 6m 57s |
| invincible_2021 | 4m 25s | 2m 15s | 2 (2m 20s) | 6m 39s |
| sword_art_online_2012 | 2m 30s | 2m 56s | 1 (1m 15s) | 5m 26s |
| jujutsu_kaisen_2020 | 2m 17s | 2m 50s | 1 (42s) | 5m 07s |

**Quarantines:** P1 put 8 titles in quarantine at least once, all on older code (word caps and module rules); all 14 passed on fixed code. VERIFY quarantined 1 title (a URL with parentheses; fixed) and passed it on re-run. Canonicalize quarantined 3 titles (dialogue false positives; fixed, then all written).

## Changes to prompts, vocab, or config
| File | Old version → new | Why |
|---|---|---|
| `prompts/p1_what.md` | 1.1.0 → 1.2.0 | per-field word caps (owner-approved) |
| `prompts/verify_native.md` | 1.0.0 → 1.3.0 | no MAL pages; per-field caps; "unresolved is a normal answer"; two reception sources are enough |
| `prompts/verify_web.md` | 1.0.0 → 1.2.0 | same rules for the pages backend |
| `prompts/prior_art.md`, `prompts/baseline_web.md` | 1.0.0 → 1.1.0 | no MAL pages |
| `ontology/vocab.json` | 1.3.0 → 1.4.0 | per-field caps: 15 words, or 20 for the eleven two-part fields (`ontology/proposals/2026-09-27_word_caps.md`) |

## Deviations from spec
1. **Word caps:** changed mid-M2 by owner approval, from 12 words everywhere to 15, or 20 for two-part fields (vocab 1.4.0). Every stored phrase met the cap in force when it was written.
2. **MyAnimeList (owner rule):** before the rule, VERIFY's web tool opened 7 MAL pages across 4 titles. The 3 titles that cited MAL (Big Order, Future Diary, Hunter x Hunter) were reset to their stored P1 drafts with no model call and re-verified without MAL; none cites MAL now. MAL fetches are blocked, and MAL links are never admissible citations.
3. **VERIFY rules (owner, mid-M2):** one call per title with no evidence retries. Visual details and moment locators are checked for gold titles only. Two reception sources settle an outcome. The last 3 VERIFY runs used these rules; the earlier 11 had more checks, which is not a loss.
4. **AC-12 comparison:** the eval compares canonical gold profiles with the second run (09 says two P1 runs). Computing it both ways gives the same 0.7333. The first gold runs used P1 prompt 1.1.0 and the second runs used 1.2.0; the new caps don't touch enums, but the wording changed.
5. **v1.3 code landed early** (`failure_level`, `animedex migrate --to 1.3.0`). The migration updated 3 candidate outcomes.
6. **Tools added for M2** (owner requests): `animedex p1 --replay` (reset to a stored draft, no call), per-stage timing (`make timing`), detached resumable batches (`make batch`, `make status`), and the length-only repair.

## Ontology proposals pending review
7 off-vocab values across 4 fields: demographic 2, cost_of_power 2, gate 1, visible_counter 2. Four come from gold titles, so all 7 stay unshown and untracked until the annotations are done or waived (blind and partner rules). They cluster in the same fields that fail AC-12, which suggests the enum sets are missing values.

## NEEDS_ADJUDICATION and unsettled CONTESTED items
None (M3).

## Decisions needed from Kingsley
1. **AC-12 gate.** Recommended: M3 waits until v1.7 gather-first re-measures AC-12, with the power-system enums gathered from wikis plus one-line definitions for every enum value, and it must reach 0.80 before M3 uses P1 output. Alternative: add the enum definitions now and re-run the 5 gold pairs (10 calls).
2. **Effort level.** Recommended: in the v1.7 run, A/B `effort: medium` against `high` for INTERPRET and VERIFY on 3 titles. It could roughly halve model time; keep high if quality drops.
3. **Proposals.** Review the 7 enum proposals after the annotations. Until then only counts are shown.

## Known issues and risks
1. The run log stores uncached input tokens only (cache reads are dropped), so input size per call is understated. Fix with v1.7's compact-context work.
2. Canonicalize is all-or-nothing per record type: one quarantined title held back every moment and outcome. Consider holding back only the affected title's records.
3. `data/quarantine/` keeps older entries from runs that later passed. Treat it as history, not the current state.
4. Jikan is returning 504 (it can't reach MAL), and MAL's official API needs a client ID. No MAL numbers are needed; outcomes rest on AniList plus critics.
5. The repo is public as of 2026-09-27. After canonicalize, `git add -A` committed model outputs (canonical profiles, the gold second runs, generated proposals) into local commits. The pre-push check caught them. They were removed from the unpushed history with the files kept on disk, and they are now git-ignored. Nothing was ever pushed.

## Next milestone readiness
- [ ] All ACs pass (AC-12 waits on v1.7, per decision 1)
- [x] Report filed
