# Changelog — docs/implementation

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
