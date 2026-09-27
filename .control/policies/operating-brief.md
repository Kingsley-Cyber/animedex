# Operating brief — ANIMEDEX build (owner prompt)

- **Source:** Kingsley's session prompt, 2026-09-26, stored verbatim below.
- **Authority:** DECLARED/HUMAN. Change only on the owner's instruction.
- **Harness:** URCP (owner instruction 2026-09-26: "use the control plane repo on my github to do this").
- **Spec:** `docs/implementation/` v1.1 is the source of truth; this brief governs how the agent works through it.

---

ROLE
You are the lead engineer building ANIMEDEX in this repo. The spec in docs/implementation/ is the
source of truth. Before doing anything, read in this order: CHANGELOG.md, 00, 02, 03, 04, 05, 06,
07, 08, 10, 11. At the start of every milestone, re-read that milestone in 07 and its ACs in 08.

GOAL
Deliver V1: the thin vertical slice, M0 through M5, end to end. Done means:
- AC-01 through AC-29 pass (08).
- `rm -rf build && make build` reproduces identical CQ answers.
- The M5 blind-review packet is ready for me (per 09): 20 ANIMEDEX elite idea cards + 20 baseline
  premises, shuffled, identically formatted, with no metadata that reveals which is which.
AC-30 closes after I complete the review and you record the results. Do not start M6 until I
approve the M5 results.

HOW TO WORK (every milestone)
1. Plan: list the files you'll create or change and the ACs each one satisfies. Keep it short.
2. Contracts and tests first: models, fixtures, failing tests.
3. Implement the thinnest version that passes the ACs. No gold-plating, nothing from 02's non-goals.
4. Verify: make validate, make test, clean rebuild. Fix until green. Never weaken, skip, or delete
   a test to make it pass.
5. Write the completion report (12) at docs/implementation/reports/M<n>_REPORT.md, commit, and tag
   m<n>-complete.
6. Continue to the next milestone automatically unless a human gate below is open.

HUMAN GATES (the only times you stop)
Batch everything you need from me into one "Decisions needed" list, each item answerable in one
line. Don't ask mid-milestone unless you are truly blocked.
- G0, after M0: I approve the gap report. M0 changes no code.
- G1, during M1 (prepare these, then keep building while I fill them):
  a. config/settings.yaml placeholders and .env.example: list exactly what I need to fill
     (models per pass, budget caps, search backend, API keys).
  b. Propose the gold set's mixed and flop titles from VERIFIED reception data, with sources,
     and a scope (version, seasons, numbering) for all 5 gold titles. I approve.
  c. Create blank annotation templates in eval/gold/ for each gold title: key P1 enum fields,
     3–5 load-bearing elements, and the main engine in one sentence. I fill them blind.
- G2, before any live run on a gold title: that title's annotation files must be filled and
  committed. Check them yourself. If a title's files are empty, keep working on everything else
  and wait on that title only. Never show me model output for a gold title before its
  annotations are committed; that breaks the blind test.
- G3, at each milestone end: ontology proposals, NEEDS_ADJUDICATION items, and unsettled
  CONTESTED atoms, listed in the report for my decision.
- G4, after M5: I complete the blind review; you compute and record the results.

DECIDE WITHOUT ASKING
- Implementation details inside the contracts: code layout within src/, libraries from the
  default stack, internal design, test structure.
- P3 partner titles, chosen by the deterministic rule in 05.
- Fixes to bugs you introduced.
Anything that changes a contract (04), a threshold, the taste standard, scope (02), or adds a
field, module, operator, or pass: propose it in the report. Don't do it.

COST AND SAFETY
- Develop against the mock provider. Live calls only for `make smoke` and milestone runs on the
  gold set and its partners, within the budget caps. If a cap is hit, stop cleanly and report.
- Secrets only in .env. No transcripts, subtitles, dialogue, or copied text anywhere. Paraphrase.
- Recall is not verification. Stay inside each title's scope.

STOP AND ASK IMMEDIATELY IF
- two docs conflict, or this prompt conflicts with a doc,
- an AC looks impossible as written,
- any data would be deleted,
- a budget cap is hit.

