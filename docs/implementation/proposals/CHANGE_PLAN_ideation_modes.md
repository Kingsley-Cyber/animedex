# Change plan: ideation modes (seed types, steering library, call brief, amplify, stress tests)

- **Status:** plan only, 2026-09-27. Nothing here is built until Kingsley approves it.
- **When:** after blind review #1 (scope freeze). Three parts come earlier, each at a milestone boundary, never mid-milestone (operating-brief.md:90-91):
  - item 1's small slice (fight-first seeds) may land in M5, at the M4→M5 boundary, before the first live `make ideas`;
  - item 3's first part, the M5 brief, is already ruled into M5 (operating-brief.md:201);
  - item 2's base lands with v1.8: `steering/rules.yaml`, hard or soft rules, every card listing the rules it satisfies (CHANGE_PLAN_v1.8.md:62; operating-brief.md:211).
- **Builds on:** v1.7 (Qwen3 embeddings, compact inputs); v1.8 (kit, MC edge, set fields, abstract layer, failure patterns, P4 principles, M7 predictive rule, steering file); the controls plan (A5 fairness, A6 provenance, A8 flags, B1 minimal brief, B2 market lines, B4 serial-readiness rung); and the 2026-09-27 rulings (60-call ideation cap, census-backed novelty only with 200 or more powered census rows, the judge weighing `why_different`).
- **Reuses from v1.8, not duplicated:** the steering file is the library's first version; the kit, edge and set fields are fight-first steps 3–5 and amplify rungs 1–3; `premise_abstraction` feeds meaning retrieval; `failure_patterns` fill the brief's failure slot; P4 principles become brief principles and seeds once M7 marks them predictive. The alternative grid dimensions work unchanged, since every card files under `ideate.grid_dims`.
- **Live runs:** none before M3. The atom pool is empty until P2–P4 run (ADVISOR_SNAPSHOT.md:92, 95, 388).
- **Words used here:** a *seed* is what a card starts from. The *call brief* is the small input assembled for one generate call (item 3), not v1.8's "steering brief", which is now the steering file. A *rung* is one step of the amplify ladder. A *stress test* is one of two extra judge questions per card.
- **Request:** word for word in the appendix.

## 1. Today (read from the code on 2026-09-27)

### 1.1 What one generate call receives
One call writes one card. The slot `ideate_generate` is claude_cli, Opus 5.5, effort high (settings.yaml:52). The system prompt is `prompts/ideate_generate.md` 1.0.0 (lines 5–24). `generate_user` (llm.py:65-87) builds the user message as plain labelled text, in this order:

| # | Block | Content | Code |
|---|---|---|---|
| 1 | THEME ROOT | a random corpus core_question | llm.py:68; run.py:176; context.py:114 |
| 2 | OPERATOR | name + one-line definition | llm.py:20-31, 68 |
| 3 | TARGET PROFILE | the cell's gate, cost_of_power, progression | llm.py:69 |
| 4 | PATTERNS | 1–3 transfer atoms: id, pattern, bridge, essential, variable, failure. The ids name the source title | llm.py:59-62, 69-70 |
| 5 | FLOP TO REVIVE or BORROWED SYSTEM | only for those two operators. The borrowed line says no census title uses the system | llm.py:71-75 |
| 6 | CORPUS TITLES | every title with its logline_hook, no cap | llm.py:76-79 |
| 7 | MIXED AND FLOP TITLES | every graveyard row with failure level and reason, no cap | llm.py:80-84 |
| 8 | REWORK | the failed checks, on a retry | llm.py:85-86 |

- **Output:** strict JSON (llm.py:44-56). `closest_existing` is an enum of every corpus id (:50), and premortem sources are an enum of graveyard ids (:53-55).
- **Not sent:** other profile fields, hit outcomes, census rows, gap counts, lanes, parent card text.
- **Checked in code** (llm.py:118-138): the given pattern ids, names in the logline and premise (the only text checked), 2–3 premortem items, the revival improvement, and the card's shape.
- **A failed check** costs one repair, and every attempt counts as a call (client.py:239-261). Cache hits are free (client.py:224-230). Since v1.6.5 the cache key covers the whole user message (run.py:313-321).

### 1.2 How the target cell is chosen
- **Grid:** gate × cost_of_power × progression (settings.yaml:122), minus `other`: 9 × 8 × 4 = 288 cells (run.py:101-103; `ontology/vocab.json`).
- **Choice:** each generation lists the empty cells once (run.py:165). Each of its 12 candidates takes `rng.choice(empty or cells)` (run.py:175), repeats allowed, seeded `7:<generation>` (run.py:251; settings.yaml:126).
- **Only a request:** the prompt says "Aim for the target profile" (ideate_generate.md:18), no check enforces it (llm.py:118-138), and the card is filed under its own profile (run.py:326-327, 533).
- **Not built:** the spec's "operator most likely to move a parent toward the target" (05:168).

### 1.3 How operators are applied
- **Eight operators** (llm.py:20-31; settings.yaml:123-124), with eligibility checked each run (run.py:111-125). Revive needs an evidenced execution-level flop and a hit engine atom; borrow needs a census and a system no census title uses; import_lane needs a non-anime atom; combine needs 2 source titles.
- **Dealing:** each generation shuffles the eligible list and deals it round-robin to the 12 candidates (run.py:169-174), with no weighting.
- **Atoms follow the operator** (run.py:179-197): revive takes 1 hit engine atom plus a flop; borrow takes 2 atoms plus a system; import_lane starts with a non-anime atom; combine takes 2; the rest take 1–3. They come from different titles, preferring different media (run.py:145-157).
- **Parents:** from generation 1, there's a 50% chance to start from up to 2 atoms of a random champion (run.py:192-196). Only the parent's id is kept.
- **Enforcement:** the prompt says to apply the operator "exactly once" (ideate_generate.md:14). Only the judge's H1 and coherence answers test whether it changed anything.

