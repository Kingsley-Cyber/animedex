---
version: 1.3.0
pass: P1
---
You extract a compact profile of ONE screen title, inside the given scope. Output JSON only.

Rules
- Fill every core field. The schema offers only the modules this title's medium and format allow; fill each one whose activation rule below applies. If a judgment module (power_combat, relationships, comedy_satire) does not apply, set every one of its fields to value null, conf 0.
- Use only events inside the scope. Ignore other adaptations, films, spin-offs, and source material the scope excludes.
- Enum fields: choose from the listed values. If none fits, write "other:<short phrase>". Where tests are listed under an enum, choose the value whose test holds.
- Multi-value fields (marked "one or more"): a list of listed values; ["none"] alone when none applies; null if unknown.
- List fields (institutions, anticipation_hooks): up to the stated number of items, every part filled; [] when there are none.
- Group fields (thematic_argument): an object with every part; a part you do not know is null; the whole value is null if no part is known.
- Secondary fields (story_engine_secondary, cost_of_power_secondary): only when a second value weighs as much as the first, and never the same value; otherwise null.
- promise_break: only for a mixed or flop title, and only a break a reception source documents (it is always checked on the web); otherwise null.
- premise_abstraction: the premise with no names, places, or medium words (anime, manga, episode, season, show, film, and the like).
- Phrase fields: stay within the word limit in each field's description (15 words; 20 for two-part fields such as want_vs_need), normalized wording, no names of the title itself.
- flaw and moral_line: add a condition (when the flaw shows / what would make them cross the line).
- Sensory fields: documented signatures only (how a technique is widely described to look). Never describe framing, blocking, editing, camera, or shot choices.
- conf 0.0-1.0 per field = how sure you are. Unknown -> value null, conf 0. Never guess to fill.
- Every field with conf below {conf_threshold} needs an uncertainty_reason (15 words or fewer). If you cannot say why you are unsure, set value null and conf 0 instead of guessing.
- epistemic per field: observed (on screen), derived (follows from observed facts), interpretive (why it works / what it means).
- Extract mechanics, structure, and appeal. Not plot summary.
- 3-5 moments: paraphrase only, 25 words or fewer each; no dialogue, no quotes, no quotation marks. Give season and episode when you know them (null if not).
- verify: list the field paths you are least sure of (the pipeline adds mandatory checks itself).
