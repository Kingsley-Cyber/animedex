# Changelog — docs/implementation

## Length repair for every stage — 2026-09-27
- **CHECK 1.2.0 (D-035).** The critic also gets the profile of every partner a proof compares against (the evidence P3 had). With 1.1.0 it still called all proofs of two titles unsupported, because it could not see the partners.
- **CHECK 1.1.0 (D-034).** The live M3 run showed three input defects: the critic never saw the moments atoms cite (so it rejected them as unsupported), read a proof's partner comparisons as scope leaks (all 12 of one title's proofs), and re-checked a revised proof without its atom. The critic now gets the title's moments, a scope rule that exempts what a proof says about partners, and `context` lines in the re-check round; verdicts on anything but the round's targets are ignored instead of failing the answer. CHECK re-runs on every title from the cached P2 and P3 outputs.
- **CHECK re-check fix.** A proof revised again in the re-check round no longer looks up its atom there (the round holds only revised targets); Btooom!'s CHECK crashed on it in the live M3 run.
- **D-030.** `providers/length_repair.py`: the client's last resort before quarantine. When the repaired output still fails only on word caps, one `<record>.shorten` call rewrites just the named texts; the result is validated again (guards included) and cached under the original key. P1 and INTERPRET keep their own earlier shorten step.

## v1.7 comparison — 2026-09-27
- **Report:** `reports/V17_COMPARISON.md`. Gather-first is 25% faster per title (6m 32s → 4m 54s), retries fell from 39 to 3, gold enum agreement rose from 0.73 to 0.96 on M2's fields, and 36% of values carry a web source (was 10%). The effort A/B keeps INTERPRET at medium (D-029).
- **`animedex eval`:** the recall-first P1 agreement line no longer compares gather-first gold profiles with recall-first second runs; it says it is superseded and points to the kappa gate.