START NOW
Begin M0: audit the existing repo against 03, 04, and 05 and write
docs/implementation/M0_GAP_REPORT.md, marking each component reuse / adapt / replace, including
how any existing layer extractors map onto P1 fields and passes P2–P4. Then give me the G0
decision list.

---

## Owner rulings (G0, 2026-09-26)
- **URCP never blocks ANIMEDEX.** URCP issues live in their own task. If the harness gets in the way, the spec's own gates (`make validate`, `make test`, completion reports) are enough to proceed.
- **GitHub:** private repo; push after each milestone tag.
- **G1 blocks every M2 live run** (Beads `animedex-b1o.5.1`). The blind is also enforced in code: a live run on a gold title refuses to start unless that title's `eval/gold/` annotation files are filled and committed.
- **Naming:** the code's archive status is `champion`. "Elite" is reserved for Kingsley's verdict.
- **Blind packet:** 20 champions vs. 20 baseline premises, up to the budget cap. Never loosen a gate to reach 20; if the cap hits first, review N vs. N.
- **Data tiers:** only `data/canonical/` is committed.
- Spec amendments from G0 are in `docs/implementation/CHANGELOG.md` v1.2.

## Standing rule: change control (Kingsley, 2026-09-26)
Typo fixes and clarifications can be applied directly. Any change that touches a contract, the scope, or more than one doc gets a change plan (`docs/implementation/proposals/`) and Kingsley's approval first, and never lands mid-milestone.

## Owner rulings (G1, 2026-09-26)
- **Models:** p1/verify on Sonnet 5 (recall quality needs a recent knowledge cutoff); p2/p3/ideate_generate on Opus 5.5; p4/ep/rollup_match on Haiku 4.5; check and ideate_judge on a non-Claude model via OpenRouter, chosen before M3. Every model id must resolve through the provider's models API before its first live run (`animedex smoke`).
- **Fallbacks never change the model silently:** provenance records the model that actually served each call; a substituted answer is never cached; CHECK and the judge are strict slots that refuse any substitution (never cross model families).
- **Keys** live only in `.env`, pasted by Kingsley. OpenRouter is the OpenAI-compatible endpoint. Search: Brave. Caps: $25/run, $3/title, $0.25/episode.
- **Partner runs** start as soon as G1a closes. Report only cost, errors, and verify stats; never show partner or gold profiles before the gold annotations are committed.
- **Gold annotations** come from Kingsley's own viewing, in his own words, without AI help (`eval/gold/README.md`).

## Owner ruling (G1a providers, 2026-09-26): subscriptions, no model API keys
Supersedes the provider, key and dollar-cap lines of the G1 rulings. The model choices stay the same. This is a G1a decision, so it lands inside M2. It changes providers, config and budget wording, not data contracts (CHANGELOG v1.2.1).
- **Providers:**
  - `claude_cli`: `claude -p` on Kingsley's Claude subscription login. Never `--bare`, which is API-key only.
  - `codex_cli`: `codex exec`, ephemeral, read-only sandbox, on his ChatGPT plan login. This is the non-Claude family for CHECK and the judge.
  - Ollama: embeddings, and any pass later proven to work on a local model.
- **Slots:**
  - p1, verify: Sonnet.
  - p2, p3, ideate_generate: Opus.
  - p4, ep, rollup_match: Haiku.
  - check, ideate_judge: codex.
  - embeddings: Ollama. Pull a local embedding model before M5.
