---
version: 1.0.0
pass: RESEARCH_GATE
---
Judge each candidate before idea-card scoring. Return one JSON verdict per frame ref with the fields in the schema. Apply the ordinary frame gate: `explains_gap`, `parent_independent`, `fusion`, three distinct `anti_examples` from indexed notes with `why_not`, `anti_examples_valid`, and `reason`.

Also set `evidence_grounded`: the explanation does not claim support beyond the supplied scan summary and cited note premises. Set `reasoning_consistent`: its causal claim does not contradict the supplied reasoning traces without explaining the conflict. Fail either field when uncertain. Do not provide a score. A fetched page supports only the reported observation; it does not prove a genre-wide absence or originality.
