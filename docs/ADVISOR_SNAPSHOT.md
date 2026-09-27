# ANIMEDEX advisor snapshot

**As of:** 2026-09-27, main `5be85a3` (tag `m2-complete`), repo `Kingsley-Cyber/animedex` (public).
**What it is:** a batch pipeline that turns a list of screen titles into idea cards for new anime concepts. It profiles each title and checks facts on the web. Then it explains why the title works, checks those explanations, abstracts transferable patterns, and evolves new premises in a quality-diversity archive (MAP-Elites). The ideas are rated blind against two baselines.
**Rules for this document:** no code bodies, no secrets, and no gold-title model output (the blind test is pending). Counts and structure only.

---

## 1. Repo tree (2 levels)
| Path | Purpose |
|---|---|
| `src/animedex/` | The Python package. `cli.py` is the Typer CLI, entry point `animedex`. |
| `src/animedex/pipeline/` | Stages: p1, verify, canonicalize, p2, p3, check, p4, orchestrate (`run`), census, partners, common helpers. |
| `src/animedex/providers/` | LLM access: `client.py` (cache, budget, pacing, repair, run log), `claude_cli.py` and `codex_cli.py` (subscription CLIs), `cli_common.py`, `factory.py`, mock and API adapters. |
| `src/animedex/ideate/` | Ideation loop: context, gates, llm (prompts and schemas), run (MAP-Elites), report, blind packet, review page. |
| `src/animedex/analyze/` | CQ queries over DuckDB (`cq.py`), graveyard, lanes, determinism check. |
| `src/animedex/build/` | Builds DuckDB from canonical JSONL. |
| `src/animedex/catalog/` | AniList client, title resolver, backfill planning. |
| `src/animedex/models/` | Pydantic data contracts (04): title, evidence, atoms, ideation. |
| `src/animedex/store/` | Atomic writes, response cache, canonical store (all-or-nothing writes), run logs, quarantine. |
| `src/animedex/embeddings/`, `search/` | Local embedder (Ollama) and search backends (native web search is the default). |
| `src/animedex/*.py` | Budget, guards (blind and live), content guards (AC-11), eligibility, integrity, evaluation, timing, batch runner, migrations, validate. |
| `config/` | `settings.yaml`: providers, model slots, caps, thresholds (section 5). |
| `corpus/` | `titles.yaml`: 14 titles with scopes. `queue/`: backfill lists. |
| `ontology/` | `vocab.json` (enums and P1 lens), `bridge.json` (9 bridge concepts), `competency_questions.yaml` (33 CQs), `migrations/`, `proposals/` (hand-written plans are tracked; generated proposals are git-ignored). |
| `prompts/` | One file per pass with a versioned header. `p1_modules/` holds the per-module lens text. |
| `schemas/` | JSON Schemas generated from the models (`animedex schemas`). |
| `data/` | Git-ignored pipeline data: `canonical/` (source of truth), `candidates/`, `cache/`, `raw/runs/` (every request and response), `quarantine/`. |
| `eval/` | `gold/` (annotation templates, `BLIND.yaml`, the gold-set proposal), `agreement/` (AC-12 second runs; ignored), `blind/` (review packets; ignored), `regression/`. |
| `batches/` | Batch files for detached runs (`make batch`). |
| `docs/implementation/` | Spec 00–12, CHANGELOG, `proposals/` (change plans), `reports/` (milestone reports M0–M2). |
| `tests/` | `unit/`, `pipeline/`, `contract/`, `fixtures/`: 292 tests, all synthetic data. |
| `.control/` | URCP harness: the `policies/operating-brief.md` owner rulings and the `tasks/issues.jsonl` Beads export. |
| `build/` | Git-ignored generated reports: timing, verify rates, analysis, batch status. |

## 2. Pipeline stages
Model slots are listed in section 5. Status: **live** means run on real titles; **implemented** means code and tests exist but it hasn't run live; **stub** means not built.

| Stage | Command | Inputs → outputs | Slot | Prompt (version) | Status |
|---|---|---|---|---|---|
| P1 WHAT | `animedex p1 --title ID / --all` (`--agreement` for the AC-12 second run; `--replay` rebuilds from the stored draft with no call) | corpus entry → title profile, 3–5 moments, verify list (candidates) | p1 | `p1_what` 1.2.0 + `p1_example` 1.1.0 + `p1_modules/*` 1.0.0 | live, 14 titles |
| VERIFY | `animedex verify` (`--outcome-only`) | P1 candidate + verify list → web-checked fields and moments, outcome record | verify (+ WebSearch/WebFetch) | `verify_native` 1.3.0 | live, 14 titles |
| CANONICALIZE | `animedex canonicalize` | candidates → `data/canonical/*.jsonl` (validated, referential, content-guarded, all-or-nothing) | — | — | live |
| P2 WHY | `animedex p2` | canonical title + moments → mechanism atoms (effect and engine) | p2 | `p2_why` 1.0.0 | implemented |
| P3 PROOF | `animedex p3` | atoms + partner titles → proofs (ablation, contrast, explanation test) | p3 | `p3_proof` 1.0.0 | implemented |
| CHECK | `animedex check` | atoms and proofs → verdicts (ACCEPT/REVISE/REJECT/CONTESTED/NEEDS_ADJUDICATION) | check (non-Claude, strict) | `check` 1.0.0 | implemented |
| P4 TRANSFER | `animedex p4` | eligible atoms → transfer atoms (pattern, bridge, essential/variable/failure conditions) | p4 | `p4_transfer` 1.0.0 | implemented |
| RUN | `animedex run` | P2 → P3 → CHECK → P4 per title, one fresh retry for P1/VERIFY quarantines | as above | — | implemented |
| EP / ROLLUP | `animedex ep`, `animedex rollup` | episode indexing and rollup (M6) | ep, rollup_match | — | stub (parked) |
| BUILD / ANALYZE | `animedex build [--verify-determinism]`, `make analyze` | canonical → DuckDB → CQ answers, graveyard, lanes, `build/reports/analysis.md` | — | — | implemented (runs on current data) |
| CENSUS | `animedex census --top N` or `--list` | AniList popular list → counts-only power-system rows | census | `census` 1.0.0 | implemented |
| IDEATE | `animedex ideate` / `make ideas` | canonical + archive → idea cards, archive, prior-art checks, `build/reports/ideas.md` | ideate_generate, ideate_judge, prior_art | 1.0.0 / 1.0.0 / 1.1.0 | implemented (needs M3 atoms) |
| PACKET / REVIEW | `make packet`, `make review` | champions + 2 baselines → blind packet; localhost rating page → `eval/blind/ratings_<date>.yaml` | ideate_generate (baselines) | `baseline_plain` 1.0.0, `baseline_web` 1.1.0 | implemented |
| BACKFILL | `make backfill LIST=<file>` | title list → resolved corpus entries (AniList/TVmaze), then the pipeline for up to 8 pending titles | — | — | implemented, not run on the queue |
| Support | `eval`, `validate`, `schemas`, `migrate --to`, `smoke`, `timing`, `batch start/run/status`, `gold-init/status` | reports, checks, detached batches | — | — | implemented |

