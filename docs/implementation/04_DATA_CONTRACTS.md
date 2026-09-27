# 04 — Data Contracts

Pydantic models in `src/animedex/models/` are the source of truth for shapes. JSON Schemas in `schemas/` are generated from them (`make schemas`). Every record carries the provenance block.

## Conventions
- **IDs:** `title_id` = slug + year (`hunter_x_hunter_2011`). Moments `{title_id}.mo.{nn}`; characters `{title_id}.c.{nn}` (v1.8); atoms `{title_id}.m.{nnn}`; transfers `{title_id}.t.{nnn}`; episodes `{title_id}.s{ss}e{ee}`; links `{title_id}.l.{nnnn}`; patterns `pattern.{nnn}`; ideas `idea.{run_id}.{nnn}`; steering rules `rule.{nnn}` (v1.8).
- **Versions:** semver for `schema_version`, `vocab_version`, `bridge_version`, and each prompt file.
- **Text:** paraphrase only. Phrases ≤ 12 words, sentences ≤ 25 words, episode summaries ≤ 60 words, unless noted. No quotes from sources.
- **P1 word caps (vocab 1.4.0, owner-approved 2026-09-27):** P1 phrase fields allow 15 words. Eleven two-part fields allow 20: core.logline_hook, core.core_question, core.premise_engine, core.want_vs_need, core.opposition_logic, core.stakes_clock, core.world_rules, core.broken_rule, core.central_mystery, core.knowledge_gap, series_engine.episode_template. `condition` and `uncertainty_reason` allow 15. The vocab holds each field's cap (`max_words`, default `lens.phrase_max_words`).
- **v1.8 word caps (vocab 1.5.0, owner decision 2026-09-27):** the caps above stay. A new phrase field or part defaults to 15 words; one whose cap the request states keeps it (20: promise_mechanism, promise_break, premise_abstraction, thematic_argument.resolution; 12: real_world_isomorphism, reacts_against, institutions.role, anticipation_hooks.hook; 6: institutions.name). The character and idea-card caps are listed with their records.

## Provenance block (every record)
```json
{
  "run_id": "run_20260926_001",
  "pass": "P1|VERIFY|P2|P3|CHECK|P4|CANONICALIZE|EP|ROLLUP|PATTERNS|IDEATE|CENSUS",
  "model": "provider/model-id or null for deterministic stages",
  "prompt_version": "1.0.0",
  "schema_version": "1.1.0",
  "vocab_version": "1.1.0",
  "cache_key": "sha256:...",
  "created_at": "ISO-8601"
}
```

## Scope (corpus entry and title record)
```json
"scope": {
  "version": "e.g., anime (2024–)",
  "seasons": [1, 2],
  "numbering": "broadcast|streaming|home_video",
  "exclude": ["e.g., source-material arcs not yet adapted"]
}
```
Films use `seasons: []` and `numbering: null`; `version` is always required. Every pass uses only events inside scope. Different adaptations of the same story are different titles (`hunter_x_hunter_1999` vs. `hunter_x_hunter_2011`; `fullmetal_alchemist_2003` vs. `fullmetal_alchemist_brotherhood_2009`).

## Field value shape (every P1 field)
```json
{
  "value": "enum value | phrase within the field's cap (15 words; 20 for the two-part fields) | null",
  "condition": "≤15 words; character fields only (flaw, moral_line): when it shows / what would make them cross it",
  "conf": 0.0,
  "uncertainty_reason": "≤15 words; required when conf < verify.conf_threshold",
  "source": "recall|web|episodes",
  "verification": "not_required|unverified|web_confirmed|web_corrected|derived_from_episodes|unresolved",
  "source_ref": "URL or null",
  "epistemic": "observed|derived|interpretive|external_metric"
}
```
`conf` is a routing signal (it decides what gets verified), not a calibrated probability. Never report it as one.

### Field kinds (vocab 1.5.0, schema 1.4.0)
The envelope above (`conf`, `uncertainty_reason`, `source`, `verification`, `source_ref`, `epistemic`, and `condition` on conditional fields) is the same for every kind. Only `value` changes shape. `null` is always "unknown" and carries `conf` 0.

| Kind | `value` | Rules |
|---|---|---|
| `phrase` | a string | within the field's cap |
| `enum` | one vocab value | in the field's vocab |
| `enum_multi` | a non-empty list of vocab values | no repeats; `none` stands alone |
| `list` | up to `max_items` objects with typed parts, e.g. `[{"name": "", "type": "enum", "role": ""}]` | every part filled; `[]` means there are none |
| `group` | one object with fixed parts, e.g. `{"thesis_mc": "", "antithesis_villain": "", "resolution": null}` | a part may be `null` (unknown); a group with no known part is written `null` |

