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
| `animedex packet` / `make packet` | Blind review packet: ANIMEDEX + plain baseline + web baseline (v1.6) |
| `animedex census --top N` / `make census` | Census of catalog titles, counts only (v1.6) |
| `animedex backfill --list <file>` / `make backfill LIST=<file>` | Resolve a title list, add it to the corpus, run the full pipeline in paced batches |
| `animedex migrate --to <version>` | Mechanical data migration |
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
- **Outcome `failure_level`** (v1.3): for mixed and flop outcomes, VERIFY classifies the main failure as premise, execution, external, or unknown.
  - Any level except `unknown` cites a retrieved page. An unsourced level is stored as `unknown`.
  - `animedex verify --outcome-only` re-checks just the outcomes of canonical mixed/flop titles.
  - `animedex migrate --to 1.3.0` gives older records the honest default `unknown`.
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
  2. **Novelty:** the idea must contain a pair/triple of atoms or enum values with zero co-occurrence (under adequate coverage), or an explicit inversion of a hit's broken rule.
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

### CENSUS (v1.6)
- **In:**
  - catalog titles: AniList's popular franchise roots since 1995, anime + donghua;
  - or resolved queue lines.
- **Out:** `census.jsonl` records, about 10 titles per call. Values are `trust: recall`, used only as counts: grid occupancy, coverage adequacy, and the `borrow_system` gate.
- **Model:** Sonnet, unless a sampled accuracy check shows Haiku is good enough.

### BACKFILL
- **Picking the version:** a version in parentheses is used as given; otherwise the most-watched adaptation is picked, and the choices go to `build/reports/backfill.md`.
- **Scope:** TV sequels with gaps under 5 years become seasons. Other adaptations are excluded.
- **Pairing:** two versions of the same story become each other's nearest neighbor.
- **Mix warning:** an all-hit or all-anime list gets a warning and suggestions, never a block.
- **Running:** the full pipeline runs in paced batches, and the report shows counts only.

## Caching and idempotency
`cache_key = sha256(id | pass | prompt_version | schema_version | vocab_version | model | params | upstream_hash)`, where `upstream_hash` hashes the canonical inputs the pass reads.
- Changing the P3 prompt invalidates P3, CHECK, and P4 for affected titles, never P1 or P2.
- Support-count increments are excluded from `upstream_hash`; status, explanation, and promotion changes are included. So new supporting episodes never trigger re-runs.
- Reruns skip cached calls.

## Token-efficiency rules
- Fixed system prompt per pass (cache-friendly); title- or episode-specific content only in the user message.
- JSON only; enums wherever possible; length caps per field.
- Inactive modules omitted.
- VERIFY runs only on flagged and mandatory fields.
- P3 batches all of a title's atoms into one call.
- EP sends a compact atom list (ID + gist), not full atoms; one episode per call.
- Every call logs tokens and cost to `data/raw/runs/`. Subscription CLI calls log the CLI's own cost estimate as a shadow cost, kept apart from charged cost.

## Config (`config/settings.yaml`) — placeholders to fill before M2
```yaml
providers:        # G1a v1.2.1: subscription CLIs; no model API keys
  claude_cli: {type: claude_cli, binary: claude, send_params: [effort]}
  codex_cli:  {type: codex_cli,  binary: codex,  send_params: [effort]}
  local:      {type: openai_compatible, base_url: http://localhost:11434/v1}   # Ollama
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
  embeddings:      {provider: local, model: "<embedding-model>"}
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
coverage: {min_titles_with_module: 5, min_field_completion: 0.8}
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
  grid_dims: ["power_combat.gate", "power_combat.cost_of_power", "power_combat.progression"]
  operators: [reverse_incentive, redistribute_knowledge, transfer_cost, change_rule, combine_mechanisms, import_lane]
  h1_min_changed_dimensions: 2
  generations: 3
  candidates_per_generation: 12
  diversity_alarm: {champion_share: 0.40, cell_share: 0.10}
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
dilemma follow from the cost, and does the mechanic express the theme? Then evaluate each taste
criterion only with the required evidence.
```
