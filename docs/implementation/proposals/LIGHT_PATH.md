# Light path (owner instruction, 2026-09-27) — the plan of record

Kingsley's instruction, kept verbatim as the authority for D-050 to D-055. It replaces "finish it" and every pending change plan.

> PIVOT TO THE LIGHT PATH. Final instructions. This replaces the "finish it" plan and every pending change plan. Decide everything yourself and log decisions in DECISIONS.md; don't ask.
>
> 0. STOP THE HEAVY PATH. Pause the running 30-title backfill now and keep whatever finished. From here, the heavy pipeline (gather → interpret → verify → atoms → proofs → critic → patterns) runs on the 5 gold titles only. No census, no plans, no new records, no schema changes, no URCP work.
>
> 1. STEERING RULES (steering/rules.yaml, used as hard constraints by quick and diagnose). R1 (hard): the MC is legibly the strongest without holding the biggest number, through creative use of the power as a medium, or through a cost nobody else pays, or both. R2 (soft): power affinities come from domains of meaning, not elements; each affinity is a named entity bound to a host, with its own history; the power is derived from the concept, not assigned to it. R3 (soft): the premise is built out from the fight: a cold-open image first, then the medium, the cost, the engine, the world.
>
> 2. BUILD `make ingest LIST=<file>` (one call per show, 3 shows per call, Sonnet with web). For each show, write notes/<show_slug>.json: premise (≤25 words); engine (goal, constraint, strategy, cost, dilemma); gate, cost_of_power, progression, visible_counter, fight_medium (existing enums); MC edge; power kit (medium, 3 functions, 3 tools, limits); villain type; story engine; setting; the 3 elements the show can't survive without, one line each, and for each the reusable pattern with names stripped out; 2 source URLs (Wikipedia + one wiki); paraphrase only. Famous shows answer from knowledge and cite the pages; obscure shows read the pages. Skip shows whose notes exist. Outcome (hit/mixed/flop) comes from the AniList API using the existing label rule, no model call; print titles use AniList manga data plus adaptation status. Budget: under 2 minutes per show.
>
> 3. BUILD `make quick SEED="<text>" [SHOWS="a, b, c"] [N=6]` (exactly 4 calls, under 10 min). SEED is a concept, a fight image, or a lane. 1) RESEARCH (Sonnet, web, one call): pick the 3–5 most relevant shows if SHOWS is absent; write notes for any that lack them, same format as ingest. Skip if all notes exist. 2) GENERATE (Opus): brief = seed + notes + steering rules. Fight image → derive medium → functions → kit → cost → engine → premise, in that order. Lane → fill the lane. Concept → keep its strongest part and rebuild the rest. N cards: logline, premise, engine, MC edge, power kit, consequences (choices / relationships / outcomes), closest existing show, why not a clone. 3) CHECK (Codex, one call for all cards): consequence test (≥2 of 3 dimensions differ from the closest show), steering rules satisfied, closest note and how close, one line on the biggest weakness. Drop cards that fail the consequence test or R1. 4) PRIOR ART (Sonnet, web, only if a surviving card claims "never done"): search for counterexamples; downgrade the claim if found. Output build/quick/<timestamp>.md: surviving cards ranked by the check, each with its weakness line and sources. Print the path and total time.
>
> 4. `make diagnose TEXT="..."` stays; point it at notes/ and steering/rules.yaml.
>
> 5. STORAGE. notes/ is the index and lives in the private data repo. Cards and my concepts go only to the private data repo, never the public one. Rebuild the DuckDB counts from notes/ for the gap and lane queries; anything the notes don't cover reports "not tracked."
>
> 6. ORDER AND DONE. a. Build ingest with tests. Run it on priority_1.txt, my 6 titles, and donghua.txt. b. Build quick with tests. Run it twice on SEED="a cold-open feral scaled transformation mid-fight" with no SHOWS: the second run must skip research. c. Push the data repo. d. One message: "ready", with ingest totals (time, notes written, failures with reasons), both quick timings, and the path of the first quick run. The existing blind packet stays available through `make review`; don't rebuild it.
>
> 7. RULES THAT STAY. Subscription CLIs only. Paraphrase only. Stay inside each title's scope. No MAL scraping. Keep tests green. Stop only for data deletion or a plan limit (pause, resume, don't ask).

Where it landed: 05 "Light path", 08 AC-66 to AC-70, DECISIONS D-050 to D-055, USAGE section 0, AGENTS operating table; code in `src/animedex/light/`.
