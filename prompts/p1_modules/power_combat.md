---
version: 1.1.0
block: power_combat
---
power_combat (active when extraordinary abilities or structured combat are a central engine)
- power_source: where power comes from
- gate: how someone gains access to power (enum)
- progression: how power grows (enum)
- cost_of_power: what power takes from its user (enum)
- cost_of_power_secondary: a second cost only if the story weighs it as heavily as the first (enum; else null)
- visible_counter: how progress is shown to the audience (enum)
- ranking_ladder: the ranking system, if any
- fight_medium: how fights are fought (enum)
- signature_technique: the signature ability, described generically
- mc_edge: how the protagonist is legibly the strongest (enum); creative_reinterpretation = using the power as a medium beyond its design; unique_cost = paying what nobody else will
- power_embodiment: the form power takes (enum); bound_entity = a power with its own history and character
- set_structure: how the roster of powers is organized (enum): closed_set = a fixed roster; hierarchical = a base set with sub-disciplines; open_variety = every user unique; pantheon = a roster of mythic or historical beings; universal_energy = one shared energy, many techniques
- subset_mechanics: how sub-skills relate to a base power (one or more; enum)
- set_scaffold: what the set is built on (enum): arbitrary = numbers or labels; cultural_reference = a scaffold the audience already knows (tarot, zodiac, sins, myth); semantic_domain = powers built from domains of meaning
- member_depth: how much each power in the set carries: a label, an ability, or an identity with a history (enum)
- world_integration: how deeply powers shape the world (enum)
- rarity: how many people have power (enum)
- power_up_mode: how users power up in a fight (one or more; enum); domain = the user rewrites the battlefield
- power_up_cost: what powering up costs
- fight_logic: what decides fights (one or more; enum); rules_exploitation = vows, restrictions, conditions
