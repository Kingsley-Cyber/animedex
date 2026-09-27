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
Six non-gold titles went through the fast path today: the owner's four (The Bugle Call (manga), Witch Hat Atelier 2026, Dragon Raja 2022, Levius 2019) and the next two of the priority-1 list (Bleach 2004, Bleach TYBW 2022). Minutes of machine time per title and stage, from the run logs.

**As run today** (first attempts, repairs, `.shorten` retries and the failed 3-title CHECK batches included):

| Title | PROFILE | VERIFY | P2 | P3 | CHECK | P4 | Total min | Calls |
|---|---|---|---|---|---|---|---|---|
| the_bugle_call_song_of_war_2022 | 5.4 | 1.0 | 0.3 | 0.5 | 7.4 | 0.8 | 15.4 | 14.7 |
| witch_hat_atelier_2026 | 3.9 | 0.7 | 0.3 | 0.6 | 5.0 | 0.5 | 11.0 | 10.7 |
| dragon_raja_the_blazing_dawn_2022 | 3.5 | 1.2 | 0.3 | 0.4 | 4.3 | 1.7 | 11.3 | 12.7 |
| levius_2019 | 2.2 | 1.3 | 0.6 | 0.6 | 2.2 | 0.5 | 7.3 | 9.0 |
| bleach_2004 | 3.5 | 0.8 | 0.7 | 0.9 | 1.8 | 1.9 | 9.5 | 10.0 |
| bleach_thousand_year_blood_war_2022 | 6.8 | 2.5 | 0.4 | 0.7 | 2.2 | 0.9 | 13.5 | 9.0 |
| **mean of 6** | 4.2 | 1.2 | 0.4 | 0.6 | 3.8 | 1.0 | **11.3** | 11.0 |

**Clean path** (first attempts of the calls that produced a record; no repairs, no quarantined batches):

| Title | PROFILE | VERIFY | P2 | P3 | CHECK | P4 | Total min | Calls |
|---|---|---|---|---|---|---|---|---|
| the_bugle_call_song_of_war_2022 | 3.5 | 1.0 | 0.3 | 0.5 | 2.3 | 0.8 | 8.4 | 9.0 |
| witch_hat_atelier_2026 | 3.9 | 0.7 | 0.3 | 0.6 | 2.1 | 0.5 | 8.1 | 9.0 |
| dragon_raja_the_blazing_dawn_2022 | 3.5 | 1.2 | 0.3 | 0.4 | 1.3 | 1.5 | 8.1 | 9.0 |
| levius_2019 | 2.2 | 1.3 | 0.5 | 0.6 | 2.2 | 0.5 | 7.2 | 8.0 |
| bleach_2004 | 3.5 | 0.8 | 0.6 | 0.8 | 1.0 | 1.3 | 8.1 | 5.7 |
| bleach_thousand_year_blood_war_2022 | 3.9 | 2.5 | 0.4 | 0.6 | 2.2 | 0.9 | 10.5 | 7.0 |
| **mean of 6** | 3.4 | 1.2 | 0.4 | 0.6 | 1.9 | 0.9 | **8.4** | 7.9 |

**Before → after, per stage (machine minutes per title, clean path):** GATHER + INTERPRET 4.1 → PROFILE 3.4; VERIFY 1.7 → 1.2; P2 0.7 → 0.4; P3 2.2 → 0.6; CHECK 2.8 → 1.9; P4 1.3 → 0.9. **Total 12.8 → 8.4 min** (9 → 8 calls). The merged PROFILE call saves little time by itself (one Opus call with the pages in context, ~228K input tokens per call, against a Haiku gather plus two Opus calls); the savings come from medium effort on P3 and P2, the shorter VERIFY, and CHECK without the re-check of untouched verdicts.

Machine time is the sum of the calls' wall time (`timing.call_s` in the run logs); a CHECK call shared by a group is split evenly across its titles. Retries and `.shorten` repairs are included.

