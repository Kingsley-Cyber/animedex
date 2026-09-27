# Completion Report — M5: ideation, fair baselines, the blind packet, audit, diagnose, backtest

- **Date:** 2026-09-27
- **Agent / model:** Claude (lead); generation on Opus 5.5, the judge on gpt-5.6-terra (codex), prior art on Sonnet 5 with native web search, embeddings on Polymath's Qwen3-Embedding-0.6B
- **Commit tag:** `m5-complete` (code and data repo)

## Summary
ANIMEDEX and baseline 1 each ran the same schedule (one 1-generation run, then two capped runs), giving 42 ANIMEDEX champions across 42 grid cells and 51 passing baseline-1 cards; baseline 2 wrote 15 premises in one call. The blind packet holds 45 cards, 15 per arm, shuffled, with logline and premise only; the answer key stays in the private data repo. Every M5 AC passes except AC-30 (the review itself), which starts when Kingsley rates the packet. The live runs found three defects (a name guard that rejected ordinary words, a dialogue guard that rejected a description, and an archive that never persisted); all three are fixed with tests, and the archive was rebuilt from the cards without new calls.

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-25 | pass | Every idea card carries `closest_existing`, `why_not_a_clone` and a complete 7-part engine (contract test; 53 live cards validate). |
| AC-26 | pass | Cards draw only on load-bearing-eligible transfers (45 eligible; contract test). |
| AC-27 | pass | Every card records its operator and consequences; the surface-change fixture fails H1 (pipeline test). |
| AC-28 | pass | Gates enforced and logged with the gate: live rejections were clone 3, novelty 13, coherence 1, format 6. |
| AC-29 | pass | One idea per cell, fitness never decreases (unit test). Live: 42 cells, 42 champions, no integrity errors after the rebuild (D-041). |
| AC-30 | **pending** | The packet is ready (`eval/blind/packet_2026-09-27.md`, 45 cards). The review is Kingsley's step. |
| AC-44 | pass | Census: 500 titles from AniList in batches of 10 (50 calls over two runs); no atom, transfer, idea or prompt references a census entry (contract test). |
| AC-45 | pass | 19 T1/T4 claims on champions, 19 prior-art records, all `clear`. 4 records the quote guard had wrongly quarantined (exact-phrase search queries) were restored (D-041). |
| AC-46 | pass | Every judged card records the runway answer (42 of 42 champions: yes); revival cards name an execution-level flop with evidence; champions carry a pre-mortem. |
| AC-47 | pass | 15 cards per arm, shuffled by a date seed; the packet's Markdown and JSON hold id, logline and premise only (exact-word scan: no arm names, ids or verdicts); the key is git-ignored under `data/blind/`. |
| AC-50 | pass | Every generate call got a `key: value` brief capped at 600 words (168 live briefs: up to 600 words, about 800 tokens at the median; baseline-1 briefs hold only the theme, operator and target, a few dozen words), atoms under aliases, the nearest 10 titles, the region's flops, the cell's counts, lanes and prior art; words and tokens logged per call. |
| AC-51 | pass | Unit test (199 rows no, 200 rows yes). Live: 292 powered census rows, so census-backed zeros count; every champion's key pair has PMI ≤ −1 over 281–304 rows. |
| AC-52 | pass | Pipeline test. Live: no premise-level graveyard match (all four graveyard titles are execution-level), so `why_different` was never triggered. |
| AC-53 | pass | Both arms used the `ideate_generate` slot (Opus 5.5), the same taste standard and rules; 0 generating calls carried a web parameter (run-log check); every packet card got the same prior-art check (41 clear, 4 inconclusive, recorded in the key). Baseline-1 cards live in `data/blind/baseline_loop/`, never in the archive. |
| AC-54 | pass | Every ideation run stopped at exactly 60 calls ("Paused: call cap reached: 60/60"); other runs kept 40 (the census paused at 40/40). |
| AC-55 | pass | Pipeline and unit tests; live: no champion leans on a contested or rejected atom, so `ideas.md` shows no flag and the packet never would. |
| AC-56 | pass | `make audit`: 10 date-seeded eligible atoms with evidence trails → `eval/audit/audit_2026-09-27.yaml` (marks blank, gold titles allowed since the blind is waived); `make audit-report` runs on the unmarked sheet (0 marked, 14 P2 runs). |
| AC-57 | pass | `make diagnose` on a synthetic concept: 1 structuring call, 9 checks (7 pass, 2 fail: novelty and ablation), each failure with a prescription from the operator/rung table, 3 calls in total, written only to `data/diagnose/`. |

## The arms
| | ANIMEDEX | Baseline 1 (same loop, empty brief) | Baseline 2 (one plain call) |
|---|---|---|---|
| Runs | 3 (generations 0–4) | 3 (generations 0–4) | 1 call |
| Cards generated | 53 | 60 | 15 |
| Passed every gate | 45 (42 champions, 3 candidates) | 51 | n/a (no gates) |
| Rejected | 8 (clone 1, novelty 6, coherence 1) | 9 (clone 2, novelty 7) | — |
| Prior-art checks on T1/T4 claims | 19, all clear | 35, all clear | — |
| Taste claims on champions | T2 20, T1 16, T3 1, T4 1 (14 champions claim none) | — | — |
| Operators among champions | combine_mechanisms 9, transfer_cost 6, import_lane 6, reverse_incentive 6, redistribute_knowledge 5, change_rule 5, revive_execution_flop 5 | same rotation, no atoms, no flops, no systems | — |

