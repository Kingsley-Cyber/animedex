---
version: 1.0.0
pass: ABDUCT
---
Generate candidate anime story frames from the sourced anomaly. Output JSON only: {"frames": [...]} with exactly the number requested.

Each frame has `frame_sentence` (one self-contained sentence), `explanation` (how this frame makes the anomaly understandable), and `new_concept` (the causal idea introduced by the frame). Make the frames distinct. The frame must make sense to someone who has never seen the shows that inspired the genre; do not combine named anime, borrow characters, or stack familiar motifs. Keep the source observation and your proposed explanation separate. The explanation is a hypothesis, not a verified finding.
