# Change plan: v1.6 (ideation quality: census + prior art, judge training, execution-flop revival, concept bible + runway, search and testing)

- **Status:** awaiting Kingsley's approval (gate). No doc or code changes for v1.6 have been made.
- **Received:** Kingsley's adjustments of 2026-09-27 (verbatim in the appendix), applied to the five upgrades proposed the same day.
- **Depends on:** v1.3 `failure_level` (item 3) and the v1.5 Studio bible schema (item 4). Both are still at their own gate (`CHANGE_PLAN_v1.3-v1.5.md`).
- **Request A:** not received. Nothing was pasted, so it is treated as deferred until Kingsley sends it (before M4). v1.4 stays reserved for it.
- **Lands:** at the M4→M5 boundary. The census and prior-art checks run between M4 and M5, so blind review #1's "never done" claims are credible. Standing rule: nothing lands mid-milestone.

## 0. Decisions already made (Kingsley, 2026-09-27)
| # | Item | Decision |
|---|---|---|
| 1 | Census + prior art | Lands between M4 and M5. The title list comes from a real catalog (e.g. AniList), not model recall. About 10 titles per census call. Census values are counts only: they never become atoms or ideation input. Use Sonnet unless a sampled accuracy check shows Haiku is good enough. The prior-art web check applies to every absence claim: T1, T4, and imported/export lanes. |
| 2 | Judge training | Starts after blind review #1. Kingsley's pairwise picks split into examples and a held-out test set; judge agreement is reported on held-out pairs only. |
| 3 | Execution-flop revival + pre-mortems | Approved. A revival needs evidence that the failure was execution-level. |
| 4 | Concept bible | One schema with the Studio bible. The runway check moves forward as an M5 judge question: "does the cost still hurt by arc 5?" |
| 5a | Operator weighting | Not before M7, with a minimum share per operator. |
| 5b | Solo Leveling recipe operator | Allowed only when the borrowed system has zero occurrences as a power system in the census. |
| 5c | Strong baseline | Blind review #1 has three arms: ANIMEDEX, a plain prompt, and the same model with web search finding gaps itself. 15 cards per arm, 45 total. |
| — | Backlog | Manhwa/web-novel/game demand and non-power grids are logged as backlog, not scheduled. |

## 1. Impact map

### Item 1: census + prior art (M4→M5)
| Doc | Change |
|---|---|
| 00 | Core bet 5 ("zero is not novel"): coverage adequacy may be measured from census counts. |
| 01 | Inputs: a catalog title list. Promise: census values are counts only and never become atoms, evidence, or ideation input. New CQs: census coverage per grid cell; prior-art outcome per claim. |
| 02 | In scope: the census (breadth of titles, not fields) and prior-art checks. The "Scraping" non-goal is clarified: catalog metadata through an official API is allowed; descriptions and reviews are never stored. |
| 03 | Flow: CENSUS (between ANALYZE and IDEATE) and a PRIORART check. Storage: census records. Web sources: prior art uses the native CLI web path that VERIFY already uses. |
| 04 | New contracts `CatalogTitle`, `CensusEntry`, `PriorArtCheck`. Invariant: no atom, transfer atom, idea card, or ideation prompt references a `CensusEntry`. |
| 05 | Commands `animedex census {fetch, run, accuracy}` and `animedex prior-art`. Stage contracts, `census:`/`prior_art:` config, and model slots `census` and `prior_art`. |
| 06 | Controls: the counts-only invariant; the prior-art gate on every absence claim; the census accuracy check before choosing a model. |
| 07 | A census step between M4 and M5. |
| 08 | New ACs (numbered when applied): catalog-sourced list; batches of ≤10; counts-only invariant (contract test); accuracy check recorded with the model choice; every T1/T4/lane claim carries a `PriorArtCheck`. |
| 09 | Accuracy-check protocol; prior-art pipeline tests on mock web evidence. |
| 11 | New rows: catalog API unavailable; census accuracy below the bar; prior art finds a counterexample. |
| 12 | Report fields: census size and accuracy, model used, prior-art outcomes per claim. |

**Contracts:**
- `CatalogTitle`: catalog, catalog id, title, year, format, episodes, genres, catalog tags, popularity, `root` (no prequel). Metadata only, never descriptions.
- `CensusEntry`: catalog ref, the grid enums (gate, cost_of_power, progression, visible_counter, fight_medium, power_is), and `borrowed_system` if decision 8 is yes. Plus `trust: recall`, batch id, and provenance. No free text.
- `PriorArtCheck`: claim kind (`T1 | T4 | lane`), the structured claim (the key combination), queries, counterexamples (title, retrieved URL, match note of ≤25 words paraphrased), verdict (`clear | counterexample | inconclusive`), and provenance.

