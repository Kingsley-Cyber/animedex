---
version: 1.1.0
pass: ADAPT_FRAMES
---
The critic rejected the listed frames. Follow the controller direction derived from those verdicts and return exactly the requested number of replacement frames as JSON `{"frames": [...]}`. Each replacement has one `frame_sentence`, an `explanation` of the sourced anomaly, a `new_concept`, and `lens_refs` naming the reasoning modes it uses.

Change the causal rule that caused rejection. Do not reword the same fusion, invent a source, or claim that novelty has been proven. The replacements will face the same unscored frame gate before the owner can select one.

If challenge hypotheses are supplied, cite the `hypothesis_refs` used by each replacement. Keep unanswered falsification questions visible as uncertainty, not as evidence.
