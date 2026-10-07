---
version: 1.0.0
pass: SUSPEND
---
Hold the candidate frames open before the gate. Return JSON with `comparisons` and `syntheses`. Compare distinct frame refs and mark each relation `tension`, `compatible`, or `independent`, with a concrete reason. If a tension yields a new causal rule, propose a one-sentence synthesized frame with `frame_sentence`, `explanation`, `new_concept`, and at least two `parents` refs. Leave `syntheses` empty when no coherent synthesis exists.

Do not treat a mixture of recognizable show parts as a synthesis. The later frame gate will judge every candidate and synthesis. This step is a software comparison of hypotheses, not quantum computation.