**Prompt files:**

| Prompt file | Pass | Version |
|---|---|---|
| `prompts/baseline_plain.md` | IDEATE | 1.0.0 |
| `prompts/baseline_web.md` | IDEATE | 1.1.0 |
| `prompts/census.md` | CENSUS | 1.0.0 |
| `prompts/check.md` | CHECK | 1.0.0 |
| `prompts/ideate_generate.md` | IDEATE | 1.0.0 |
| `prompts/ideate_judge.md` | IDEATE | 1.0.0 |
| `prompts/p1_example.md` | P1 | 1.1.0 |
| `prompts/p1_modules/anime_production.md` | — | 1.0.0 |
| `prompts/p1_modules/comedy_satire.md` | — | 1.0.0 |
| `prompts/p1_modules/core.md` | — | 1.0.0 |
| `prompts/p1_modules/film.md` | — | 1.0.0 |
| `prompts/p1_modules/power_combat.md` | — | 1.0.0 |
| `prompts/p1_modules/relationships.md` | — | 1.0.0 |
| `prompts/p1_modules/sensory.md` | — | 1.0.0 |
| `prompts/p1_modules/series_engine.md` | — | 1.0.0 |
| `prompts/p1_what.md` | P1 | 1.2.0 |
| `prompts/p2_why.md` | P2 | 1.0.0 |
| `prompts/p3_proof.md` | P3 | 1.0.0 |
| `prompts/p4_transfer.md` | P4 | 1.0.0 |
| `prompts/prior_art.md` | IDEATE | 1.1.0 |
| `prompts/verify_native.md` | VERIFY | 1.3.0 |
| `prompts/verify_web.md` | VERIFY | 1.2.0 |

## 3. Canonical records (`data/canonical/`)
Every record carries `provenance` {run_id, pass, model, prompt_version, schema_version, vocab_version, cache_key, created_at}. Rows are counted as of this snapshot.