**Prior-art verdict rules:**
- `counterexample`: T1 falls back to T2. The idea must then differ from the counterexample on at least one essential atom, or the claim is dropped. A T4 zero-occurrence claim is dropped. A lane claim is marked `contested` and cannot be used as T4 evidence.
- `inconclusive` counts as not cleared.

**Config sketch:**
```yaml
census:
  catalog: anilist                  # decision 2
  size: 500
  selection: {formats: [TV, TV_SHORT, ONA, MOVIE], years: [1995, 2026], roots_only: true, order: popularity}
  batch_size: 10
  accuracy: {sample: 32, haiku_min: 0.80, haiku_max_gap: 0.05}   # decision 6
prior_art: {max_searches: 4, max_fetches: 6}
models:
  census:    {provider: claude_cli, model: claude-sonnet-5}      # Haiku only if the accuracy check passes
  prior_art: {provider: claude_cli, model: claude-sonnet-5}      # native web tools, as VERIFY
```

**Accuracy check:** Sonnet and Haiku each census the same 32 titles:
- the 5 gold titles, scored against your committed picks;
- the 7 partners, scored against their P1+VERIFY values;
- 20 census titles checked on the web.

Haiku is chosen only if it meets the bar in decision 6. The `borrowed_system` label, if added, is scored too.

### Item 2: judge training (after blind review #1)
| Doc | Change |
|---|---|
| 04 | New `PairwisePick`: pair id, two card ids, winner, optional reason in your own words, split (`example | heldout`), split seed. |
| 05 | `animedex eval pairs {collect, split, score}`. The judge prompt gains an examples block built only from `example` pairs. |
| 06 | Held-out pairs never enter any prompt (contract test). The split is seeded and recorded, and only you can re-split. |
| 09 | Pairwise protocol: pairs come from the 45 blind-review cards, across arms. Agreement is reported only on held-out pairs, with a 95% interval and a naive baseline (always pick the ANIMEDEX card). |
| 08 | New AC: held-out agreement recorded with its interval; no held-out pair in any prompt. |
| 11 | New row: judge agreement at or below the naive baseline. Change the rubric, not the metric. |

**Size:** about 60 pairs (about 10 minutes), split 50/50. With 30 held-out pairs the 95% interval is roughly ±17 points, so one review is a first reading, not a verdict. The held-out set grows with each review.

### Item 3: execution-flop revival + pre-mortems (M5)
- **Operator `revive_execution_flop`:**
  - **Source:** a flop or mixed title whose `failure_level` is `execution` (v1.3). The evidence must be a VERIFY-sourced `failure_reason` with a retrieved citation, or your recorded override (v1.3 decision 5). Missing evidence is a deterministic gate reject.
  - **Move:** keep the flop's premise atoms. Replace the atom(s) tied to the failure with a `load_bearing` engine atom from a hit, respecting its essential conditions.
  - **Card:** names the flop and maps the improvement to its recorded weakness. That is T5's required evidence.
- **Pre-mortem on every champion:**
  - 2–3 risks, each drawn from a flop or mixed title that shares an atom or cell with the card (its `failure_level` and `failure_reason`), each with a mitigation.
  - The judge checks that each mitigation answers its risk.
  - The pre-mortem never appears in blind packets.
- **Contracts:** IdeaCard gains `premortem[]` and `revival_of` (title id plus evidence ref).
- **Docs:** 04, 05 (operator table and judge step), 06 (revival evidence gate), 08 (ACs), 09 (a revival fixture without execution-level evidence must be rejected).

### Item 4: concept bible + runway
- **One schema:** the v1.5 Studio `Bible` gains `origin: concept | studio`. Concept bibles are for champions; studio bibles are for shows in production. If v1.5 is not approved, v1.6 introduces the same schema with the concept fields only.
- **Runway judge question (M5):** "Does the engine's cost still hurt by arc 5?" The answer (yes/no plus a one-line reason) is recorded on the card. The handling of a "no" is decision 7.
- **Develop step** (champions only; timing is decision 11):
  - world rules: each power's gate, cost, counter and visible sign;
  - factions: who gains and who loses from each rule;
  - a 5-arc runway sketch;
  - cast engine: the lead's want vs. need, tied to the cost;
  - a pilot hook and 3 key moments;
  - a world lint that flags any moment breaking a rule.
- **Docs:** 04 (Bible `origin`, IdeaCard `runway`), 05 (judge step 5), 08, 09.

