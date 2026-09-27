# 05 — Pipeline Contract

## Commands
| Command | Stage |
|---|---|
| `animedex p1 --title <id>` | P1 WHAT |
| `animedex verify --title <id>` | VERIFY |
| `animedex p2 --title <id>` | P2 WHY |
| `animedex p3 --title <id>` | P3 PROOF |
| `animedex check --title <id>` | CHECK |
| `animedex p4 --title <id>` | P4 TRANSFER |
| `animedex canonicalize` | CANONICALIZE |
| `animedex run --title <id>` | P1 → CANONICALIZE for one title |
| `animedex ep --title <id> [--episodes key\|<list>]` | EP (M6) |
| `animedex rollup --title <id>` | ROLLUP (M6) |
| `animedex analyze` | Coverage, gaps, lanes, graveyard, episode analytics |
| `animedex patterns` | Pattern cards (M7) |
| `animedex ideate --generations N` / `make ideas` | MAP-Elites; cards in `build/reports/ideas.md` |
| `animedex ideate --arm baseline_loop` / `make ideas ARM=baseline_loop` | Baseline 1 for the blind review: the same loop with an empty brief (M5) |
| `animedex packet` / `make packet` | Blind review packet: ANIMEDEX + baseline 1 (the same loop, empty brief) + baseline 2 (one call) (M5) |
| `animedex audit [--date D]` / `make audit` | 10 eligible atoms with evidence trails to `eval/audit/audit_<date>.yaml`, for Kingsley to mark (M5) |
| `animedex audit-report` / `make audit-report` | Wrong rate per audit date and extractor–critic disagreement per P2 run, `build/reports/audit.md` (M5) |
| `animedex diagnose --file PATH \| --text "…"` / `make diagnose FILE=… \| TEXT="…"` | Check your own concept: every gate, the judge and an ablation pass, with prescriptions (M5) |
| `animedex census --top N` / `make census` | Census of catalog titles, counts only (v1.6) |
| `animedex backfill --list <file>` / `make backfill LIST=<file>` | Resolve a title list, add it to the corpus, run the full pipeline in paced batches |
| `animedex migrate --to <version>` | Mechanical data migration |
| `animedex recalibrate` / `make recalibrate` | Score the recalibration premise pairs with the embedder and propose clone thresholds (v1.7; proposal only) |
| `animedex timing` / `make timing` | Where the time and input tokens go, per stage, from the run logs |
| `animedex review --summary` / `make review-report` | Review import: Bradley–Terry strengths per card and per arm from the ratings and panel picks, and the judge's agreement, `build/reports/taste.md` (statistics as gates) |
| `animedex backtest [--list <file>]` / `make backtest LIST=<file>` | Retrodiction backtest on held-out titles, `build/reports/backtest.md` (controls B1; statistics as gates) |
| `animedex stats` / `make stats` | Read-only statistics summary collected from the stages, `build/reports/stats.md` (statistics as gates) |
| `make validate` / `make build` / `make clean-build` / `make test` / `make eval` / `make smoke TITLE=<id>` | Tooling |

Flags: `--all` (every title in the corpus), `--dry-run` (print prompts and cache status, no model calls).

## Stage contracts

### P1 WHAT
- **In:** corpus entry (including scope). **Out:** title profile + 3–5 moments (candidates) + `verify` list.
- The P1 system prompt contains every module definition (cached). The model sets `modules_active` by these rules and fills only active modules:

| Module | Active when |
|---|---|
| power_combat | Extraordinary abilities or structured combat are a central engine |
| relationships | A bond, rivalry, mentorship, or team structure is load-bearing to plot or power |
| sensory | Medium is animated, or power_combat is active |
| anime_production | medium == anime |
| series_engine | format != film |
| comedy_satire | Comedy is a primary engine |
| film | format == film |

- Use only events inside the title's scope.
- Character fields `flaw` and `moral_line` carry a `condition`.
- Sensory fields: documented signatures only; no framing/blocking/editing claims.
- Unknown field → `value: null`, `conf: 0`. Never guess to fill. Fields under the confidence threshold carry an `uncertainty_reason`.
- `verify` list = fields with `conf < verify.conf_threshold` + `core.outcome` + all sensory fields + all moment locators. Code recomputes it from `conf` and `verify.always_verify`; the model's list is advisory.

### VERIFY
- **In:** P1 candidate + verify list. **Out:** updated fields (`source: web`, verification status, `source_ref`) + outcomes record.
- Search cap: `verify.max_searches_per_title` (+ `verify.outcome_extra_searches` for outcomes).
- Native search (`search.backend: native`):
  - The model gets WebSearch and WebFetch only.
  - Limits: searches = the cap above; fetches = searches × `verify.pages_per_search`; hard turn limit = searches + fetches + 2.
  - Searches above the cap are flagged in the title's verify notes.
  - A status of confirmed or corrected needs a URL that the same call's searches returned or fetches opened.
- Owner rules (2026-09-27): `unresolved` is a result, not a failure.
  - No retries for evidence: an uncited, blocked, over-cap, quoted or off-vocab answer is stored as `unresolved`, and the title's verify notes count it. Only unreadable output gets the one repair.
  - Visual-detail fields (`sensory.*`) and moment episode numbers are checked for gold titles only. For other titles they stay `unresolved`, with no search spent on them.
  - Outcome: two independent reception sources are enough (for example AniList plus one critic source such as ANN or a Wikipedia reception section). MAL is optional. Uncited signals drop out; a mixed or flop label without a level is stored with `failure_level: unknown`.
  - Blocked sources (owner rule, 2026-09-27): the call cannot fetch myanimelist.net pages, and a myanimelist.net URL is never an admissible citation here or in the prior-art check. MAL numbers come only through AniList, Jikan, or MAL's official API.