- **Isolation:** strip `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from every CLI subprocess, since either one switches billing to the API. Run each call from an empty scratch directory, with tools off and the pass prompt as the system prompt. Check the init metadata and report anything from user-level config that still gets in.
- **Provenance and cache keys** record the CLI name, CLI version and served model.
- **Budget:** CLI providers use call caps per run and per title instead of dollar caps. Each call's reported cost is logged as a shadow cost. On a rate-limit error, stop cleanly and resume from cache later. A pipeline run must not exhaust the limits Kingsley's coding sessions need.
- **First live step:** one tiny test call per provider, then stop. Kingsley checks his usage dashboards to confirm the calls counted against the subscriptions, not API billing, before any partner run.
- **.env:** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` stay empty.
- **Follow-ups (Kingsley, 2026-09-27):**
  - Upgrade codex, but use an older model for CHECK and the judge, since the task is simple. They run on `gpt-5.6-terra` (codex-cli 0.157.1).
  - Call caps confirmed at 40 per run and 6 per title.
  - Search: VERIFY uses the model harness's own web search (claude's WebSearch/WebFetch). There is no Brave, SearXNG, or search key (CHANGELOG v1.2.2).
  - Gold: Kingsley has seen SAO. Big Order stays pending until he says what he has watched, since the annotations must come from his own viewing.

## Owner ruling: autopilot (Kingsley, 2026-09-27)
> Switch to autopilot. Goal: I send a plain list of anime titles and get idea cards back. Build everything needed for that, without waiting on me.
> Scope: finish M2 through M5, plus the v1.6 census and prior-art check. Then build `make backfill LIST=<file>` (one title per line: resolve each title to a catalog entry with scope, run the full pipeline, report counts only; for ambiguous titles pick the most-watched adaptation and list the choices in the report; warn, without blocking, if the list is all hits or all anime and suggest flops and non-anime titles), `make ideas` (cards to build/reports/ideas.md), and a one-page plain-language USAGE.md.
> Decisions: use your own recommendations for everything pending (v1.3 failure_level, the v1.6 section 7 items, the change plan). Plan the Studio but don't build it yet. Change request A stays deferred.
> Gold set: pick the flop yourself from verified reception data. Annotations are now optional: gold runs may proceed, but never show me gold-title outputs (counts only) until I say "annotations done" or "annotations waived". Mark any AC that depends on my input as "deferred (owner: Kingsley)", not failed, and keep going.
> Blind review: prepare the packet when M5 is done, including both baselines, but don't block on it.
> Only stop for: plan limits or budget caps (pause and tell me how to resume), deleting data, anything that would change the taste standard, or a conflict your own recommendation can't resolve. All existing safety rules stay: subscription-only CLIs, paraphrase only, scope, and no copied text.
> Updates: one short plain-language message per milestone: what's done, what's next, and anything I must do (ideally nothing).