| File | Record | Rows now | Fields (type or enum) |
|---|---|---|---|
| `titles.jsonl` | title | 14 | see below |
| `moments.jsonl` | moment | 65 | `conf` number; `description` string; `locator` MomentLocator{episode, episode_id, season, timestamp}; `moment_id` string; `moment_type` {transformation, reveal, sacrifice, first_victory, power_up, defeat, reversal, reunion, other}; `source_ref` string?; `title_id` string; `verification` {not_required, unverified, web_confirmed, web_corrected, derived_from_episodes, unresolved}; `why_it_hit` string |
| `outcomes.jsonl` | outcome | 14 | `confounders` Confounders{budget_signal, platform, release_context, source_popularity, studio}; `failure_evidence` string?; `failure_evidence_ref` string?; `failure_level` {premise, execution, external, unknown}?; `failure_level_source` {verify, owner, migration}?; `failure_reason` string?; `label` {hit, mixed, flop}; `signals` list[Signal{metric, source_ref, value}]; `title_id` string |
| `mechanisms.jsonl` | mechanism | 0 | `atom_id` string; `atom_kind` {effect, engine}; `conf` number; `effect` Effect{because, element, element_ref, feeling, rival_because}?; `engine` Engine{agent, benefit, constraint, cost, dilemma, dramatic_question, feeling, goal, strategy}?; `epistemic` string; `evidence_refs` list[string]; `explanation` {settled, contested}; `module` string; `origin` {p2, promoted_from_episodes}; `support` Support{contradicting_episodes, reframing_episodes, status, supporting_episodes}; `title_id` string |
| `proofs.jsonl` | proof | 0 | `ablation` Ablation{conf, if_removed, verdict}; `atom_id` string; `contrast` list[Contrast{difference, partner_has, partner_role, partner_title_id}]; `explanation_test` ExplanationTest{favors, note, via_partner}? |
| `checks.jsonl` | check | 0 | `reasons` list[{unsupported, overreach, merged_claims, off_vocab, contradiction, circular, granularity, scope_leak}]; `revision` object?; `target_id` string; `target_type` {mechanism, proof}; `verdict` {ACCEPT, REVISE, REJECT, CONTESTED, NEEDS_ADJUDICATION} |
| `transfers.jsonl` | transfer | 0 | `atom_kind` {effect, engine}; `bridge` list[{borrowed_system, broken_rule, unserved_appetite, visible_progress_counter, cost_of_advancement, access_gate, core_tension, information_asymmetry, bond_as_power}]; `essential_conditions` list[string]; `failure_conditions` list[string]; `pattern` string; `source_atom_id` string; `transfer_id` string; `variable_details` list[string] |
| `episodes.jsonl` | episode | 0 | `atom_support` list[AtomSupport{atom_id, note, relation}]; `decisions` list[Decision{actual, agent, choice, expected, goal, options, rejected}]; `end_hook` {threat_cliffhanger, reveal_cliffhanger, open_question, power_tease, emotional_resolution, none, other}; `engine_beat` EngineBeat{advances, engine_atom_id, note}?; `episode_id` string; `function` {pilot_hook, setup, escalation, reversal, revelation, payoff, respite, closure, other}; `info_shift` InfoShift{audience_learns, characters_learn, gap_change}; `locator` EpisodeLocator{episode, episode_title, numbering, season}; `moment_refs` list[string]; `payoffs` list[Payoff{payoff, setup_episode_id}]; `proposed_atoms` list[ProposedAtom{atom_kind, draft}]; `selection_reason` {pilot, moment, finale, control}; `setups` list[string]; `source` string; `source_ref` string; `summary` string; `title_id` string; `verification` {web_confirmed, unresolved} |
| `links.jsonl` | link | 0 | `evidence` string; `from_id` string; `link_id` string; `title_id` string; `to_id` string; `type` {sets_up, pays_off, reveals, reframes, advances, supports, contradicts, enables, prevents} |
| `patterns.jsonl` | pattern | 0 | `alternative_explanations` list[string]; `boundary_conditions` list[string]; `counterexamples` list[Counterexample{title_id, why}]; `pattern_id` string; `scope` {title, corpus_subset, corpus}; `statement` string; `supporting_titles` list[string]; `transfer_ids` list[string] |
| `coverage.jsonl` | coverage | 14 | `episode_backed_share` number; `episodes` EpisodeCounts{in_scope, indexed, selection, unsourced}; `field_completion` number; `modules_active` list[string]; `passes_done` list[{P1, VERIFY, P2, P3, CHECK, P4, EP, ROLLUP}]; `title_id` string; `verified_share` number |
| `ideas.jsonl` | idea | 0 | `appetite` string; `atoms_used` list[string]; `borrowed_from` list[string]; `bridge` list[{borrowed_system, broken_rule, unserved_appetite, visible_progress_counter, cost_of_advancement, access_gate, core_tension, information_asymmetry, bond_as_power}]; `broken_rule` string; `closest_existing` string; `consequences` Consequences{choices, outcomes, relationships}; `engine` IdeaEngine{benefit, constraint, cost, dilemma, dramatic_question, goal, strategy}; `gates` Gates{coherence, consequence_test, failure_conditions_triggered, graveyard_hits, novel_combo, premise_cosine_max, procedural_jaccard_max, structural_jaccard_max}; `generation` integer; `grid_cell` string; `human_rating` HumanRating{criteria, greenlight, rating}?; `idea_id` string; `logline` string; `parent_ids` list[string]; `premise` string; `premortem` list[PremortemItem{mitigation, risk, source_title_id}]; `profile` IdeaProfile{cost_of_power, fight_medium, gate, power_is, progression, visible_counter}; `revival_of` RevivalRef{failure_evidence_ref, improvement, title_id}?; `runway` Runway{hurts_by_arc5, reason}?; `status` {candidate, champion, rejected}; `target_domain` string; `taste` Taste{criteria_met, evidence, hard_fail}; `theme_root` string; `transformation` Transformation{operator, source_transfer_ids, what_changed}; `why_different` string?; `why_not_a_clone` string |
| `archive.jsonl` | archive | 0 | `cell_key` string; `fitness` list[number]; `generation` integer; `idea_id` string; `replaced_idea_id` string? |
| `prior_art.jsonl` | prior_art | 0 | `check_id` string; `claim` string; `claim_kind` {T1, T4, lane}; `counterexamples` list[Counterexample{match_note, title, url}]; `queries` list[string]; `subject_id` string; `verdict` {clear, counterexample, inconclusive} |
| `census.jsonl` | census | 0 | `batch_id` string; `borrowed_system` {game, exam_or_school, job_or_bureaucracy, market_or_economy, sport, social_rating, law_or_contract, card_or_collection, crafting_or_cooking, military_rank, ritual_or_religion, none, …+1}?; `census_id` string; `cost_of_power` {physical_toll, lifespan, memory, identity_or_humanity, relationships, resource, moral, none, other}?; `fight_medium` {unarmed, weapon, energy, summon, vehicle_or_mech, mixed}?; `format` string; `gate` {innate, trained, inherited, contract, system_granted, artifact, death_or_ritual, mutation, none, other}?; `has_power_system` boolean?; `medium` {anime, donghua, western_animation, adult_animation, live_action, film}; `popularity` integer?; `power_is` {individual, paired, collective}?; `progression` {lateral, linear, hybrid, none}?; `title` string; `trust` string; `visible_counter` {numeric_level, rank_tier, collectible_count, transformation_stage, none, other}?; `year` integer? |

**Title profile (`titles.jsonl`):** the top-level keys are `anime_production`, `comedy_satire`, `core`, `film`, `format`, `medium`, `modules_active`, `power_combat`, `relationships`, `role_tags`, `scope`, `sensory`, `series_engine`, `title`, `title_id`, `year`. Each lens block (`core` plus the active modules) maps field names to a **FieldValue**:
- `value`: an enum value, or a phrase within the field's word cap, or null
- `conf`: 0–1
- `uncertainty_reason`: ≤15 words; required when conf < 0.7
- `condition`: flaw and moral_line only, ≤15 words
- `source`: recall | web | episodes
- `verification`: not_required | unverified | web_confirmed | web_corrected | derived_from_episodes | unresolved
- `source_ref`: URL
- `epistemic`: observed | derived | interpretive | external_metric

The lens fields are listed in section 4.