- Recall vs. web conflict: web wins if the source is credible; otherwise `unresolved`. Conflicts are logged.
- **Reception data** (v1.7, controls A1/A2): outcome signals come from official APIs through `catalog/reception.py`, never from pages.
  - MAL API v2 is primary (`GET /v2/anime/{id}?fields=mean,num_scoring_users,rank,popularity`, header `X-MAL-CLIENT-ID` from `MAL_CLIENT_ID` in `.env`). Without a client ID, or when MAL fails, Jikan serves the same numbers. AniList adds its own score and popularity.
  - The lookup follows the corpus entry's `catalog_ref` (`anilist:ID`), or the AniList resolver, to AniList's `idMal`. Titles AniList doesn't know get no reception records.
  - A record keeps only its source, the MAL and AniList ids, score, scorers, rank, popularity, a page URL to cite and `fetched_at`. MAL pages are cited, never fetched. The client ID is sent only as a header and never appears in a record, the cache or a log.
  - Responses are cached for 30 days in `data/cache/reception/`. Calls are paced (MAL 1 s, Jikan 1.1 s apart), and a 429 waits for Retry-After.
  - Only deep-indexed titles fetch reception (GATHER in the full pipeline, when it lands); the census never does (contract test). MAL stays optional in the label rule.
- **Outcome `failure_level`** (v1.3): for mixed and flop outcomes, VERIFY classifies the main failure as premise, execution, external, or unknown.
  - Any level except `unknown` cites a retrieved page. An unsourced level is stored as `unknown`.
  - `animedex verify --outcome-only` re-checks just the outcomes of canonical mixed/flop titles.
  - `animedex migrate --to 1.3.0` gives older records the honest default `unknown`.
- **Calibration** (statistics as gates, item 6): `make eval` adds to `build/reports/verify_rates.md`, per field, the Brier score of the extraction's confidence against verified correctness: `web_confirmed` or `gathered` = right, `web_corrected` = wrong, `unresolved` left out. VERIFY and INTERPRET's gathered step raise a checked field's stored `conf` to at least `verify.conf_threshold`, so the confidence is read from the stored P1/INTERPRET draft in the response cache (the record's provenance cache key; no call). Where the draft is gone, the stored value stands in and is counted as floored (D-022).
- Precondition for P2.

### P2 WHY
- **In:** verified profile + moments. **Out:** mechanism atoms of two kinds.
  - **Effect atoms** (up to `p2.max_effect_atoms`): element → feeling → because, plus `rival_because`.
  - **Engine atoms** (`p2.engine_atoms.min`–`max`, default 1–3): goal, constraint, strategy, benefit, cost, dilemma, dramatic question.
- Limits are soft: total ≤ `p2.max_atoms`; fewer than `p2.low_atom_alarm` is flagged for review, not failed. There is no quota beyond one engine atom.
- `because` must be causal, not a restatement of the element. `evidence_refs` required. One claim per atom. Stay inside scope.
- New atoms start with `explanation: settled`, `support.status: profile_only`, `origin: p2`.

### P3 PROOF
- **In:** the title's atoms + partner profiles. **Out:** one proof record per atom, in a single call per title.
- **Partner selection** (deterministic, via DuckDB over canonical P1; overridable in `corpus/titles.yaml`):
  - `nearest_neighbor`: highest structural overlap, same medium.
  - `flop`: a mixed/flop title sharing ≥1 active module.
  - `cross_medium`: for anime titles, the nearest non-anime title. Required.
- **Explanation test** (effect atoms): the partners act as a natural experiment. If a partner has the element but not the feeling, or the feeling without the element, which explanation (`because` or `rival_because`) survives?
- **Engine contrast:** does the partner run a similar engine, and how do its cost and dilemma differ?
- **Ablation:** "If this element or engine were removed and nothing else changed, would the title still deliver its primary_feeling and premise_engine?" Collapses → `load_bearing`. Weakened → `supporting`. Unchanged → `decoration`.
- Expect 3–5 load-bearing atoms per title. More than `p3.load_bearing_alarm` → flag.

### CHECK
- **In:** P2 atoms + P3 proofs. **Out:** check records.
- The critic tries to falsify, not improve: evidence present and sufficient for the entire claim? Inference beyond evidence? Merged claims? Circular `because`? Events outside scope? Off-vocab? Contradicts another atom or a verified field?
- If the explanation test favors the rival → `REVISE` the atom to the rival explanation.
- If `because` and the rival remain equally supported → `CONTESTED` (sets `explanation: contested`; the atom stays in the index but is not load-bearing-eligible).
- `REVISE` → apply revision, re-check once. `NEEDS_ADJUDICATION` → queue for Kingsley. `REJECT` → quarantine with reason.

### P4 TRANSFER
- **In:** load-bearing-eligible atoms (see 04). **Out:** transfer atoms.
- Strip proper nouns and medium words; map each to ≥1 bridge concept; list essential, variable, and failure conditions.
- v1.8 abstraction ladder: every transfer also gives a mechanism (≤20 words), a principle (≤25 words, "when X, do Y, because Z") and an anti-pattern (≤12 words), under the same no-names, no-medium-words rule.

### CANONICALIZE
- Validate schema → normalize enums (alternate labels → preferred) → off-vocab to proposals (store `other`) → dedupe near-duplicate atoms within a title (keep higher `conf`) → atomic write → update coverage ledger.
- **Per-title transactions (owner ruling 2026-09-27):** a title's records (profile, moments, outcome, atoms, proofs, checks, transfers, episodes, links) land together or not at all. A title with an invalid record, or one that breaks referential integrity, is held: its bad records are quarantined, its candidate files stay pending, and every other title is written. Global types (patterns, ideas, archive, prior art, census) keep one transaction per type.

### EP (M6) — episode evidence
- **Selection** (`--episodes key`), capped at `episodes.max_per_title`, deduplicated:
  1. `pilot`: first in-scope episode.
  2. `moment`: episodes holding verified P1 moment locators (max 3).
  3. `finale`: last episode of the first in-scope season (or a known arc finale).
  4. `control`: the in-scope episode at the midpoint between pilot and finale that holds no P1 moment; if its summary can't be fetched, the nearest episode that can.