**Decisions recorded under this ruling (the agent's recommendations):**
- **v1.3 `failure_level`:** lands at the M2→M3 boundary, with an outcome-only re-verify. Hits carry null; mixed and flop require a value. A `failure_level_override` in `corpus/titles.yaml` is allowed.
- **v1.5 Studio:** planned, not built. Its docs, models and stages land when M8 starts. Its decisions 6–10 follow the plan's recommendations.
- **v1.6:** approved with the section 7 recommendations:
  - Catalog: AniList, assuming personal use; if ideas will be sold, switch to Wikidata.
  - Census: the top 500 franchise roots from 1995–2026, stored as `census_entry` in `data/canonical/` with `trust: recall`, counts only, no premise line.
  - Haiku only if its accuracy is ≥0.80 and within 5 points of Sonnet.
  - A runway "no" means rework once, then reject.
  - `borrowed_system` is a census-only label.
  - Pairwise picks use the CLI.
  - Minimum operator share at M7 is 5%.
  - The concept bible comes after blind review #1.
  - The new operators and stages are owner-approved exceptions, re-judged at M7.
- **Gold flop:** Platinum End (2021), the backup chosen from verified reception data in `eval/gold/G1B_PROPOSAL.md`.
  - Big Order stays in the corpus as a non-gold flop, which adds graveyard and revival evidence.
  - Future Diary becomes Platinum End's nearest neighbor: both are god-candidate battle royales.
- **Gold blind:** gold live runs are allowed without annotations. Gold-title outputs are shown only as counts until "annotations done" or "annotations waived". ACs that need Kingsley's input are marked "deferred (owner: Kingsley)".

## Owner ruling: priority order, scope frozen until blind review #1 (Kingsley, 2026-09-27)
- **Critical path, the only build work until blind review #1:**
  1. M2 finish.
  2. v1.3 `failure_level` (between M2 and M3).
  3. M3, then M4.
  4. The v1.6 census and prior-art check.
  5. M5, then the blind-review packet.
- **Donghua:** the vocab change lands at a milestone boundary (the census needs it). Deep-indexing donghua waits.
- **Backfill and ideas:** building `make backfill` and `make ideas` stays in scope. Running the big backfill queue waits.
- **Blind-review page:** a small local page on localhost only. Shuffled cards, a 1–5 rating, greenlight y/n, and T1–T5 tags; keyboard-driven; ratings saved to `eval/blind/`. Not the full dashboard. This is an owner exception to the 02 "no UI before V1.1" non-goal.
- **Parked** (planning is fine; build nothing until Kingsley has seen blind review #1 results):
  - change request A (MCP chat + commentary + `search_atoms`);
  - change request C (dashboard);
  - change request B (Studio);
  - M6 episodes;
  - the storyboard spike (it never started, so it stays parked);
  - the big backfill run;
  - URCP fixes beyond what is already done.
- **After blind review #1:**
  - If ANIMEDEX beats both baselines: A, then backfill priority 1, then M6, then C, then storyboards, then the Studio. Kingsley confirms the order then.
  - If it loses to either baseline: stop building and diagnose, in the order in doc 11.
- **Updates:** short and plain, one per milestone.

## Owner ruling: evidence order, word caps, sources (Kingsley, 2026-09-27)
- **Order:** the work branch is merged to main. Live runs go strictly in milestone order: finish M2 (re-run the quarantined titles on the fixed code), file and tag the M2 report, then M3 live on the gold set, then M4, the census, and M5. Check each milestone's ACs and metrics before the next one consumes its output. No live run on code that is behind a known fix.
- **Word caps:** before spending more retries, report which fields overflow the 12-word cap and how often. Per-field caps are a contract change for Kingsley's approval. Never retry until outputs happen to fit.
- **Sources:** pipeline code must not scrape MyAnimeList pages. Use AniList, Jikan, or MAL's official API. Web calls block myanimelist.net fetches, and its pages are never admissible citations.
- **Queue:** Dragon Raja added to the donghua list.
- **Word caps (approved):** P1 phrases 15 words, 20 for the eleven two-part fields (vocab 1.4.0).
- **Stop chasing confirmations:** `unresolved` is a result. VERIFY never retries for evidence. Visual details and moment episodes are verified for gold titles only. Two independent reception sources settle an outcome; MAL is optional. None of this blocks M2; v1.7 gather-first sources these fields up front.
- **Batch runs:** up to 3 titles at once, as detached jobs with a status file; they pause on plan limits and resume on the next run. Run logs record per-stage timing, and the M2 report shows where the time goes.
- **v1.7 (approved in principle):** plan now; land after the M2 report and before any M3 live run. Embeddings stay, switched to Qwen3-Embedding-0.6B on local Ollama (the one allowed local model).
- **v1.8 (requested 2026-09-27, consolidated):** concept, character and abstract layers (`docs/implementation/proposals/v1.8_request.md`, plan `CHANGE_PLAN_v1.8.md`). Lands with v1.7 before any M3 live run. Then the 14 titles are re-extracted for the new fields (partial re-runs only), and `make backfill` captures everything for new titles. **Lean rule:** this completes the V1 lens; no further fields until blind review #1.

## Owner ruling: data sources and risk controls (Kingsley, 2026-09-27, approved)
- **Reception:** the MAL API v2 is primary (`MAL_CLIENT_ID` in `.env`), Jikan is the fallback, cached monthly. MAL stays optional in the label rule. Only deep-indexed titles fetch reception; the census never does.
- **AniList:** stay under 30 requests/min (the degraded limit), cache everything, store only the fields used, no bulk mirroring.
- **The `animedex` PyPI package:** evaluate it as a replacement for the catalog client. Finding (2026-09-27): no such package exists on PyPI; the hand-written client stays.
- **Blind review fairness:** baselines get the same model, taste standard, steering rules and web search as ANIMEDEX; the only difference is index access.
- **Reports and audit:** the M5 report gets a provenance-of-winners section. `make audit` (10 atoms with evidence trails, marked true/plausible/wrong in `eval/audit/`) tracks the wrong rate over time and the extractor–critic disagreement per run. Idea cards that lean on contested or contradicted atoms carry a visible flag.

## Owner ruling: validation and timing (Kingsley, 2026-09-27, plan now)
- The backtest runs before blind review #1; the timing layer, taste panel and serial readiness come after it; the Roblox demand signal is backlog. Plan: `docs/implementation/proposals/CHANGE_PLAN_controls_validation_timing.md`.
- **Constraint:** snapshots and counts only. Each item is one command over stages that already exist. Demand signals are dated records from the existing AniList client, and every trend is a GROUP BY over them. No forecasting, no scoring models, no new services. The brief gets at most three lines of market context.

## Owner ruling: snapshot review, corrections and decisions (Kingsley, 2026-09-27)
- **Before M3 live runs:**
  1. **Grid reliability.** Every value of gate, cost_of_power, progression and visible_counter gets a one-sentence discrimination test, in the prompt and in vocab.json. cost_of_power carries a primary value plus an optional secondary. Re-run AC-12 after v1.7. Hard rule: no grid dimension with per-field agreement under 0.80. If progression can't reach it, propose a replacement axis (set_structure after v1.8).
  2. **Scopes.** A series defaults to its full completed run (all seasons). Widen Avatar, Jujutsu Kaisen, Demon Slayer, Mob Psycho, Invincible and The Boys, and re-profile them in the combined v1.7 + v1.8 run.
  3. **Fixes (done 2026-09-27):** the IDEATE cache key includes the corpus lists; canonicalize is per-title transactional; cache reads are logged next to input tokens.
- **Before M5 live runs:**
  4. **Brief assembly lands in M5:** opaque atom ids (no source titles); only the nearest 10 titles and the graveyard rows in the target region; plus the cell's adequacy, lane and prior-art evidence. The brief is capped and its tokens are logged.
  5. **Census-backed novelty** needs at least 200 powered census rows. Until the census runs, novelty rests on bridge-concept pairs only.
  6. **The judge evaluates `why_different`** on graveyard matches; "not blank" is not a pass.
  7. **Baselines** get the same model, taste standard, steering rules and web tools as ANIMEDEX. If they don't, fix the baseline prompts before the packet.
  8. **Ideation call cap:** 60 per run, so one run covers three generations.
- **Decisions:**
  - Word caps: the per-field caps stay. New v1.8 phrase fields default to 15 words; the listed ones get 20.
  - One combined 14-title run for v1.7 + v1.8: yes.
  - The current canonical data stays until the gather-first comparison is reviewed.
  - INTERPRET runs on claude-opus-5-5 at effort medium. Run the effort A/B (medium vs high) on 3 titles for gather-first P1 and INTERPRET, and report agreement and time.
  - Steering: `steering/rules.yaml` with id, rule, hard|soft, and 1–2 examples. Every card lists the rules it satisfies.
  - AC-12 stays gated on v1.7 plus item 1.
  - The 7 enum proposals: apply the agent's recommendations and list them in the M3 report.
  - URCP branch: push OK (pushed 2026-09-27; no PR opened).

## Owner ruling: backups, open questions, diagnose (Kingsley, 2026-09-27)
- **Backups:** the private repo `Kingsley-Cyber/animedex-data`, with `make data-push` and `make data-pull`. Contents: data/canonical, data/blind, eval/blind, eval/gold, and later ideas, archive and studio/; plus steering/, seeds/ and data/diagnose/ (Kingsley's own inputs). Cache and raw run logs are skipped. Push after every batch run and every milestone tag, and tag the data repo with the same milestone tags as the code. Doc 03 records this as the replacement for "canonical data lives in git".
- **Open questions:** go with the agent's recommendations. One guard: the audit samples from non-gold titles only until the annotations are done.
- **`animedex diagnose` (M5, small; reuses the M5 gates and judge):** a concept as text, from a file or pasted, goes through one structuring call that turns it into an idea card (logline, premise, engine, profile, closest existing title). The card is stored in the private data repo, never the public repo. Every gate and the judge run on it exactly as on generated cards, plus an ablation pass over its own parts (which atom is load-bearing?). Output: one line per check (pass or fail, and why), and a prescription for each failure, mapped to an operator or a concept-ladder rung. The full rebuild (`amplify`) stays in the post-review plan.
- **Embedder (Kingsley, 2026-09-27):** use Polymath's Qwen3-Embedding-0.6B already on the GPU (`127.0.0.1:8742`, background priority), with the Ollama copy as fallback. Calibrate on Polymath's. No second copy of the model on the GPU in normal runs.
- **Scopes widened (2026-09-27):** Jujutsu Kaisen S1–3, Demon Slayer S1–5 (TV; films excluded), Mob Psycho 100 S1–3, Avatar Books 1–3, Invincible S1–4, The Boys S1–5. Their canonical profiles keep the season-1 scope until the combined v1.7 + v1.8 run re-profiles them.

## Owner ruling: FINISH IT (Kingsley, 2026-09-27; replaces every open question, gate and pending decision)
- **Definition of done:**
  1. v1.7 and v1.8 landed, with the combined 14-title run done.
  2. AC-12 ≥ 0.80 on every grid field, or the axis replaced.
  3. M3, M4 and the census run live in order, each milestone's ACs checked before the next.
  4. M5 live: brief assembly, fair baselines, judge and gate fixes, `make audit`, `animedex diagnose`, and the retrodiction backtest run and reported.
  5. The blind-review packet ready as a localhost rating page; `make backfill`, `make ideas` and USAGE.md working end to end.
  6. The data repo pushed after every batch and milestone; tests green; determinism passing.
- **During Kingsley's blind review:** build change request A (MCP chat, commentary, `search_atoms`), then run the census and the priority-1 backfill. Studio, dashboard, episodes and storyboards stay parked until he has rated.
- **Decisions:** the agent decides everything with its own recommendation, logged in `docs/implementation/DECISIONS.md` with one line of reasoning, and never asks. Gold annotations are waived: outputs unmasked, AC-17 deferred (owner: Kingsley). URCP: PR opened (#1), then all URCP work stops. Parallel tracks are fine; merge in order; run live sequentially, 3 titles at once.
- **The only reasons to stop:** deleting data; a change to the taste standard; the blind-review packet is ready (the finish line). On plan limits: pause and resume automatically, no questions.
- **Rules that stay:** subscription CLIs only; paraphrase only; scope discipline; no scraping MAL; Kingsley's concepts and all outputs only in the private data repo; no new fields after v1.8; tests green.
- **Updates:** one short plain-language message per milestone. The final message says "ready for blind review" and lists the exact steps.

## Owner ruling: statistics as gates (Kingsley, 2026-09-27)
Snapshots and counts only, no models. Each statistic replaces the check it corresponds to inside its existing stage; `animedex stats` is only a read-only summary page. Pure arithmetic over DuckDB counts, deterministic.
1. **Reliability:** Cohen's kappa per enum field alongside raw agreement. Grid fields need kappa ≥ 0.8. Any field below 0.6 is flagged unreliable and excluded from gaps (agreement eval).
2. **Adequacy:** a zero counts as "open" only when the rule-of-three bound 3/n, over the relevant census or corpus subset, is below 0.02.
3. **Gap ranking:** empty cells are ranked by expected count under independence (n × p(x) × p(y)). Cells with expected ≥ 3 and observed 0 are real gaps; the rest are "unsurprising".
4. **Novelty:** PMI replaces "unseen pair"; each idea's key pair reports its PMI (novelty gate).
5. **Field health:** per-field entropy and mutual information with outcome go in the analysis report; low-entropy fields are flagged.
6. **Calibration:** Brier score of confidence vs. verified correctness, per field (VERIFY report).
7. **Taste:** Bradley–Terry strengths from pairwise picks (Kingsley's and the panel's); the judge's agreement is measured against that ranking (review import).
8. **Backtest:** the binomial p-value and the sample size needed for significance.
