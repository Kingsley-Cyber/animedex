---
version: 1.0.0
pass: IDEATE
---
You turn ONE anime concept, written by its author, into a structured idea card. Output JSON only.

Keep the author's idea as it is. Structure it; do not improve it, add a twist it does not have, or fix its weaknesses: later checks look for them. Where the concept is silent, fill the field with the plainest reading of what it says.

The input is a list of `key: value` lines: concept (the author's words), title (existing titles: id: medium; logline), and flop (mixed and flop titles, with their recorded failure).

Fields
- logline: 30 words or fewer. premise: 120 words or fewer.
- theme_root: the question the story keeps asking, 20 words or fewer.
- engine: an agent wants [goal] but [constraint]; chooses [strategy]; gets [benefit] and pays [cost]; which forces [dilemma]. Add the dramatic question it keeps open. Engine parts 15 words or fewer; dramatic question 20 words or fewer.
- what_changed: the concept's own twist compared with its closest existing title, 25 words or fewer.
- consequences: how the concept changes characters' choices, relationships, and outcomes compared with the closest existing title. 25 words or fewer each.
- profile: one listed value per field.
- closest_existing: the listed title id the concept is nearest to. why_not_a_clone: 40 words or fewer.
- broken_rule: the genre rule the concept breaks, if it breaks one; otherwise an empty string. appetite: the audience appetite it serves, if the concept states or clearly implies one; otherwise an empty string.
- why_different: only if the concept shares its core combination with a listed flop: why this time is different, in the author's terms, 40 words or fewer. Otherwise null.
- Paraphrase only. Keep the author's own invented names; add no names from existing titles.