- **Source:** an episode summary fetched from the web and confirmed by title + number (+ episode name when available). No fetched source → episode skipped and counted as `unsourced`. **Never extract an episode from recall alone.**
- **In:** fetched summary (transient) + compact list of the title's atoms (ID + ≤12-word gist) + scope. **Out:** one episode record (see 04), one call per episode.

### ROLLUP (M6) — compounding
Deterministic except steps 3 and 5, which call a model.
1. **Aggregate** `atom_support` into each atom's `support` block.
2. **Status transitions:** `profile_only` → `episode_backed` (≥1 support, 0 contradictions); → `mixed` (both); → `contradicted` (≥2 contradictions, 0 support).
3. **Promotions:** match `proposed_atoms` across episodes (embedding similarity ≥ `episodes.match_similarity`, confirmed by the `rollup_match` prompt). A proposal seen in ≥ `episodes.promote_threshold` distinct episodes becomes a P2 candidate with `origin: promoted_from_episodes`, then runs P3 → CHECK → P4.
4. **Re-runs:** any status change to `mixed` or `contradicted`, and any atom with `explanation: contested` that gained new episode evidence, re-runs P3/CHECK (and P4 if eligibility changes) for that atom only, with the episode evidence attached.
5. **Derived fields:** once ≥ `episodes.derive_min_episodes` episodes including the control are indexed, re-derive `series_engine.episode_template`, `series_engine.cliffhanger_cadence`, and `core.reveal_cadence` from episode records (`source: episodes`, `verification: derived_from_episodes`). If the derived value disagrees with P1, the derived value wins and the conflict is logged.
6. **Links:** write `sets_up`/`pays_off` links from episode payoffs to their setups; `advances` links from episodes to engine atoms; `supports`/`contradicts` links to atoms.
7. **Coverage:** update episode counts, selection mix, and `episode_backed_share`.

**Economics rule:** a new supporting episode only updates counts. It never invalidates downstream passes. Only status changes and promotions spend tokens.

### BUILD
- Reads canonical only. Creates DuckDB tables and views: long-format title fields, incidence matrix, pair co-occurrence, load-bearing view, outcomes with confounders, episodes, links, atom support. Exports CSV and Markdown reports. Sorted by ID; fixed seeds.

### ANALYZE
- Coverage report; gap cells with coverage-adequacy flag; imported/export lanes; graveyard index (load-bearing combinations of mixed/flop titles + `failure_reason` + `failure_level`; M6: flop pilot structures). Only **premise**-level failures warn (v1.3). **Execution**-level failures are listed as T5 "retold better" evidence. External/unknown are listed with no warning.
- **Statistics as gates** (owner ruling 2026-09-27; see the section below):
  - **Adequacy:** a zero is `open` only when the rule-of-three bound 3/n is below 0.02 (n ≥ 151). For module questions n is the titles with the module active and `field_completion ≥ coverage.min_field_completion`; for census-backed questions (CQ-G10, CQ-G16, CQ-I23) n is the census rows with `has_power_system`. This replaced `coverage.min_titles_with_module` (5).
  - **Gap ranking:** the grid-gap questions (CQ-G01, CQ-G04, CQ-G10, CQ-G17) rank their empty cells by the count expected under independence, n × p(x) × p(y), over the n rows with both fields known (`gap_ranking` in the answer): expected ≥ 3 with none observed is a **real gap**; the rest are **unsurprising**. Ties by value, so the order is deterministic.
  - **Reliability:** a question whose zeros rest on a field that `eval/agreement/reliability.json` flags `unreliable` (kappa < 0.6) is excluded from the gap reports (`zeros_are: excluded: unreliable field`, with the field and its kappa). No file, no exclusion.
  - **Field health:** per single-value enum field, entropy, normalized entropy (by the number of allowed values; under 0.5 is flagged low) and mutual information with the outcome label over the titles that have one, in `build/reports/analysis.md`.
  - The numbers go to `build/stats/analysis.json` for `animedex stats`.
- M6 episode analytics: pilot structures (CQ-E02), engine presence in control episodes (CQ-E05), setup→payoff distances and unresolved setups (CQ-E06), atom support statuses (CQ-E07), decision shapes (CQ-E08).
- Saves CQ answers to `build/cq_answers/*.json` for regression.

### PATTERNS (M7)
- Cluster transfer atoms (embeddings); for each cluster, write a pattern card with supporting titles, a counterexample search (titles that have the pattern and flopped, or lack it and succeeded), boundary conditions, alternative explanations, and scope.
- Principle test (v1.8): a card is marked `predictive` only if its principle explains at least one load-bearing atom in a held-out title it wasn't extracted from (04). Only predictive principles feed ideation as principles.

### IDEATE
- **Atom pool:** load-bearing-eligible transfer atoms; `episode_backed` preferred over `profile_only`.
- **Generate:** theme root (a `core_question` from the corpus, or one Kingsley supplies) + 1–3 atoms from different titles (prefer different media) + a target cell (prefer empty cells). Apply **one** operator:

| Operator | Move |
|---|---|
| reverse_incentive | What was rewarded becomes costly, or vice versa |
| redistribute_knowledge | Change who knows the secret, or when |
| transfer_cost | The cost lands on someone else |
| change_rule | Alter one world or power rule |
| combine_mechanisms | Join two engines whose consequences interfere |
| import_lane | Bring a pattern from another medium where it's absent |

  The transformation must respect every essential condition of the atoms it uses. The LLM writes the card, including the idea's own **engine** and its **consequences** for choices, relationships, and outcomes.
