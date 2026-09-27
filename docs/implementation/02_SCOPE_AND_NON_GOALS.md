# 02 — Scope and Non-Goals

## In scope
**V1 (M0–M5)**
- **Media:** anime, donghua (Chinese animation; added v1.3), Western animation, adult animation, live-action series, film. Anime is roughly 50% of the corpus.
- **Title scope:** every title declares version/adaptation, seasons in scope, and episode numbering.
- **P1 lens:** core fields + modules switched on by content (`power_combat`, `relationships`, `sensory`, `anime_production`, `series_engine`, `comedy_satire`, `film`) + 3–5 moments per title.
- **Passes:** P1 WHAT, VERIFY, P2 WHY (effect + engine atoms, rival explanations), P3 PROOF (contrast, explanation test, ablation), CHECK, P4 TRANSFER (pattern + essential/variable/failure conditions).
- **Sourcing:** recall draft + targeted web verification.
- **Storage:** canonical JSONL; DuckDB build; derived CSV and Markdown reports.
- **Analysis:** coverage ledger, co-occurrence, gaps, imported/export lanes, graveyard lookup.
- **Ideation:** MAP-Elites with transformation operators, idea engines, consequence tracing, gates, and a judge. Target domain: anime premises.
- **Eval:** gold set, agreement, regression snapshots, blind baseline comparison.
- **Interface:** CLI + Makefile only.

**V1.1 (M6)**
- **Episode evidence layer:** key episodes only (pilot, moment episodes, a finale, one control episode) per title, from fetched summaries; rollup into atom support status; promotion of recurring new atoms; derived series-engine fields; setup/payoff links.

## Non-goals
| Non-goal | Why | Revisit when |
|---|---|---|
| Roblox and ad target domains | Keep V1 narrow | M9, after V1.1 wins blind review |
| Episode/beat generation | Premise quality first | M8 |
| Exhaustive episode indexing | Cost; key episodes carry most of the signal | A pattern card shows a gap only more episodes can fill |
| Recall-only episode records | Episode-level recall is unreliable | Never |
| Per-scene audiovisual analysis (framing, blocking, editing, shot choices) | Can't be done reliably without watching | Not planned |
| Neo4j or any graph DB | DuckDB handles 2-hop at this size | >300 titles or 3+ hop queries |
| Universal kernel/pack split | Premature without a second domain | Roblox work starts |
| Scraping, transcripts, subtitles, video analysis | Copyright and cost | Not planned |
| Frontend/UI | CLI is enough | After V1.1 |
| Fine-tuning | Not needed | Not planned |
| More than four analysis passes | Depth past transfer yields philosophy, not ideas | Evidence of a specific failure |
| Adding fields up front | Dilutes extraction quality | An idea-card failure a field would fix |
| Automatic ontology changes | Taste control | Never; human approval only |

## Future-domain readiness (must not block)
- P4 transfer atoms contain no proper nouns or medium-specific words.
- Idea cards carry `target_domain` (V1 value: `anime`).
- Domain vocabulary lives in `ontology/`, `config/`, and `prompts/`, never hardcoded in `src/`.

## Scope-change rule
Any change to this file requires Kingsley's approval, recorded in a completion report.
