# 03 — Architecture

## Flow
```text
corpus/titles.yaml  (each title carries its scope)
      │
      ▼
P1 WHAT ─► VERIFY          profile + moments; flagged fields checked on the web
      │
      ▼
P2 WHY                     effect atoms (with rival explanations) + 1–3 engine atoms
      │
      ▼
P3 PROOF                   contrast + explanation test + ablation → load-bearing
      │
      ▼
CHECK                      falsify: ACCEPT / REVISE / REJECT / CONTESTED / NEEDS_ADJUDICATION
      │
      ▼
P4 TRANSFER                domain-neutral pattern + essential / variable / failure conditions
      │
      ▼
CANONICALIZE ──────────────► data/canonical/*.jsonl   (source of truth)
      ▲                                  │
      │                                  ▼
ROLLUP ◄── EP (key episodes, M6)   BUILD ─► ANALYZE ─► IDEATE
 support status, promotions,         (DuckDB)            operators → engine → consequences
 derived series-engine fields;                            → gates → judge → MAP-Elites archive
 status changes re-run P3/CHECK/P4
 for the affected atoms only
```
Batch order: run P1 + VERIFY for every title in a batch before P3, because P3 needs its contrast partners' profiles. CANONICALIZE runs after P1 + VERIFY for the batch (P3 partner selection reads canonical P1) and again after P4.

## Breadth vs. depth
- **Breadth** = P1 fields: a small lens of core fields + modules.
- **Depth** = four analysis passes, each reading the previous pass's output.

| Pass | Question | Output | Cost |
|---|---|---|---|
| P1 WHAT | What is it? | Title profile + moments | Low |
| VERIFY | Is the recall right? | Corrected fields + sources | Low |
| P2 WHY | Why does it feel good, and why does it keep going? | Effect atoms + engine atoms | High |
| P3 PROOF | Is it real, which explanation holds, is it load-bearing? | Contrast, explanation test, ablation | High |
| CHECK | Can it be falsified? | Critic verdict per atom/proof | Medium |
| P4 TRANSFER | What's the domain-neutral pattern, and what can change? | Transfer atoms + conditions | Low |
| EP (M6) | What does this episode show about its show? | Episode record + atom support | Low per episode |
| ROLLUP (M6) | What changed in the show model? | Status transitions, promotions, derived fields | Mostly deterministic |

## Two atom kinds
| Kind | Shape | What it captures |
|---|---|---|
| Effect | element → feeling → because (+ rival explanation) | Why the audience keeps watching |
| Engine | goal → constraint → strategy → benefit + cost → dilemma (+ dramatic question) | Why the story keeps generating episodes |

A premise needs both: effect atoms make it addictive, engine atoms make it last.

## The compounding loop (M6)
Episodes are never free-floating. Each episode record belongs to one in-scope title and exists to strengthen, challenge, or extend that title's atoms.

1. **Support.** Each episode marks which show atoms it supports, contradicts, or reframes.
2. **Status.** ROLLUP turns that into a per-atom status: `profile_only` → `episode_backed` (support, no contradiction) → `mixed` (both) → `contradicted` (≥2 contradictions, no support).
3. **Economics.** A new supporting episode only updates counts; it spends no tokens. Only a status change (or a promotion) re-runs P3/CHECK/P4, and only for the affected atoms.
4. **Discovery.** Episodes propose new atoms. A proposal is promoted to a real atom only when ≥2 distinct episodes independently suggest it (induction threshold), then it goes through P3/CHECK/P4.
5. **Settling.** Atoms whose explanation CHECK marked `contested` are re-checked when new episode evidence arrives. Episodes are what settle them.
6. **Derivation.** Once ≥3 episodes (including the control) are indexed, series-engine fields are re-derived from observed episodes instead of recall.
7. **Cross-show.** Pilots, finales, and control episodes become comparable across the corpus (CQ-E02, CQ-E05).

Result: every episode added makes the show model more trustworthy, and the cost stays proportional to what actually changes.

