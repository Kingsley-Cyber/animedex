---
version: 1.0.0
pass: IDEATE
---
You write ONE original anime premise by transforming the given patterns with ONE operator. Output JSON only.

You get:
- a theme root: the question the story keeps asking;
- 1-3 domain-neutral patterns, each with essential, variable, and failure conditions;
- one operator;
- a target profile.

Rules
- Apply the operator exactly once, to the patterns given. Use every pattern (list their ids in source_transfer_ids).
- Respect every essential condition. Trigger no failure condition.
- Give the idea its own engine: an agent wants [goal] but [constraint]; chooses [strategy]; gets [benefit] and pays [cost]; which forces [dilemma]. Add the dramatic question it keeps open. The dilemma must follow from the cost, and the mechanic must express the theme.
- Consequences: how does this change characters' choices, relationships, and outcomes compared with the closest existing title? 25 words or fewer each. A change that alters none of them is a surface change and will be rejected.
- profile: one listed value per field. Aim for the target profile.
- closest_existing: the corpus title id your idea is nearest to. why_not_a_clone: 40 words or fewer.
- premortem: 2-3 ways this idea could fail. Each draws on one listed mixed or flop title (source_title_id) and its recorded failure, with a mitigation. 25 words or fewer each.
- why_different: only if you were told the idea matches a flop's combination. Say why this time is different, 40 words or fewer; otherwise null.
- revival_improvement: only for the revive operator. Name the specific improvement mapped to the flop's recorded weakness, 25 words or fewer; otherwise null.
- Length limits: logline 30 words or fewer; premise 120 words or fewer; what_changed 25 words or fewer; engine parts 15 words or fewer; dramatic question 20 words or fewer.
- Original characters and world only: no existing titles, characters, or places in the logline or premise. Paraphrase only.
