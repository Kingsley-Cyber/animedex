# v1.7 comparison: recall-first vs gather-first

**Date:** 2026-09-27. **Baseline:** M2's recall-first run (P1 on Sonnet 5 at effort high, then VERIFY), data tag `m2-complete`. **New:** the combined v1.7 + v1.8 run: GATHER (Haiku 4.5 with web), INTERPRET (Opus 5.5 at effort medium, no web, plus the cast call), then VERIFY on unsourced documented fields only. Same 14 titles. Six titles were widened to their full run in v1.7 (Avatar, Jujutsu Kaisen, Demon Slayer, Mob Psycho 100, Invincible, The Boys), so their rows are marked scope-changed.

## Result

| Measure | Recall-first (M2) | Gather-first (v1.7) |
|---|---|---|
| Time per title, mean | 6m 32s | **4m 54s** (−25%) |
| Time per title, same-scope titles (8) | 6m 53s | **5m 08s** (−25%) |
| Time per title, widened titles (6) | 6m 03s (season 1) | **4m 35s** (full run) |
| Retried calls | 39 of 85 | **3 of 64** |
| Enum agreement, 5 gold titles, the M2 fields (45 comparisons) | 0.73 | **0.96** |
| Enum agreement, 14 titles, every enum field (425 comparisons) | not measured | **0.87** |
| AC-12 grid gate (raw / kappa) | failed | **pass**: gate 1.0/1.0, set_structure 0.93/0.89, progression 1.0/1.0 (D-028) |
| Values with a web source | 64 of 613 (10%) | **394 of 1,101 (36%)** |
| Values left unresolved by VERIFY | 161 (26%) | **75 (7%)** |
| Web correction rate among checked values | 0.16 (10 of 64) | 0.26 (10 of 39) |

Times are the median run per stage per title, summed; they include each run's own retries. Enum agreement compares two independent runs of the same title (M2: the canonical profile vs the P1 second run; v1.7: the INTERPRET first run vs its agreement rerun).

- **Faster, even with more to read.** VERIFY fell from 4m 00s to 1m 40s a title, because GATHER already sources the documented facts and VERIFY checks only what is still unsourced. GATHER (1m 38s) plus INTERPRET (1m 36s, including the cast call) takes 43 seconds more than P1 did (2m 31s), so the whole saving is in VERIFY.
- **Agreement is fixed where it failed.** M2's misses were cost_of_power 0.2, progression 0.4 and visible_counter 0.4. On the same titles, gather-first gives 0.8, 1.0 and 1.0. Only cost_of_power stayed under the grid bar across all 14 titles (0.79 raw, kappa 0.74), so set_structure replaced it as a grid axis (D-028).
- **The correction rate rose because the checked set changed.** VERIFY now sees only the values GATHER couldn't source, which are the hard ones. The count of web corrections is the same (10), and 36% of values now carry a source, up from 10%.

## Where the time went (gather-first, per call)

| Stage | Calls | Model | Web | Other | Startup | Input tokens per call |
|---|---|---|---|---|---|---|
| GATHER | 15 | 34% | 30% | 36% | 1% | 48.7k |
| INTERPRET | 50 | 78% | 0% | 21% | 1% | 22.2k |
| VERIFY | 14 | 20% | 18% | 61% | 1% | 49.1k |

"Other" is wall time the CLI doesn't attribute to model or web time. It is largest in the stages that use web tools. Input tokens include cache reads and writes. Recall-first had per-part timing on only 18 of its 85 calls: 92% model, 7% web.

## Per title

| Title | Scope | P1 | VERIFY | Recall-first | GATHER | INTERPRET | VERIFY | Gather-first |
|---|---|---|---|---|---|---|---|---|
| avatar_the_last_airbender_2005 | widened | 3m 05s | 3m 11s | 6m 16s | 1m 44s | 1m 38s | 53s | 4m 15s |
| big_order_2016 | same | 2m 35s | 5m 14s | 7m 48s | 1m 14s | 1m 18s | 3m 15s | 5m 47s |
| btooom_2012 | same | 3m 10s | 7m 56s | 11m 06s | 1m 37s | 1m 31s | 2m 02s | 5m 10s |
| demon_slayer_kimetsu_no_yaiba_2019 | widened | 2m 55s | 2m 54s | 5m 49s | 1m 14s | 1m 31s | 1m 00s | 3m 44s |
| fullmetal_alchemist_brotherhood_2009 | same | 2m 02s | 3m 48s | 5m 50s | 1m 05s | 1m 33s | 1m 22s | 4m 00s |
| future_diary_2011 | same | 2m 05s | 2m 39s | 4m 44s | 1m 04s | 1m 21s | 2m 15s | 4m 40s |
| hunter_x_hunter_2011 | same | 2m 02s | 3m 32s | 5m 34s | 1m 22s | 1m 35s | 2m 50s | 5m 47s |
| invincible_2021 | widened | 2m 12s | 2m 15s | 4m 27s | 1m 16s | 1m 24s | 32s | 3m 12s |
| jujutsu_kaisen_2020 | widened | 2m 17s | 2m 50s | 5m 07s | 4m 11s | 1m 42s | 2m 18s | 8m 11s |
| mob_psycho_100_2016 | widened | 3m 15s | 3m 42s | 6m 57s | 1m 28s | 1m 48s | 1m 10s | 4m 25s |
| platinum_end_2021 | same | 3m 02s | 5m 44s | 8m 45s | 1m 20s | 1m 12s | 1m 59s | 4m 30s |
| solo_leveling_2024 | same | 2m 31s | 3m 16s | 5m 47s | 1m 48s | 1m 40s | 1m 38s | 5m 05s |
| sword_art_online_2012 | same | 2m 30s | 2m 56s | 5m 26s | 2m 11s | 2m 33s | 1m 23s | 6m 08s |
| the_boys_2019 | widened | 1m 37s | 6m 06s | 7m 44s | 1m 18s | 1m 40s | 46s | 3m 45s |

Jujutsu Kaisen's GATHER (4m 11s) is the one slow run: three seasons of wiki pages within the fetch limit.

## Effort A/B (INTERPRET, medium vs high, 3 titles)

Hunter x Hunter, Future Diary and Mob Psycho 100 were interpreted a third time at effort high.

| Measure | Medium | High |
|---|---|---|
| Profile call time, mean | 1m 10s | 1m 38s (+40%) |
| Enum agreement with the medium first run (93 comparisons) | 0.85 (the medium rerun) | 0.89 |
| Grid values (gate, set_structure, progression) and cost_of_power | — | identical on all 3 titles |

High moves the answers no more than a second medium run does, and the grid values don't change at all. **Decision: INTERPRET stays at effort medium** (D-029).
