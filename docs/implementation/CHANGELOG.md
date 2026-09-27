# Changelog — docs/implementation

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
