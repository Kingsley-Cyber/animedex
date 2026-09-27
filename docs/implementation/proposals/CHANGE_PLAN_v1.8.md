# Change plan v1.8: concept, character, and abstract layers (lands with v1.7)

**Status:** requested by Kingsley on 2026-09-27. This consolidated request supersedes every earlier v1.8 message; the spec is saved word for word in `v1.8_request.md`.
**Lands:** together with v1.7 (gather-first, `CHANGE_PLAN_v1.7.md`), after the M2 report and before any M3 live run.
**Lean rule:** this completes the V1 lens. No further fields until blind review #1 shows where the ideas are weak.

## 1. What changes

| Area | Change | Contracts |
|---|---|---|
| Title fields (vocab 1.5.0) | 36 new lens fields. power_combat gets 11: mc_edge, power_embodiment, set_structure, subset_mechanics, set_scaffold, member_depth, world_integration, rarity, power_up_mode, power_up_cost, fight_logic. core gets 25: the story engine (story_engine, story_engine_secondary, pilot_hook_type, ending_type), the world engine (setting_type, world_visibility, conflict_scale, institutions), MC and cast (mc_archetype, mc_start, mc_goal_type, ensemble_size, rival_type, threat_structure) and the abstract layer (thematic_argument, audience_promise, promise_mechanism, promise_break, escalation_model, anticipation_hooks, premise_abstraction, real_world_isomorphism, core_fantasy, genre_move, reacts_against). Every enum value is exactly as listed in the request. | 04, vocab |
| Field shapes (schema 1.4.0) | Three new lens kinds sit beside `phrase` and `enum`. `enum_multi` is a list of enum values (subset_mechanics, power_up_mode, fight_logic, core_fantasy). `list` holds up to N items with typed sub-fields (institutions, anticipation_hooks). `group` has fixed sub-fields (thematic_argument). Every kind keeps conf, source, verification, source_ref and epistemic. | 04, models |
| Characters (new record) | `characters.jsonl`, up to 4 per title (protagonist, main rival, main antagonist, mentor or deuteragonist), id `{title_id}.c.{nn}`. Holds the base fields, a power kit for up to 3 powered characters (protagonist first) and villain fields for antagonists, all as in the request. `drama_source` replaces creativity for `stat_block` kits. Character names join the name-leak list, so they never reach patterns or idea cards. | 04, models, pipeline |
| Outcomes | `failure_patterns` (multi, mixed/flop only), each with its source URL. Pre-mortems and graveyard warnings cite them. | 04 |
| P4 transfer atoms | Adds `mechanism` (≤20 words), `principle` (≤25 words; checked for the "when X, do Y, because Z" form) and `anti_pattern` (≤12 words). The existing conditions stay. | 04, 05, p4 prompt |
| M7 principle test | A principle is `predictive` only if it explains at least one load-bearing atom in a held-out title it wasn't extracted from. Only predictive principles feed ideation as principles. The contract lands now and the code with M7. | 04, 05 |
| IDEATE | Cards gain the MC's edge, origin, wound and origin-power link, the MC's power kit (kind, medium, functions, 3 signature tools, limits, creativity path), plus thematic argument, audience promise, escalation model, core fantasy and premise abstraction. The clone check embeds `premise_abstraction`, not the surface premise. `make ideas BRIEF=<file>` takes hard constraints and rejects failing ideas before scoring (see decision 5). mc_edge, story_engine and mc_archetype become selectable gap-map dimensions. | 04, 05, ideate |
| Census | Adds set_structure, story_engine and mc_archetype. The census hasn't run yet, so these join its first run; no top-up is needed. | census prompt |
| CQs | At least one per new field: the 13 in the request plus coverage questions, about 45 in total. Each gets a DuckDB query in `analyze/cq.py`. The orphan test enforces it: a field without a CQ fails `make test`. | competency_questions.yaml |

## 2. Who fills what

