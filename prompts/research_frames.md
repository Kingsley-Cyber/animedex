---
version: 1.1.0
pass: RESEARCH_FRAMES
---
Use the three independent reasoning traces and the sourced anomaly to propose exactly the requested number of self-contained anime frames. Return JSON `{"frames": [...]}`. Every frame has one `frame_sentence`, an `explanation` of the anomaly, a `new_concept` that changes the genre's causal rule, and `lens_refs` naming the reasoning modes that informed it.

The indexed shows are counterexamples and boundaries, not parts to combine. Keep observations, hypotheses, and invented story rules distinct. A frame must interest a reader who knows none of the indexed shows.

If challenge hypotheses are supplied, use them as competing explanations. Each frame must cite the `hypothesis_refs` that it explores. Do not present a supporting or falsifying question as if it has already been answered.
