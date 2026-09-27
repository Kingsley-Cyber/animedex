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

### Reception data (approved controls A1–A3, `CHANGE_PLAN_controls_validation_timing.md`)
- GATHER's outcome signals come from APIs, not page scraping:
  - MAL API v2 is primary (score, scorers, rank, popularity; client ID `MAL_CLIENT_ID` in `.env`), with Jikan as the fallback.
  - AniList supplies its score and popularity.
  - All of it is cached for 30 days.
  - One critic source from the web completes the two-source label rule. MAL stays optional.
- Only deep-indexed titles fetch reception data; the census never does.
- AniList is paced at 30 requests/min and cached (already done).

### Grid reliability (owner ruling, 2026-09-27)
- Every value of gate, cost_of_power, progression and visible_counter gets a one-sentence **discrimination test**: what makes this value right and its nearest neighbour wrong. The tests live in `vocab.json` (per value) and are rendered into the P1/INTERPRET prompts.
- cost_of_power carries a **primary** value and an optional **secondary** one (schema change).
- After v1.7, AC-12 is re-run. **Hard rule:** no grid dimension may have per-field agreement under 0.80. If progression can't reach it, a replacement axis is proposed (set_structure, after v1.8).
- The 7 pending enum proposals are applied with the agent's recommendations (new value, merge into an existing value, or reject) and listed in the M3 report without title attribution (blind rule).

### Scopes (owner ruling)
A series defaults to its full completed run, all aired seasons. Avatar, Jujutsu Kaisen, Demon Slayer, Mob Psycho 100, Invincible and The Boys are widened and re-profiled in the combined run. Their recall-first rows are season-1 baselines, so their time and agreement comparisons are marked as scope-changed.

### Models (owner decisions)
- INTERPRET runs on `claude-opus-5-5` at effort **medium**.
- An **effort A/B** (medium vs high) runs on 3 titles for gather-first P1 and INTERPRET. It reports agreement and time.

## 2. Embeddings: Qwen3-Embedding-0.6B (owner decision 2026-09-27: Polymath's GPU copy first, Ollama as fallback)
- **Primary:** Polymath's embedder sidecar at `127.0.0.1:8742` (`POST /infer`). It already runs the same model (Qwen/Qwen3-Embedding-0.6B) at full precision on the Mac GPU, so ANIMEDEX adds no second copy and no GPU contention. Requests carry no priority header, so they run at background priority and never get ahead of Polymath's interactive work.
- **Fallback:** the local Ollama copy `qwen3-embedding:0.6b` (pulled 2026-09-27, 639 MB, loaded only when used). A run picks one backend at start and never mixes them.
- If neither is up, the command stops with a clear message naming both.
- **Recalibration** runs on the primary. When the fallback is reachable, it also reports the largest per-pair difference between the two backends.
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