## Grid axis — 2026-09-27
- **AC-12 on the grid (D-028).** The gather-first agreement eval over 14 titles failed only on `power_combat.cost_of_power` (raw 0.79, kappa 0.74). `ideate.grid_dims` is now gate × set_structure × progression; all three pass (1.0/1.0, 0.93/0.89, 1.0/1.0).
- **Idea profile.** `IdeaProfile` gains `set_structure` (so a card's cell is computable); the ANALYZE structural set, the backtest kit and the diagnose ablation carry it too. cost_of_power stays everywhere it was except the grid.
- **Docs:** 04 (idea profile, grid note), 05 (config). `schemas/idea.schema.json` regenerated; `schema_version` unchanged (no card has been written yet).

## Statistics as gates — 2026-09-27
Kingsley's ruling "statistics as gates" (operating brief): snapshots and counts only, no models; each statistic replaced the check it corresponds to inside its existing stage, and `animedex stats` is only a read-only summary. Offline: nothing here ran a live call. Items 2–8 and the page here; item 1's AC-12 kappa gate is in the agreement eval.
- **Reliability, consumer side (item 1).** `eval/agreement/reliability.json` (`{"fields": {path: {n, raw, kappa, unreliable, pass}}}`): a field flagged unreliable takes its gap questions out of the gap reports (`zeros_are: excluded: unreliable field`), never forms a novelty pair, and marks a grid cell's zeros untrusted in the brief. No file, no exclusion (D-021c).
- **Adequacy (item 2, 04, 05).** A zero is open only when 3/n < 0.02 (n ≥ 151): module zeros over the titles with the module and good completion, census-backed zeros (CQ-G10, CQ-G16, CQ-I23, `borrow_system`) over the powered census rows, ideation adequacy over both. Census rows still count only past the 200-row floor. `coverage.min_titles_with_module` is retired (D-021b).
- **Gap ranking (item 3).** CQ-G01, CQ-G04, CQ-G10 and CQ-G17 rank their empty cells by n × p(x) × p(y) (`gap_ranking`): expected ≥ 3 with none observed is a real gap, the rest unsurprising. `analysis.md` shows them.
- **Novelty (item 4, 04, 05).** PMI replaced "unseen pair": a card's key pair (profile values, or bridge concepts from 2+ titles) is novel at PMI ≤ −1.0 over more than 150 rows that could show it (D-021). `IdeaCard.gates` gains one optional field, `pmi_key_pair` (type in `models/novelty.py`); `ideas.md` shows it. T1 still needs zero co-occurrence. With 14 corpus titles no subset is adequate, so ideation novelty now needs the census.
- **Field health (item 5).** `analysis.md`: entropy, normalized entropy (low under 0.5) and mutual information with the outcome, per enum field.
- **Calibration (item 6, 05).** `make eval` adds the Brier score per field to `verify_rates.md`, using the confidence stored before any check (the P1/INTERPRET draft in the response cache; floored values counted when it is gone, D-022).
- **Taste (item 7).** `animedex review --summary` / `make review-report`: Bradley–Terry strengths per card and per arm from the ratings (higher wins, ties skipped) and `eval/panel/*.json` picks, and the judge's agreement with that ranking, to `build/reports/taste.md`. Counts only until every card is rated (D-022b).
- **Backtest (item 8, controls B1, 05).** `animedex backtest [--list FILE]` / `make backtest LIST=FILE`: held-out titles into `data/backtest/` (git-ignored; a corpus title is refused), GATHER + INTERPRET unchanged, then the judge predicts hit/mixed/flop from the premise abstraction and power kit with a blank brief and with the index brief (`prompts/backtest_predict.md` 1.0.0). Report: both accuracies, the difference, the exact McNemar p-value and the sample size needed (D-022c). Config `backtest: {batch: 5, neighbors: 5}`.
- **Summary page.** `animedex stats` / `make stats` writes `build/reports/stats.md` from `eval/agreement/reliability.json`, `build/stats/*.json` and the champions' key pairs, recomputing nothing model-dependent.
- **Docs:** 04 (adequacy, `gates.pmi_key_pair`), 05 (ANALYZE, novelty gate, VERIFY calibration, BACKTEST, STATS, the replaced-check table, config), 09 (statistics), USAGE (`make stats`, `make backtest`). `schema_version` is unchanged: the change is additive.

## M5 prep — 2026-09-27
Kingsley's "before M5 live runs" rulings (items 4–8), the accepted controls decision 1, controls A7 and A8, and the diagnose ruling. Offline only: nothing here ran a live call. ACs AC-50 to AC-57 (08).
- **Call brief (05 IDEATE, item 4).** Each generate call gets `key: value` lines, not every title and flop. The brief holds:
  - the plan's atoms under opaque aliases A1…, which cards map back to real transfer ids;
  - the nearest 10 titles by structural Jaccard;
  - the flops in the target region;
  - the cell's counts, lanes and recorded prior art;
  - the steering rules.

  It is capped at `ideate.brief_max_words` (600) and trimmed optional-lines-first; an over-cap brief is refused before the call. Its words and estimated tokens go in the run log (`meta.brief`). `ideate_generate` 2.0.0.
- **Novelty (item 5).** Census-backed enum zeros, and census-backed coverage adequacy, need `ideate.census_novelty_min_rows` (200) powered census rows. Until then novelty rests on bridge-concept pairs.
- **Judge (item 6).** On a premise-level graveyard match the judge weighs `why_different` against the flop's recorded failure (pass/fail with a reason). A fail gets one rework, then rejection. `ideate_judge` 1.1.0.
- **Fair baselines (item 7; controls A5, decision 1).** The arms are ANIMEDEX, baseline 1 (the same loop with an empty brief, `make ideas ARM=baseline_loop`) and baseline 2 (one call, `baseline_single.md` 2.0.0, renamed from `baseline_plain.md`).
  - Every arm shares one taste standard (`prompts/taste_standard.md` 1.0.0), the steering rules and the `ideate_generate` slot.
  - No arm uses the web while generating: `baseline_web.md` is retired. Every packet card gets the same prior-art check, recorded in the answer key.
  - IdeaCard gains `arm` (animedex | baseline_loop | baseline_single, default animedex). Only animedex cards must use atoms.
  - Baseline-1 cards live in `data/blind/baseline_loop/`, never in the canonical ideas or the archive.
- **Call cap (item 8).** Ideation runs share `ideate.calls_per_run: 60` across generate, judge and prior art; other runs keep 40.
- **Contested-evidence flag (controls A8).** `ideas.md` flags a card whose atoms are now contested, rejected, missing or (M6 hook) contradicted. The packet never shows the flag.
- **Audit (controls A7).** `make audit` writes 10 date-seeded eligible atoms with evidence trails to `eval/audit/audit_<date>.yaml`, which is git-ignored and backed up with `make data-push`. It skips gold titles while the blind is pending. `make audit-report` writes `build/reports/audit.md`: the wrong rate per date and the extractor–critic disagreement per P2 run.
- **Diagnose (owner ruling).** `make diagnose FILE=… | TEXT="…"` structures a concept (`diagnose_structure.md` 1.0.0), then runs:
  - every gate;
  - the judge;
  - an ablation pass (`diagnose_ablation.md` 1.0.0), which gives each part load-bearing, supporting or decoration.

  It makes three calls under `diagnose.calls_per_run: 6`. The output is one line per check, plus a prescription for each failure from a fixed operator/rung table. Everything is written under `data/diagnose/` only.
- **Docs:** 03 (backups include eval/audit), 04 (`arm`), 05 (IDEATE additions, AUDIT, DIAGNOSE, config), 06 (controls), 08 (AC-50–AC-57), 09 (arms), USAGE ("Check your own idea"). `schema_version` is unchanged: the change is additive (a defaulted field, a relaxed minimum on non-animedex arms).

## v1.8 contracts — 2026-09-27 (lens 1.5.0, schema 1.4.0)
The data contracts of change plan v1.8 (`proposals/CHANGE_PLAN_v1.8.md`; the request is `proposals/v1.8_request.md`) plus the grid-reliability ruling. No new pipeline passes: GATHER and INTERPRET (v1.7) fill these fields, and IDEATE wires the steering rules at M5.
- **Grid reliability (04, vocab):** every value of gate, cost_of_power, progression and visible_counter has a one-sentence discrimination test in `vocab.json` (`tests`), rendered into the P1 prompt from there. New `power_combat.cost_of_power_secondary` (same vocab, must differ from the primary); the grid keeps the primary.
- **Enum proposals (applied as the lead decided):** cost_of_power += self_imposed_restriction, imposed_penalty; visible_counter += gauge; anime_production.demographic += no_magazine_demographic. A wish an entity grants during a catastrophe is `contract`; a qualitative power category is `none` (both tests say so). No other enum changed.
- **Title fields (04, vocab 1.5.0):** 37 lens fields: power_combat 12 (mc_edge, power_embodiment, set_structure, subset_mechanics, set_scaffold, member_depth, world_integration, rarity, power_up_mode, power_up_cost, fight_logic, and the secondary cost), core 25 (story engine, world engine, MC and cast, abstract layer). Word caps: the existing caps stay; new phrases default to 15; caps the request states are kept (04 lists them).
- **Field kinds (04, models):** `enum_multi`, `list` and `group` join `phrase` and `enum`, with the same envelope. Lens options: `since` (a title made under an older vocab may omit the field; nothing is null-filled, so the 14 canonical titles stay valid until they are re-extracted), `differs_from`, `outcome_in`, `needs_source`, `abstract`. P1's schema and checks, the length-only repair, VERIFY corrections, CANONICALIZE's enum mapping, the coverage ledger and BUILD read the new kinds.
- **Characters (04):** new record `characters.jsonl` (`{title_id}.c.{nn}`): base fields, power kit (stat_block kits take drama_source; other kits a creativity level backed by sourced moves), villain fields on the main antagonist; per-title role, kit and turning-point limits are integrity checks. Names join the name-leak list. Atoms may cite a character id.
- **Outcomes:** `failure_patterns` (mixed/flop only, each with a URL); optional and left out when empty, so earlier outcomes keep their form.
- **P4 (04, 05, prompt p4_transfer 1.1.0):** transfers gain `mechanism`, `principle` ("when X, do Y, because Z", checked) and `anti_pattern`; optional in the record, required in every P4 answer, with the no-names, no-medium-words rule.
- **M7 contract:** pattern cards gain `predictive` and `predictive_evidence`; predictive needs a load-bearing atom in a held-out title. The test itself lands with M7.
- **Idea cards:** optional `mc`, `power_kit`, `thematic_argument`, `audience_promise`, `escalation_model`, `core_fantasy`, `premise_abstraction` and `rules` (the steering rules a card satisfies and fails).
- **Steering library:** `SteeringRule` (id, rule, hard|soft, 1–2 examples, optional code check), a loader for `steering/rules.yaml` (absent means no rules), and `config/steering.example.yaml`.
- **Census (prompt census 1.1.0):** adds set_structure, story_engine and mc_archetype.
- **CQs (set 1.8.0):** 35 new questions (CQ-G11–G17, CQ-I16–I39, CQ-C01–C04), the request's 13 among them, each with a DuckDB query. The orphan check now also covers the v1.8 record fields. BUILD adds `title_field_members`, `title_field_parts`, `characters`, `character_parts`, `outcome_failure_patterns`, `pattern_predictive_evidence`, `idea_concepts` and `idea_rules`; `v_incidence` includes multi-value members and enum parts.
- **Prompts:** p1_what 1.3.0, p1_example 1.2.0, the core, power_combat and anime_production fragments 1.1.0, verify_native 1.4.0 and verify_web 1.3.0 (corrections take the field's shape), p4_transfer 1.1.0, census 1.1.0. `schema_version` 1.4.0 (additive).

## v1.7 plumbing — 2026-09-27
Change plan v1.7 §2–§3 and controls A1/A2, approved by Kingsley. No data contract changes; config and pipeline behaviour only.
- **Reception data (A1/A2, 05):** new `catalog/reception.py`. MAL API v2 is primary (`MAL_CLIENT_ID` in `.env`, sent only as the `X-MAL-CLIENT-ID` header), Jikan is the fallback when there is no client ID or MAL fails, and AniList adds its own score and popularity. `reception_for(entry)` follows `catalog_ref` (or the resolver) to AniList's `idMal`.
  - Records keep only source, the MAL and AniList ids, score, scorers, rank, popularity, a page URL to cite (MAL pages are cited, never fetched) and `fetched_at`.
  - Responses are cached for 30 days in `data/cache/reception/`; MAL is paced at 1 s and Jikan at 1.1 s, and a 429 waits for Retry-After.
  - Only deep-indexed titles fetch reception; the census never does (contract test). GATHER wires it in when it lands.
- **Embeddings (05, config):** Qwen3-Embedding-0.6B, the one allowed local model.
  - Owner decision: Polymath's embedder sidecar (the same model on the Mac GPU, background priority) is the primary; the Ollama copy (`qwen3-embedding:0.6b`) is the fallback, used only when Polymath's isn't ready. One backend per run, never mixed.
  - Plain stops: "Ollama is not running…", "The embedding model isn't installed. Run: ollama pull qwen3-embedding:0.6b", and a message naming both backends when neither is ready.
  - Config: `models.embeddings` takes a `fallback`; new provider type `polymath_embedder` (embeddings only).
  - `animedex recalibrate` / `make recalibrate`: scores `eval/recalibration/pairs.yaml` (10 similar and 10 different premise pairs, original and name-free) on the primary, compares the fallback, and proposes `premise_cosine_reject` in `build/reports/recalibration.md`. It never changes config; Kingsley approves the numbers.
- **Compact context (05):** per-call model inputs (P2, P3, CHECK, P4, census, VERIFY, the P1 length repair) are `key: value` lines, never Markdown: no bullets, headings or tables, with the same information. A contract test checks every input. Cache keys are unchanged: they hash the canonical inputs, which did not change.
- **Timing (05):** `animedex timing` adds input tokens per stage (input + cache reads + cache writes, total and per call).

## v1.6.6 — 2026-09-27 (private data repo)
- Canonical data, blind-review files, gold annotations, steering rules, seeds, diagnosed concepts and (later) the Studio are backed up to the private repo `Kingsley-Cyber/animedex-data` with `make data-push [TAG=…]` and restored with `make data-pull`. This replaces "canonical data lives in git" (03). Pushes happen after every batch run (once the local clone exists) and every milestone tag, and the data repo carries the same milestone tags as the code. Cache and raw run logs are skipped.

## v1.6.5 — 2026-09-27 (fixes before M3 live runs; owner snapshot review)
- CANONICALIZE is one transaction per title (05). A held title keeps its candidate files pending, so a fix plus a rerun applies them. One bad title no longer holds back every moment and outcome.
- IDEATE cache keys cover the whole input, including the corpus and flop lists (generate) and the closest-title facts (judge). A changed corpus never serves a stale cached card.
- Run logs record cached input tokens (`cache_read_tokens`, `cache_write_tokens`) next to input tokens.
- AniList: one request per 2 s (the degraded 30/min limit) and a 30-day response cache.
- Model outputs (canonical profiles, agreement runs, blind packets, generated proposals) are git-ignored while the blind test is pending; the repo is public (03).

## v1.6.4 — 2026-09-27 (AC-11 dialogue heuristic precision)
- A "Label: description" phrase (e.g. a technique name, then what it does) no longer counts as dialogue. A speaker label counts as dialogue when the text after it reads as speech (first or second person, an exclamation or question, an opening quote mark), or when a text has two or more speaker lines. Found at M2 canonicalize: 3 titles were quarantined for descriptive phrases, and the cascade held back every moment and outcome.
- P1 phrase fields and VERIFY corrections now run the same dialogue check as the canonical boundary, so a real dialogue line is caught where it can be repaired or left unresolved.

## v1.6.3 — 2026-09-27 (owner rules: stop chasing confirmations)
- VERIFY makes one call per title. Evidence problems never trigger a retry: they are stored as `unresolved` and counted in the verify notes (05).
- Visual-detail fields and moment episode numbers are verified for gold titles only; other titles skip them (unresolved, no search).
- Outcomes: two independent reception sources are enough; MAL is optional. Btooom! stays mixed on AniList 68 + ANN B-; its MAL figure is removed from the corpus note and the G1b addendum.
- Prompts: verify_native 1.3.0, verify_web 1.2.0.

## v1.6.2 — 2026-09-27 (owner-approved: per-field word caps)
- P1 phrase fields allow 15 words; the eleven two-part fields allow 20; `condition` and `uncertainty_reason` allow 15 (04 lists them). Vocab 1.4.0 carries each cap (`max_words`); FieldValue, the P1 checks and schema, the length-only repair, and VERIFY corrections all read it. Other passes keep 12.
- Why: in 41 live P1 drafts, 217 phrases went over 12 words, in 33 of 41 fields, and 23 drafts needed a length repair. With these caps, 16 phrases and 5 drafts would. Record: `ontology/proposals/2026-09-27_word_caps.md`.
- Prompts: p1_what 1.2.0, verify_native 1.2.0, verify_web 1.1.0. Existing candidates stay valid (every phrase was ≤ 12).

## v1.6.1 — 2026-09-27 (owner rule: sources)
- Pipeline code never scrapes MyAnimeList pages. Claude web calls pass `--disallowedTools WebFetch(domain:myanimelist.net)`, and the VERIFY, prior-art and web-baseline prompts say so (prompt versions 1.1.0).
- A myanimelist.net URL is never an admissible citation (VERIFY fields, moments, outcome signals, failure evidence; prior-art counterexamples). It gets a specific repair message, and `apply` drops it to `unresolved` even without validation.
- Before this rule, four VERIFY calls (Big Order, Future Diary, Hunter x Hunter, one gold title) opened seven MAL pages. Their MAL-cited facts are listed in the M2 report and are re-verified without MAL before M2 closes.
- Backfill: announced (not yet released or future-dated) sequels are not added as seasons.

## v1.6 — 2026-09-27 (approved under Kingsley's autopilot ruling with the agent's recommendations)
- Placement: code and docs landed at the M2→M3 boundary with v1.3. The census and prior-art checks still run between M4 and M5, as ordered, so blind review #1's "never done" claims are credible.
- **Census (00, 02, 04, 05, 06, 07, 08):**
  - Catalog titles (AniList), about 10 per call, `trust: recall`, counts only (AC-44).
  - New CQ-G10: empty cells across the census.
- **Prior art (04, 05, 06, 08, 11):**
  - A native web check for every T1/T4 and lane claim (AC-45).
  - New CQ-I15: which claims survived.
- **IDEATE (04, 05, 06, 07, 08):**
  - Operators: `revive_execution_flop` (execution-level evidence) and `borrow_system` (census zero). Operator weighting waits for M7.
  - The runway judge question.
  - Pre-mortems, and "why this time is different" for graveyard matches (AC-46).
- **Blind review #1 (07, 09):** three arms of 15 (ANIMEDEX, plain prompt, same model with web search), with the answer key kept outside the repo (AC-47). This supersedes G0 D6's 20 vs 20.
- **Backfill (02, 05, 11):** `make backfill LIST=<file>` and `make ideas`, plus a one-page `USAGE.md`.
- **Scope note (02):** catalog metadata through official APIs is allowed; descriptions and reviews are never stored.
- **Judge training:** after blind review #1, pairwise picks are split into examples and held-out pairs, and agreement is reported on held-out pairs only. Not built yet; it needs your picks.
- `schema_version` 1.3.0 (additive), CQ set 1.6.0.

## v1.3 — 2026-09-27 (M2→M3 boundary)
Two changes land together:
- `failure_level`: change plan v1.3, approved under Kingsley's autopilot ruling with the agent's recommendations.
- Donghua: an ontology change Kingsley approved directly (`proposals/NOTE_donghua.md`).

**Outcome `failure_level` (01, 04, 05, 06, 08)**
- Outcomes carry `failure_level` (premise | execution | external | unknown): required for mixed and flop, null for hits. They also carry `failure_evidence` + `failure_evidence_ref` (a web-sourced level must cite a retrieved page) and `failure_level_source` (verify | owner | migration).
- `corpus/titles.yaml` may set `failure_level_override`, and Kingsley's call wins. Corpus entries may also carry `catalog_ref`.
- The graveyard warns on premise-level failures only. Execution-level failures become T5 "retold better" evidence (CQ-I14, new). CQ-G02 is reworded.
- Migration: `animedex migrate --to 1.3.0` sets the honest default `unknown`. `animedex verify --outcome-only` then records sourced levels for mixed/flop titles.
- AC-23 is reworded; AC-43 is new.
- `schema_version` 1.3.0, `vocab_version` 1.3.0, CQ set 1.3.0.

**Donghua (00, 02, 04)**
- New medium `donghua` and source medium `manhua`.
- `anime_production` stays anime-only.
- Donghua counts as animated for `sensory`.
- The census includes donghua.

## v1.2.2 — 2026-09-27
G1a search decision by Kingsley: VERIFY uses the model harness's own web search. There is no search API.

- `search.backend: native` (03, 05):
  - The VERIFY call on `claude_cli` gets exactly WebSearch and WebFetch, pre-approved.
  - Limits come from the existing caps: searches = `max_searches_per_title` (+ outcome extra); fetches = searches × `pages_per_search`; hard turn limit = searches + fetches + 2.
- **Evidence rule (05, 06):** a confirm/correct must cite a URL that the same call's searches returned or its fetches opened. The citation check reads URLs from the call's tool traffic, and page text is never kept. The cache stores the URL list, so cached answers keep their evidence.
- **Controls (06, 11):** searches over the cap are flagged in the verify notes. Hitting the turn limit skips the title.
- CHECK and the judge run on `gpt-5.6-terra` via `codex_cli`. Kingsley ruled that an older model is enough.
- Call caps confirmed: 40 per run, 6 per title.

## v1.2.1 — 2026-09-26
G1a provider change, decided by Kingsley. It lands inside M2 because it changes providers, config and budget wording, not data contracts. Noted in `proposals/CHANGE_PLAN_v1.3-v1.5.md`.

**Providers (03)**
- No model API keys. Every model call goes through Kingsley's subscriptions, using the official CLIs in headless mode:
  - `claude_cli` (`claude -p`, Claude login): Sonnet for P1/VERIFY; Opus for P2/P3/ideate_generate; Haiku for P4/EP/rollup_match.
  - `codex_cli` (`codex exec`, ChatGPT login): CHECK and the ideation judge.
  - Ollama (local): embeddings.
- **Isolation on every CLI call:**
  - The subprocess gets an allowlisted environment, with no `ANTHROPIC_*`/`OPENAI_*`/`CLAUDE*`/`CODEX_*` variables.
  - It runs from an empty scratch directory.
  - Tools are off, and the pass prompt is the system prompt.
  - No user settings, skills, plugins, hooks, MCP servers or memory load.
  - The init metadata is checked and user-level leaks are reported.
  - Logins that use an API key are refused.
- Provenance and cache keys use `<cli>@<version>/<served model>`.

**Budget and controls (05, 06, 11)**
- CLI providers use call caps (`budget.calls_per_run`, `budget.calls_per_title`) and `min_seconds_between_calls` instead of dollar caps. Each call's reported cost is logged as a shadow cost. Dollar caps stay for API-billed providers.
- A plan usage/rate limit stops the run cleanly, with no retries. Finished calls stay cached, and the rerun resumes from the cache.
- `animedex smoke --providers` makes one tiny call per CLI provider and reports the login method, what loaded, and the shadow cost.

## v1.2 — 2026-09-26
G0 decisions, approved by Kingsley (recorded in `reports/M0_REPORT.md`).

**Contracts (04)**
- Films use `scope.seasons: []` and `scope.numbering: null`; `scope.version` stays required. (D2)
- `provenance.pass` adds `CANONICALIZE` (coverage ledger) and `PATTERNS` (from M7). (D3)
- Idea `status` is `candidate | champion | rejected`. A champion holds its MAP-Elites cell; "elite" is reserved for Kingsley's verdict. (D5)
- P1 fields deleted because no competency question needs them: `sensory.sound_motif`, `comedy_satire.satire_target`, `comedy_satire.comic_roles`, `comedy_satire.running_gag_system`. (D4)
- `schema_version` 1.2.0.

**Competency questions (01)**
- CQ-E04 adds episode template. New CQ-I13: which transformation operators produce champions, and which mostly fail gates. (D4)

**Storage (03)**
- Only `data/canonical/` is committed; `data/raw/`, `data/candidates/`, `data/quarantine/` are gitignored. Raw logs replace fetched web text with URL + sha256 + length. (D1)
- CANONICALIZE runs after P1 + VERIFY for a batch and again after P4.

**Controls (06)**
- Gold blind guard: a live run on a gold title refuses to start unless `eval/gold/<title_id>/` annotations are filled and committed.
- Raw-log redaction. Diversity alarm counts champions.

**Eval (09)**
- Blind review: 20 champions vs. 20 baseline premises. Never loosen a gate to reach 20; if the budget cap hits first, review N vs. N. (D6)
- The AC-17 spot-check is recorded in the M3 completion report. (D7)

**Config (05)**
- `pricing:` per model, `models.eval_match`, `diversity_alarm.champion_share`. The verify list is recomputed in code.

**Clarifications (accepted defaults, no contract change)**
- `make build` runs BUILD plus ANALYZE's deterministic CQ step (from M4). Determinism hashes cover sorted table contents, not the DuckDB file.
- IDEATE writes candidates; CANONICALIZE promotes ideas and the archive.
- Prompts use synthetic worked examples only, never gold or partner titles.
- AC-16 also flags fewer than 3 `load_bearing` atoms. Agreement reruns use distinct params so the cache cannot return run 1.

## v1.1 — 2026-09-26
From the extraction-framework review and the episode decision.

**Extraction**
- P2 now produces two atom kinds: effect atoms (with a rival explanation) and 1–3 engine atoms (goal → constraint → strategy → benefit + cost → dilemma + dramatic question).
- P3 adds an explanation test: contrast partners decide between `because` and `rival_because`.
- CHECK adds `CONTESTED` (`explanation: contested` atoms are not load-bearing-eligible) and a `scope_leak` reason.
- P4 transfer atoms carry essential, variable, and failure conditions.
- Every title declares a scope (version, seasons, numbering); every pass stays inside it.
- Atom counts are soft limits (AC-14 changed); `flaw` and `moral_line` carry conditions; low-confidence fields carry `uncertainty_reason`; sensory fields limited to documented signatures.

**Ideation**
- Six transformation operators replace the ad-hoc mutations.
- Every idea card carries its own engine.
- Consequence tracing is the operational H1 test (≥2 of choices/relationships/outcomes must differ from the closest title).
- Failure-condition check added to the gates.

**Episodes (new M6)**
- Key episodes (pilot, moments, finale, control), from fetched summaries only, tied to their title's scope.
- ROLLUP compounds episode evidence into atom support status, promotes recurring new atoms, settles contested atoms, re-derives series-engine fields, and writes setup/payoff links.
- Only status changes spend tokens.

**Plan**
- Milestones renumbered: M6 Episode evidence, M7 Scale + calibrate + pattern cards, M8 Episode generation, M9 Target domains.
- ACs renumbered AC-01 to AC-42.

## v1.0
Initial set.