### 1.4 What the judge sees
- **Slot:** `ideate_judge` is codex_cli gpt-5.6-terra, strict (settings.yaml:53), with 4 cards per call (settings.yaml:125; run.py:376-389).
- **Per card (llm.py:154-172):** the card (logline, premise, theme, operator + what_changed, engine, consequences, profile); the patterns' texts and failure conditions; the closest title's logline_hook, premise_engine, primary_feeling and 6 enums.
- **Supplied facts** (run.py:364-373): the untried pair, coverage, premise-level graveyard hits, lane concepts, the revived flop's id.
- **Not sent:** why_not_a_clone, why_different, premortem, broken_rule, appetite, revival_improvement, the flop's recorded weakness.
- **Returns** (llm.py:142-151; ideate_judge.md:5-18): H1 per dimension with reasons, triggered failure conditions, coherence, runway, and taste claims with evidence of 25 words or fewer.
- **Applied:**
  - fewer than 2 of 3 H1 dimensions, or failed coherence: reject (run.py:398-411);
  - failure conditions or a runway "no": one rework, then reject (run.py:266-283, 414-420);
  - a taste claim stays only with its evidence rule, and T2 has no rule (run.py:423-443);
  - prior art drops T1 and T4 unless the verdict is "clear" (run.py:446-497).

### 1.5 Already ruled for M5, not yet in code (operating-brief.md:201-205)
- **M5 brief:** opaque atom ids, the nearest 10 titles, graveyard rows in the target region, and the cell's adequacy, lane and prior-art evidence. It is capped and its tokens are logged.
- **Novelty** rests on bridge-concept pairs until the census has 200 or more powered rows.
- **The judge** weighs `why_different`. **Baselines** get the same model, taste standard, steering rules and web tools.
- **Call cap:** ideation runs get 60 calls; other runs keep 40 (settings.yaml:72).

### 1.6 Gaps that matter for these modes
1. **No way in.** `animedex ideate` takes only `--generations` (cli.py:310), and `make ideas` passes nothing (Makefile:34-35). The spec's "theme Kingsley supplies" (05:137) has no path.
2. **No seed can own a cell.** Cards file by their own profile (run.py:533).
3. **The judge sees no chain, rule or stress question** (llm.py:154-172). T2 passes on its word alone (run.py:423-443).
4. **Name checks cover the logline and premise only** (llm.py:124-126). A derivation or a rung would go unchecked.
5. **Fitness has no slot for rules or stress tests** (run.py:500-506). That is fine if they act as gates.
6. **Fight-first cards could miss review #1.** The packet takes the top champions by fitness alone (packet.py:81-82).
7. **Missing data until v1.8 and M7.** Kits, sets, MC edge, failure patterns and principles arrive with v1.8 (CHANGE_PLAN_v1.8.md:11-17) and M7 (:16).

## 2. Requirement 1: seed types

### Today
There is one implicit seed, the gap cell (§1.2). `revive_execution_flop` and `borrow_system` resemble flop_revival and real_system, but they pick their flop or system at random (run.py:128-142, 179-185).

### Change
| Seed type | You give | What it fixes | Lands |
|---|---|---|---|
| gap_cell | nothing (the default) | the target cell, as today | exists |
| fight_image | a paragraph describing a fight | the derivation chain below; no target cell | **M5 slice** |
| user_concept | your own idea, 150 words or fewer | a core that must survive; the judge confirms it did | after #1 |
| real_system | a real system (text), plus an optional borrowed-system kind | the borrowed system | after #1 |
| flop_revival | a flop's title id | which flop to revive (execution-level evidence still required) | after #1 |
| principle_id | a pattern id | the principle and its own atoms | after M7 |

**Fight-first derivation.** One call writes the steps in this order. Each step also gets `follows_from` (15 words or fewer): what in the step above led to it.

| # | Step | Writes | Checked in code |
|---|---|---|---|
| 1 | medium | what the fighter manipulates, 6 words or fewer | present; names |
| 2 | functions | 3–6 affordances the fight shows or implies | count |
| 3 | kit | power kind, 3 signature tools, limits, creativity path (the v1.8 kit) | each tool names a function |
| 4 | set | set_structure (v1.8 enum) + a note of 15 words or fewer | vocab value |
| 5 | MC edge and cost | mc_edge (v1.8), cost_of_power, cost in 15 words or fewer | the cost equals `profile.cost_of_power` |
| 6 | engine | the 7-part engine; the operator acts here | engine complete |
| 7 | premise | logline + premise | caps; names |

- **v1.8 fallback:** if v1.8 slips, steps 3–5 take plain text and their enum checks switch off.
- **Atoms:** 2, from 2 titles, preferring 2 media. This keeps the bridge-pair novelty route open, the only route before the census (operating-brief.md:202).
- **Theme:** the model picks one of 3 corpus core questions (an enum), the one the fight expresses best. A random theme would fail coherence too often.
- **Operator:** the normal rotation minus revive and borrow. It acts at the engine step.
- **Region for the M5 brief:** a fight has no cell. Its "nearest 10 titles" are those whose title texts (gates.py:42-48) sit closest to the fight image by embedding, and its graveyard rows come from those titles.

