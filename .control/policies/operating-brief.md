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