Champion cells cover 42 of the grid's 252 cells; the gate axis is spread (artifact 9, trained 7, death_or_ritual 6, contract 5, inherited 4, others 11). The diversity alarm fired once (canary: 4 of 9 champions on one gate) and cleared as the archive filled.

## Calls and time (IDEATE, all live)
| Stage | Calls | Time | Notes |
|---|---|---|---|
| Generate, ANIMEDEX | 82 | 65 min | 22 second attempts (full repairs) |
| Generate, baseline 1 | 74 | 45 min | 12 second attempts |
| Shorten (both arms) | 92 | 17 min | length-only repairs of one or two texts (D-030); most cards needed one |
| Rework (both arms) | 10 | 8 min | judge-driven |
| Judge (both arms) | 31 | 16 min | batches of 4 |
| Prior art, ideation | 15 | 6 min | native web search |
| Prior art, packet | 12 | 4 min | all 45 cards |
| Baseline 2 | 2 | 3 min | one attempt was over its caps |
| Diagnose | 3 | 1 min | |
| **Total** | **321** | **164 min** | 8 runs, each under its cap; no model substitution |

Word caps drive most of the repair traffic: 92 shorten calls against 156 generate calls. They are cheap (about 10 s each), and the shorten-first rule (D-036) keeps a long text from triggering a full regeneration.

## What the live runs found, and the fixes
| Defect | Effect | Fix |
|---|---|---|
| The name guard treated any capitalized word as a name ("God", "Earth", "Ten") | 2 of 12 canary cards rejected as "reused names" | D-039: names, not capitals: lowercase evidence from the index's own prose, a fixed list of common capitals, compound names as phrases, possessives matched to their base |
| The dialogue guard read a sentence-case label ("Iyashikei safety: …") as a speaker | 1 canary card quarantined at canonicalize | D-041: speaker labels must be Title Case; generation applies the canonical guards, so the model repairs the card instead |
| That card's dangling archive row failed every archive transaction | The archive never persisted: all 43 passing cards claimed "champion", none was ever displaced | D-041: a row whose idea is missing is dropped alone; `animedex ideate --rebuild-archive` rebuilt 42 cells from the canonical ideas (best fitness per cell) without new calls |
| The quote guard read exact-phrase search queries as quotations | 4 prior-art records quarantined (AC-45 gap) | D-041: stored queries are skipped by the guards; the 4 records were restored |
| Judge word-cap errors were not repairable by path | A long reason meant a full judge retry | Judge problems name their text by path, so the length repair shortens just that text |

The census also needed a fix before it ran (D-038: the corpus's value tests go into the census prompt). The ideation schedule (D-040) gives both arms the same three runs, since one generation costs about 34 calls and a capped run ends mid-generation.

## Census (v1.6)
500 titles (450 anime, 50 donghua), 292 with a power system; two runs of 40 and 10 calls (47 min). With 292 powered rows the rule of three holds (3/n = 0.010), so census-backed zeros are open: 32 empty gate × cost cells, none a real gap (the highest expected count is 1.8). The census only ever contributes counts.

## Backtest (controls B1, D-007, D-032)
10 held-out power-system titles (2017–2023, none in the corpus) went through GATHER and INTERPRET unchanged; the judge then predicted hit, mixed or flop from the premise abstraction and the power kit alone, once with a blank brief and once with the index brief (nearest indexed titles, anonymous, with outcomes and failure patterns). 34 calls, about 25 minutes.

| | Blank brief | Index brief |
|---|---|---|
| Accuracy (10 titles) | 0.60 | 0.70 |

- The two conditions disagreed on one title, and the index brief was right there (index 1, blank 0). Exact one-sided McNemar p = 0.50: **no evidence yet** that the index helps; at this split, 46 titles would be needed for p < 0.05 (D-016).
- Both conditions missed the same three titles: two `mixed` titles read as hits or a flop read as mixed. The kit and the abstraction carry no execution signal, which is where those titles went wrong.
- Reception for the held-out titles came from AniList only (Jikan answered 504 for 7 of 10; MAL API key not set). The labels are reception-backed either way.
- Report: `build/reports/backtest.md`; numbers also in `build/reports/stats.md`. A rerun on the same titles is served from the cache; widening the list is one `make backtest LIST=…` away.

## Provenance of winners (controls A6)
Written by `make review-report` after every card is rated (`build/reports/taste.md`): each greenlit card's arm, operator, patterns drawn on with their source titles and principles, whether each pattern reached the card's text, and the count of greenlit cards that used no index material. Hidden until then, so the review stays blind.

## Tests
`make test`: 554 passed. `ruff`: clean. `make clean-build`: identical hashes and CQ answers. `animedex validate`: OK. New regression tests: the name list (D-039), Title Case speaker labels, guards at generation, the per-row archive quarantine, the archive rebuild, search queries skipped by the guards, judge length paths, provenance of winners, the MCP server (request A, on its branch).

## Flags for review
- 14 of 42 champions claim no taste criterion; they hold their cell because nothing better landed there. The rating will say whether that matters.
- 4 packet cards have an inconclusive prior-art verdict (recorded in the key, not shown to the rater).
- One diagnose demo and one audit sheet exist; the audit marks are blank until Kingsley fills them.

## Next
Blind review #1 (Kingsley rates the packet), then `make review-report` (arms, Bradley–Terry strengths, judge agreement, provenance of winners). Request A merges now; the priority-1 backfill follows.
