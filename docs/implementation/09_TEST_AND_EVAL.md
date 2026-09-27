# 09 — Test and Eval

## Test layers
| Layer | What it covers | Where |
|---|---|---|
| Unit | Models, enum normalization, cache keys (incl. support-count exclusion), Jaccard, archive logic, episode selection, status transitions | `tests/unit/` |
| Contract | Schema validation, referential integrity, invariants from 04 | `tests/contract/` |
| Pipeline (offline) | Every stage on the mock provider with fixtures, including malformed JSON, off-vocab values, missing evidence, name leaks, scope leaks, recall-only episodes, surface-change idea cards | `tests/pipeline/` + `tests/fixtures/<pass>/<id>.json` |
| Determinism | Clean rebuild → identical table and CQ-answer hashes; ROLLUP twice → identical output | `tests/contract/` |
| Regression | Snapshot canonical data + CQ answers per milestone; diff after any prompt or vocab change | `eval/regression/` |
| Live smoke | One title (and in M6, one episode) through real providers, budget-capped | `make smoke TITLE=<id>` |

Fixtures are synthetic or paraphrased. No transcripts or copied text.

## Gold set (`eval/gold/`)
For each gold title, Kingsley records, **before seeing model output**:
- Scope (version, seasons in scope).
- Key P1 enum fields (gate, cost_of_power, progression, visible_counter, fight_medium, power_is, outcome).
- 3–5 load-bearing elements, in his own words, including the main engine in one sentence.

Metrics:
- P1 enum accuracy vs. gold.
- Load-bearing recall and precision vs. gold. Semantic matching is done by an LLM matcher, then spot-checked by Kingsley; the spot-check is recorded in the M3 completion report.
- Engine match: does the model's primary engine atom match Kingsley's one-sentence engine?

## Agreement (`eval/agreement/`)
- P1 run twice (same model at temperature > 0, or two models) → enum agreement. Bar: ≥ 0.80.
- P3 run twice → load-bearing verdict agreement. Bar: ≥ 0.70.
- Below the bar: tighten the field definition or add examples in the prompt. Never loosen the metric.

## Verification metrics
- Per field: share flagged for verify, share corrected by web.
- A high correction rate means recall can't be trusted for that field: add it to `always_verify`.
- Calibration (statistics as gates): per field, the Brier score of the extraction's own confidence (from its stored draft, D-022) against verified correctness (`web_confirmed` or `gathered` right, `web_corrected` wrong, `unresolved` left out), in `build/reports/verify_rates.md`.

## Compounding eval (M6+)
- **Status movement:** atoms moved to `episode_backed`, `mixed`, `contradicted`; contested atoms settled by episodes.
- **Promotions:** proposals promoted and how many survived P3/CHECK as load-bearing.
- **Derived-field conflicts:** where episodes overturned recall (another signal of recall weakness).
- **Highlight bias:** does each title's engine appear in its control episode? An engine seen only in highlight episodes is flagged.
- **Cost of compounding:** tokens per episode, and re-run tokens triggered by status changes.
- **Lift:** blind review #2 vs. #1 on the same baseline protocol.

## Ideation eval
- **Gate stats:** pass/fail per gate per generation, including H1 consequence-test failures (how often the generator produces surface changes).
- **Operator stats:** which operators produce champions, and which mostly fail gates.
- **Grid coverage:** occupied cells / total cells, and the distribution across cells.
- **Blind review protocol:**
  1. Generate three arms of 15 (v1.6, replacing 20 vs 20; arms per the M5 fair-baseline ruling, controls decision 1; `make ideas ARM=baseline_loop`, then `make packet`):
     - ANIMEDEX champions;
     - baseline 1: the same ideation loop with an empty brief (no atoms, titles or flops), its best card per cell;
     - baseline 2: one "write N premises" call.

     All arms use the same model, the same taste standard text, the same steering rules and the same length limits. No arm searches the web while generating; every packet card gets the same prior-art check, recorded in the answer key. Never loosen a gate to reach 15; with fewer cards in any arm, every arm shrinks to N.
  2. Strip metadata; format identically (logline + premise only).
  3. Shuffle. Kingsley rates each 1–5, marks "would greenlight" y/n, and tags any taste criterion met (T1–T5).
  4. Unblind and compare. Record in `eval/blind/<date>.json`. `make review-report` turns the ratings (and any panel picks in `eval/panel/*.json`) into Bradley–Terry strengths per card and per arm and scores the judge's own ordering against them (see Statistics below).
- Formatting must not leak which side a card came from (no atom IDs, no system vocabulary, no engine fields).

## Statistics (owner ruling 2026-09-27: statistics as gates)
Snapshots and counts only; pure arithmetic in `src/animedex/stats.py`, each inside the stage whose check it replaced (05). `make stats` collects them on one read-only page, `build/reports/stats.md`.

| Statistic | Where | Rule |
|---|---|---|
| Cohen's kappa per enum field, next to raw agreement | agreement eval (AC-12) | grid fields need kappa ≥ 0.8; kappa < 0.6 is unreliable and excluded from gaps and novelty pairs (undefined kappa, one category: judged on raw agreement, D-014) |
| Rule of three, 3/n | ANALYZE zeros, ideation adequacy, `borrow_system` | a zero is open only when 3/n < 0.02 over the relevant subset |
| Expected count n × p(x) × p(y) | ANALYZE grid gaps | expected ≥ 3 and none observed: a real gap; else unsurprising |
| PMI of the key pair (add-half, D-015) | IDEATE novelty gate | novel at PMI ≤ −1.0 on an adequate subset (D-021) |
| Entropy, normalized entropy, mutual information with outcome | ANALYZE report | normalized entropy < 0.5 flags a low-entropy field |
| Brier score | VERIFY report | per field; 0 is perfect, a constant 0.5 scores 0.25 (D-022) |
| Bradley–Terry strengths, ranking agreement | review import | from rating pairs (higher wins, ties skipped) and panel picks (D-017); the judge's fitness order is scored against them |
| Exact McNemar p-value, sample size needed | backtest | one-sided, on the titles only one brief got right; the smallest n where the same split reaches p < 0.05 (D-016) |

Tests check each function against hand-computed values (`tests/unit/test_stats.py`) and each stage's use of it on synthetic data.

## Cost eval
- Tokens and cost per title per pass, per episode, and per ROLLUP re-run; ideation cost per champion. Reported in every completion report.
