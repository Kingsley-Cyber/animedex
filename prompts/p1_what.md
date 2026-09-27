---
version: 1.0.0
pass: P1
---
You extract a compact profile of ONE screen title, inside the given scope. Output JSON only.

Rules
- Fill every core field. Set modules_active by the activation rules below; fill only active modules and omit the rest.
- Use only events inside the scope. Ignore other adaptations, films, spin-offs, and source material the scope excludes.
- Enum fields: choose from the listed values. If none fits, write "other:<short phrase>".
- Phrase fields: 12 words or fewer, normalized wording, no names of the title itself.
- flaw and moral_line: add a condition (when the flaw shows / what would make them cross the line).
- Sensory fields: documented signatures only (how a technique is widely described to look). Never describe framing, blocking, editing, camera, or shot choices.
- conf 0.0-1.0 per field = how sure you are. Unknown -> value null, conf 0. Never guess to fill.
- Every field with conf below {conf_threshold} needs an uncertainty_reason (12 words or fewer).
- epistemic per field: observed (on screen), derived (follows from observed facts), interpretive (why it works / what it means).
- Extract mechanics, structure, and appeal. Not plot summary.
- 3-5 moments: paraphrase only, 25 words or fewer each; no dialogue, no quotes, no quotation marks. Give season and episode when you know them (null if not).
- verify: list the field paths you are least sure of (the pipeline adds mandatory checks itself).
