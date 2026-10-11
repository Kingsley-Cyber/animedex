---
version: 1.0.0
pass: REASON_LENS
---
Read the sourced anomaly and the indexed note premises. Work only in the reasoning mode named in the user input. Do not see or assume the other modes' answers. Return JSON with `hypothesis` and `steps`; each step has `claim` and `premise_ids` citing the supplied note slugs.

Abductive: propose a causal explanation that would make the observation less surprising. Deductive: test consequences if a proposed explanation were true and name contradictions. Inductive: describe what the indexed examples support and where that sample is too small. A cited note is a comparison premise, not proof that the live discourse gap holds across the genre. Do not invent source content or combine named shows into a pitch.
