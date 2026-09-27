# Speed pass (v1.10, D-048): time per stage before and after, and the grid-field agreement

**Owner instruction (2026-09-27):** merge gather and interpret into one call; medium effort on every non-gold call; VERIFY only the outcome and the moment locators; the critic on 3 titles per call; 4 titles in parallel; target under 6 minutes per show; report time per stage before and after, and any drop in agreement on the grid fields. Gold titles keep the full path.

## Before (14 titles, gather-first, one title at a time; `make timing` on 2026-09-27 morning)
| Stage | Per title | Calls per title |
|---|---|---|
| GATHER (Haiku, web) | 1.7 min | 1 |
| INTERPRET (Opus, medium; profile + cast) | 2.4 min | 2 |
| VERIFY (Sonnet, web; documented fields + outcome) | 1.7 min | 1 |
| P2 (Opus, high) | 0.7 min | 1 |
| P3 (Opus, high) | 2.2 min | 1 |
| CHECK (codex; check + re-check, one title per call) | 2.8 min | 2 |
| P4 (Haiku) | 1.3 min | 1 |
| **Total machine time** | **12.8 min** | **9** |

Wall clock equalled machine time: one title at a time, so a batch of 4 took about 50 minutes.

## After (first fast batches, 2026-09-27)
AFTER_TABLE

Machine time is the sum of the calls' wall time (`timing.call_s` in the run logs); a CHECK call shared by a group is split evenly across its titles. Retries and `.shorten` repairs are included.

WALL_CLOCK

## Grid-field agreement (AC-12 style: first PROFILE run vs a second PROFILE run of the same titles)
KAPPA_TABLE

## What the first live batch found (fixed the same day, `f16d1fa`)
- A batched CHECK call carried the label `a+b+c` as its title id; the corpus/blind guard refused it ("not in corpus/titles.yaml"). Now every title of the group is guarded and charged; the client sees the label.
- One Budget across all stages made the per-title cap (6, set when every stage built its own client) stop the 7-call fast path at CHECK. Now `Budget.stage_view()`: the run cap (40) is one for the whole run, the per-title cap is per stage as before.

## Observations
OBSERVATIONS