- **Deterministic gates, in order:**
  1. **Clone:** Jaccard of the idea's structural set vs. every title. Structural set = enum values of gate, cost_of_power, progression, visible_counter, fight_medium, power_is + bridge concepts of the atoms used. Procedural set = gate, cost_of_power, progression, visible_counter. Premise cosine via embeddings on logline + premise.
     - **Embeddings (v1.7):** Qwen3-Embedding-0.6B, the one allowed local model. Polymath's embedder sidecar (the same model on the Mac GPU, `POST /infer`, at most 32 texts per request, `representation_kind: child_chunk`, no priority header so it runs at background priority) is used when its `/ready` says ready and its manifest names the configured model. Otherwise the Ollama copy (`qwen3-embedding:0.6b`) is used. One backend serves the whole run and its name is printed; the backends are never mixed. When neither is ready, the run stops with a message naming both and how to start one.
     - **Recalibration:** each embedding model scores on its own scale. `animedex recalibrate` scores `eval/recalibration/pairs.yaml` (about 10 similar and 10 different premise pairs, original and name-free) on the primary backend, compares the fallback when it is reachable (largest per-pair difference), and proposes `premise_cosine_reject` between the lowest similar-pair score and the highest different-pair score. It writes `build/reports/recalibration.md` and never changes config; Kingsley approves the numbers. `premise_cosine_with_structural` is reported, not recalibrated.
  2. **Novelty (statistics as gates: PMI replaced "unseen pair"):** the card's key pair is the pair of its profile values, or of its atoms' bridge concepts when the atoms come from 2+ titles, with the lowest PMI (add-half smoothed, D-015) on an adequate subset. The pair is novel when PMI ≤ −1.0 (it co-occurs at most half as often as chance, D-021) over more than 150 rows that could show it (both fields known; rule of three). Enum rows are the corpus titles, plus the powered census rows once `ideate.census_novelty_min_rows` (200) is met; bridge rows are the corpus titles. Fields flagged unreliable never form a pair. The key pair and its PMI are recorded on the card (`gates.pmi_key_pair`) and shown in `ideas.md`.
  3. **Graveyard:** if its key combination matches a **premise**-level flop's load-bearing combination, the card must state why this time is different, or it is rejected. Execution-level matches are not warnings; they are T5 evidence (v1.3).
- **Judge (different model family when available):**
  1. **H1 consequence test:** for each of choices, relationships, outcomes: does it differ from what happens in `closest_existing`? Fewer than `ideate.h1_min_changed_dimensions` → H1 fail → reject.
  2. **Failure conditions:** does the idea trigger any failure condition of the atoms it uses? → rework once, else reject.
  3. **Coherence:** theme ↔ mechanic link holds, and the engine's dilemma follows from its cost.
  4. **Taste criteria with required evidence:**

| Criterion | Evidence required |
|---|---|
| T1 | Key combination has zero co-occurrence with adequate coverage; graveyard empty |
| T2 | Nearest title shares the concept; idea differs on ≥1 load-bearing atom |
| T3 | Atoms come from different bridge concepts or media, and coherence passes |
| T4 | Imported/export lane evidence, or a high-appetite pattern with zero occurrence |
| T5 | Named source title + a specific improvement mapped to its recorded weakness |

- **Fitness (lexicographic, no invented scores):** (1) all gates and H1 pass; (2) number of evidenced taste criteria; (3) more episode-backed atoms used; (4) lower max structural overlap; (5) Kingsley's rating overrides when present.
- **Archive:** place if the cell is empty or fitness beats the incumbent. Champions are parents for the next generation; empty-cell targeting picks the operator most likely to move a parent toward the target cell.

### IDEATE additions (v1.6)
- **Operators:**
  - `revive_execution_flop`: runs only when a flop's `failure_level` is `execution`, backed by web evidence or Kingsley's override. It keeps the premise, replaces the failed part with a proven engine, and names the improvement (T5).
  - `borrow_system`: runs only when the census shows zero titles using the borrowed system as a power system.
  - Operator weighting (a bandit with a minimum share of 5% per operator) waits for M7.
- **Every card also carries:**
  - a pre-mortem: 2–3 risks drawn from mixed/flop titles, each with a mitigation;
  - the judge's runway answer to "does the cost still hurt by arc 5?" A "no" gets one rework, then the card is rejected;
  - "why this time is different", when a premise-level graveyard combination matches.
- **Taste criteria** stay only with their deterministic evidence (05 table).
- **Prior art:** every T1 and T4 claim gets a prior-art web check, using the model's own web tools and the same evidence rule as VERIFY. A counterexample or an unclear result removes the claim.
- **Call cap:** runs respect the per-run call cap and continue from the archive.

### IDEATE additions (M5; owner rulings 2026-09-27, "before M5 live runs")
- **Call brief (item 4).** Each generate call gets a small brief, not every title and flop (`ideate/brief.py`). It is compact `key: value` lines, not Markdown:
  - `theme`, `operator` (with its definition), `target` (the cell);
  - `atom A1`, `atom A2`…: the plan's atoms under opaque aliases, with bridge concepts and essential, variable and failure conditions. No source title and no transfer id is shown. The model lists aliases in `source_transfer_ids`, and the card maps them back to the real transfer ids;
  - `revive` / `borrowed_system` for those two operators;
  - `cell`: corpus titles and census rows in the target cell (counts only, AC-44) and whether zeros there are trusted;
  - `lanes`: imported/export lane concepts among the atoms' bridges; `prior_art`: verdicts already recorded for earlier cards in the cell;
  - `title`: the nearest `ideate.brief_titles` (10) titles, by the clone gate's structural Jaccard between the target profile + the atoms' bridge concepts and each title's structural set (ties by id). `closest_existing` may still be any corpus id;
  - `flop`: mixed/flop titles in the target region, meaning their structural set overlaps the target set (most overlap first, up to `ideate.brief_graveyard_max`, 5). If none overlaps, the first two rows by id stand in so the pre-mortem keeps sources (AC-46); the call meta records `graveyard_region: fallback`. Pre-mortem sources are limited to the flops shown;
  - `rule`: every steering rule; `rework`: the failed checks on a retry.
  - **Cap:** `ideate.brief_max_words` (600). Optional lines go first (farthest titles, extra flops, prior art, lanes, the last flop). A brief whose required lines alone pass the cap is refused before any call (`brief:` rejection). Each call's run-log entry carries `meta.brief`: words, estimated tokens (characters / 4), and counts per slot.