## Where the original 13 layers live
| Layer | Location |
|---|---|
| Thematic | `core.core_question` (root; ideas anchor here) |
| Semantic / structural | Core fields |
| Procedural | `power_combat` module |
| Character | Core (`want_vs_need`, `flaw` + condition, `moral_line` + condition, `opposition_logic`) + engine atoms + episode decisions |
| Relationship | `relationships` module |
| Information economy | Core (`central_mystery`, `knowledge_gap`, `reveal_cadence`) + episode info shifts + setup/payoff links |
| Episodic | `series_engine` / `film` modules + episode records |
| Sensory | `sensory` module (documented signatures only) |
| Valence | Every atom's `feeling` + `core.primary_feeling` |
| Moment | Moments list, analyzed by P2/P3, anchored to episodes in M6 |
| Context/timing | `core.borrowed_template` + outcome confounders |
| Outcome | `core.outcome` + outcomes record |
| Associative | P3 contrast records + P4 bridge mappings + intra-title links |

## Modules switch on by content, not origin
`power_combat` runs for Avatar, Invincible, and The Boys as well as Bleach. `anime_production` is the only origin-gated module.

## Storage tiers
| Tier | Location | Rules |
|---|---|---|
| Raw runs | `data/raw/runs/<run_id>/` | Every request/response + token/cost log; fetched web text replaced by URL + sha256 + length; gitignored |
| Candidates | `data/candidates/` | Pre-canonical outputs per pass; gitignored |
| Quarantine | `data/quarantine/` | Invalid JSON, schema failures, rejected atoms, with reasons; gitignored |
| Canonical | `data/canonical/*.jsonl` | Source of truth; written only by CANONICALIZE and ROLLUP; atomic writes. **Versioned in the private data repo, not the public code repo (owner ruling 2026-09-27; replaces "canonical data lives in git"):** `make data-push` backs up data/canonical, data/blind, data/diagnose, eval/audit, eval/blind, eval/gold, steering/, seeds/ and studio/ to `Kingsley-Cyber/animedex-data`, after every batch run and every milestone tag. The data repo gets the same milestone tags as the code, so code and data versions always pair. `make data-pull` restores them. Cache and raw run logs are not backed up |
| Derived | `build/` | DuckDB, CSV, MD; gitignored; fully rebuildable |

## Repo layout
```text
animedex/
├── pyproject.toml
├── Makefile
├── README.md
├── .env.example                   # API keys (never committed: .env)
├── config/settings.yaml           # models, budgets, thresholds, verify and episode rules
├── corpus/titles.yaml             # corpus + scope + role tags + optional partner overrides
├── ontology/
│   ├── vocab.json                 # enums per field, alternate labels, cq_refs; versioned
│   ├── bridge.json                # domain-neutral bridge concepts; versioned
│   ├── competency_questions.yaml
│   ├── migrations/
│   └── proposals/                 # off-vocab proposals awaiting review
├── schemas/                       # JSON Schemas generated from pydantic models
├── prompts/
│   ├── p1_what.md
│   ├── p1_modules/*.md            # one fragment per module
│   ├── verify_web.md
│   ├── p2_why.md
│   ├── p3_proof.md
│   ├── check_critic.md
│   ├── p4_transfer.md
│   ├── ep_evidence.md             # M6
│   ├── rollup_match.md            # M6: matching proposed atoms
│   └── ideate_{generate,judge}.md
├── src/animedex/
│   ├── cli.py
│   ├── config.py
│   ├── models/                    # pydantic models = data contracts
│   ├── providers/                 # base, claude_cli, codex_cli, openai_compatible, anthropic, mock
│   ├── embeddings/                # base + local adapter
│   ├── search/                    # web verification + episode summary adapter
│   ├── pipeline/                  # p1, verify, p2, p3, check, p4, canonicalize, ep, rollup
│   ├── store/                     # jsonl io, atomic writes, cache
│   ├── build/                     # duckdb, exports, reports
│   ├── analyze/                   # coverage, cooccur, gaps, lanes, graveyard, episodes, patterns
│   └── ideate/                    # grid, operators, generate, gates, judge, archive
├── data/{raw,candidates,quarantine,canonical}/
├── eval/{gold,agreement,regression,blind}/
├── tests/{unit,contract,pipeline,fixtures}/
└── build/                         # gitignored
```

