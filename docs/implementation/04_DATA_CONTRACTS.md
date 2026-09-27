# 04 — Data Contracts

Pydantic models in `src/animedex/models/` are the source of truth for shapes. JSON Schemas in `schemas/` are generated from them (`make schemas`). Every record carries the provenance block.

## Conventions
- **IDs:** `title_id` = slug + year (`hunter_x_hunter_2011`). Moments `{title_id}.mo.{nn}`; atoms `{title_id}.m.{nnn}`; transfers `{title_id}.t.{nnn}`; episodes `{title_id}.s{ss}e{ee}`; links `{title_id}.l.{nnnn}`; patterns `pattern.{nnn}`; ideas `idea.{run_id}.{nnn}`.
- **Versions:** semver for `schema_version`, `vocab_version`, `bridge_version`, and each prompt file.
- **Text:** paraphrase only. Phrases ≤ 12 words, sentences ≤ 25 words, episode summaries ≤ 60 words, unless noted. No quotes from sources.

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
  "value": "enum value | ≤12-word phrase | null",
  "condition": "≤12 words; character fields only (flaw, moral_line): when it shows / what would make them cross it",
  "conf": 0.0,
  "uncertainty_reason": "≤12 words; required when conf < verify.conf_threshold",
  "source": "recall|web|episodes",
  "verification": "not_required|unverified|web_confirmed|web_corrected|derived_from_episodes|unresolved",
  "source_ref": "URL or null",
  "epistemic": "observed|derived|interpretive|external_metric"
}
```
`conf` is a routing signal (it decides what gets verified), not a calibrated probability. Never report it as one.

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
  "provenance": {}
}
```

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
  "evidence_refs": ["field paths, moment_ids, or episode_ids"],
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
    "via_partner": "title_id",
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
  "provenance": {}
}
```
Example (illustrative): pattern *only the protagonist can see the measure of his own growth, so the audience shares his secret*. Essential: *progress visible to the audience*; *hidden from other characters*. Variable: *form of the interface*; *setting*; *what is being measured*. Failure: *others can see the measure*; *growth stops being measurable*.

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
  "provenance": {}
}
```
Frequency alone is not causation: a pattern card is invalid unless a counterexample search was run (an empty result is recorded as such).

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
Corpus-level coverage is derived in DuckDB. A zero-count gap is reportable as "open" only if at least `coverage.min_titles_with_module` titles have the relevant module active with `field_completion ≥ coverage.min_field_completion`.

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
    "gate": "", "cost_of_power": "", "progression": "",
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
    "coherence": "pass|fail"
  },
  "taste": {"criteria_met": ["T1"], "evidence": {"T1": "..."}, "hard_fail": false},
  "why_different": "≤40 words; required when a premise-level graveyard combination matches (v1.6)",
  "premortem": [{"risk": "≤25 words", "source_title_id": "a mixed/flop title", "mitigation": "≤25 words"}],
  "revival_of": {"title_id": "an execution-level flop", "failure_evidence_ref": "URL or null", "improvement": "≤25 words"},
  "runway": {"hurts_by_arc5": true, "reason": "≤25 words"},
  "status": "candidate|champion|rejected",
  "generation": 0, "parent_ids": [],
  "human_rating": null,
  "provenance": {}
}
```
- `champion` means the card holds its MAP-Elites cell. "Elite" is reserved for Kingsley's verdict (`human_rating`, `eval/blind/`).
- The `profile` uses the same enums as titles so overlap is computable.
- `consequence_test` records, per dimension, whether the idea's consequences differ from what happens in `closest_existing`. `h1_pass` requires at least `ideate.h1_min_changed_dimensions` of 3.

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
  "trust": "recall", "batch_id": "", "provenance": {}
}
```
- **Counts only.** The census measures how occupied the grid is, which decides whether a zero is trustworthy. It gates `borrow_system`. No atom, transfer, idea, or ideation prompt ever references a census entry.
- **Catalog.** The title list comes from a real catalog (AniList); model recall never supplies it.

## Archive — `archive.jsonl`
One record per occupied grid cell: `{cell_key, idea_id, fitness, replaced_idea_id, generation}`.

## Controlled vocabulary (`vocab.json` v1.1.0 starter)
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
| power_combat.cost_of_power | physical_toll, lifespan, memory, identity_or_humanity, relationships, resource, moral, none, other |
| power_combat.visible_counter | numeric_level, rank_tier, collectible_count, transformation_stage, none, other |
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
| anime_production.demographic | shonen, seinen, shojo, josei, kodomo, other |
| anime_production.source_medium | manga, light_novel, web_novel, webtoon, manhua, original, game, other |

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
- Transfer patterns contain no title or character names (string match against a name list built from canonical titles, moments, and episodes).