- **Novelty (item 5).** Census rows count for novelty only once the census holds at least `ideate.census_novelty_min_rows` (200) rows with `has_power_system: true`. Census-backed coverage adequacy, and the `borrow_system` operator's census zero, use the same 200-row floor (it clears the rule of three). Since statistics as gates, novelty is the PMI rule of gate 2: with 14 corpus titles no subset is adequate, so novelty needs the census.
- **Judge on `why_different` (item 6).** On a premise-level graveyard match the judge sees the card's `why_different` and each matched flop's recorded failure (reason and level). It returns `why_different_verdict` pass | fail | not_applicable with a reason of 25 words or fewer. "Not blank" is no longer a pass: a blank answer still fails the gate, and a judged fail gets one rework, then rejection (like runway). A card with a match must get pass or fail (one repair).
- **Fair baselines (item 7; controls A5, decision 1).** The blind review has three arms, and only index access differs:
  - `animedex`: the champions;
  - `baseline_loop` (baseline 1): `run_ideate(..., index=False)`, the same loop (prompt, operators, gates, judge, prior-art check) with an empty brief: theme, operator, target, steering rules and rework notes (title ids redacted). No atoms, titles, flops, cell counts, lanes or prior art. It never runs `revive_execution_flop` or `borrow_system`, which need index evidence. It sees no title ids, so its `closest_existing` is the title the clone gate measures (structural nearest, else premise-cosine nearest). Its cards carry `arm: baseline_loop`, may have no atoms, and live in `data/blind/baseline_loop/`. They never enter the canonical ideas, the archive or the champions, and the packet takes its best card per cell by the same fitness;
  - `baseline_single` (baseline 2): one "write N premises" call (`prompts/baseline_single.md`).
  - All arms use the `ideate_generate` slot and the same taste standard text (`prompts/taste_standard.md`, included in the generate and baseline prompts). They get the same steering rules (`steering/rules.yaml`, a list of `{id, rule, strength: hard|soft}`, rendered as `rule <id> (<strength>): <text>`; no file means no rules; a malformed file stops the run). No arm uses web tools while generating: the web baseline and `prompts/baseline_web.md` are retired. Every packet card then gets the same prior-art check, recorded in the answer key only (`data/blind/key_<date>.json`: arm, source, prior-art verdict).
- **Call cap (item 8).** Ideation runs (`make ideas`, either arm) share one cap across generate, judge and prior art: `ideate.calls_per_run` (60), so one run covers three generations. Other runs keep `budget.calls_per_run` (40).
- **Contested-evidence flag (controls A8).** When `ideas.md` is written, a card whose `atoms_used` lean on an atom now CONTESTED or REJECTed by its latest CHECK, with `explanation: contested`, gone from the index, or (M6 hook) `support.status: contradicted` shows an **Evidence flag** line. It is computed from the current canonical state every time and never shown in the blind packet.

### CENSUS (v1.6)
- **In:**
  - catalog titles: AniList's popular franchise roots since 1995, anime + donghua;
  - or resolved queue lines.
- **Out:** `census.jsonl` records, about 10 titles per call. Values are `trust: recall`, used only as counts: grid occupancy, coverage adequacy, and the `borrow_system` gate.
- **Model:** Sonnet, unless a sampled accuracy check shows Haiku is good enough.
- **No reception data (A2):** the census never fetches reception; the census module has no path to the reception client (contract test).

### BACKFILL
- **Picking the version:** a version in parentheses is used as given; otherwise the most-watched adaptation is picked, and the choices go to `build/reports/backfill.md`.
- **Scope:** TV sequels with gaps under 5 years become seasons. Other adaptations are excluded.
- **Pairing:** two versions of the same story become each other's nearest neighbor.
- **Mix warning:** an all-hit or all-anime list gets a warning and suggestions, never a block.
- **Running:** the full pipeline runs in paced batches, and the report shows counts only.

### BACKTEST (controls plan B1; statistics as gates, item 8)
- **`animedex backtest [--list FILE]`** (`make backtest LIST=FILE`): one command over existing stages.
  1. **Titles.** `--list` resolves each line with the catalog resolver (the backfill rules) into `data/backtest/titles.yaml`. A title already in the corpus is refused: backtest titles are held out and never enter the corpus or canonical data (AC-BT-1). `data/backtest/` is git-ignored.
  2. **GATHER + INTERPRET**, unchanged, against `BacktestPaths`: the same prompts, models, response cache and run logs, with the title list, candidates and quarantine under `data/backtest/` (`gathered/<id>.json`, `interpret/<id>.json`). The live title guard reads the backtest list, so every title keeps a declared scope. The outcome label is INTERPRET's reception-backed outcome; a title without one is reported, not scored. Finished titles are not run again.
  3. **Predictions** (slot `ideate_judge`, `prompts/backtest_predict.md` 1.0.0): hit, mixed or flop from the premise abstraction and the power kit (the six structural enums) only, twice per title: with a blank brief, and with the index brief (the `backtest.neighbors` (5) nearest corpus titles by structural Jaccard, anonymous, with their outcome labels, and for mixed and flop ones the failure level, patterns and reason). Batches of `backtest.batch` (5) titles. The name-leak check (held-out and corpus titles, character names, profile proper nouns) runs on the free text of every judge input: a title whose premise names anything is not sent, a neighbour reason that names anything is dropped, and an input still holding a title id is refused (AC-BT-2).
  4. **Report** (`build/reports/backtest.md`, `build/stats/backtest.json`): per-title predictions, accuracy with each brief and the difference (AC-BT-3), the exact one-sided McNemar p-value on the titles only one brief got right, and the sample size the observed split would need for p < 0.05 (D-016). A rerun with the same titles is served from the cache (AC-BT-4).