## 4. Ontology
### Enum fields (`ontology/vocab.json`)
- **vocab 1.4.0** (24 enum fields).
- `medium`: anime, donghua, western_animation, adult_animation, live_action, film
- `format`: film, episodic, serialized, hybrid
- `scope.numbering`: broadcast, streaming, home_video
- `power_combat.progression`: lateral, linear, hybrid, none
- `power_combat.gate`: innate, trained, inherited, contract, system_granted, artifact, death_or_ritual, mutation, none, other
- `power_combat.cost_of_power`: physical_toll, lifespan, memory, identity_or_humanity, relationships, resource, moral, none, other
- `power_combat.visible_counter`: numeric_level, rank_tier, collectible_count, transformation_stage, none, other
- `power_combat.fight_medium`: unarmed, weapon, energy, summon, vehicle_or_mech, mixed
- `relationships.power_is`: individual, paired, collective
- `core.outcome`: hit, mixed, flop
- `atom_kind`: effect, engine
- `feeling`: awe, triumph, dread, grief, catharsis, superiority, curiosity, tension, humor, warmth, disgust, other
- `explanation`: settled, contested
- `support.status`: profile_only, episode_backed, mixed, contradicted
- `moment_type`: transformation, reveal, sacrifice, first_victory, power_up, defeat, reversal, reunion, other
- `episode.selection_reason`: pilot, moment, finale, control
- `episode.function`: pilot_hook, setup, escalation, reversal, revelation, payoff, respite, closure, other
- `episode.end_hook`: threat_cliffhanger, reveal_cliffhanger, open_question, power_tease, emotional_resolution, none, other
- `info_shift.gap_change`: widens, narrows, flips, none
- `link.type`: sets_up, pays_off, reveals, reframes, advances, supports, contradicts, enables, prevents
- `transformation.operator`: reverse_incentive, redistribute_knowledge, transfer_cost, change_rule, combine_mechanisms, import_lane, revive_execution_flop, borrow_system
- `anime_production.demographic`: shonen, seinen, shojo, josei, kodomo, other
- `anime_production.source_medium`: manga, light_novel, web_novel, webtoon, manhua, original, game, other
- `outcome.failure_level`: premise, execution, external, unknown

### P1 lens (fields per block; kinds; caps)
- Default phrase cap `lens.phrase_max_words` = 15 words; fields marked (20) allow 20.
- **core** (19): logline_hook [phrase (20)], core_question [phrase (20)], premise_engine [phrase (20)], primary_feeling [phrase], tone [phrase], want_vs_need [phrase (20)], flaw [phrase (conditional)], moral_line [phrase (conditional)], central_opposition [phrase], opposition_logic [phrase (20)], stakes_clock [phrase (20)], world_rules [phrase (20)], borrowed_template [phrase], broken_rule [phrase (20)], unserved_appetite [phrase], central_mystery [phrase (20)], knowledge_gap [phrase (20)], reveal_cadence [phrase], outcome [enum]
- **power_combat** (8; activation judgment): power_source [phrase], gate [enum], progression [enum], cost_of_power [enum], visible_counter [enum], ranking_ladder [phrase], fight_medium [enum], signature_technique [phrase]
- **relationships** (5; activation judgment): core_bond [phrase], rival [phrase], mentor [phrase], team_structure [phrase], power_is [enum]
- **sensory** (4; activation rule: medium in ['anime', 'donghua', 'western_animation', 'adult_animation']; module power_combat): power_visual_signature [phrase], choreography_style [phrase], color_motif [phrase], animation_signature [phrase]
- **anime_production** (4; activation rule: medium in ['anime']): source_medium [enum], demographic [enum], arc_cour_structure [phrase], adaptation_fidelity [phrase]
- **series_engine** (5; activation rule: format not in ['film']): episodic_vs_serialized [phrase], status_quo_reset [phrase], episode_template [phrase (20)], season_arc_shape [phrase], cliffhanger_cadence [phrase]
- **comedy_satire** (1; activation judgment): comedic_engine [phrase]
- **film** (4; activation rule: format in ['film']): act_structure [phrase], runtime_compression [phrase], set_pieces [phrase], closure [phrase]

### Bridge concepts (`ontology/bridge.json`)
- bridge 1.1.0 (9 concepts): borrowed_system, broken_rule, unserved_appetite, visible_progress_counter, cost_of_advancement, access_gate, core_tension, information_asymmetry, bond_as_power

### Competency questions (`ontology/competency_questions.yaml`)
CQ set 1.6.0 (33 questions). Query column: a DuckDB query exists in `analyze/cq.py`.

