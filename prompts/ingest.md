---
version: 1.0.0
pass: NOTES
---
You write a short study note for each listed show (one to three shows). Output JSON only: {"notes": [one note per listed show, in the order given]}.

For each show, inside the scope given:
- premise: 25 words or fewer.
- engine: goal, constraint, strategy, cost, dilemma; 15 words or fewer each. An agent wants [goal] but [constraint]; chooses [strategy]; pays [cost]; which forces [dilemma].
- gate, cost_of_power, progression, visible_counter, fight_medium, story_engine: one of the listed values; `other: <two or three words>` only when none fits.
- mc_edge: how the main character wins against stronger opponents, 20 words or fewer.
- power_kit: medium (what the power works through, 8 words or fewer), functions (exactly 3 things the power does), tools (exactly 3 techniques, items or moves), limits (12 words or fewer).
- villain_type: 8 words or fewer. setting: 12 words or fewer.
- elements: exactly 3, the things the show cannot survive without. Each has `element` (one line, 20 words or fewer) and `pattern`: the same thing as a reusable pattern with every name stripped out (no titles, characters, places, or medium words), 25 words or fewer.
- sources: exactly 2 URLs: the show's Wikipedia page and one fan wiki page (fandom, wikia, or the show's own wiki). Never a myanimelist.net page.

Famous shows: answer from what you know and cite the two pages. Obscure or recent shows: search and read the pages, inside the search and fetch limits given. Paraphrase only: no quotes, no dialogue lines. The catalog numbers (score, popularity) are already recorded; do not restate them.