- **Calls:** about 3 per title for GATHER and INTERPRET plus 2 × ⌈titles / 5⌉ judge calls, under the usual caps (40 per run, 6 per title).

### STATS (statistics as gates; read-only)
- **`animedex stats`** (`make stats`) writes `build/reports/stats.md` from the stage outputs only: reliability (`eval/agreement/reliability.json`), adequacy per subset, the top real gaps and field health (`build/stats/analysis.json`), the champions' key-pair PMI (canonical idea cards), calibration (`build/stats/calibration.json`), taste (`build/stats/taste.json`) and the backtest (`build/stats/backtest.json`). It recomputes nothing that depends on a model; a missing input names the command that makes it.

### Statistics as gates (owner ruling 2026-09-27)
Snapshots and counts only, no models; each statistic replaced the check it corresponds to inside its existing stage (`src/animedex/stats.py` holds the arithmetic, `statgates.py` the stage plumbing):

| Stage | Check before | Statistic now |
|---|---|---|
| Agreement eval (AC-12) | raw enum agreement ≥ 0.80 | Cohen's kappa per enum field next to raw agreement; grid fields need kappa ≥ 0.8; kappa < 0.6 flags a field unreliable (`eval/agreement/reliability.json`) |
| ANALYZE adequacy, IDEATE `ctx.adequate`, `borrow_system` | ≥ 5 titles with completion ≥ 0.8, or ≥ 200 powered census rows | a zero is open only when 3/n < 0.02 over the relevant subset (census rows still count only past the 200-row floor) |
| ANALYZE gap report | every empty cell listed | empty cells ranked by n × p(x) × p(y); expected ≥ 3 = real gap, else unsurprising; unreliable fields excluded |
| ANALYZE report | — | field health: entropy, normalized entropy (low < 0.5), mutual information with outcome |
| IDEATE novelty gate | an unseen pair under adequate coverage | the key pair's PMI ≤ −1.0 on an adequate subset, recorded on the card |
| VERIFY report | correction rate per field | plus the Brier score of the pre-check confidence per field |
| Review import | — | Bradley–Terry strengths per card and per arm; the judge's agreement with that ranking |
| Backtest | — | accuracy per brief, exact McNemar p-value, sample size needed |

