# Changelog — docs/implementation

## v1.1 — 2026-09-26
From the extraction-framework review and the episode decision.

**Extraction**
- P2 now produces two atom kinds: effect atoms (with a rival explanation) and 1–3 engine atoms (goal → constraint → strategy → benefit + cost → dilemma + dramatic question).
- P3 adds an explanation test: contrast partners decide between `because` and `rival_because`.
- CHECK adds `CONTESTED` (`explanation: contested` atoms are not load-bearing-eligible) and a `scope_leak` reason.
- P4 transfer atoms carry essential, variable, and failure conditions.
- Every title declares a scope (version, seasons, numbering); every pass stays inside it.
- Atom counts are soft limits (AC-14 changed); `flaw` and `moral_line` carry conditions; low-confidence fields carry `uncertainty_reason`; sensory fields limited to documented signatures.

**Ideation**
- Six transformation operators replace the ad-hoc mutations.
- Every idea card carries its own engine.
- Consequence tracing is the operational H1 test (≥2 of choices/relationships/outcomes must differ from the closest title).
- Failure-condition check added to the gates.

**Episodes (new M6)**
- Key episodes (pilot, moments, finale, control), from fetched summaries only, tied to their title's scope.
- ROLLUP compounds episode evidence into atom support status, promotes recurring new atoms, settles contested atoms, re-derives series-engine fields, and writes setup/payoff links.
- Only status changes spend tokens.

**Plan**
- Milestones renumbered: M6 Episode evidence, M7 Scale + calibrate + pattern cards, M8 Episode generation, M9 Target domains.
- ACs renumbered AC-01 to AC-42.

## v1.0
Initial set.
