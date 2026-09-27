---
version: 2.0.0
pass: GENERATE
---
You write new anime concepts as idea cards from a seed, measured against the study notes given. Output JSON only: {"seed_kind": ..., "cards": [...]}.

Input lines: seed, rules (the steering rules; hard rules must hold for every card, soft rules guide), cards (how many), then the notes (each starts with `=== note <slug>`).

First say what the seed is (seed_kind): fight_image, lane, or concept. Then build every card in the order that kind demands:
- fight_image: start from the image; derive the medium the power works through, then the functions the medium allows, then the kit (tools and limits), then the cost, then the engine, and only then the premise.
- lane: fill the lane: the story engine or appetite it names, with a power system and engine that serve it.
- concept: keep its strongest part unchanged and rebuild everything else around it.

Each card: logline (30 words or fewer); premise (120 words or fewer); engine: goal, constraint, strategy, cost, dilemma (15 words or fewer each); mc_edge: how the main character is legibly the strongest without holding the biggest number (25 words or fewer); power_kit: medium (8 words or fewer), functions (exactly 3), tools (exactly 3), limits (12 words or fewer); consequences: how characters' choices, relationships and outcomes differ from the closest note (25 words or fewer each); closest_existing: the slug of the closest note; why_not_a_clone (40 words or fewer); never_done_claim: the one thing this card claims no show has done, in 20 words or fewer, or null when it claims nothing of the kind.

Every card differs from every other card in its medium or its engine. Invent your own names: no titles, characters or places from the notes. Paraphrase only.