Part kinds are `phrase` (own cap) and `enum` (own vocab). CANONICALIZE maps enum members and parts like single enums: an alternate label becomes its preferred value, an off-vocab value becomes `other` plus a proposal, and a member or item whose vocab has no `other` is dropped (the field becomes unknown if nothing is left).

**Lens field options (vocab 1.5.0):**
- `since`: a field added at that vocab version. A title made under an older vocab (`provenance.vocab_version`) may omit it; an omitted field is left out of the record, not null-filled, and counts as not filled in the coverage ledger. A record at or after that version must carry it.
- `differs_from`: an optional second value (story_engine_secondary, cost_of_power_secondary). It must differ from its primary and needs one.
- `outcome_in`: only titles whose `core.outcome` is listed carry a value (promise_break: mixed, flop).
- `needs_source`: a value needs a cited page (`source_ref`). P1 always sends it to VERIFY; if VERIFY leaves it unresolved, the value is cleared.
- `abstract`: no names or medium words (premise_abstraction). It is the clone check's text.

### Epistemic classes (never collapse)
| Class | Meaning | Example |
|---|---|---|
| observed | What happens on screen | Jinwoo receives a progression interface |
| derived | Follows from observed facts | Progress is visible to the audience |
| interpretive | Why it works / what it means | The mechanic serves measurable self-improvement |
| external_metric | Outside data | Ratings, awards, viewership |