**Wall clock** (4 titles in parallel; the owner's four): PROFILE → P3 took 10.5 min for the batch (10:01–10:11, including a minute of catalog resolution), CHECK + P4 took 5 + 14 min over two runs because the 3-title CHECK batch failed twice and fell back to single calls. About 29 min for 4 titles, 7.4 min per show as run. The second batch (Bleach 2004, Bleach TYBW, and two titles already profiled) took 18 min for 4 titles, 4.5 min per show. On the clean path a batch of 4 is about 12–13 min of wall clock, **about 3 min per show**; the machine time per show is 8.4 min. The owner's target of under 6 minutes per show holds for wall clock in batches of 4, not for machine time per title.

## Grid-field agreement: is the fast path less stable?
Two PROFILE runs of the owner's four titles (first run 10:01, rerun 10:46; `agree4.py` = `animedex profile --agreement` for four titles at once), scored like AC-12 (raw agreement and Cohen's kappa per enum field). "Collapsed" counts two `other:<free text>` values as the same value.

| Grid field | Baseline: 14 titles, INTERPRET vs INTERPRET (raw / kappa) | Fast path: PROFILE vs PROFILE, 4 titles, strict | same, `other:*` collapsed | Control: INTERPRET vs INTERPRET on the SAME 4 titles and facts, strict | same, collapsed |
|---|---|---|---|---|---|
| power_combat.gate | 1.0 / 1.0 | 0.50 / 0.43 | 0.75 / 0.67 | 1.0 / 1.0 | 1.0 / 1.0 |
| power_combat.set_structure | 0.93 / 0.89 | 0.75 / 0.56 | 0.75 / 0.56 | 0.50 / 0.20 | 0.75 / 0.56 |
| power_combat.progression | 1.0 / 1.0 | 0.50 / 0.20 | 0.50 / 0.20 | 0.75 / 0.50 | 0.75 / 0.50 |
| all other enum fields, mean raw (28 fields) | 0.86 | 0.78 | 0.81 | 0.85 | 0.89 |

What changed between the two PROFILE runs: Dragon Raja `set_structure` open_variety → closed_set and `progression` lateral → hybrid (both `not_required`, conf 0.40–0.45); Levius `gate` two different `other:` texts and `progression` linear → hybrid (conf 0.45); The Bugle Call `gate` innate → other:spire-linked branch growth (a documented field, conf 0.75 → 0.70); Witch Hat Atelier agreed on all three. The control (two classic INTERPRET runs, separate profile and cast calls, reading the same gathered facts) also flipped Dragon Raja's two low-confidence fields and Witch Hat's `set_structure` `other:` wording, and agreed on Bugle Call's gate both times.

Reading: with n = 4 one title is 0.25 of raw agreement. Part of the drop is the titles (a donghua, a 12-episode anime, a 2026 anime and a manga have thinner sources than the 14 baseline anime; both paths disagree on Dragon Raja's guessed fields). The merged call is a little less stable than the classic path on the same titles: one grid field (gate on the print title) and about 0.08 of raw agreement across the other enum fields, with the web gathering re-done each run (the classic control held the facts fixed). The AC-12 gate over all 18 titles with agreement runs still passes: gate 0.889 / 0.87, set_structure 0.889 / 0.83, progression 0.889 / 0.82 (`make eval`, 2026-09-27).

Next measurement that would settle it: a third PROFILE run (4 calls) to see which value wins 2 of 3 on the flipped fields, or the classic control with its own gathering (GATHER + INTERPRET twice, 24 calls).

## What the first live batch found (fixed the same day, `f16d1fa`)
- A batched CHECK call carried the label `a+b+c` as its title id; the corpus/blind guard refused it ("not in corpus/titles.yaml"). Now every title of the group is guarded and charged; the client sees the label.
- One Budget across all stages made the per-title cap (6, set when every stage built its own client) stop the 7-call fast path at CHECK. Now `Budget.stage_view()`: the run cap (40) is one for the whole run, the per-title cap is per stage as before.

## Observations
- PROFILE varies 2.2–6.8 min per title and carries ~228K input tokens per call (the fetched pages); one of six calls needed a fresh run after a quarantine. GATHER + INTERPRET before: 49K + 23K tokens per call.
- The 3-title CHECK batch (owner's item 4) failed 2 of 3 times (REVISE verdicts without reasons, with prompt 1.4.0 and 1.4.1) and passed once after a repair; single-title calls passed 5 of 5. Default is back to one title per call (D-049); a quarantined batch now falls back to single calls (`batch_fallback` counted and flagged).
- Jikan answered 504 all morning: outcomes on these titles rest on AniList numbers plus critic verdicts (the label rule still holds: two sources).
- The 6-call per-title cap was per stage in practice (each stage built its own client); the shared run budget now keeps that (`Budget.stage_view()`), so the run cap of 40 is the real cap per `make backfill` run (4 titles × 8 calls = 32).