| ID | Question (one line) | Query |
|---|---|---|
| CQ-G01 | Which gate x cost-of-power combinations have zero titles, given adequate coverage? | yes |
| CQ-G02 | For each empty cell, untried or tried by a mixed/flop title? Was that failure premise-level or execution-level, and what was the recorded reason? | yes |
| CQ-G03 | Which unserved appetites (and the borrowed templates and broken rules that served them) appear in hits but in only one title's load-bearing atoms? | yes |
| CQ-G04 | Which progression types have never been paired with a given fight medium? | yes |
| CQ-G05 | Which load-bearing patterns appear in >= 2 non-anime titles and 0 anime titles? (imported lanes) | yes |
| CQ-G06 | Which load-bearing anime patterns never appear in Western media? (export lanes) | yes |
| CQ-G07 | Where is coverage too thin to trust a zero? | yes |
| CQ-G08 | Which tone x premise-engine combinations are unused in battle anime? | yes |
| CQ-G09 | Which source mediums, demographics, and adaptation-fidelity levels cluster among hits vs. flops, with confounders shown? | yes |
| CQ-I01 | Which load-bearing transfer atoms share a bridge concept but come from different media? | yes |
| CQ-I02 | Which pairs of load-bearing atoms both appear in hits but never co-occur? | yes |
| CQ-I03 | For a chosen theme (core_question), which power gates have never embodied it? | yes |
| CQ-I04 | What is the nearest existing title to a candidate idea, by structural overlap and logline/premise similarity? | yes |
| CQ-I05 | Does a candidate's key combination match a flop's load-bearing combination? | yes |
| CQ-I06 | Which information-economy patterns (central mystery x knowledge gap x reveal cadence) have never been used with a visible power counter? | yes |
| CQ-I07 | Which relationship structures (power_is = paired/collective; core bond, rival, mentor, team structure) are unused in battle anime? | yes |
| CQ-I08 | Which comedic engines from Western/adult animation have never been paired with a power ladder? | yes |
| CQ-I09 | Which film structures (act structure, runtime compression, set pieces, closure) could compress into a single anime arc or cour? | yes |
| CQ-I10 | Which character and world structures (want vs. need, flaw and its condition, moral line and its condition, opposition and its logic, stakes/clock, world rules) recur in hits' load-bearing atoms? | yes |
| CQ-I11 | Which engine atoms from hits (goal, constraint, strategy, cost, dilemma) have never been combined with a given gate or cost of power? | yes |
| CQ-I12 | For a transfer pattern, which variable details have only ever taken one value across the corpus? | yes |
| CQ-I13 | Which transformation operators produce champions, and which mostly fail gates? | yes |
| CQ-G10 | Which power gate x cost-of-power cells are empty across the whole census (catalog-wide), not just the deep corpus? | yes |
| CQ-I15 | Which "never done" and lane claims survived the prior-art web check, and which met a counterexample? | yes |
| CQ-I14 | Which execution-level failures offer a T5 "retold better" lane (a sound premise whose execution failed)? | yes |
| CQ-E01 | Which moment types recur across the most iconic fights, and what mechanism and primary feeling explain each? | yes |
| CQ-E02 | Which pilot structures (function, end hook, information shift) precede hits vs. flops? (M6) | yes |
| CQ-E03 | For an iconic fight, what are its power rules, choreography, and visual signature? (fight brief) | yes |
| CQ-E04 | Which series engines (episodic vs. serialized, reset, episode template, cliffhanger cadence, season arc shape) pair with hits in each medium? | yes |
| CQ-E05 | Does each title's engine run in ordinary (control) episodes, or only in highlight episodes? (M6) | yes |
| CQ-E06 | How far apart are setups and payoffs, and which setups stay unresolved? (M6) | yes |
| CQ-E07 | Which show-level atoms are episode-backed, mixed, or contradicted? (M6) | yes |
| CQ-E08 | Which decision shapes (options, rejected alternative, expected vs. actual outcome) recur in hits' key episodes? (M6) | yes |

Some queries answer only part of their question: G03, G08, G09, I03 and I06–I12 return raw rows or leave the gap for M7, and the E-series waits for episode data (M6). See section 7.

## 5. Config (values only; `config/settings.yaml`)
- **Providers:**
  - `claude_cli` and `codex_cli`: subscription CLIs, 900 s timeout.
  - `local`: Ollama at `localhost:11434` (embeddings only).
  - `openai_compatible`, `anthropic`, `mock`: present but unused.
- **Model slots:**

| Slot | Provider | Model | Params |
|---|---|---|---|
| p1, verify | claude_cli | claude-sonnet-5 | effort high |
| p2, p3, ideate_generate | claude_cli | claude-opus-5-5 | effort high |
| p4, ep, rollup_match, eval_match | claude_cli | claude-haiku-4-5 | — |
| check, ideate_judge | codex_cli | gpt-5.6-terra | strict_model (no substitution) |
| prior_art, census | claude_cli | claude-sonnet-5 | — |
| embeddings | local (Ollama) | mxbai-embed-large | v1.7 plans a switch to `qwen3-embedding:0.6b` |

- **Budget:**
  - Call caps: 40 per run and 6 per title, with at least 5 s between calls.
  - Dollar caps (API only; subscriptions use call caps): $25 per run, $3 per title, $0.25 per episode.
  - Shadow cost is logged, never charged.