## Title profile (P1) — `titles.jsonl`
```json
{
  "title_id": "", "title": "", "year": 0,
  "medium": "anime|donghua|western_animation|adult_animation|live_action|film",
  "format": "film|episodic|serialized|hybrid",
  "scope": {},
  "role_tags": ["gold", "hit", "mixed", "flop", "contrast"],
  "modules_active": [],
  "core": {
    "logline_hook": {}, "core_question": {}, "premise_engine": {},
    "primary_feeling": {}, "tone": {},
    "want_vs_need": {}, "flaw": {}, "moral_line": {},
    "central_opposition": {}, "opposition_logic": {},
    "stakes_clock": {}, "world_rules": {},
    "borrowed_template": {}, "broken_rule": {}, "unserved_appetite": {},
    "central_mystery": {}, "knowledge_gap": {}, "reveal_cadence": {},
    "outcome": {}
  },
  "power_combat": {
    "power_source": {}, "gate": {}, "progression": {}, "cost_of_power": {},
    "visible_counter": {}, "ranking_ladder": {}, "fight_medium": {}, "signature_technique": {}
  },
  "relationships": {
    "core_bond": {}, "rival": {}, "mentor": {}, "team_structure": {}, "power_is": {}
  },
  "sensory": {
    "power_visual_signature": {}, "choreography_style": {}, "color_motif": {},
    "animation_signature": {}
  },
  "anime_production": {
    "source_medium": {}, "demographic": {}, "arc_cour_structure": {}, "adaptation_fidelity": {}
  },
  "series_engine": {
    "episodic_vs_serialized": {}, "status_quo_reset": {}, "episode_template": {},
    "season_arc_shape": {}, "cliffhanger_cadence": {}
  },
  "comedy_satire": {
    "comedic_engine": {}
  },
  "film": {
    "act_structure": {}, "runtime_compression": {}, "set_pieces": {}, "closure": {}
  },
  "provenance": {}
}
```
- Inactive modules are omitted, not null-filled.
- Character fields are conditional, never permanent labels: record when a flaw shows, and what would make a character cross their moral line.
- Sensory fields describe **documented signatures only** (e.g., a technique's widely described look). No claims about framing, blocking, editing, or shot choices.

### v1.8 title fields (vocab 1.5.0; `since` 1.5.0)
Enum values are exactly those of the request (`v1.8_request.md` §1–4, 6) and live in `vocab.json`.

| Block | Field | Kind | Cap / limit |
|---|---|---|---|
| power_combat | cost_of_power_secondary | enum (the cost_of_power vocab) | differs from cost_of_power |
| power_combat | mc_edge, power_embodiment, set_structure, set_scaffold, member_depth, world_integration, rarity | enum | |
| power_combat | subset_mechanics, power_up_mode, fight_logic | enum_multi | |
| power_combat | power_up_cost | phrase | 15 |
| core | story_engine, pilot_hook_type, ending_type, setting_type, world_visibility, conflict_scale, mc_archetype, mc_start, mc_goal_type, ensemble_size, rival_type, threat_structure, escalation_model, genre_move | enum | |
| core | story_engine_secondary | enum (the story_engine vocab) | differs from story_engine |
| core | institutions | list of {name, type, role} | ≤ 3 items; name 6, type `core.institution_type`, role 12 |
| core | thematic_argument | group {thesis_mc, antithesis_villain, resolution} | 15, 15, 20 |
| core | audience_promise | phrase | 15 |
| core | promise_mechanism | phrase | 20 |
| core | promise_break | phrase | 20; mixed/flop only; needs a source |
| core | anticipation_hooks | list of {hook, type} | ≤ 3 items; hook 12, type `core.anticipation_hook_type` |
| core | premise_abstraction | phrase | 20; no names or medium words |
| core | real_world_isomorphism, reacts_against | phrase | 12 |
| core | core_fantasy | enum_multi | |

The primary cost of power stays in the idea profile and the overlap gates; since D-028 it is no longer a grid axis (set_structure replaced it). The phrase parts of list and group values feed the name-leak list like any phrase.

## Moment — `moments.jsonl`
```json
{
  "moment_id": "", "title_id": "",
  "description": "paraphrase, ≤25 words",
  "locator": {"season": null, "episode": null, "timestamp": null, "episode_id": null},
  "moment_type": "enum",
  "why_it_hit": "≤25 words",
  "conf": 0.0, "verification": "", "source_ref": null,
  "provenance": {}
}
```
`locator.episode_id` is filled once the episode is indexed (M6).

## Character (v1.8) — `characters.jsonl`
Up to 4 per title: the protagonist (exactly one), the main rival, the main antagonist, and a mentor or a deuteragonist (one slot). Names are allowed here and join the name-leak list, so they never reach transfers, pattern cards or idea cards. Base fields are written out; `null` means unknown.
```json
{
  "character_id": "{title_id}.c.{nn}", "title_id": "",
  "name": "≤6 words",
  "role": "protagonist|main_rival|main_antagonist|mentor|deuteragonist",
  "origin": "≤25 words", "wound": "the formative loss or event, ≤15 words",
  "want": "≤15 words", "need": "≤15 words",
  "flaw": {"value": "≤15 words", "condition": "≤15 words"},
  "moral_line": {"value": "≤15 words", "condition": "≤15 words"},
  "relationship_to_power": "enum: power_combat.mc_edge",
  "origin_power_link": "origin_creates_power|origin_shapes_use|origin_sets_cost|unrelated|other",
  "arc_type": "positive_change|flat|fall|corruption|disillusionment|redemption|other",
  "backstory_reveal": "upfront|gradual|late_twist|never",
  "turning_points": [{"event": "≤15 words", "locator": {"season": null, "episode": 12}}],
  "power_kit": {
    "power_kind": "medium|stat_block|technique_system|bound_entity|object|system_interface|skill_or_trait|none",
    "medium": "≤6 words",
    "functions": ["3–6 core affordances, ≤15 words each"],
    "tools": [{"tool": "≤15 words", "function": "one of the functions"}],
    "limits": ["≤15 words each"],
    "forms": [{"name": "≤6 words", "trigger": "≤15 words", "cost": "≤15 words"}],
    "creativity_level": "literal|inventive|transcendent",
    "creativity_moves": [{"move": "≤15 words", "source_ref": "URL"}],
    "drama_source": "restraint|vulnerability|corruption|isolation|other",
    "evolution": "≤20 words"
  },
  "villain": {
    "villain_type": "ideological|predator|mirror_of_mc|system_or_institution|tragic|hidden_manipulator|nihilist|force_of_nature|other",
    "villain_reveal": "upfront|gradual|betrayal_twist|never_fully",
    "relation_to_mc": "mirror|opposing_ideology|obstacle|personal_betrayal|other"
  },
  "source_refs": ["URLs of the pages the documented facts came from"],
  "provenance": {}
}
```
- **Turning points:** at most 3. On a non-film title each needs its episode, and a given season must be inside the title's scope.
- **Power kit:** on at most 3 characters per title, and the protagonist's comes first (a title with any kit has one on its protagonist). Kit lists: tools ≤5 (each names one of the functions), limits ≤5, forms ≤5, creativity moves ≤3. A kit of kind `none` has no functions, tools, forms or creativity.
- **Creativity or drama:** a `stat_block` kit takes `drama_source` (required) instead of creativity. Any other kit may take `creativity_level`; `inventive` and `transcendent` need at least one creativity move, and every move cites its source.
- **Villain fields:** required on the main antagonist, and on no other role.
- P2 may cite a character record (its `character_id`) in an atom's `evidence_refs`.

## Outcome — `outcomes.jsonl` (external_metric)
```json
{
  "title_id": "",
  "label": "hit|mixed|flop",
  "signals": [{"metric": "", "value": "", "source_ref": ""}],
  "confounders": {
    "studio": "", "budget_signal": "", "source_popularity": "",
    "platform": "", "release_context": ""
  },
  "failure_reason": "≤25 words or null",
  "failure_level": "premise|execution|external|unknown; required for mixed/flop, null for hits (v1.3)",
  "failure_evidence": "≤25 words, paraphrased, or null",
  "failure_evidence_ref": "URL the evidence came from, or null",
  "failure_level_source": "verify|owner|migration or null",
  "failure_patterns": [{"pattern": "enum", "source_ref": "URL", "note": "≤12 words"}],
  "provenance": {}
}
```
- **`failure_patterns`** (v1.8): how a mixed/flop title failed, each with the page that says so. Values: promise_broken, power_scaling_collapse, villain_deflation, cast_bloat, pacing_collapse, adaptation_compression, tone_whiplash, protagonist_passivity, ending_failure, production_quality, other. Hits carry none; a pattern appears once. Optional (empty by default, and left out of the record when empty), so earlier outcomes stay valid. Pre-mortems and graveyard warnings cite them.

- **`failure_level`** (v1.3):
  - Hits carry `null`; mixed and flop outcomes require a level.
  - A web-sourced level other than `unknown` needs `failure_evidence` and its `failure_evidence_ref`.
  - Kingsley's `failure_level_override` in `corpus/titles.yaml` wins and is recorded as source `owner`.
- **Corpus entry** (v1.3): optional `failure_level_override` and `catalog_ref` (e.g. `anilist:127401`).
- **Donghua** (v1.3): uses the same lens as anime, except `anime_production`, which stays anime-only.

## Mechanism atom (P2) — `mechanisms.jsonl`
Two kinds share one envelope. Exactly one of `effect` / `engine` is present, matching `atom_kind`.
```json
{
  "atom_id": "", "title_id": "",
  "atom_kind": "effect|engine",
  "effect": {
    "element": "≤12 words",
    "element_ref": {"field": "power_combat.visible_counter", "moment_id": null},
    "feeling": "enum",
    "because": "≤25 words: the causal mechanism",
    "rival_because": "≤25 words: the strongest alternative explanation"
  },
  "engine": {
    "agent": "role, ≤6 words",
    "goal": "≤15 words", "constraint": "≤15 words", "strategy": "≤15 words",
    "benefit": "≤15 words", "cost": "≤15 words", "dilemma": "≤15 words",
    "dramatic_question": "≤20 words",
    "feeling": "enum: the feeling the engine sustains"
  },
  "module": "core|power_combat|relationships|sensory|anime_production|series_engine|comedy_satire|film",
  "epistemic": "interpretive",
  "conf": 0.0,
  "evidence_refs": ["field paths, moment_ids, episode_ids, or character_ids (v1.8)"],
  "explanation": "settled|contested",
  "support": {
    "status": "profile_only|episode_backed|mixed|contradicted",
    "supporting_episodes": [], "contradicting_episodes": [], "reframing_episodes": []
  },
  "origin": "p2|promoted_from_episodes",
  "provenance": {}
}
```
Engine example (paraphrased, illustrative): goal *provide for his family*; constraint *weakest hunter alive*; strategy *secretly grind a private leveling system*; benefit *rapid, visible growth*; cost *must hide what he's becoming and obey a system he doesn't understand*; dilemma *every gain raises the stakes of the secret*; dramatic question *what is the system turning him into?*

## Proof record (P3) — `proofs.jsonl`
```json
{
  "atom_id": "",
  "contrast": [
    {
      "partner_title_id": "",
      "partner_role": "nearest_neighbor|flop|cross_medium",
      "partner_has": "yes|no|partial",
      "difference": "≤25 words"
    }
  ],
  "explanation_test": {
    "favors": "because|rival|both|neither",
    "via_partner": "title_id | null (null only when favors is both or neither: no partner decides it, D-036)",
    "note": "≤25 words"
  },
  "ablation": {
    "if_removed": "≤25 words",
    "verdict": "load_bearing|supporting|decoration",
    "conf": 0.0
  },
  "provenance": {}
}
```
- `explanation_test` is required for effect atoms. For engine atoms, `contrast.difference` states how the partner's cost and dilemma differ.
- Every anime title's contrast set includes ≥1 `cross_medium` partner.

## Check record — `checks.jsonl`
```json
{
  "target_id": "",
  "target_type": "mechanism|proof",
  "verdict": "ACCEPT|REVISE|REJECT|CONTESTED|NEEDS_ADJUDICATION",
  "reasons": ["unsupported", "overreach", "merged_claims", "off_vocab", "contradiction", "circular", "granularity", "scope_leak"],
  "revision": null,
  "provenance": {}
}
```
**Load-bearing eligibility:** P3 verdict `load_bearing` AND CHECK accepted (directly or after one REVISE) AND `explanation == settled` AND `support.status` in {`profile_only`, `episode_backed`}.

## Transfer atom (P4) — `transfers.jsonl`
```json
{
  "transfer_id": "", "source_atom_id": "", "atom_kind": "effect|engine",
  "pattern": "≤25 words; no proper nouns; no medium-specific words",
  "bridge": ["enum from bridge.json"],
  "essential_conditions": ["≤12 words each"],
  "variable_details": ["≤12 words each"],
  "failure_conditions": ["≤12 words each"],
  "mechanism": "≤20 words: how the pattern works (v1.8)",
  "principle": "≤25 words, in the form when X, do Y, because Z (v1.8)",
  "anti_pattern": "≤12 words: the failure the principle prevents (v1.8)",
  "provenance": {}
}
```
Example (illustrative): pattern *only the protagonist can see the measure of his own growth, so the audience shares his secret*. Essential: *progress visible to the audience*; *hidden from other characters*. Variable: *form of the interface*; *setting*; *what is being measured*. Failure: *others can see the measure*; *growth stops being measurable*.

**Abstraction ladder (v1.8):** `mechanism`, `principle` and `anti_pattern` follow the pattern's rules (no names, no medium words). The principle must contain "when" and then "because". They are optional in the record, so earlier transfers stay valid, and required in every P4 answer (prompt 1.1.0).

## Episode record (M6) — `episodes.jsonl`
```json
{
  "episode_id": "", "title_id": "",
  "locator": {"season": 1, "episode": 1, "episode_title": "", "numbering": "broadcast"},
  "selection_reason": "pilot|moment|finale|control",
  "summary": "paraphrase, ≤60 words",
  "function": "enum",
  "end_hook": "enum",
  "engine_beat": {"engine_atom_id": "", "advances": "goal|constraint|strategy|benefit|cost|dilemma", "note": "≤25 words"},
  "decisions": [
    {"agent": "", "goal": "", "options": ["", ""], "choice": "", "rejected": "",
     "expected": "", "actual": ""}
  ],
  "info_shift": {"audience_learns": "", "characters_learn": "", "gap_change": "widens|narrows|flips|none"},
  "setups": ["≤12 words each"],
  "payoffs": [{"payoff": "≤12 words", "setup_episode_id": null}],
  "moment_refs": ["moment_ids"],
  "atom_support": [{"atom_id": "", "relation": "supports|contradicts|reframes", "note": "≤25 words"}],
  "proposed_atoms": [{"atom_kind": "effect|engine", "draft": "≤25 words"}],
  "source": "web", "source_ref": "URL", "verification": "web_confirmed|unresolved",
  "provenance": {}
}
```
At most `episodes.max_decisions_per_episode` decisions. Episodes without a fetched source are not recorded (see coverage `unsourced`).

## Link (M6) — `links.jsonl`
```json
{
  "link_id": "", "title_id": "",
  "from_id": "", "to_id": "",
  "type": "sets_up|pays_off|reveals|reframes|advances|supports|contradicts|enables|prevents",
  "evidence": "≤25 words",
  "provenance": {}
}
```
`enables` and `prevents` are causal: their evidence must show more than the order of events.

## Pattern card (M7) — `patterns.jsonl`
```json
{
  "pattern_id": "",
  "statement": "context → trigger → response → consequence, ≤40 words",
  "transfer_ids": [],
  "supporting_titles": [],
  "counterexamples": [{"title_id": "", "why": "≤25 words"}],
  "boundary_conditions": ["≤12 words each"],
  "alternative_explanations": ["≤25 words each"],
  "scope": "title|corpus_subset|corpus",
  "predictive": false,
  "predictive_evidence": [{"title_id": "", "atom_id": "a load-bearing atom of that title"}],
  "provenance": {}
}
```
Frequency alone is not causation: a pattern card is invalid unless a counterexample search was run (an empty result is recorded as such).

**Principle test (v1.8, code at M7):** a card is `predictive` only if its principle explains at least one load-bearing-eligible atom in a held-out title, one not among its `supporting_titles`; `predictive: true` needs such an item in `predictive_evidence`. Only predictive principles feed ideation as principles.

## Coverage ledger — `coverage.jsonl`
```json
{
  "title_id": "",
  "passes_done": ["P1", "VERIFY", "P2", "P3", "CHECK", "P4", "EP", "ROLLUP"],
  "field_completion": 0.0,
  "verified_share": 0.0,
  "modules_active": [],
  "episodes": {
    "in_scope": 0, "indexed": 0, "unsourced": 0,
    "selection": {"pilot": 0, "moment": 0, "finale": 0, "control": 0}
  },
  "episode_backed_share": 0.0,
  "provenance": {}
}
```
Corpus-level coverage is derived in DuckDB. A zero-count gap is reportable as "open" only when the rule-of-three bound 3/n is below 0.02, where n is the titles that have the relevant module active with `field_completion ≥ coverage.min_field_completion` (or, for census-backed gaps, the census rows with a power system). This replaced `coverage.min_titles_with_module` (statistics as gates, 2026-09-27).

## Idea card — `ideas.jsonl`
```json
{
  "idea_id": "", "target_domain": "anime",
  "logline": "≤30 words", "premise": "≤120 words",
  "theme_root": "the core_question it anchors to",
  "engine": {
    "goal": "", "constraint": "", "strategy": "", "benefit": "", "cost": "", "dilemma": "",
    "dramatic_question": ""
  },
  "transformation": {
    "operator": "reverse_incentive|redistribute_knowledge|transfer_cost|change_rule|combine_mechanisms|import_lane|revive_execution_flop|borrow_system",
    "source_transfer_ids": [],
    "what_changed": "≤25 words"
  },
  "consequences": {"choices": "≤25 words", "relationships": "≤25 words", "outcomes": "≤25 words"},
  "profile": {
    "gate": "", "cost_of_power": "", "progression": "", "set_structure": "",
    "visible_counter": "", "fight_medium": "", "power_is": ""
  },
  "bridge": ["bridge concepts of atoms used"],
  "grid_cell": "derived from profile per config.ideate.grid_dims",
  "atoms_used": ["transfer_ids (eligible only)"],
  "borrowed_from": ["title_ids"],
  "broken_rule": "", "appetite": "",
  "closest_existing": "title_id",
  "why_not_a_clone": "≤40 words",
  "gates": {
    "structural_jaccard_max": 0.0, "procedural_jaccard_max": 0.0,
    "premise_cosine_max": 0.0, "novel_combo": true,
    "graveyard_hits": [],
    "failure_conditions_triggered": [],
    "consequence_test": {"choices": true, "relationships": true, "outcomes": false, "h1_pass": true},
    "coherence": "pass|fail",
    "pmi_key_pair": {"basis": "enum|bridge", "pair": ["path=value or bridge:concept", "..."], "pmi": -2.3,
                     "together": 0, "n": 214, "adequate": true, "novel": true}
  },
  "taste": {"criteria_met": ["T1"], "evidence": {"T1": "..."}, "hard_fail": false},
  "why_different": "≤40 words; required when a premise-level graveyard combination matches (v1.6)",
  "premortem": [{"risk": "≤25 words", "source_title_id": "a mixed/flop title", "mitigation": "≤25 words"}],
  "revival_of": {"title_id": "an execution-level flop", "failure_evidence_ref": "URL or null", "improvement": "≤25 words"},
  "runway": {"hurts_by_arc5": true, "reason": "≤25 words"},
  "status": "candidate|champion|rejected",
  "arm": "animedex|baseline_loop|baseline_single (M5; default animedex)",
  "generation": 0, "parent_ids": [],
  "human_rating": null,
  "provenance": {},
  "mc": {"edge": "power_combat.mc_edge", "origin": "≤25 words", "wound": "≤15 words",
         "origin_power_link": "character.origin_power_link"},
  "power_kit": {"kind": "character.power_kind", "medium": "≤6 words", "functions": ["3–6, ≤15 words each"],
                "tools": [{"tool": "≤15 words", "function": "one of the functions"}], "limits": ["1–5, ≤15 words each"],
                "creativity_path": "≤20 words"},
  "thematic_argument": {"thesis_mc": "≤15 words", "antithesis_villain": "≤15 words", "resolution": "≤20 words"},
  "audience_promise": "≤15 words",
  "escalation_model": "core.escalation_model",
  "core_fantasy": ["core.core_fantasy"],
  "premise_abstraction": "≤20 words; no names or medium words",
  "rules": {"version": "the steering library's version", "satisfied": ["rule.nnn"], "failed": ["rule.nnn"]}
}
```
- **v1.8 concept layer:** every field from `mc` on is optional, so earlier cards stay valid. Power-kit tools (at most 3) each name one of the kit's functions. `core_fantasy` lists a value once. A rule is listed as satisfied or failed, not both.
- The clone check embeds `premise_abstraction`, not the surface premise (IDEATE, M5).
- `gates.pmi_key_pair` (statistics as gates; optional, so earlier cards stay valid) is the pair the novelty gate judged: two profile values or two bridge concepts, their PMI over the `n` rows that could show both, how often they were seen `together`, whether that subset is adequate by the rule of three, and whether the pair is novel (PMI ≤ −1.0 on an adequate subset, D-021).
- `champion` means the card holds its MAP-Elites cell. "Elite" is reserved for Kingsley's verdict (`human_rating`, `eval/blind/`).
- `arm` (M5, controls decision 1) names the blind-review arm that wrote the card. Only `animedex` cards must list atoms (`atoms_used`, `source_transfer_ids` ≥ 1). `baseline_loop` cards (the same loop with an empty brief) are stored in `data/blind/baseline_loop/`, never in `ideas.jsonl` or the archive.
- The `profile` uses the same enums as titles so overlap is computable.
- `consequence_test` records, per dimension, whether the idea's consequences differ from what happens in `closest_existing`. `h1_pass` requires at least `ideate.h1_min_changed_dimensions` of 3.

## Steering rule (v1.8) — `steering/rules.yaml`
Kingsley's own input: git-ignored, backed up to the private data repo. `config/steering.example.yaml` shows the format; a missing file is an empty library.
```yaml
version: "1.0.0"
rules:
  - id: rule.001                     # rule.nnn, unique
    rule: "≤30 words"
    strength: hard                   # hard: an idea that fails it is rejected before scoring; soft: listed on the card
    examples: ["1–2 examples, ≤40 words each"]
    check: {field: mc.edge, op: not_in, values: [biggest_number, not_strongest]}   # optional
```
- `check` is for rules code can test: `field` is a dotted idea-card path and `values` must belong to that field's vocab. On a list field, `in` passes when any member is listed and `not_in` when none is. Rules without a check are answered yes/no by the judge.
- A library with rules needs a `version`; each card records it in `rules.version`. IDEATE wires the rules in M5.

## Prior-art check (v1.6) — `prior_art.jsonl`
```json
{
  "check_id": "", "claim_kind": "T1|T4|lane", "subject_id": "idea_id or lane:<concept>",
  "claim": "the absence being claimed, paraphrased",
  "queries": ["searches run"],
  "verdict": "clear|counterexample|inconclusive",
  "counterexamples": [{"title": "", "url": "a page retrieved in the same call", "match_note": "≤25 words"}],
  "provenance": {}
}
```
- Every T1 claim, T4 zero-occurrence claim, and imported/export lane claim carries one.
- `counterexample` downgrades the claim: T1 falls back to T2 if the idea still differs on a load-bearing pattern; otherwise the claim is dropped.
- `inconclusive` counts as not cleared.

## Census entry (v1.6) — `census.jsonl`
```json
{
  "census_id": "anilist:127401", "title": "", "year": 0, "medium": "anime|donghua", "format": "",
  "popularity": 0, "has_power_system": true,
  "gate": "", "cost_of_power": "", "progression": "", "visible_counter": "", "fight_medium": "", "power_is": "",
  "borrowed_system": "game|exam_or_school|job_or_bureaucracy|market_or_economy|sport|social_rating|law_or_contract|card_or_collection|crafting_or_cooking|military_rank|ritual_or_religion|none|other",
  "set_structure": "", "story_engine": "", "mc_archetype": "",
  "trust": "recall", "batch_id": "", "provenance": {}
}
```
- **v1.8 census fields:** `set_structure` (titles with a power system), `story_engine` and `mc_archetype` (every title), same vocab as the title fields, so gap counts cover them (census prompt 1.1.0).
- **Counts only.** The census measures how occupied the grid is, which decides whether a zero is trustworthy. It gates `borrow_system`. No atom, transfer, idea, or ideation prompt ever references a census entry.
- **Catalog.** The title list comes from a real catalog (AniList); model recall never supplies it.

## Archive — `archive.jsonl`
One record per occupied grid cell: `{cell_key, idea_id, fitness, replaced_idea_id, generation}`.

## Controlled vocabulary (`vocab.json`; v1.1.0 starter, now 1.5.0)
Structure:
```json
{
  "version": "1.1.0",
  "fields": {
    "power_combat.gate": {
      "enum": ["innate", "trained", "inherited", "contract", "system_granted", "artifact", "death_or_ritual", "mutation", "none", "other"],
      "alternate_labels": {"system_granted": ["game system", "status window"]},
      "cq_refs": ["CQ-G01", "CQ-I03"]
    }
  }
}
```

| Field | Enum |
|---|---|
| medium | anime, donghua, western_animation, adult_animation, live_action, film |
| outcome.failure_level | premise, execution, external, unknown |
| format | film, episodic, serialized, hybrid |
| scope.numbering | broadcast, streaming, home_video |
| power_combat.progression | lateral, linear, hybrid, none |
| power_combat.gate | innate, trained, inherited, contract, system_granted, artifact, death_or_ritual, mutation, none, other |
| power_combat.cost_of_power | physical_toll, lifespan, memory, identity_or_humanity, relationships, resource, moral, self_imposed_restriction, imposed_penalty, none, other |
| power_combat.visible_counter | numeric_level, rank_tier, collectible_count, transformation_stage, gauge, none, other |
| power_combat.fight_medium | unarmed, weapon, energy, summon, vehicle_or_mech, mixed |
| relationships.power_is | individual, paired, collective |
| core.outcome | hit, mixed, flop |
| atom_kind | effect, engine |
| feeling | awe, triumph, dread, grief, catharsis, superiority, curiosity, tension, humor, warmth, disgust, other |
| explanation | settled, contested |
| support.status | profile_only, episode_backed, mixed, contradicted |
| moment_type | transformation, reveal, sacrifice, first_victory, power_up, defeat, reversal, reunion, other |
| episode.selection_reason | pilot, moment, finale, control |
| episode.function | pilot_hook, setup, escalation, reversal, revelation, payoff, respite, closure, other |
| episode.end_hook | threat_cliffhanger, reveal_cliffhanger, open_question, power_tease, emotional_resolution, none, other |
| info_shift.gap_change | widens, narrows, flips, none |
| link.type | sets_up, pays_off, reveals, reframes, advances, supports, contradicts, enables, prevents |
| transformation.operator | reverse_incentive, redistribute_knowledge, transfer_cost, change_rule, combine_mechanisms, import_lane, revive_execution_flop, borrow_system |
| anime_production.demographic | shonen, seinen, shojo, josei, kodomo, no_magazine_demographic, other |
| anime_production.source_medium | manga, light_novel, web_novel, webtoon, manhua, original, game, other |

**Vocab 1.5.0 (v1.8):**
- The v1.8 enums (title fields, `core.institution_type`, `core.anticipation_hook_type`, the `character.*` fields, `outcome.failure_pattern`) carry exactly the request's values; see `vocab.json`.
- Enum proposals, applied as the lead decided: `power_combat.cost_of_power` adds self_imposed_restriction (the user chooses a limit or vow to gain strength) and imposed_penalty (an outside authority or system punishes failure or disobedience with harm); `power_combat.visible_counter` adds gauge (a filling meter or percentage the audience watches approach a threshold); `anime_production.demographic` adds no_magazine_demographic. A wish an entity grants during a catastrophe is `contract`; a qualitative power category is `none` for visible_counter. Nothing else changed.
- **Discrimination tests (grid reliability ruling):** every value of gate, cost_of_power, progression and visible_counter carries one sentence (≤30 words) saying what makes it right and its nearest neighbour wrong, under `tests` on the vocab field. The P1 prompt renders them from `vocab.json`, the one source.

**Bridge concepts** (`bridge.json` v1.1.0): `borrowed_system`, `broken_rule`, `unserved_appetite`, `visible_progress_counter`, `cost_of_advancement`, `access_gate`, `core_tension`, `information_asymmetry`, `bond_as_power`. Each carries a definition and `cq_refs`.

Phrase fields (e.g., `logline_hook`, `core_question`) are short normalized phrases, not enums. On an enum field, `other:<phrase>` writes a proposal to `ontology/proposals/` and stores `other` until Kingsley approves.

## Invariants (tested)
- Every vocab field, module, and bridge concept has ≥1 `cq_refs`; every CQ's `requires:` references real fields.
- Every canonical record validates against its schema.
- No canonical enum value outside `vocab.json`.
- Every title has a scope; every episode's season is inside its title's scope.
- Every mechanism atom has exactly one of `effect` / `engine`, matching `atom_kind`; every effect atom has `rival_because`.
- Every transfer atom has non-empty essential, variable, and failure conditions.
- Every moment, mechanism, proof, check, transfer, episode, and link references existing records.
- Every idea card has a complete engine and all three consequence dimensions filled.
- Transfer patterns contain no title or character names (string match against a name list built from canonical titles, moments, and episodes). v1.8: the list also takes every word of each character's name, the capitalized mid-sentence words of character texts and of list and group parts; the check also covers the transfer's mechanism, principle and anti-pattern, and pattern-card statements. A title's premise_abstraction is checked against its own title, its own cast's names, and any mid-sentence capital, so adding a title never changes another title's result.
- (v1.8) A title carries every lens field its vocab version requires; a secondary differs from its primary; promise_break only on mixed/flop titles and with a source.
- (v1.8) Characters: a known title; at most 4 per title, one per role (mentor or deuteragonist share a slot), exactly one protagonist; at most 3 power kits, the protagonist's first; villain fields only on the main antagonist; turning points at in-scope episodes.
- (v1.8) Failure patterns only on mixed/flop outcomes, each with a URL. A predictive pattern card has held-out evidence, and that evidence is a load-bearing-eligible atom.
- (v1.8) Every new lens field, character field, `outcome.failure_patterns`, the P4 ladder fields, `pattern.predictive`, the idea-card concept fields, and the new census fields have ≥1 CQ (`CQ_RECORD_FIELDS`; the orphan check).