## Providers (local-first, no lock-in)
- One interface: `complete(system, user, json_schema, params) -> (json, usage)`.
- Adapters: `claude_cli` and `codex_cli` (subscription CLIs in headless mode), `openai_compatible` (covers OpenRouter, Ollama, vLLM, LM Studio, and hosted OpenAI-compatible APIs), `anthropic`, and `mock` (fixtures, for tests).
- Billing (G1a, v1.2.1): no model API keys. Every pass calls a model through Kingsley's subscriptions: `claude -p` on his Claude login for the Claude slots, `codex exec` on his ChatGPT login for CHECK and the judge. Ollama (through `openai_compatible` on localhost) serves embeddings and any pass later proven to work on a local model.
- CLI isolation, on every call:
  - The subprocess environment is an allowlist (HOME, PATH, locale, proxy/CA). It never carries `ANTHROPIC_*`, `OPENAI_*`, `CLAUDE*` or `CODEX_*` variables. An API key there would bill the API instead of the plan.
  - The call runs from a fresh, empty scratch directory with tools off and the pass prompt as the system prompt.
  - `claude` runs with `--safe-mode` (no CLAUDE.md, skills, plugins, hooks, MCP servers, memory), `--setting-sources project` (no user settings), `--strict-mcp-config`, and no session persistence. It never uses `--bare` (API-key only) or `--fallback-model`.
  - `codex` runs `--ephemeral` in a read-only sandbox with `--ignore-user-config` and `--ignore-rules`. Its shell, browser, apps, plugins and multi-agent features are off.
  - The init metadata of each call is logged and checked. Anything that still loads from user-level config is reported. For `codex`, that is `~/.codex/AGENTS.md` and the installed-skills list.
  - A login that uses an API key is refused.
- Provenance and cache keys use the provider identity (`claude_cli@<cli version>`) plus the model that actually served the call.
- Model per pass is configuration, not code. Cheap models for P1/P4/EP; strongest model for P2/P3/CHECK.
- CHECK and the ideation judge should use a different model family from the one that produced the work, when available.
- All pass calls are single-turn. If a future step uses multi-turn tool calls with a thinking model, the adapter must preserve reasoning content across turns; some OpenAI-compatible clients strip it and the provider rejects the follow-up.
- Structured output: use native JSON-schema mode when supported; otherwise validate + one repair attempt.
- Embeddings: separate adapter; default is a local model (config). Used for premise similarity and for matching proposed atoms in ROLLUP.

## Web sources
- Backend is config. `native` (G1a, v1.2.2) means the VERIFY model searches with its CLI's own WebSearch/WebFetch tools. There is no search API and no key.
  - These are the only tools such a call gets: pre-approved, with a hard turn limit.
  - A citation counts only if that call's own tool traffic retrieved the URL.
- API backends keep the adapter interface `search(query) -> results`, `fetch(url) -> text`.
- Used for field verification (VERIFY) and episode summaries (EP).
- Web text is used transiently and never stored. Only paraphrased values (≤60 words for episode summaries) and source URLs are kept.

## Ideation engine (MAP-Elites)
- **Grid:** 2–3 dimensions. V1 default: `power_combat.gate × power_combat.cost_of_power × power_combat.progression`. M7: dimensions from mechanism-atom clusters.
- **Atom pool:** load-bearing transfer atoms whose explanation is settled and whose support status is `profile_only` or `episode_backed`; episode-backed atoms preferred.
- **Loop:** pick a theme root → pick atoms → apply one transformation operator (reverse the incentive, redistribute knowledge, transfer the cost, change the rule, combine mechanisms, import a lane), respecting each atom's essential conditions → write the card with its own engine and traced consequences → deterministic gates (clone, novelty, graveyard) → judge (H1 consequence test, failure conditions, coherence, taste with evidence) → place if the cell is empty or the card beats the incumbent → repeat.
- **Output:** best idea per cell + the empty-cell map.

## Design principles
1. Canonical JSONL is truth; everything else rebuilds.
2. No domain vocabulary in `src/`.
3. One title (or one episode) per call; fixed, cacheable system prompts; JSON only; enums wherever possible; inactive modules omitted.
4. Every stage is idempotent and cache-keyed.
5. Prefer no atom over a weak atom.
6. Episodes are evidence for their show, never free-floating.
7. Only status changes spend tokens.
