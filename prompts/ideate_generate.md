---
version: 2.0.0
pass: IDEATE
---
You write ONE original anime premise by transforming the given patterns with ONE operator. Output JSON only.

{taste_standard}

The brief is a list of `key: value` lines:
- theme: the question the story keeps asking.
- operator: the one move to apply, with its definition.
- target: the profile to aim for.
- atom A1, A2...: domain-neutral patterns under opaque aliases, each with bridge concepts and essential, variable, and failure conditions. "patterns: none given" means you start from a premise of your own and apply the operator to it.
- revive, borrowed_system: only for those two operators.
- cell: how many existing titles share the target cell, and whether an empty cell can be trusted.
- lanes, prior_art: lane concepts among the patterns, and what earlier web checks found in this cell.
- title: the existing titles nearest the target (id: medium; logline).
- flop: mixed and flop titles in the target region, with their recorded failure.
- rule: steering rules. Hard rules are constraints; soft rules are preferences.
- rework: checks the previous version failed. Fix them.

Rules
- Apply the operator exactly once. When patterns are given, use every one and list their aliases (A1...) in source_transfer_ids.
- Respect every essential condition. Trigger no failure condition.
- Give the idea its own engine: an agent wants [goal] but [constraint]; chooses [strategy]; gets [benefit] and pays [cost]; which forces [dilemma]. Add the dramatic question it keeps open. The dilemma must follow from the cost, and the mechanic must express the theme.
- Consequences: how does this change characters' choices, relationships, and outcomes compared with the closest existing title? 25 words or fewer each. A change that alters none of them is a surface change and will be rejected.
- profile: one listed value per field. Aim for the target profile.
- closest_existing: the existing title your idea is nearest to. Use a title id from the brief, or any id the schema lists; when the brief lists no titles, name the nearest existing title in any medium. why_not_a_clone: 40 words or fewer.
- premortem (only when the brief lists flops): 2-3 ways this idea could fail. Each draws on one listed flop (source_title_id) and its recorded failure, with a mitigation. 25 words or fewer each.
- why_different: only if you were told the idea matches a flop's combination. Say what changes so that flop's recorded failure cannot repeat, 40 words or fewer; otherwise null. A judge checks it against the recorded failure: not blank is not enough.
- revival_improvement: only for the revive operator. Name the specific improvement mapped to the flop's recorded weakness, 25 words or fewer; otherwise null.
- Length limits: logline 30 words or fewer; premise 120 words or fewer; what_changed 25 words or fewer; engine parts 15 words or fewer; dramatic question 20 words or fewer.
- Original characters and world only: no existing titles, characters, or places in the logline or premise. Paraphrase only.
