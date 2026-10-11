---
version: 1.0.0
pass: FRAME_GATE
---
Check candidate frames before any idea cards are built or scored. Output JSON only: {"frames": [one verdict per frame]}.

For each frame, answer:
- `explains_gap`: does its proposed causal idea make the sourced anomaly understandable, rather than merely restating it?
- `parent_independent`: would the premise still be interesting to someone who has never seen its nearest anime?
- `fusion`: is its appeal mainly a combination of recognizable existing shows, characters, power systems, or motifs?
- `anti_examples`: name three distinct indexed shows that are not this frame, using their note slugs and a short `why_not` for each.
- `anti_examples_valid`: do those contrasts actually demonstrate the frame's difference?
- `reason`: state the decisive reason for keeping or rejecting it. Do not give a score.

Use the supplied note index only to test differences. A high novelty claim cannot be established by these notes alone. If the evidence is insufficient, fail the relevant check rather than inventing support.