### AUDIT (controls A7, M5)
- **`animedex audit [--date D] [--size 10]`:** samples 10 load-bearing-eligible atoms at random, seeded by the date, and writes `eval/audit/audit_<date>.yaml`. The folder is git-ignored and backed up to the private data repo. Per atom the sheet holds:
  - the atom's text and its P2 run;
  - each evidence ref (and the effect's `element_ref`) resolved to the profile field, moment or episode it names, with value or text, verification status and source URL;
  - the CHECK verdict history (target, verdict, reasons, run);
  - a blank `mark:` for Kingsley: `true` | `plausible` | `wrong`.
- **Guards:** while `eval/gold/BLIND.yaml` is `pending`, gold titles are never sampled; partner titles are (owner ruling 2026-09-27). An existing sheet is never overwritten, since it may hold marks.
- **`animedex audit-report`:** reads every sheet and writes `build/reports/audit.md` (counts only, no atom text):
  - the wrong rate per audit date (wrong / marked), followed over time;
  - the extractor–critic disagreement per P2 run: the share of checked atoms whose first CHECK verdict was not ACCEPT, grouped by the run that extracted them. Atoms CHECK rejected are counted from quarantine.

### DIAGNOSE (owner ruling 2026-09-27, M5; reuses the M5 gates and judge)
- **In:** a concept as text, `--file PATH` or `--text "…"` (up to `diagnose.max_concept_words`, 800). **Out:** `data/diagnose/<id>.json` (the concept, the card, every result) and `data/diagnose/<id>.md`, both private (git-ignored, backed up to the private data repo, never in the public repo), plus printed lines. The id is `diag_<yyyymmdd>_<sha8 of the text>`.
- **Steps (3 calls under `diagnose.calls_per_run`, 6, since each call may spend its one repair):**
  1. **Structure** (slot `ideate_generate`, `prompts/diagnose_structure.md` 1.0.0): the concept becomes a card (`models/diagnose.py`): logline, premise, theme, engine (7 parts), twist (`what_changed`), consequences, profile (6 enums), closest existing title, why not a clone, broken rule, appetite, why different. The model structures and does not improve. While the gold blind is pending it sees no gold title.
  2. **Gates**, exactly as on generated cards: clone, novelty, graveyard, name leak. A concept has no atoms, so novelty can only come from census-backed enum pairs (PMI on an adequate sample; item 5 floor).
  3. **Judge**: the IDEATE judge prompt and call shape, one card: H1, coherence, runway, and `why_different` on a premise-level match. Taste claims are listed, unverified (diagnose runs no prior-art check).
  4. **Ablation** (slot `ideate_judge`, `prompts/diagnose_ablation.md` 1.0.0): for each part (the 7 engine parts, the twist, the broken rule when present, the 6 profile values), `load_bearing` | `supporting` | `decoration` with a reason of 20 words or fewer. The check fails when the twist is decoration or when no part is load-bearing.
- **Output:** one line per check (PASS, FAIL or SKIP, and why). No reworks, and the full rebuild (`amplify`) stays after blind review #1. Each FAIL gets a prescription from this fixed table (in code, `ideate/diagnose.py`):

| Failure | Prescription | Kind |
|---|---|---|
| structure (no valid card) | kit | rung |
| clone: structural overlap | change_rule | operator |
| clone: procedural overlap | kit | rung |
| clone: premise similarity | redistribute_knowledge | operator |
| novelty | combine_mechanisms | operator |
| graveyard (blank why different) | promise and hooks | rung |
| why different (judged fail) | promise and hooks | rung |
| name leak | world | rung |
| H1 consequence test | transfer_cost | operator |
| coherence | villain and thematic argument | rung |
| runway | engine and escalation | rung |
| ablation: the twist is decoration | change_rule | operator |
| ablation: no load-bearing part | reverse_incentive | operator |

  The concept ladder: kit → set → MC → villain and thematic argument → world → engine and escalation → promise and hooks → pilot hook → three key frames → storyboard.
- **Gold blind:** gold names are masked, and a judge reason written against a gold title is withheld while the blind is pending.

## Caching and idempotency
`cache_key = sha256(id | pass | prompt_version | schema_version | vocab_version | model | params | upstream_hash)`, where `upstream_hash` hashes the canonical inputs the pass reads.
- Changing the P3 prompt invalidates P3, CHECK, and P4 for affected titles, never P1 or P2.
- Support-count increments are excluded from `upstream_hash`; status, explanation, and promotion changes are included. So new supporting episodes never trigger re-runs.
- Reruns skip cached calls.

## Token-efficiency rules
- Fixed system prompt per pass (cache-friendly); title- or episode-specific content only in the user message.
- **Compact inputs** (owner ruling v1.7 §3): a per-call model input is a compact structured slice, never a rendered Markdown report. Every line is `key: value`: the title's identity and scope, profile fields as `path: value [verification]`, and groups of records opened by a `key: count` line (`moments: 3`, `atoms: 5`, `partner: <id>; role: <role>`) with one `id: part: value; ...` line per record. No bullets, headings or tables. VERIFY's fetched pages stay raw text under `page: <url>` lines, so the run log can redact them. A contract test checks every per-call input.
- JSON only; enums wherever possible; length caps per field.
- Inactive modules omitted.
- VERIFY runs only on flagged and mandatory fields.
- P3 batches all of a title's atoms into one call.
- EP sends a compact atom list (ID + gist), not full atoms; one episode per call.
- Every call logs tokens and cost to `data/raw/runs/`. Subscription CLI calls log the CLI's own cost estimate as a shadow cost, kept apart from charged cost.
- `animedex timing` reports input tokens per stage (input + cache reads + cache writes, total and per call) next to where the time goes, for calls that log cache tokens.

## Config (`config/settings.yaml`) — placeholders to fill before M2
```yaml
providers:        # G1a v1.2.1: subscription CLIs; no model API keys
  claude_cli: {type: claude_cli, binary: claude, send_params: [effort]}
  codex_cli:  {type: codex_cli,  binary: codex,  send_params: [effort]}
  local:      {type: openai_compatible, base_url: http://localhost:11434/v1}   # Ollama: the embeddings fallback
  polymath_embedder: {type: polymath_embedder, base_url: http://127.0.0.1:8742}  # v1.7: embeddings only
models:           # concrete model ids, not aliases; strict_model refuses any other served model
  p1:     {provider: claude_cli, model: "<sonnet-id>"}
  verify: {provider: claude_cli, model: "<sonnet-id>"}
  p2:     {provider: claude_cli, model: "<opus-id>"}
  p3:     {provider: claude_cli, model: "<opus-id>"}
  check:  {provider: codex_cli,  model: "<codex-model>", strict_model: true}
  p4:     {provider: claude_cli, model: "<haiku-id>"}
  ep:     {provider: claude_cli, model: "<haiku-id>"}
  rollup_match: {provider: claude_cli, model: "<haiku-id>"}
  ideate_generate: {provider: claude_cli, model: "<opus-id>"}
  ideate_judge:    {provider: codex_cli,  model: "<codex-model>", strict_model: true}
  embeddings:      {provider: polymath_embedder, model: Qwen/Qwen3-Embedding-0.6B,   # v1.7
                    fallback: {provider: local, model: "qwen3-embedding:0.6b"}}      # one backend per run
  prior_art:       {provider: claude_cli, model: "<sonnet-id>"}   # v1.6 native web search
  census:          {provider: claude_cli, model: "<sonnet-id>"}   # v1.6 counts only
  eval_match:      {provider: claude_cli, model: "<haiku-id>"}
pricing:          # API-billed provider/model pairs only; CLI calls log their reported cost as a shadow cost
  "<provider/model>": {input_per_mtok: "<set>", output_per_mtok: "<set>"}
search: {backend: native}   # or brave | tavily | searxng (API backends; brave/tavily need SEARCH_API_KEY)
budget:
  calls_per_run: "<set>"        # subscription CLIs: call caps, not dollars
  calls_per_title: "<set>"
  min_seconds_between_calls: 5
  run_cap_usd: "<set>"          # API-billed providers only
  per_title_cap_usd: "<set>"
  per_episode_cap_usd: "<set>"
verify:
  conf_threshold: 0.7
  max_searches_per_title: 3
  outcome_extra_searches: 2
  always_verify: ["core.outcome", "sensory.*", "moments.*.locator"]
p2:
  max_atoms: 15
  max_effect_atoms: 12
  engine_atoms: {min: 1, max: 3}
  low_atom_alarm: 5
p3: {load_bearing_alarm: 8}
check: {reject_rate_alarm: 0.30}
coverage: {min_field_completion: 0.8}   # zeros: rule of three, 3/n < 0.02 (replaced min_titles_with_module: 5)
episodes:
  selection: [pilot, moment, finale, control]
  max_per_title: 6
  max_moment_episodes: 3
  require_fetched_source: true
  summary_max_words: 60
  max_decisions_per_episode: 2
  match_similarity: 0.85
  promote_threshold: 2
  derive_min_episodes: 3
  contradiction_storm_alarm: 0.30
gates:
  structural_jaccard_reject: 0.70
  procedural_jaccard_reject: 0.75
  premise_cosine_reject: 0.90
  premise_cosine_with_structural: 0.55
ideate:
  grid_dims: ["power_combat.gate", "power_combat.set_structure", "power_combat.progression"]   # D-028
  operators: [reverse_incentive, redistribute_knowledge, transfer_cost, change_rule, combine_mechanisms, import_lane]
  h1_min_changed_dimensions: 2
  generations: 3
  candidates_per_generation: 12
  diversity_alarm: {champion_share: 0.40, cell_share: 0.10}
  calls_per_run: 60              # M5: ideation runs; other runs keep budget.calls_per_run
  brief_max_words: 600           # M5 call brief
  brief_titles: 10
  brief_graveyard_max: 5
  census_novelty_min_rows: 200   # M5: census rows count (adequacy, novelty PMI) only from this many powered rows
backtest: {batch: 5, neighbors: 5}   # statistics as gates, item 8: titles per judge call; neighbours in the index brief
diagnose: {calls_per_run: 6, max_concept_words: 800}
```
Gate and episode thresholds are initial calibration values, not truths. Recalibrate in M7.

## Prompt contracts (excerpts; full text lives in `prompts/`, versioned)

**P1 WHAT**
```text
You extract a compact profile of ONE screen title, inside the given scope. Output JSON only.
- Fill core fields. Set modules_active by the activation rules; fill only active modules.
- Use only events inside the scope. Ignore other adaptations and unadapted source material.
- Enum fields: choose from the provided enum. If none fits, use "other:<phrase>".
- Phrase fields: within each field's word cap (15 words; 20 for two-part fields; 04), normalized wording.
- flaw and moral_line: add a condition (when it shows / what would make them cross it).
- Sensory: documented signatures only. No claims about framing, blocking, editing, or shots.
- conf 0.0–1.0 per field = how sure you are. Unknown → value null, conf 0. Never guess to fill.
  If conf < 0.7, give an uncertainty_reason (≤15 words).
- Extract mechanics, structure, and appeal. Not plot summary.
- 3–5 moments. Paraphrase only. No dialogue, no quotes.
- source = "recall" for every field.
- verify = every field with conf < 0.7, plus core.outcome, all sensory fields, all moment locators.
```

**P2 WHY**
```text
From this verified profile and its moments, write two kinds of atoms. Stay inside the scope.
EFFECT atoms (up to 12): element → feeling (enum) → because (≤25 words), plus rival_because:
the strongest alternative explanation for the same feeling.
ENGINE atoms (1–3): an agent wants [goal] but [constraint]; chooses [strategy]; gets [benefit]
and [cost]; which forces [dilemma]. Add the dramatic_question the engine keeps open.
- "because" must explain WHY the audience feels it. Restating the element is invalid.
- Cite evidence_refs for every atom. One claim per atom.
- Fewer strong atoms beat many weak ones. There is no minimum beyond one engine atom.
```

**P3 PROOF**
```text
For each atom:
1. CONTRAST with each partner: does the partner have it (yes/no/partial)? How does the effect differ?
   Effect atoms: using the partners as a natural experiment, which explanation survives —
   because, rival, both, or neither?
   Engine atoms: does the partner run a similar engine? How do its cost and dilemma differ?
2. ABLATION: if this element or engine were removed and nothing else changed, would the title
   still deliver its primary_feeling and premise_engine?
   Collapses → load_bearing. Weakened → supporting. Unchanged → decoration.
Be strict. Most elements are decoration. Expect roughly 3–5 load-bearing atoms per title.
```

**CHECK**
```text
Your job is to falsify, not improve. For each atom and proof: is the whole claim supported by its
cited evidence? Any inference beyond the evidence? Merged claims? Circular "because"? Events outside
the title's scope? Off-vocabulary? Contradicts another atom or a verified field?
If the explanation test favors the rival, REVISE the atom to the rival explanation.
If because and rival remain equally supported, return CONTESTED.
Verdict: ACCEPT | REVISE | REJECT | CONTESTED | NEEDS_ADJUDICATION, with reasons.
If REVISE, return the corrected record.
```

**P4 TRANSFER**
```text
Rewrite each atom as a domain-neutral pattern (≤25 words). No titles, character names, or
medium-specific words (e.g., anime, manga, episode, season, show, film). Map to ≥1 bridge concept.
Then list:
- essential_conditions: what must stay true for the pattern to work
- variable_details: what can change freely (setting, role, power form, aesthetic)
- failure_conditions: what would dissolve the pattern
```

**EP (M6)**
```text
You record evidence from ONE episode of ONE title, using only the provided episode summary.
Paraphrase only; no quotes. Stay inside the title's scope. Output JSON only.
- summary ≤60 words; function (enum); end_hook (enum).
- engine_beat: which engine atom this episode advances, and which part
  (goal, constraint, strategy, benefit, cost, dilemma).
- decisions (max 2): agent, goal, options, choice, rejected alternative, expected vs. actual outcome.
- info_shift: what the audience learns, what characters learn, whether the gap widens, narrows, or flips.
- setups planted and payoffs delivered. Link a payoff to an earlier episode only if the summary supports it.
- atom_support: for each listed atom this episode bears on: supports | contradicts | reframes,
  with a ≤25-word note. Omit atoms it doesn't bear on.
- proposed_atoms: effect or engine patterns this episode suggests that no listed atom covers.
Prefer omission over speculation.
```

**IDEATE**
```text
GENERATE: Apply ONE operator to the given transfer atoms, respecting each atom's essential_conditions.
Write the idea card, including its own engine (goal, constraint, strategy, benefit, cost, dilemma,
dramatic question) and its consequences for characters' choices, relationships, and outcomes.

JUDGE: For each consequence dimension, does it differ from what happens in closest_existing?
(yes/no + reason). Does the idea trigger any failure_condition of the atoms it uses? Does the
dilemma follow from the cost, and does the mechanic express the theme? On a premise-level graveyard
match, does why_different answer the matched flop's recorded failure (pass/fail + reason; not blank
is not a pass)? Then evaluate each taste criterion only with the required evidence.
```
M5: the generate prompt (2.0.0) reads the call brief and carries the shared taste standard; the
judge prompt is 1.1.0.
