# Change plan: data-source controls, validation, and timing

**Status (2026-09-27):**
- **Part A (data sources and risk controls):** approved by Kingsley. Each item lands at the milestone named below.
- **Part B (validation and timing):** plan only. B1 (backtest) runs before blind review #1; B2–B5 come after it.

**Constraint for all of Part B (Kingsley, verbatim):**
> Snapshots and counts only. Each item is one command over stages that already exist. Demand signals are dated records from the existing AniList client, and every trend is a GROUP BY over them. No forecasting, no scoring models, no new services. The brief gets at most three lines of market context.

## How the agent captures signals
Every signal takes the same three steps the index already uses:
1. Take a dated snapshot.
2. Store it as a record.
3. Count it in DuckDB.

The agent never computes trends, predicts, or scores anything beyond counting. That keeps signals cheap, deterministic and easy to check.

---

## Part A: data sources and risk controls (approved)

| # | Control | What changes | Lands |
|---|---|---|---|
| A1 | **Reception data from MAL's official API** | New `catalog/reception.py`. MAL API v2 is primary for score, scorers, rank and popularity, sent with header `X-MAL-CLIENT-ID` from `.env` `MAL_CLIENT_ID`. Jikan is the fallback. Every response is cached for 30 days in `data/cache/reception/`. Records keep only those 4 numbers, the source and the date. GATHER uses them as outcome signals with the API URL as the source. MAL stays optional in the label rule: two independent sources settle a label. | with v1.7 |
| A2 | **Only deep-indexed titles fetch reception** | Only GATHER calls the reception client, which runs for titles going through the full pipeline. The census has no reception path, and a test enforces that. | with v1.7 |
| A3 | **AniList limits** | **Done** (`ea5569d`). One request per 2 s (30/min, the degraded limit), a 30-day disk cache, and the query asks only for fields we use. No bulk mirroring: the census reads at most 40 list pages, and demand snapshots (B2) read one list per season. | done |
| A4 | **The `animedex` PyPI package** | **Not found.** PyPI has no `animedex` project (404 on the JSON API and the simple index, and on 5 name variants), and web searches turn up only unrelated tools. Even if it existed, its name would clash with our own package. Recommendation: keep our catalog client (about 150 lines, metadata only, paced, cached, tested) and add A1. If you have a link to the package you meant, I'll evaluate that. | — |
| A5 | **Blind review fairness** | Every arm uses the same model (Opus 5.5), the same taste standard (T1–T5 and hard fail), the same steering rules, and the same web search: the prior-art check on the final cards. The only difference is index access. See decision 1 for how the two baselines differ. | M5 |
| A6 | **Provenance of winners** (M5 report) | For each greenlit card: its arm, the atoms it drew on and their source titles, and its principles (M7+). Also a count of greenlit cards that used no index material at all (baseline wins, plus any ANIMEDEX card whose atoms didn't reach the final text). Built by joining the ratings, the packet key and the idea records. | M5 report |
| A7 | **`make audit`** | Samples 10 random eligible atoms with their evidence trails (atom text, evidence refs resolved to profile fields, moments and episodes with source URLs, CHECK verdict history). Writes them to `eval/audit/audit_<date>.yaml` with a blank mark (true / plausible / wrong) for you to fill in. `make audit-report` then tracks the wrong rate over time and the extractor–critic disagreement rate per run (the share of atoms CHECK didn't accept first time). Blind rule: see decision 2. | M3 |
| A8 | **Flag for contested evidence** | An idea card that leans on an atom now contested (CHECK) or contradicted (episodes, M6) gets a visible flag in `ideas.md`, the amplify output and the M5 report. The flag is computed from the current status each time the report is written, so it appears as soon as an atom's status changes. It is not shown in the blind packet, where it would reveal the arm. | M5 |

**Your step for A1:**
1. Log in to MyAnimeList.
2. Open `https://myanimelist.net/apiconfig`.
3. Choose **Create ID**, with App Type "other" and non-commercial use.
4. Put the Client ID in `.env` as `MAL_CLIENT_ID=`.

It stays out of git and out of every log, and I never print it. Until it's there, GATHER uses AniList plus a critic source.

---

## Part B: validation and timing (plan)

Each item is one command. Calls are subscription calls under the usual caps (40 per run, 6 per title, 5 s pacing).

### B1. Retrodiction backtest: `make backtest` (runs before blind review #1)
- **Question:** does the index make the judge better at predicting how a new premise will land?
- **Titles:** 10 real titles that are not in the index, chosen from AniList (existing client). They are mid-popularity and recent (the last 3 years), with a mix of likely hits, mixed and flops. Recent, less-known titles limit what the model already knows. They're stored under `data/backtest/`, never in the corpus or the index.
- **Capture (existing stages only):**
  - GATHER and INTERPRET (v1.7/v1.8) produce each title's premise abstraction and power kit. Names are hidden, and the name-leak check runs on the judge's inputs.
  - Outcome labels come from the label rule (A1 reception data plus a critic source).
- **Use:** the existing judge predicts hit / mixed / flop twice per title:
  - (a) with a blank brief;
  - (b) with the index brief: the nearest existing titles and their labels, plus the failure patterns in that region.
- **Output:** one table with accuracy (a), accuracy (b), and the difference, plus per-title predictions. These titles aren't gold or partners, so they can be shown.
- **Calls:** about 3 per title for GATHER and INTERPRET (30), plus 4 judge calls (2 conditions × 2 batches of 5). About 34 in total, one run.
- **Machinery:** none new. One command over existing stages.
- **Depends on:** v1.7 + v1.8 (GATHER, INTERPRET, premise abstraction, power kit). The minimal index brief reuses the existing context functions (structural nearest titles, graveyard).
- **ACs:**
  - AC-BT-1: backtest titles never enter the corpus or canonical data.
  - AC-BT-2: the judge inputs contain no title names.
  - AC-BT-3: the report shows both accuracies and their difference.
  - AC-BT-4: a rerun with the same titles is served from cache.

### B2. Timing layer: `make demand` (monthly; after review #1)
- **Capture:**
  - One monthly snapshot from the existing AniList client: the top 50 titles of each of the last 8 seasons, with popularity and score. It's saved as `demand_snapshots.jsonl` records (`snapshot_date`, `season`, `anilist_id`, `title`, `popularity`, `score`, `format`, `country`).
  - Titles not yet tagged go through the existing census stage for their cell fields. That's counts only, about 5 calls a month.
- **Use:** one SQL view.
  - Saturation per cell is a count per season.
  - Trend is the last 4 seasons against the 4 before.
  - Breakouts are the biggest popularity gains between two snapshots.
  - The generate brief gets at most 3 lines: cells heating up, cells cooling down, recent breakouts.
  - Each idea card gets `why_now` (≤20 words) citing those snapshot record ids as evidence.
- **Dropped:** clip-view signals. They'd need a new service, which the constraint rules out.
- **ACs:**
  - AC-TM-1: snapshots are dated and append-only.
  - AC-TM-2: every trend line equals a GROUP BY query (a determinism test).
  - AC-TM-3: `why_now` cites snapshot ids.
  - AC-TM-4: the brief never has more than 3 market lines.

### B3. Taste panel: `make panel` (after review #1)
- **Capture:**
  - `make panel` turns the blind packet into one self-contained HTML file: no server, no accounts.
  - People pick the better card of each pair, then press "Download picks" to save a JSON file.
  - You send the file to 3–5 people and they send the JSON back.
- **Use:**
  - `make panel IMPORT=picks.json` merges each file into `eval/panel/`, with panelists numbered, not named.
  - The report counts wins per arm and each panelist's agreement with your picks.
- **ACs:**
  - AC-TP-1: the HTML works offline from a file.
  - AC-TP-2: an import rejects a packet mismatch.
  - AC-TP-3: the report is plain counts.

### B4. Serial readiness in amplify (after review #1)
- **Change:** one more amplify rung, a single prompt that returns:
  - a three-chapter skeleton, with the promise landing in chapter 1 and the payoff by chapter 3;
  - three logline variants.
- **Calls:** 1 per idea. Testing the loglines with real people stays manual, for example a poll or a Discord post.

### B5. Backlog: Roblox demand signal
The popularity of anime-style Roblox games as a sign of demand for power fantasies. The simplest version is a monthly manual list of the top anime-style games and their visit counts. Parked.

---

## Decisions for Kingsley (recommendations first)
1. **How the two baselines differ (A5).** Recommended:
   - Baseline 1 runs the same loop as ANIMEDEX (same prompt, operators, judge and prior-art check) with an empty brief. That isolates the index exactly.
   - Baseline 2 is a single "write N premises" call with the same model, taste standard and steering rules. It's the naive-use comparison.
   - No arm uses web search while generating; all arms get the same prior-art web check.
   - Alternative: keep the v1.6 web arm (web research while generating), and give ANIMEDEX's generate call the same web access.
2. **Audit and the blind rules (A7).** Every current title is gold or a partner, and their outputs stay hidden until the annotations are done or waived.
   - Recommended: `make audit` samples only titles outside gold and partners (backfill titles) until then, and covers everything after.
   - Alternative: allow audits of partner atoms now.
3. **Backtest size (B1).** Recommended: 10 titles in one run (about 34 calls). Alternative: 20 titles over 2 runs, for a steadier accuracy number.

## Order
- A3: done.
- A1 + A2: land with v1.7.
- A7: M3.
- A5, A6, A8: M5 (A6 appears in the M5 report).
- B1: after v1.7/v1.8 land, before blind review #1.
- B2–B4: after blind review #1.
- B5: backlog.