### Item 5: search and testing
- **5a Operator weighting (M7):** Thompson sampling on each operator's champion rate, with a minimum share per operator (decision 10). Until M7, operator choice stays as specified in 05.
- **5b `borrow_system` operator (the Solo Leveling recipe):**
  - The move: borrow a system audiences already know from outside fiction's power systems (game, exam, job, market, sport, social rating…), break one of its rules, aim it at an unserved appetite, and make progress visible.
  - It is allowed only when the census shows zero titles using that system as a power system. This needs a census-only label (decision 8).
  - It lands at M5, since the census exists by then.
- **5c Three-arm blind review #1, 15 cards per arm:**
  - **Arms:** ANIMEDEX champions; a plain prompt (same model, taste standard included); and the same model with WebSearch/WebFetch, asked to find gaps first and then write premises (taste standard included, turn cap as VERIFY).
  - **Formatting:** identical length limits and formatting. URLs and citations are stripped from the web arm.
  - **Shortfalls:** never loosen a gate to reach 15; if the call cap hits first, review N per arm.
  - **Doc changes:** 09's protocol, AC-30's wording, and G0 decision D6 (20 vs 20 becomes 15 × 3).

## 2. Conflicts and proposed resolutions
1. **Core bet 1 ("depth over breadth") vs. the census.** The census adds titles, not fields or passes. The four passes still run only on the deep corpus, and census values are counts. Resolution: amend core bet 5's wording only.
2. **02 non-goal "Scraping" vs. a catalog list.** The list comes from an official API as metadata (ids, titles, year, format, tags, popularity). Descriptions and reviews are never stored. Resolution: clarify the non-goal row.
3. **"Recall is not verification" vs. a recall-based census.** Census values carry `trust: recall` and are used only to count occupancy, never as evidence on a card. Every absence claim gets the prior-art web check, and the accuracy check measures recall error.
4. **02 non-goal "adding fields up front" vs. `borrowed_system`.** Your condition 5b needs it. It is census-only (not in the P1 lens), so extraction quality is untouched. Decision 8.
5. **02 non-goal "Frontend/UI until V1.1" vs. pairwise picks.** V1 uses the CLI (one keypress per pair). A review page waits for V1.1 unless you allow it (decision 9).
6. **G0 D6 (20 vs 20) vs. 15 × 3.** Your decision supersedes D6. Recorded in CHANGELOG and the brief.
7. **06 decision rights ("operators and passes need idea-card failure evidence first") vs. two new operators, a census stage, and a prior-art check approved up front.** Record them as owner-approved exceptions, and re-judge them at M7 on CQ-I13 operator stats (decision 12).
8. **07 M5 says "the six operators".** That becomes eight: the six plus `revive_execution_flop` and `borrow_system`. CQ-I13 covers all eight.
9. **Catalog terms.** AniList's API terms restrict commercial use. If ideas may be sold, use Wikidata (CC0) or get AniList's permission (decision 2).
10. **Call budget.** Estimated extra subscription calls, about 120–170 in total:

   | Work | Calls |
   |---|---|
   | Census batches | ~50 |
   | Accuracy check | ~10 |
   | Prior-art lane checks (M4→M5) | 10–20 |
   | Prior-art card checks (M5) | 20–40 |
   | Web arm | 2–4 |
   | Held-out judge scoring | ~3 batched |

   At the 40-call run cap that is 4–5 runs, scheduled away from your coding hours.

## 3. Consolidation (build once, share)
- Prior art reuses VERIFY's native web path: the same CLI web tools, turn cap, retrieved-URL evidence rule, and URL-only cache.
- The census prompt is a P1 subset over the same `vocab.json`. There is no parallel vocabulary.
- The concept bible and the Studio bible are one model with an `origin` field.
- Pre-mortems reuse M4's graveyard lookup and v1.3's `failure_level`.
- The web arm reuses the native web tools. Pairwise picks reuse the blind-review card pool and formatting.

## 4. Versioning and migrations
| Version | Schema | Vocab | CQs | Prompts | Migration |
|---|---|---|---|---|---|
| v1.6 | 1.6.0: + CatalogTitle, CensusEntry, PriorArtCheck, PairwisePick; IdeaCard + `premortem`, `revival_of`, `runway`; Bible + `origin` | 1.6.0: + operators `revive_execution_flop`, `borrow_system`; + census-only `borrowed_system` (decision 8) | + census coverage, prior-art outcome, judge agreement | new `census.md`, `prior_art.md`, `baseline_web.md` at 1.0.0; `ideate_generate` and `ideate_judge` bumped | None. Everything is additive; census and prior-art records are new |

