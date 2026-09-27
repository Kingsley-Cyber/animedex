---
version: 1.0.0
pass: IDEATE
---
You judge ONE anime concept, written by its author and structured into a card, against the study note of its closest existing show and the steering rules. Output JSON only: {"cards": [one entry]}.

Input lines: rules (the steering rules, hard or soft), the closest note (starts with `=== note <slug>`), graveyard match lines (flop or mixed notes that share the card's core combination, or none), and the card (starts with `=== CARD`).

1. Consequence test: compared with the closest note, do the card's consequences truly differ for characters' choices? For relationships? For outcomes? Answer each true or false with a reason of 25 words or fewer. A known premise with one surface change fails all three.
2. Coherence: pass if the dilemma follows from the cost and the mechanic expresses the theme; otherwise fail. Give a reason.
3. Runway: does the engine's cost still hurt by arc 5, or does growing power dissolve the dilemma? Answer true or false with a reason.
4. Why different: when a graveyard match is listed, judge the card's why_different against that show's outcome. Pass only if it names a concrete change in the premise or engine that keeps the same fate from repeating; fail if it is blank, restates the premise, or promises better execution without saying how. With no match, answer not_applicable with an empty reason.
5. Rules: for every steering rule, pass or fail with a reason of 20 words or fewer. Judge the concept as written, not as it could be fixed.

Be strict.
