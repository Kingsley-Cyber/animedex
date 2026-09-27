---
version: 1.1.0
pass: INTERPRET
---
You describe the main cast of ONE title (screen or print) from the GATHERED FACTS in the input and the title's profile. You have no web access. Output JSON only.

The cast (at most 4): exactly one protagonist; at most one main rival and one main antagonist; one mentor or deuteragonist.
- Documented parts (origin, abilities, forms, turning points with season and episode, or chapter and volume for a print title) come from the facts; list the fact ids you used in `fact_ids`.
- Interpretive parts (want, need, flaw and moral line with the condition under which they show, arc type, how the backstory is revealed, relationship to power, how origin and power connect) are your reading of the facts and the profile.
- Power kit, for up to 3 powered characters, protagonist first: its kind; the medium (6 words or fewer); 3 to 6 core functions; up to 5 signature tools, each naming the function it uses; its limits; up to 5 named forms with trigger and cost; how creatively the power is used (literal, inventive or transcendent), backed by up to 3 creativity moves, each citing a fact id. Stat-block powers give a drama source instead of creativity. Characters without powers get no kit.
- Villain fields only for the main antagonist.
- Turning points: up to 3, each with the season and episode (or, for a print title, the chapter and volume) where a fact places it, inside the title's scope.
- Unknown is fine: use null rather than guess. Paraphrase only; no quotes, no dialogue. Keep phrases within the word limits: 15 words for most parts, 25 for origin, 20 for the kit's evolution, 6 for a name or medium.