- **Search:** native (the model's own WebSearch/WebFetch).
  - The claude CLI blocks WebFetch on myanimelist.net.
- **VERIFY:**
  - Thresholds and limits: conf threshold 0.7; 3 searches per title, plus 2 for the outcome; 2 pages per search; turn limit = searches + fetches + 2.
  - Always verified: `core.outcome`, `sensory.*`, `moments.*.locator`. The owner rule narrows sensory and moment checks to gold titles.
  - No evidence retries. Two reception sources settle an outcome.
- **P2 / P3 / CHECK:**
  - P2: at most 15 atoms and 12 effect atoms; 1–3 engine atoms; alarm under 5 atoms.
  - P3: load-bearing alarm above 8, low flag under 3.
  - CHECK: reject-rate alarm at 0.30.
- **Coverage adequacy:** at least 5 titles with the module and field completion ≥ 0.8.
- **Episodes (M6):**
  - Selection: pilot, moment, finale, control. At most 6 episodes per title, 3 of them moment episodes.
  - A fetched source is required. Summaries ≤ 60 words; at most 2 decisions per episode.
  - Thresholds: match similarity 0.85, promote at 2, derive from 3, contradiction alarm 0.30.
- **Clone gates:** structural Jaccard ≥ 0.70 rejects; procedural Jaccard ≥ 0.75 rejects; premise cosine ≥ 0.90 rejects when structural ≥ 0.55.
- **Census:** batches of 10, 50 donghua, titles since 1995.
- **Ideation:**
  - Target domain anime (config value; the code hard-codes it). Grid: gate × cost_of_power × progression.
  - 8 operators. Judge batch 4. Seed 7.
  - H1 needs ≥ 2 of 3 dimensions changed.
  - 3 generations of 12 candidates each.
  - Diversity alarm: champion share 0.40, cell share 0.10.
- **Content guards:** a quote is 3+ words; 22 framing terms are banned in sensory fields.
- **Eval:**
  - Gold key fields: 6 power/relationship enums plus the outcome. Gold elements: 3–5.
  - Bars: P1 enum agreement 0.80, P3 load-bearing agreement 0.70, load-bearing recall 0.60.

## 6. Ideation loop (as implemented; M5 code, not yet run live)
- **Modules:**
  - `context.build_context`: rebuilds everything from canonical each run: the eligible atom pool, title structure sets, graveyard, lanes, pair counts, adequacy, themes, name list, census systems.
  - `gates.run_gates`: clone, then novelty, then graveyard.
  - `llm`: the generate, judge and prior-art prompts, schemas and validators.
  - `run.run_ideate`: plan → generate → gate → judge → rework → taste evidence → prior art → fitness → archive.
  - `report`: `ideas.md`, with gold titles masked.
  - `packet` / `review`: the blind packet and the rating page.
- **Pool:** transfers whose source atom is P3 load-bearing, with the latest CHECK = ACCEPT, explanation settled, and support profile_only or episode_backed.
- **Generate call (one card per call; Opus, effort high):**
  - The user message is **plain labelled text**, not JSON:
    1. `THEME ROOT`: a random canonical core_question.
    2. `OPERATOR` with its definition.
    3. `TARGET PROFILE`: the cell's gate, cost and progression.
    4. `PATTERNS`: 1–3 transfer atoms, each with transfer_id, pattern, bridge, essential/variable/failure conditions. The ids reveal the source title.
    5. Optional `FLOP TO REVIVE` (with its recorded failure) or `BORROWED SYSTEM`.
    6. `CORPUS TITLES`: every title with its logline_hook, uncapped.
    7. `MIXED AND FLOP TITLES`: every graveyard row with its failure level and reason, uncapped.
    8. Optional `REWORK` notes.
  - Not sent: title profiles beyond the logline, hit outcomes, census rows, gap counts, lanes, parent card text.
  - Output: strict JSON.
    - Text fields: logline, premise, what_changed, broken_rule, appetite, why_not_a_clone, why_different, revival_improvement.
    - Structured fields: engine (goal, constraint, strategy, benefit, cost, dilemma, dramatic question), source_transfer_ids (must equal the given set), consequences (choices, relationships, outcomes), and a 6-enum profile.
    - Links: closest_existing (enum of title ids) and a premortem of 2–3 items tied to graveyard ids.
- **Target cell:**
  - The grid is 9 gates × 8 costs × 4 progressions = 288 cells.
  - Each candidate aims at a random empty cell (any cell if none is empty), with repeats allowed. There is no weak-cell targeting.
  - The archive places the card by **its own** profile; the target is only a request.
  - The seed is `7:<generation>`.
- **Operators:** reverse_incentive, redistribute_knowledge, transfer_cost, change_rule, combine_mechanisms, import_lane, revive_execution_flop, borrow_system.
  - Eligibility:
    - revive needs an execution-level flop with evidence or an owner level, plus a hit engine atom;
    - borrow needs a census and a borrowable system never used;
    - import_lane needs a non-anime atom;
    - combine needs 2 source titles.
  - Assignment is a shuffled round-robin across the 12 candidates, with no weighting.
  - A 50% chance to seed from one random champion's atoms. No parent text is passed and there is no crossover.
- **Judge** (codex, batches of 4, plain text per card):
  - It sees: logline, premise, theme, operator and change, engine, consequences, profile, pattern texts and their failure conditions, the closest title's logline/engine/feeling/6 enums, and supplied facts (untried combination, adequacy, premise-level graveyard matches, lane concepts, revived flop).
  - It does not see: why_not_a_clone, why_different, the premortem, broken_rule, appetite, or the revival improvement.
  - It returns H1 (choices/relationships/outcomes differ, with reasons), the triggered failure conditions, coherence pass/fail, runway (does the cost still hurt by arc 5), and taste T1–T5 with evidence ≤25 words.
  - Applied as: H1 needs 2 of 3 changed dimensions; H1 or coherence fail rejects; triggered failure conditions or a failed runway earn one rework.
- **Prior art** (Sonnet + web, T1/T4 claims only, 4 claims per call; 4 searches, 6 fetches, 12 turns):
  - `clear` keeps the criterion.
  - A counterexample, inconclusive, or missing verdict **removes** the criterion.
  - There are no lane checks yet, and no T1→T2 fallback (the doc describes one).
- **Gates:**
  - **Clone:** structural Jaccard ≥ .70, procedural ≥ .75, or cosine ≥ .90 with structural ≥ .55. Cosine embeds the card's logline + premise against each title's logline + engine + core question. One rework allowed.
  - **Novelty:** passes on an unseen enum pair (with adequate coverage) or an unseen bridge-concept pair (atoms from 2+ titles). Otherwise reject, with no rework.
  - **Graveyard:** a premise-level mixed/flop match needs a non-blank `why_different`; the match rule is key subset plus Jaccard ≥ .5.
  - **Name-leak:** checks logline and premise.
- **Fitness (lexicographic):** human rating (always 0 today), passed, number of taste criteria, episode-backed atoms, then negative structural Jaccard.
- **Archive:** at most 1 champion per cell. A new card replaces the champion only when strictly better; the replaced one goes back to candidate.
- **Diversity alarm:** reports when top values hold more than 40% of champions. It is report-only; planning ignores it.
- **Calls:**
  - One shared budget covers generate, judge and prior art.
  - A clean generation takes about 12 + ⌈live/4⌉ + ⌈claims/4⌉ ≈ 15–18 calls, so about 2 generations fit under the 40-call cap.
  - A stop pauses cleanly (exit 3).
- **Idea card fields:** idea_id, target_domain, logline (≤30 words), premise (≤120), theme_root, engine{7}, transformation{operator, source_transfer_ids, what_changed}, consequences{3}, profile{6}, bridge, grid_cell, atoms_used, borrowed_from, broken_rule, appetite, closest_existing, why_not_a_clone, why_different, premortem[], revival_of, runway, gates{…}, taste{criteria_met, evidence, hard_fail}, status, generation, parent_ids, human_rating, provenance.
- **Blind packet:**
  - Arms: 15 top champions, a plain baseline, and a web baseline (the baselines use the ideate_generate slot).
  - Cards are shuffled and numbered C01….
  - The answer key goes to `data/blind/`.
  - Ratings are saved to `eval/blind/` and never written back into the cards.
- **Doc-vs-code gaps found (2026-09-27):**
  - Rating comes first in fitness (the doc puts it fifth).
  - No T1→T2 fallback.
  - No lane prior-art checks.
  - No "inverted broken rule" or "triple" novelty routes.
  - No episode-backed preference in atom picking.
  - The diversity alarm is report-only.
  - `target_domain` is hard-coded.

## 7. Analyze
- **Queries:** all 33 CQs have a DuckDB query. Answers go to `build/cq_answers/*.json`, with hashes.
- **Adequacy:**
  - A module is adequate when ≥5 titles have it with field completion ≥0.8.
  - G01 and G04 (power_combat) and I07 (relationships) mark zero answers as "open" or "insufficient coverage".
  - G07 lists adequate titles per module.
  - Ideation also accepts ≥5 powered census rows.
- **Graveyard:**
  - Contains mixed/flop titles and their failure level (default unknown).
  - Only premise-level rows warn. Execution-level rows are T5 evidence, used through the revive operator only.
- **Lanes:**
  - Imported: a bridge concept in ≥2 non-anime titles and 0 anime.
  - Export: in anime and in 0 Western titles.
  - Ideation recomputes lanes over its own pool.
- **Determinism:** `build --verify-determinism` rebuilds DuckDB from scratch and compares per-CQ hashes. It passes on M2 data.

## 8. Backfill and census
- **Resolver (AniList, TVmaze fallback for non-anime):**
  - A year in parentheses picks that version.
  - Otherwise the most-watched series wins; any series beats a film. Up to 4 alternatives are listed.
  - Direct TV sequels starting ≤5 years apart become seasons. The chain stops at unreleased or cancelled sequels (up to 8).
  - ALTERNATIVE, SPIN_OFF and SIDE_STORY titles go to `scope.exclude`.
  - CN origin → donghua. A film gets no seasons.
  - `title_id` = slug + year.
- **Backfill:**
  - Skips titles already in the corpus.
  - Pairs same-story versions as nearest neighbours.
  - Warns when the mix is all hits or all anime, and suggests flops, mixed titles and non-anime titles.
  - Appends to `corpus/titles.yaml`, then runs up to 8 pending titles per run.
- **Queue state:**
- `corpus/queue/donghua.txt`: 11 titles
- `corpus/queue/priority_1.txt`: 36 titles
- `corpus/queue/priority_2.txt`: 17 titles
  - Only the priority 1 list gets deep-indexed; that run is parked until blind review #1.
- **Census:**
  - Fields: has_power_system, gate, cost_of_power, progression, visible_counter, fight_medium, power_is, borrowed_system. v1.8 adds set_structure, story_engine and mc_archetype.
  - Batches of 10; counts only; trust "recall"; never feeds the atom pool.
  - `make census` = top 500 (450 anime + 50 donghua). It runs over about 2 runs because of the call cap.
  - Status: not run yet.

## 9. Eval so far (M2, recall-first baseline)
- **AC-12 P1 enum agreement on gold:** **0.7333** over 45 comparisons (5 of 5 gold titles); the bar is 0.80.
  - Per field: cost_of_power 0.2, progression 0.4, visible_counter 0.4, gate 0.8, demographic 0.8.
  - source_medium, outcome, fight_medium and power_is are 1.0.
  - The first runs used P1 prompt 1.1.0; the second runs used 1.2.0.
- **AC-13 VERIFY:** 232 field checks across 46 fields.
  - Results: 54 confirmed, 10 corrected, 168 unresolved.
  - Correction rate among settled checks: 0.16.
  - The most-flagged enums are cost_of_power (10 of 14 titles), progression (9) and visible_counter (7). They are mostly unresolved, and they are the same fields that fail AC-12.
- **Time per stage** (all M2 calls; 18 have a per-stage split):

| Stage | Calls | Total | Per call | Split (timed calls) | Retries |
|---|---|---|---|---|---|
| P1 | 62 | 1h 12m | 1m 10s | ~99% model; startup <1 s | 34 (27m 35s) |
| VERIFY | 23 | 1h 13m | 3m 12s | ~80% model, ~20% web | 5 (16m) |

- **Why P1 is slow:** at effort high, P1 writes about 2.5× the tokens of its answer (thinking).
- **Latest speeds:** the final batch took 9 steps in 9 minutes at 3 titles at once. Non-gold VERIFY takes about 2 minutes.
- **Quarantine rates:**
  - P1: 8 of 14 titles were quarantined at least once, all on older code (caps and module rules); all passed after the fixes.
  - VERIFY: 1 title, from URL parsing; fixed.
  - Canonicalize: 3 titles, dialogue false positives; fixed.
- **Tests:** 292 pass. `validate` is OK. The determinism build is identical.

## 10. Status
- **Milestones:**
  - Tagged and pushed: M0 (`m0-complete`), M1 (`m1-complete`), M2 (`m2-complete`). M2's AC-12 is gated on v1.7.
  - The M3–M5 code exists and is tested offline, but hasn't run live.
- **Branches:** `main` is the only authoritative branch. `autopilot/m2-m5`, `caps-per-field` and `batch-runner` are merged and exist locally only.
- **Change plans:**

| Plan | State |
|---|---|
| v1.2.1 / v1.2.2 | landed |
| v1.3 (`failure_level`) | landed; the outcome-only re-verify of older mixed/flop outcomes is optional |
| v1.5 Studio | planned, not built (parked) |
| v1.6 (census, prior art, IDEATE additions, 3-arm blind review, backfill) | code landed; census and prior art not run live |
| v1.6.1–v1.6.4 | landed: no-MAL rule; per-field word caps (vocab 1.4.0); no VERIFY retries plus gold-only visual/moment checks; dialogue-guard precision |
| v1.7 (gather-first P1, Qwen3 embeddings, compact context, measurement) | approved in principle; lands after M2, before M3 |
| v1.8 (concept, character, abstract layers; 36 fields, characters record) | requested; plan `CHANGE_PLAN_v1.8.md`; lands with v1.7 |
| Ideation modes (seed types, steering library, brief assembly, amplify, stress tests) | requested; plan pending; build after blind review #1 (seed types may land in M5) |

- **Open decisions:**
  - v1.8 plan: word caps, one combined 14-title run, canonical after comparison, INTERPRET model, steering brief format.
  - M2 report: the AC-12 gate, an effort A/B, reviewing 7 enum proposals after annotations.
  - URCP branch: push OK and one schema wording.
- **Parked until blind review #1:** request A, the dashboard (C), the Studio (B), M6, the storyboard spike, and the big backfill run.
- **Known issues:**
  - Input tokens are logged without cache reads.
  - Canonicalize is all-or-nothing per record type, so one bad title holds back every moment.
  - The IDEATE cache key omits the corpus lists.
  - The prior-art "Premise:" label carries the logline.
  - There are doc-vs-code gaps in section 6.
  - Jikan is down (504).

## 11. Corpus (`corpus/titles.yaml`; inputs only)
| Title id | Medium / format | Role tags | Scope | Pipeline status |
|---|---|---|---|---|
| `solo_leveling_2024` | anime / serialized | gold, hit | A-1 Pictures TV anime, seasons 1-2 (12 + 13 eps, 2024-25); broadcast numbers season 2 as 13-25; seasons 1–2 | P1+VERIFY canonical; M3 passes: none |
| `fullmetal_alchemist_brotherhood_2009` | anime / serialized | gold, hit | Bones TV series (64 eps, 2009-10); adapts the whole manga; seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `hunter_x_hunter_2011` | anime / serialized | gold, hit | Madhouse TV series (148 eps, 2011-14); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `sword_art_online_2012` | anime / serialized | mixed | A-1 Pictures TV series (25 eps, 2012); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `btooom_2012` | anime / serialized | gold, mixed | Madhouse TV anime (12 eps, 2012-10 to 2012-12); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `big_order_2016` | anime / serialized | flop | asread TV series (10 eps, 2016); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `platinum_end_2021` | anime / serialized | gold, flop | Signal.MD TV anime (24 eps, 2021-10 to 2022-03); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `future_diary_2011` | anime / serialized | contrast | Asread TV anime (26 eps, 2011-10 to 2012-04); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `jujutsu_kaisen_2020` | anime / serialized | contrast | MAPPA TV anime, season 1 (24 eps, 2020-10 to 2021-03); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `demon_slayer_kimetsu_no_yaiba_2019` | anime / serialized | contrast | ufotable TV anime, season 1 (26 eps, 2019-04 to 2019-09); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `mob_psycho_100_2016` | anime / hybrid | contrast | Bones TV anime, season 1 (12 eps, 2016-07 to 2016-09); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `avatar_the_last_airbender_2005` | western_animation / hybrid | contrast | Nickelodeon animated series, Book One: Water (20 eps, 2005); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `invincible_2021` | adult_animation / serialized | contrast | Amazon Prime Video animated series, season 1 (8 eps, 2021); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |
| `the_boys_2019` | live_action / serialized | contrast | Amazon Prime Video series, season 1 (8 eps, 2019); seasons 1–1 | P1+VERIFY canonical; M3 passes: none |

Gold set: Solo Leveling, FMA: Brotherhood and Hunter x Hunter (hits); Btooom! (mixed); Platinum End (flop). Their model outputs stay hidden until the annotations are done or waived.

## 12. Constraints in force
- **Providers:**
  - Only the subscription CLIs (`claude`, `codex`); no model API keys.
  - `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are stripped from every CLI subprocess.
  - Each call runs in an empty scratch directory with tools off (web tools only for VERIFY and prior art), user settings off, and no MCP servers or sessions.
  - Identity and version go into cache keys and provenance.
- **The one local model:** embeddings through Ollama. mxbai-embed-large today; Qwen3-Embedding-0.6B in v1.7. If Ollama isn't running, the run stops with a clear message.
- **No scraping of MyAnimeList:**
  - WebFetch on myanimelist.net is blocked, and MAL links are never admissible citations.
  - MAL numbers only through AniList, Jikan or MAL's official API.
- **Blind rules:**
  - Gold-title model output is never shown before annotations are done or waived; partner profiles likewise.
  - Reports show counts only and mask gold titles.
  - Model outputs are git-ignored (the repo is public).
- **Text rules:**
  - Paraphrase only: no transcripts, subtitles, dialogue or quotes.
  - Web page text is transient and never stored.
  - Stay inside each title's scope.
- **Change control:**
  - Vocab, contract and taste-standard changes need Kingsley's approval.
  - Scope is frozen until blind review #1. The lean rule applies: no new fields after v1.8.
  - No live run on code that is behind a known fix; milestones run in order, and each one's ACs are checked before the next consumes its output.
- **Budget:** 40 calls per run and 6 per title, 5 s pacing. Batches run at most 3 titles at once, pause on plan limits, and resume.
