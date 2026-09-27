---
version: 1.0.0
pass: P3
---
You test ONE title's atoms against partner titles, inside each title's scope. Output JSON only.

For each atom:
1. CONTRAST with every partner listed: does the partner have this element or engine (yes / no / partial)? Say how it differs, 25 words or fewer. Use each partner's role exactly as listed.
   - Effect atoms: use the partners as a natural experiment. If a partner has the element but not the feeling, or the feeling without the element, which explanation survives: because, rival, both, or neither? Name the partner that decides it (via_partner) and say why, 25 words or fewer.
   - Engine atoms: does the partner run a similar engine? How do its cost and dilemma differ? Leave the explanation_test fields null.
2. ABLATION: if this element or engine were removed and nothing else changed, would the title still deliver its primary feeling and its premise engine? Collapses -> load_bearing. Weakened -> supporting. Unchanged -> decoration. Say what would happen, 25 words or fewer, with conf 0.0-1.0.

Be strict. Most elements are decoration. Expect roughly 3-5 load_bearing atoms per title.
Paraphrase only; no quotes.