| Pass | Model | Web | Fills |
|---|---|---|---|
| GATHER (v1.7) | Haiku 4.5 | yes: Wikipedia first, then show wikis | Documented facts, each with its URL: ability and technique lists, forms and their triggers, backstories and origins, institutions, turning-point episodes, endings, reception and critic complaints (the evidence for failure_patterns and promise_break). |
| INTERPRET (v1.7) | strong model (decision 4) | no | Every analysis field: all enums above, the abstract layer, and the interpretive character fields (want, need, flaw, arc_type, creativity_level, villain_type, …). Works from the gathered facts, atoms and character records. It cites a gathered URL where the request asks for a source (promise_break, creativity_moves, failure_patterns). |
| VERIFY | Sonnet 5 | yes | Only what is still unsourced. The M2 rules stay: `unresolved` is a result, there are no retries for evidence, and visual details and moment episodes are checked for gold titles only. |

- **Sources:** every gathered value keeps its source URL (`source: web`, a new verification status `gathered`, `source_ref`). Page text is never stored.
- **Scope:** GATHER keeps only facts inside the title's scope. A fact it can't place is marked `unplaced` and never settles a field.
- **Word caps:** new fields use the caps the request gives them. Otherwise phrases are ≤12 words and sentences ≤25. See decision 1 for the existing P1 fields.
- **Calls per title (cap 6):** GATHER title + GATHER characters (2), INTERPRET title + INTERPRET characters (2), VERIFY leftovers (≤1). That makes 4–5 calls.

## 3. The 14 titles already in the corpus
- One gather-first run per title covers both v1.7's measurement re-run and the v1.8 fields. M3 hasn't run yet, so no P2–P4 work gets redone. Timing splits the v1.8 share out, so the time comparison with recall-first stays fair (decision 2).
- **Size:** about 70 calls, run as a paced batch with at most 3 titles at once. That's 2 runs under the 40-call cap, roughly 2 hours of wall time.
- Blind rule: for gold titles, the new fields and characters are shown as counts only until the annotations are done or waived.

## 4. Backfill
`make backfill LIST=…` runs the whole chain for every new title as a detached batch: GATHER, INTERPRET (title and characters), VERIFY leftovers, then canonicalize.

## 5. Tests (all offline, with fakes)
- Every new field has vocab entries and a CQ (no orphans).
- Each new kind validates and rejects bad input (`enum_multi`, `list`, `group`).
- The characters record contract holds: roles, limits, a power kit only on powered characters, `drama_source` only on stat_block, villain fields only on antagonists.
- Every gathered value has a URL, and an unplaced fact never settles a field.
- INTERPRET runs with no web tools.
- The P4 principle form is checked.
- The M7 predictive rule works on a synthetic held-out title.
- A steering brief rejects ideas before scoring.
- The census counts the three new fields.

## 6. Estimates
- **Build:** v1.7 about 1 day, v1.8 about 2 days: contracts and vocab, field kinds, the characters record, GATHER and INTERPRET prompts, IDEATE, about 45 CQ queries, and tests.
- **Live:** about 70 calls to re-extract the 14 titles (roughly 2 hours at 3 titles at once), plus the recalibration pairs (embeddings only, no model calls).

## 7. Decisions for Kingsley (recommendations first)
1. **Word caps.** Recommended: keep the approved 15/20-word caps on the existing P1 phrase fields, and give new fields the request's caps (12 by default). Alternative: every phrase back to 12 words.
2. **One combined run for the 14 titles.** Recommended: a single gather-first run covering the v1.7 comparison and the v1.8 fields, with the timing split. Alternative: two runs, a clean comparison first and the new fields second, at about twice the GATHER calls.
3. **After the comparison.** Recommended: sourced gather-first values become canonical for the existing fields, and the recall-first values are kept as the baseline record.
4. **INTERPRET model.** Recommended: Sonnet 5. Alternative: Opus 5.5, which is slower.
5. **Steering brief format.** Recommended: field rules checked in code (e.g. `mc_edge not in [biggest_number, not_strongest]` for "the MC is legibly the strongest without holding the biggest number"), plus free-text rules the judge answers yes/no before scoring.

## 8. Order
1. Finish M2 (batch running), then the M2 report and tag.
2. v1.7 + v1.8 contracts: 04/05, vocab 1.5.0, schema 1.4.0 and CQs, reviewable before any code.
3. Code and tests.
4. Embedding switch (`qwen3-embedding:0.6b`, 639 MB), then recalibration on premise abstractions, then clone thresholds for approval.
5. Gather-first batch for the 14 titles, then the v1.7 comparison report.
6. M3 live on the gold set, then M4, census, M5 and blind review #1.