### M5 slice: what "small" means
- **Small:** at most 2 build days including tests; about 500 changed lines; no new pass, lens field or vocab value; no change to the gates, judge, fitness or archive; one optional card block and one new prompt.
- **Recommended slice:** gap_cell (unchanged) + fight_image, plus the packet share and fight images for both baselines. Estimate: 1.5–2 days.
- **Left out on purpose:** user_concept (your own idea in the packet is the hardest thing to rate blind), real_system, flop_revival, principle_id (no predictive principles before M7), and seed records.
- **If the slice grows past this,** it waits for review #1.

### Prompts, records, commands
| Kind | Item | When |
|---|---|---|
| Prompt | new `prompts/ideate_fight.md` 1.0.0: the derivation order, one rule per step, JSON only | M5 |
| Prompt | the generate prompt's next version reads every seed type; the fight prompt folds into it | after #1 |
| Card | optional `seed` block: seed_id (`seed.<type>.<sha8>` of the text), seed_type, derivation (7 steps) | M5 |
| Record | `seed` records (§7.1) | after #1 |
| CLI | `animedex ideate --seed-type fight_image --seeds <file>` | M5 |
| Make | `make ideas SEED=fight FILE=seeds/fights.txt` (one fight per paragraph) | M5 |
| Make | `make ideas SEED=concept FILE=…`, `SEED=system TEXT="…" KIND=…`, `SEED=revival ID=<title_id>`, `SEED=principle ID=<pattern_id>` | after #1; principle at M7 |
| Packet | the fight-first share per arm; seed type in the answer key (`data/blind/`) | M5 |
| DuckDB, CQ | an `ideas.seed_type` column; CQ-I16 "Which seed types produce champions and greenlights?" | M5 |