## 5. Placement
| Piece | Lands | Depends on | ACs |
|---|---|---|---|
| v1.6 docs + models + vocab + config | M4→M5 boundary | v1.3 and v1.5 decisions | new, after AC-42 in landing order |
| Census + prior-art stage and gate | After `m4-complete`, before M5 starts | M4 lanes; catalog choice | census + prior-art ACs |
| Runway question, revival operator + pre-mortems, `borrow_system`, three-arm blind review | M5 | v1.3 `failure_level`; census | AC-25…30 (+ AC-30 reworded) + new |
| Judge training (pairs, split, held-out agreement) | After blind review #1, before M6's review #2 | blind review #1 cards | new |
| Concept bible develop step | After blind review #1, or with Studio at M8 (decision 11) | Bible schema | numbered when applied |
| Operator weighting + minimum share | M7 | operator stats from M5/M6 | M7 AC |

## 6. Risks and pushback
- **Census recall error** skews cell counts. Mitigations: the accuracy check, prior art on every claim, and cells with few titles still reporting "insufficient coverage".
- **30 held-out pairs give a wide interval.** Don't retune the judge on one review.
- **The web arm may beat ANIMEDEX.** That is a real finding, not a failure to hide. Diagnose first: were the gaps the web arm found missing from the census?
- **The revival lane is thin until M7** (one or two flops in the corpus). An operator with no eligible input is skipped, never forced.
- **`borrow_system` depends on a census-only label.** Include that label in the accuracy check.
- **Usage:** the 120–170 extra calls compete with your coding sessions. Run them in scheduled windows.

## 7. Decisions needed (one line each)
1. Request A: deferred until before M4, since nothing was pasted. Confirm?
2. Catalog: AniList (richest; terms restrict commercial use) or Wikidata (CC0)? *AniList if ideation stays personal; Wikidata if you may sell ideas.*
3. Selection: the top 500 anime by popularity, TV/TV_SHORT/ONA/MOVIE, 1995–2026, first entry of each franchise only? *Recommended.*
4. Storage: census records committed under `data/canonical/` as `census_entry` with `trust: recall`? *Recommended over a separate `data/census/` tier.*
5. Drop the one-line premise from the census, keeping it counts-only? *Recommended; prior art covers novelty.*
6. Haiku bar: Haiku only if its accuracy is ≥ 0.80 and within 5 points of Sonnet on the 32-title sample?
7. A runway "no" means rework once, then reject? *Recommended, matching the failure-condition flow;* the alternative is a fitness penalty.
8. Add a census-only `borrowed_system` label (about 15 kinds: game, exam/school, job/bureaucracy, market, sport, social rating, law/contract, card/collection, crafting/cooking, military rank, ritual/religion, other) so 5b's condition can be tested?
9. Pairwise picks: CLI in V1 (*recommended*), or allow a private review page before V1.1?
10. Minimum operator share at M7: 5% per operator (8 operators, so a 40% floor)?
11. Concept bible develop step: after blind review #1 (*recommended*) or with Studio at M8?
12. Record the new operators and stages as owner-approved exceptions to 06's "failure evidence first" rule, re-judged at M7 on operator stats?

## 8. Backlog (logged in Beads, not scheduled)
- **Demand signals from manhwa, web novels and games:** patterns popular there but missing in anime (T4 appetite). Needs a scope change (02 lists screen media only).
- **Idea grids beyond power systems** (romance, mystery, horror). Related to M7's cluster-based grids.

## Appendix: Kingsley's adjustments, 2026-09-27 (verbatim)
> Plan it as v1.6, with these adjustments:
> 1. Census + prior-art: land between M4 and M5, so blind review #1's "never done" claims are credible.
>    - Title list from a real catalog (e.g., AniList), not model recall.
>    - Batch ~10 titles per census call. Census values are counts only; they never become atoms or ideation input.
>    - Use sonnet unless a sampled accuracy check shows haiku is good enough.
>    - The prior-art web check applies to every absence claim: T1, T4, and imported/export lanes.
> 2. Judge training: after blind review #1. Split my pairwise picks into examples and a held-out test set; report judge agreement only on held-out pairs.
> 3. Execution-flop revival + pre-mortems: yes. A revival needs evidence that the failure was execution-level.
> 4. Concept bible: one schema with the Studio bible. Pull the runway check forward as a judge question in M5: "does the cost still hurt by arc 5?"
> 5. Search and testing:
>    a. Operator weighting: not before M7, with a minimum share per operator.
>    b. Solo Leveling recipe operator: only when the borrowed system has zero occurrences as a power system in the census.
>    c. Strong baseline in blind review #1: plain prompt AND the same model with web search finding gaps itself. 15 cards per side, 45 total.
> Log the later items (manhwa/web-novel/game demand, non-power grids) as backlog.
