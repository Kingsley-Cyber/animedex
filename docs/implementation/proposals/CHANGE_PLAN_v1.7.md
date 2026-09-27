# Change plan v1.7: gather-first P1, Qwen3 embeddings, compact context

**Status:** approved in principle by Kingsley (2026-09-27). Lands after the M2 report and before any M3 live run.
**Already landed during M2** (Kingsley asked for them in the M2 report): per-stage timing in the run logs (`animedex timing`), and detached, resumable batches with a status file (`make batch`, `make status`).

## 1. Gather-first P1
P1 splits into two calls.

| Step | Model | Web | Does |
|---|---|---|---|
| GATHER | cheapest plan model (`claude_cli` Haiku 4.5) | yes: Wikipedia first, then show wikis | Collects documented facts, each with its source URL: medium, format, scope and episode list, source material, studio, outcome signals, power-system basics (gate, cost, progression, visible counter, fight medium), moment locators. |
| INTERPRET | strong model (P1 slot, Sonnet 5; see decision 1) | no | Fills the analysis fields (core question, unserved appetite, borrowed template, broken rule, primary feeling, want vs. need, and so on) from the gathered facts only. |

- **Paraphrase only.** GATHER stores a short paraphrased value plus the URL per fact, never page text (the transient-text rule, 03).
- **Scope rule.** Wikis mix manga and anime. GATHER keeps only facts inside the title's scope, and marks any fact it can't place as `scope: unplaced`. Unplaced facts never reach INTERPRET as settled.
- **VERIFY shrinks** to fields still unsourced after GATHER. The M2 rules stay: `unresolved` is a result, there are no evidence retries, and visual details and moment episodes are checked for gold titles only.
- **Contract changes:** 04 adds a `gathered` candidate (fact path, value, source URL, scope status), and each lens field is tagged `documented` or `interpretive` in the vocab. 05 gets the GATHER/INTERPRET pass contracts and the budgets: GATHER takes at most 4 searches and 8 fetches; INTERPRET takes one call.

## 2. Embeddings: Qwen3-Embedding-0.6B on local Ollama
- Switch `embeddings` from `mxbai-embed-large` to `qwen3-embedding:0.6b` from the Ollama library (639 MB). It runs locally, so ANIMEDEX doesn't depend on Polymath's server. This is the one allowed local model; all generation and analysis stay on the subscriptions.
- If Ollama isn't running, the command stops with: "Ollama is not running. Start it (open the Ollama app, or run `ollama serve`), then run the same command again."
- **Recalibrate:** score about 10 known-similar and 10 known-different premise pairs, then propose new clone thresholds (today: cosine ≥ .90 with structural ≥ .55). Each model scores on its own scale. The proposal shows every pair's score; Kingsley approves the numbers.
- Title vectors are embedded fresh on every IDEATE run and never stored, so old vectors can't mix in.

## 3. Compact context
- Model inputs are compact structured slices (JSON or `key: value` lines), never rendered Markdown reports. The audit covers every `render_*` input, starting with `render_profile` for P2/P3.
- Input tokens are already logged per call (`usage.input_tokens`). The timing report adds input tokens per stage.

## 4. Measure it
- **Baseline:** M2's recall-first numbers: time per title (`build/reports/timing.md`), web correction rate (AC-13), and enum agreement (AC-12).
- **Re-run:** P1 for the 14 titles on gather-first, as a paced batch (max 3 titles at once). It takes about 28 calls over one or two runs under the 40-call cap.
- **Report both:** time per title, web correction rate, and enum agreement, with where the time went (startup, model, web, retries).

## Decisions for Kingsley (recommendations first)
1. **INTERPRET model:** Sonnet 5, the current P1 slot (recommended). It interprets well from given facts at about a third of Opus's time. Alternative: Opus 5.5 for INTERPRET on the gold titles only, as an A/B.
2. **Clone thresholds:** decided after the recalibration pairs are scored.
3. **Gathered facts:** kept as paraphrased value plus URL (recommended), or URL only.

## Order
v1.7 lands together with v1.8. The combined order and decisions are in `CHANGE_PLAN_v1.8.md` §7–8.