### Gates, judge, archive
- **Gates:** unchanged for every seed. The name check also covers the derivation text.
- **Judge:** unchanged in M5, since coherence already asks whether the dilemma follows from the cost. After #1 it also answers "does each step follow from the one above?" for fight-first cards.
- **Archive:** a card files under its own profile (run.py:533) and competes with every card in that cell. Fitness is unchanged, and only gap_cell has a target. If set_structure replaces progression as a grid axis (operating-brief.md:197), step 4 picks that coordinate directly.
- **Packet (M5):** every arm carries the same number of fight-first cards, up to 5 of 15. ANIMEDEX takes its best fight-first cards by fitness, champions first; both baselines write that many premises from the same fight images (A5). The packet still shows logline + premise only (packet.py:87; 09:57). If fewer fight-first cards pass, the share shrinks for every arm.
- **Other seeds (after #1):**
  - flop_revival keeps the evidence rule (run.py:128-135) and refuses gold titles while the gold blind is pending, since the card would show gold-title output;
  - real_system counts as a census zero only when it maps to a borrowed-system kind (run.py:138-142); otherwise prior art decides;
  - principle_id uses the principle's own atoms (AC-26 holds), and user_concept never enters a blind packet.

### Calls per idea
- **Today:** 12 generate + ⌈12/4⌉ = 3 judge + 0–3 prior art = 15–18 calls per 12 cards, about 1.3–1.5 per idea before reworks.
- **fight_image:** the same shape plus about 0.1 for repairs on the longer schema, about 1.4–1.6. **Other seeds:** about 1.3–1.5, as today.

### ACs (offline: mock provider, mock embedder, synthetic fixtures, as in `tests/pipeline/test_ideate.py`)
- AC-IM-01: `make ideas` with no seed options plans exactly what it plans today for the same random seed.
- AC-IM-02: `SEED=fight` makes one candidate per fight image (12 or fewer per generation). Cards carry the seed type and seed id, and a rerun skips images already used.
- AC-IM-03: two fight images with the same plan never share a cached answer.
- AC-IM-04: the 7 steps appear in order. A missing or out-of-order step gets one repair, then quarantine.
- AC-IM-05: 3–6 functions; every tool names one; the step-5 cost equals `profile.cost_of_power`; the set and edge values are vocab values.
- AC-IM-06: a fight image naming a corpus title or character gets a warning on load, and no card text carries the name.
- AC-IM-07: the clone and H1 fixtures reject fight-first cards exactly as they reject gap-cell cards.
- AC-IM-08: every arm has the same fight-first count, and the baselines get the same fight images. The packet shows logline + premise only, and the answer key records the seed type.
- AC-IM-09 (after #1): flop_revival refuses a flop without execution-level evidence, and any gold title while the blind is pending. principle_id refuses a principle that isn't predictive.
- AC-IM-10 (after #1): no user_concept card enters a packet. The judge answers "is your core intact?" with evidence.

### Risks
- **A fight image copied from a show,** renamed. Mitigation: names are flagged on load, and the clone gate still checks every title.
- **You may recognize your own fight images.** Mitigation: every arm gets the same ones, so recognizing one says nothing about the arm. Results are reported with and without fight-first cards.
- **Fight-first cards may crowd a few cells,** such as energy with physical_toll. Mitigation: the diversity alarm reports it, and the packet share caps it.
- **v1.8 slips.** Mitigation: steps 3–5 fall back to plain text.

## 3. Requirement 2: steering library

### Today
- Nothing in code. **v1.8 lands the base before M3** (CHANGE_PLAN_v1.8.md:17, 62; operating-brief.md:211): `steering/rules.yaml`, each rule with an id, its text, hard or soft, and 1–2 examples. Failing ideas are rejected before scoring, and every card lists the rules it satisfies.
- **A5** gives both baselines the same rules (controls plan:28, 108).

### Change (after review #1)
- **Every mode reads the library:** all seed types, amplify rungs, both baselines and `make recheck`. A rule can be scoped with `applies_to` (modes, seed types, rungs).
- **Two ways to check a rule:**
  - **in code,** when it maps to an enum field: `check: {field, in or not_in, values}`. For example, "the MC is legibly the strongest without holding the biggest number" becomes `mc_edge not_in [biggest_number, not_strongest]`;
  - **by the judge** for the rest: yes or no, with evidence of 25 words or fewer, in the same judge call.
- **Hard and soft:** your request says "hard constraints", and your v1.8 decision added hard or soft. This plan reads that as: a hard rule rejects after one rework; a soft rule is shown to the generator and reported, but never rejects and never changes fitness.
- **Forbidden cells:** cells a hard code rule forbids are never targeted, and the diversity alarm ignores them.
- **Each card carries** `rules.satisfied` (ids), `rules.failed` (soft only) and `rules.version` (a hash of the active rules).
- **Rule changes:** older champions are flagged in `ideas.md`, and `make recheck` re-judges them when you ask.
- **Examples** go to the generator and the judge. An example that names a corpus title or character is refused on load.

### Prompts, records, commands
| Kind | Item |
|---|---|
| File | `steering/rules.yaml` (v1.8) gains optional `check` and `applies_to` |
| Prompt | generate: rules arrive with their ids; hard rules are constraints, soft rules are preferences |
| Prompt | judge: one yes-or-no question per judged rule, with evidence |
| Code | a steering gate after the graveyard gate, for code checks |
| Make | `make rules` (the list, with reject counts); `make rule TEXT="…" [SOFT=1] [FIELD=mc_edge NOT_IN=a,b]`; `make rule-off ID=rule.003`; `make recheck` |
| CQ | CQ-I17 "Which rules reject the most cards, and in which modes?" |

### Gates, judge, archive
- **A hard code rule broken:** one rework with the rule text, then rejection as `steering: rule.nnn`. No judge call is spent on it.
- **A hard judged rule answered "no":** one rework, then rejection. It joins the post-judge rework list (run.py:414-420).
- **Archive:** only passing cards are filed. Fitness is unchanged (run.py:500-506).
- **Baselines** get the same rules in their prompts and the same checks on their output (A5). **Amplify** checks scoped rules at every rung.

### Calls per idea
- **Checking:** +0 calls. Code checks are free, and judged rules ride in the judge call.
- **Reworks:** if 10–20% of cards break a hard rule once, add 1 generate + ¼ judge each: +0.13–0.25, about 1.45–1.75 per idea.
- **`make recheck`:** ⌈champions/4⌉ calls, so 30 champions take 8. Judge output grows about 30 words per judged rule per card, so active judged rules are capped at 10.

### ACs
- AC-IM-11: rules load with stable ids. `make rule` refuses a code check on an unknown field or value.
- AC-IM-12: a card that breaks a hard code rule gets one rework, then a `steering:` rejection naming the rule, with no judge call.
- AC-IM-13: judged rules reach the judge as yes-or-no questions. A "no" on a hard rule gets one rework, then rejection; a missing answer triggers the repair.
- AC-IM-14: every passing card lists every active hard rule in `rules.satisfied`, with `rules.version`. `ideas.md` flags champions from an older version.
- AC-IM-15: cells a hard code rule forbids are never targeted.
- AC-IM-16: both baselines' prompts carry the same rules, and soft rules never reject.

### Risks
- **Too many constraints empty the archive.** Mitigation: reject counts per rule in `make rules`, skipped forbidden cells, and at most 10 judged rules.
- **Vague rules get uneven answers.** Mitigation: prefer code checks, and flag rules whose answers split.
- **Strict rules make every MC alike.** Mitigation: scope rules, and watch the diversity alarm.

## 4. Requirement 3: call brief assembly

### Today
- **Input:** every title and every flop, uncapped (§1.1). IDEATE never queries DuckDB; it rebuilds its context from canonical data each run (context.py:70-119). Embeddings serve only the clone gate (gates.py:51-66).
- **Already ruled or planned:** the M5 brief (§1.5; operating-brief.md:201); B1's minimal brief for the backtest before review #1 (controls plan:59); B2's up to 3 market lines after #1 (:74).

### Change (after review #1): complete the M5 brief
| Slot | Count | Found by | Shown to the model as |
|---|---|---|---|
| target | 1 | the cell, or the seed | cell enums or seed text |
| principles | 2–3 | M7 predictive only; ranked by meaning | P1–P3 (opaque) |
| atoms | 2–4, from 2+ titles and 2+ media when available | exact field, ranked by meaning | A1–A4 (opaque) |
| nearest titles | up to 10 | structural overlap, then meaning | title id + logline |
| failure patterns | up to 3 | region graveyard rows + v1.8 failure_patterns + P4 anti_patterns | `fp.<title_id>.<kind>` |
| absence facts | up to 2 | zero pairs under adequate coverage | `gap.<a>+<b>`, n = 0 |
| steering rules | all active in scope | the library | `rule.nnn` |
| operator | 1 | the rotation | its name |
| market lines (B2) | up to 3 | snapshot counts | snapshot record ids |

- **Ids:** every item carries its record id. Atoms and principles show opaque aliases (the M5 ruling), and the brief record maps each alias to its real id.
- **One assembler, three users:** generate, the B1 backtest judge, and baseline 1's empty brief (A5).
- **Format:** JSON (v1.7 compact input), capped at about 900 words, tokens logged. Retrieval and id checks: §7.2.

### Prompts, records, commands
| Kind | Item |
|---|---|
| Prompt | generate: the input is the JSON brief; list the ids you used in `brief_refs_used` |
| Record | `brief` (§7.1); cards gain `brief_id` and `brief_refs_used` (real ids) |
| Code | `ideate/brief.py`, the one assembler; config `ideate.brief` holds the caps |
| Make | `make brief ID=<idea_id>`: a plain page of the brief behind a card, gold titles masked |

### Gates, judge, archive
- **Gates:** unchanged. The clone gate still checks every title, not only the 10 shown.
- **H1 guard:** when the gate's measured nearest title differs from the card's `closest_existing`, the judge compares the card with both. A narrower brief must not make H1 easier.
- **Judge facts** use the same numbers as the novelty gate, and every absence claim still gets a prior-art check.
- **Archive and fitness:** unchanged. The brief is part of the user message, so the cache key covers it (run.py:313-321). **A6** reads `brief_refs_used`.

### Calls per idea
- **Assembly:** 0 model calls. Embeddings run on local Ollama, outside the call cap.
- **Per idea:** unchanged, about 1.3–1.5. Input tokens drop, since capped slots replace the full title and flop lists.

### ACs
- AC-IM-17: every generate call gets a JSON brief within its caps, never the full title and flop lists.
- AC-IM-18: every brief item resolves to a canonical record. An unresolved id stops the call before it is made.
- AC-IM-19: `brief_refs_used` holds only the brief's ids (one repair, then quarantine). Aliases map back to real ids on the card.
- AC-IM-20: the same canonical state and plan give the same `brief_id`.
- AC-IM-21: absence items are counts with the adequacy flag. No census entry id ever appears (AC-44).
- AC-IM-22: principles appear only once M7 marks them predictive. Before M7 the slot is empty and says so.
- AC-IM-23: with Ollama down, the command stops with the v1.7 message. With the mock embedder, briefs repeat exactly.

### Risks
- **The small embedder may miss a good atom.** Mitigation: exact fields pick the candidates and meaning only ranks them. Each item records its route, so misses can be inspected.
- **A narrow brief may breed clones of titles it doesn't show.** Mitigation: the clone gate checks every title, and the H1 guard adds the measured nearest title.
- **Briefs hold gold-title text.** Mitigation: `make brief` masks gold titles while the blind is pending.

## 5. Requirement 4: `animedex amplify <idea_id> --to <rung>`

### Today
- Nothing in code. The v1.6 concept-bible "develop step" (world rules, factions, 5-arc runway, cast engine, pilot hook, 3 key moments, world lint) is approved for after review #1 (CHANGE_PLAN_v1.6.md:96-102; operating-brief.md:143).
- B4 adds a serial-readiness rung (controls plan:96-100), and A8 flags must show in amplify output (:31). Storyboards are parked (operating-brief.md:165, 169); episode generation is an M8 non-goal (02:25).

### Change (after review #1)
Amplify is the approved develop step, reshaped as a ladder. It climbs one rung per step, text only:

| # | Rung | Writes | Exemplars (2–3, as mechanisms) from |
|---|---|---|---|
| 1 | kit | expands the card's kit: forms with triggers and costs, limits, creativity moves, evolution | v1.8 kit shapes (enums, counts) + P4 mechanisms of power atoms |
| 2 | set | set_structure, scaffold, member depth, subset mechanics, where the MC's power sits | v1.8 set fields |
| 3 | MC | origin, wound, want vs need, flaw, moral line, arc | v1.8 character enums |
| 4 | villain + thematic argument | villain type, relation to the MC, thesis, antithesis, resolution | v1.8 villain fields + thematic_argument |
| 5 | world | setting, visibility, conflict scale, up to 3 institutions | v1.8 world fields |
| 6 | engine + escalation | series engine, escalation model, how the cost scales | engine atoms (P4) + escalation_model |
| 7 | promise + hooks | audience promise, promise mechanism, 3 anticipation hooks | abstract layer; flops with promise_broken as anti-examples |
| 7b | serial readiness (B4) | three-chapter skeleton + 3 logline variants | as B4 specifies |
| 8 | pilot hook | hook type + the pilot's hook, 60 words or fewer | pilot_hook_type (M6 pilot structures later) |
| 9 | three key frames | 3 frames, 25 words or fewer each | moments (type + why it hit) |
| 10 | storyboard | 6–12 panel descriptions, text only | rung 9 + episode functions (M6) |

- **Climb:** from the highest passed rung up to `--to`, one rung at a time. Rejected cards and skipped rungs are refused.
- **Exemplars:** the brief assembler picks them from different titles. They go in as enum shapes plus name-free P4 text; names, character tools, moves and other free text never go in.
- **Check after each rung (codex):** consistent with the card and every rung above; uses exemplars as mechanisms, not surface copies; satisfies the steering rules.
- **Code checks after each rung:** names (v1.8 adds character names to the list), word caps, text only, and a copy check (embedding similarity to each exemplar's source text, with the threshold from the v1.7 recalibration).
- **Stop:** a failed rung gets one rework with the reason. A second failure stops the climb, and the rung record keeps why. The next `make amplify` on that card starts at that rung.
- **Output:** `build/reports/amplify/<idea_id>.md`, with A8 flags and gold exemplars masked.

### Prompts, records, commands
| Kind | Item |
|---|---|
| Prompt | `prompts/amplify_rung.md` 1.0.0: one prompt; the rung spec comes from config |
| Prompt | `prompts/amplify_check.md` 1.0.0 (codex) |
| Config | `amplify.rungs`: per rung, what to write, word caps, exemplar sources |
| Pass | `AMPLIFY` joins the pass list (models/common.py:101-103). A new pass needs your approval (operating-brief.md:58-59) |
| Slots | `amplify` (claude_cli, Opus 5.5, high) and `amplify_check` (codex_cli, gpt-5.6-terra, strict) |
| Record | `rung` (§7.1) |
| CLI, Make | `animedex amplify <idea_id> --to <rung>`; `make amplify ID=<idea_id> TO=world` |
| CQ | CQ-I19 "At which rung do climbs stop, and why?" |

### Gates, judge, archive
- **The card stays fixed.** Rungs never change its profile, cell, fitness or status, and a rung that implies another profile fails its check.
- **Rungs stay out of the archive, the packet and scoring.** `ideas.md` shows "amplified to: <rung>".
- **The check is its own codex prompt.** The ideation judge is untouched, and the stress tests stay card-level.
- **Budget:** amplify runs under the 60-call ideation cap and resumes from the cache.

### Calls per idea
- **Per rung:** 1 write + 1 check = 2 calls. With 4 cards at the same rung, they share the check: 1 + ¼ = 1.25.
- **One card to the top** (11 rungs, counting 7b): 22 calls, plus 10–20% reworks, about 24–26.
- **Four cards × 5 rungs:** 20 + 5 = 25 calls, about 28 with reworks.
- **Today, for comparison:** about 1.3–1.5 calls per card, all at premise level.

### ACs
- AC-IM-24: the climb goes one rung per step from the highest passed rung. Rejected cards and unknown rungs are refused.
- AC-IM-25: each rung gets 2–3 exemplars with ids, from different titles. A fixture exemplar's names and free-text tools never reach the prompt.
- AC-IM-26: a rung that leaks a name or copies an exemplar (similarity at or above the threshold) fails.
- AC-IM-27: a rung that contradicts a rung above fails. After one rework the climb stops, the record keeps the reason, and the next run resumes there.
- AC-IM-28: rungs never change the card's profile, cell, fitness or status and never reach a packet. Gold exemplars are masked in reports.
- AC-IM-29: rung schemas are text only: no image, URL or file fields, and no image model slot.
- AC-IM-30: steering rules and A8 flags apply at every rung.

### Risks
- **Cost:** a full climb takes almost half a run. Mitigation: climb one rung by default, share checks, and climb only champions or cards you rated 4 or higher.
- **Surface copying from exemplars.** Mitigation: mechanisms only, plus the copy and name checks.
- **Drift between rungs.** Mitigation: every check sees every rung above.
- **Thin exemplars for rungs 8–10 before M6** (no episode data yet). Mitigation: fall back to P1 moments and pilot_hook_type, and mark them "thin".
- **Scope.** The approved develop step (pilot hook, 3 key moments) covers rungs 8–9. The storyboard rung waits for the storyboards slot and stays text only.

## 6. Requirement 5: stress tests on every card

### Today
Runway is the only stress test (llm.py:148; run.py:418-419). P3 already has an ablation shape for atoms: `if_removed` (25 words or fewer) and a verdict of `load_bearing`, `supporting` or `decoration` (models/atoms.py:112-115).

### Change (after review #1): two more questions in the same judge call
1. **Idea ablation.** "Remove the twist (the card's what_changed). What's left, in 25 words or fewer? Does the story still work the same?" The verdict uses P3's scale:
   - `load_bearing`: the story stops working without the twist. It passes.
   - `supporting`: it passes, with a note.
   - `decoration`: the story works the same without it, so the twist is surface. It fails.
2. **Three key frames.** From the card alone, the judge writes 3 frames, 20 words or fewer each, no dialogue: the opening image, the power in use with its cost visible, and the dilemma. It passes if the frames carry the engine without adding new elements.

The card gains a `stress` block: ablation (if_removed, verdict) and key_frames (3 frames, pass, reason).

### Prompts, records, commands
- **Judge prompt:** its next minor version adds questions 6–7, and the schema adds both answers. **Card:** the `stress` block.
- **Commands:** none new; `make ideas` runs the tests. `ideas.md` shows the results; packets never do.
- **CQ:** CQ-I18 "Which operators and seed types fail which stress test?"

### Gates, judge, archive
- **Gates, not fitness (recommended):** a `decoration` verdict or failed frames get one rework, then a `stress:` rejection. They join run.py:414-420, as runway does.
- **Archive:** only cards that pass both are filed. Fitness is unchanged.
- **Baselines:** baseline 1 runs the same loop (A5), so it gets the same tests.

### Calls per idea
- **Tests:** +0 calls; they ride in the same judge call. Judge output grows about 70 words per card, so batches stay at 4 unless repairs rise.
- **Reworks:** 10–20% of judged cards × (1 + ¼) is +0.13–0.25, about 1.45–1.75 per idea.

### ACs
- AC-IM-31: the judge answers both tests for every judged card with no extra call (a call-count test).
- AC-IM-32: a `decoration` verdict gets one rework, then a `stress: ablation` rejection. A twist-free fixture fails.
- AC-IM-33: there are exactly 3 key frames, 20 words or fewer each, with no dialogue (the AC-11 guard). A fail gets one rework, then rejection.
- AC-IM-34: `stress` is stored on the card and shown in `ideas.md`, never in a packet.

### Risks
- **The judge may read ablation unevenly.** Mitigation: reuse P3's scale and its 25-word "if removed", and spot-check in reports.
- **Frames may reward spectacle.** Mitigation: they must show power, cost and dilemma, not action alone.
- **There will be fewer champions,** since these are two new rejection routes. After review #1, that is the point.

## 7. Cross-cutting

### 7.1 Data model
| Record | Where | Id | Fields |
|---|---|---|---|
| steering_rule | `steering/rules.yaml` (v1.8) | `rule.nnn` | text (30 words or fewer), hard or soft, 1–2 examples, optional check (field, in or not_in, values), applies_to (modes, seed types, rungs), status (active or retired), date added |
| seed | `data/canonical/seeds.jsonl` (after #1) | `seed.<type>.<sha8>` | seed_type; your text (150 words or fewer) or a ref (title id, pattern id, cell key); kind (real_system only); source file; first run used; provenance (no model) |
| brief | `data/canonical/briefs.jsonl` | `brief.<sha12>` | target (kind, value or ref); items (slot, id, alias, text of 25 words or fewer, route: exact, meaning or absence; score); caps; embedder; DuckDB build hash; tokens; provenance (no model) |
| rung | `data/canonical/rungs.jsonl` | `<idea_id>.r.<nn>` | rung; content (typed per rung, text only); exemplars (id, mechanism); check (consistent, copies_exemplar, rules_satisfied, reason of 25 words or fewer); status (passed, failed or stopped); reworked; provenance (pass AMPLIFY) |
| IdeaCard additions | `ideas.jsonl` | the card's id | seed (seed_id, seed_type, derivation); brief_id; brief_refs_used; rules (version, satisfied, failed); stress (ablation, key_frames) |

- **Stress results** live on the card, like `runway`, keyed by idea id. There is no separate record.
- **Additions are optional,** so existing cards stay valid and no migration is needed. New types join `RECORD_TYPES` (models/__init__.py:44-61).
- **No lens field or vocab value is added** (the lean rule, operating-brief.md:182). Seed types are a list in the models; rungs live in config.
- **AC-IM-35:** every new record and card block validates against its generated schema, and `make validate` and `make test` pass offline on the mock provider (AC-08).
- **AC-IM-36:** on a fake run, the calls per mode match §7.3 within ±20%.

### 7.2 Retrieval for the call brief
| Route | Source | Used for |
|---|---|---|
| Exact field (DuckDB, read-only, rebuilt by `make build`) | clone-gate structural sets (context.py:84-90); eligible transfers from `v_load_bearing`, `transfers`, `transfer_bridge` (duckdb_build.py:234-236, 266-270); `v_outcomes` (:271-274) + v1.8 failure_patterns and anti_patterns; M7 predictive pattern cards | nearest titles, atom candidates, failure patterns, principles |
| Meaning (Qwen3-Embedding-0.6B, local Ollama, v1.7) | query: the seed text, or for gap_cell the theme plus the target enums; corpus: each title's premise_abstraction (v1.8), each atom's pattern + mechanism + principle; vectors made fresh each run, never stored | ranks exact-field candidates; may add up to 2 titles the enums miss |
| Absence | zero pairs from the novelty gate's own counts, corpus plus census (context.py:84-101); only under adequate coverage (context.py:117); census-backed zeros only with 200 or more powered rows (operating-brief.md:202) | absence facts, as counts; no census entry is ever cited (AC-44, 08:48) |

- **Ids:** each id is checked against canonical data before the call. The schema lists the allowed ids for `brief_refs_used`, as it lists transfer ids today (llm.py:48), and a validator rejects anything else (one repair). Aliases (A1, P1) map back to real ids on the card.
- **Determinism:** items sort by score, then by id, so the same state always gives the same `brief_id`.

### 7.3 Budget per run
Ideation runs get 60 calls (operating-brief.md:205); other runs keep 40.

| Mode | Calls per idea | Per 60-call run | Arithmetic |
|---|---|---|---|
| gap_cell today | 1.3–1.5 | about 36 ideas (3 generations) | 3 × (12 + 3 + 0–3) = 45–54 |
| fight_image (M5) | 1.4–1.6 | about 36; a file of 10–15 fights fits in one run | the same shape, plus repairs |
| any seed + rules + stress (after #1) | 1.6–2.0 | 30–36 ideas | reworks add 0.25–0.5 per idea |
| call brief | +0 | no change | local embeddings |
| amplify, one card to the top | 24–26 | 2 cards | 11 rungs × 2, plus reworks |
| amplify, 4 cards × 5 rungs | about 7 | 4 cards | 20 + 5 + about 3 |
| `make recheck` | ¼ per champion | up to about 200 champions | ⌈n/4⌉ |

### 7.4 Order of work and estimates
| Step | Work | When | Needs | Days |
|---|---|---|---|---|
| 1 | M5 slice: gap_cell + fight_image, the packet share, fight images for both baselines | M4→M5 boundary | the M5 brief, A5, v1.8 kit fields (or the text fallback) | 1.5–2 |
| 2 | stress tests | after #1 | the judge prompt bump | 1 |
| 3 | steering in every mode: code checks, scopes, versions, recheck, commands | after #1 | the v1.8 steering file | 1 |
| 4 | complete the call brief: meaning, absence facts, rules, failure patterns, ids, brief records | after #1 | v1.7 embeddings, v1.8 fields, the M5 brief | 2 |
| 5 | seeds: user_concept, real_system, flop_revival, plus seed records | after #1 | step 4 | 1 |
| 6 | amplify rungs 1–9 and 7b | after #1 | steps 3–4, v1.8 characters | 3 |
| 7 | principle_id seeds; principles in the brief | M7 | predictive principles | 0.5 |
| 8 | storyboard rung (text) | the storyboards slot (after M6 and C) | step 6 | 0.5 |

- **Totals:** 1.5–2 days in M5; about 9 days after review #1.
- **If ANIMEDEX loses review #1,** doc 11's diagnosis comes first (11:45). Steps 2–4 may then become part of the fix.
- **Docs touched:** 02 (amplify rungs vs the M8 non-goal), 03 (flow), 04 (records, card blocks), 05 (commands, IDEATE and AMPLIFY contracts, config), 06 (steering and stress gates, the amplify stop rule), 08 (AC-IM-01 to AC-IM-36), 09 (packet share, seed-type split), 11 (new failure rows), CHANGELOG (v1.9).

### 7.5 Decisions for Kingsley (recommendations first; each takes a one-line answer)
**Before M5 (the item 1 slice)**

1. Should the slice be gap_cell + fight_image only, landing at the M4→M5 boundary? *Recommended.*
2. Should every arm of review #1 get the same fight images and the same fight-first share (up to 5 of 15)? *Recommended*: it's A5 fairness, and recognizing your own fight image then says nothing about the arm.
3. Will you write 10–15 fight images in your own words (no show or character names), one paragraph each, in `seeds/fights.txt`? *Recommended.*
4. Should fight-first keep the normal operator rotation, applied at the engine step, rather than a new operator? *Recommended*, since it needs no vocab change.
5. Should `steering/` and `seeds/` stay out of the public code repo (git-ignored, like the model outputs) and be backed up in the private data repo (`make data-push`)? *Recommended.* The alternative is committing your rules to the public repo.

**After review #1**

6. Build order: stress tests, then steering in every mode, the full brief, the other seeds, and amplify? *Recommended*: cheapest wins first.
7. Should a broken hard rule, a `decoration` ablation or failed key frames each get one rework and then rejection, as runway does, while soft rules never reject or change fitness? *Recommended.*
8. Ablation: "the story works the same without the twist" means `decoration`, which fails, and `supporting` passes with a note. Is that your reading?
9. Should the judge (codex) write the three key frames from the card alone? *Recommended*, as an independent test.
10. When rules change, should older champions just be flagged, with `make recheck` re-judging them only when you ask? *Recommended.*
11. Should principles in the brief, and principle_id seeds, wait for M7's predictive principles? *Recommended* (the v1.8 rule).
12. Should your own concepts (user_concept) stay out of every blind packet? *Recommended.*
13. Should amplify be the approved concept-bible develop step as a ladder, with B4's serial-readiness rung after promise and hooks, and a failed rung getting one rework before the climb stops? *Recommended.*
14. Should AMPLIFY become a new pass with two slots (Opus writes, codex checks) under the 60-call cap, with the storyboard rung text only and waiting for the storyboards slot? *Recommended.*

## Appendix: the request (Kingsley, 2026-09-27, verbatim)
> Write docs/implementation/proposals/CHANGE_PLAN_ideation_modes.md against the actual architecture. Plan only. Build after blind review #1, except item 1 (seed types), which may land in M5 if it's small, so review #1 includes fight-first ideas.
>
> Requirements:
> 1. Seed types for `make ideas`: gap_cell (current), fight_image (a choreography description), principle_id, real_system (text), flop_revival (title_id), user_concept (my own idea). Fight-first derives medium → functions → kit → set → MC edge and cost → engine → premise, in that order, and records the derivation chain on the card.
> 2. A steering library: my rules stored as records and applied as hard constraints in every mode; each card lists "rules satisfied."
> 3. Brief assembly: each generate call gets a small assembled brief: the target, 2–3 predictive principles, 2–4 atoms from different titles and media, the nearest existing titles, failure patterns in that region, my steering rules, and the operator. Every item carries its record ID. Retrieval by exact field, by meaning (embeddings over premise abstractions and atoms), and by absence.
> 4. `animedex amplify <idea_id> --to <rung>`: climbs the concept ladder one rung at a time (kit → set → MC → villain and thematic argument → world → engine and escalation → promise and hooks → pilot hook → three key frames → storyboard), pulling 2–3 exemplars per rung as mechanisms, never surface copies, checking consistency with the rungs above, and stopping at any rung that fails a check.
> 5. Two stress tests on every card: idea ablation (remove the twist; does it still work?) and the three-key-frames test.
>
> The plan must state, for each requirement: what exists today and what changes; which prompts, records, and commands are added or modified; how it interacts with the gates, the judge, and the MAP-Elites archive; the cost per idea in calls; ACs; and risks. First, answer in the plan: what context the generate call receives today, how the target cell is chosen, how operators are applied, and what the judge sees.
