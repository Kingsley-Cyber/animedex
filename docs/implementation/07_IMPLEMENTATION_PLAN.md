# 07 — Implementation Plan

Build a thin vertical slice first: 5 titles end to end (M1–M5). Then make it compound with episodes (M6). Scale only after both beat the baseline.

```text
M0 Audit → M1 Foundation → M2 P1+Verify → M3 P2–P4+Check → M4 Analyze → M5 Ideate (first E2E)
                                                                              │
                                                     M6 Episode evidence (compounding)
                                                                              │
                                                     M7 Scale + calibrate + pattern cards
                                                                              │
                                             M8 Episode generation → M9 Target domains (deferred)
```

**Why episodes come after the first E2E:** the show-level slice has to prove it beats a plain prompt before anything is layered on top, and the M5 result gives M6 a baseline to measure lift against. Episodes come before scaling so every title added in M7 compounds from day one.

## M0 — Audit the existing repo
- Compare the current ANIMEDEX repo against 03, 04, and 05. Produce `docs/implementation/M0_GAP_REPORT.md` listing **reuse / adapt / replace** per component.
- Expected reuse: canonical JSONL, schemas, atomic writes, critic, DuckDB build, cache keys.
- Expected replace: layer-by-layer extractors (L0/L2/L3) → P1 core + modules and passes P2–P4. Map existing layer fields onto P1 fields where they match.
- **Exit:** gap report approved by Kingsley. No code changes in M0.

## M1 — Foundation
- `pyproject.toml`, Makefile, `config/settings.yaml`, `.env.example`.
- Pydantic models for every contract in 04 (including episodes, links, and patterns, even though their stages come later); `make schemas` generates JSON Schemas.
- `vocab.json`, `bridge.json`, `competency_questions.yaml` + field→CQ coverage table.
- JSONL store with atomic writes; cache (with the support-count exclusion rule); run logging (tokens, cost).
- Provider interface + `openai_compatible`, `anthropic`, `mock` adapters; embeddings adapter; search adapter interface.
- CLI skeleton with every command in 05 (later stages may be stubs).
- DuckDB build from canonical; `make validate`, `make build`, `make clean-build`, `make test`.
- **Exit:** AC-01 to AC-08.

## M2 — P1 + VERIFY on the gold set
- **Gold set (5):** Solo Leveling, Fullmetal Alchemist: Brotherhood, Hunter x Hunter (2011), plus 1 mixed and 1 flop. The mixed and flop picks are proposed from **verified** reception data (not recall) and approved by Kingsley.
- **Scope** declared for every title; Kingsley approves gold-title scopes.
- **Partner batch:** P1 + VERIFY on ~5–8 extra titles so each gold title has a nearest neighbor, a flop, and (for anime) a cross-medium partner.
- Kingsley fills gold P1 key enum fields in `eval/gold/`, blind.
- **Exit:** AC-09 to AC-13.

## M3 — P2, P3, CHECK, P4 on the gold set
- Effect atoms with rival explanations; 1–3 engine atoms per title; explanation test; `CONTESTED` handling; transfer conditions.
- Before running, Kingsley lists 3–5 load-bearing elements per gold title in `eval/gold/`, blind.
- **Exit:** AC-14 to AC-20.

## M4 — Analyze
- Coverage, co-occurrence, gaps, imported/export lanes, graveyard; CQ answers saved; determinism check.
- With 5 titles, most gaps should correctly report "insufficient coverage." M4 proves the machinery, not findings.
- **Exit:** AC-21 to AC-24.

## M5 — Ideate (first end-to-end checkpoint)
- MAP-Elites on the V1 grid with the six operators, idea engines, consequence tracing, and all gates; 3 generations under the budget cap.
- **Baseline:** same model, plain prompt that includes the taste standard: "generate N original action anime premises." Same N, same length limits.
- **Blind review #1** (see 09).
- **Exit:** AC-25 to AC-30. If ANIMEDEX does not beat the baseline, diagnose before continuing (see 11).

## M6 — Episode evidence layer (compounding)
- EP on key episodes for each gold title: pilot, up to 3 moment episodes, a finale, one control episode (cap 6).
- ROLLUP: support statuses, promotions, targeted re-runs, derived series-engine fields, setup/payoff links; moment locators linked to episode IDs.
- Episode analytics (CQ-E02, E05–E08).
- Re-run ideation on the updated index; **blind review #2**; report lift vs. #1 and a compounding report (atoms whose status changed, promotions, contested atoms settled, derived-field conflicts).
- **Exit:** AC-31 to AC-37.

## M7 — Scale, calibrate, and pattern cards
- Corpus to ~40 titles: ~20 anime (including 3–4 mixed/flop), 5 Western animation, 5 adult animation, 5 live action, 5 film. Key episodes per the selection rule for every series title; films have no episodes.
- Recalibrate gate and episode thresholds from observed distributions; document them.
- Mechanism-atom clustering (embeddings) → pattern cards with counterexample search; test cluster-based grid dimensions against the V1 grid.
- **Blind review #3.**
- **Exit:** AC-38 to AC-42.

## M8 — Episode generation
- First-episode and arc skeletons for elite ideas, built from hits' pilot structures, engine atoms, decision shapes, and setup/payoff patterns.
- Fight briefs (CQ-E03): moments + power_combat + sensory → reference sheets for fight-scene animation prompting.

## M9 — Target-domain readiness (deferred)
- Roblox and ads as target domains. The kernel/pack split happens only when this starts.

## Seed corpus suggestions (editable; roles confirmed in VERIFY)
| Medium | Titles |
|---|---|
| Anime | Solo Leveling, Fullmetal Alchemist: Brotherhood, Hunter x Hunter (2011), Jujutsu Kaisen, Demon Slayer, Chainsaw Man, My Hero Academia, Dragon Ball Z, Bleach, Naruto, Mob Psycho 100, One Punch Man, Attack on Titan, + mixed/flop picks from verified data |
| Western animation | Avatar: The Last Airbender, Gravity Falls, Arcane, + 2 |
| Adult animation | Invincible, BoJack Horseman, Rick and Morty, Castlevania, + 1 |
| Live action | Breaking Bad, The Boys, Stranger Things, + 2 |
| Film | Spider-Man: Into the Spider-Verse, Mad Max: Fury Road, John Wick, + 2 |
