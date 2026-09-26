# 01 — Product Contract

## Roles
| Role | Who | Relationship to the system |
|---|---|---|
| Producer | Kingsley | Owns taste, approves ontology and threshold changes, rates ideas |
| Builder | Coding agent | Implements milestones under 10_AGENT_EXECUTION_RULES |
| Extractor | LLM via API | Runs passes; no authority over vocabulary or taste |
| Researcher | Ideation agent | Queries the index; generates and judges idea cards |

## Inputs
- `corpus/titles.yaml`: titles with medium, format, **scope** (version, seasons, numbering), and role tags (`gold`, `hit`, `mixed`, `flop`, `contrast`)
- LLM recall (P1 draft) plus targeted web verification
- Episode summaries fetched transiently from the web (M6+), paraphrased, never stored verbatim
- Ontology (controlled vocabulary, bridge concepts) and competency questions

## Outputs
| Output | Location | Consumer |
|---|---|---|
| Title profiles | `data/canonical/titles.jsonl` | Pipeline, DuckDB |
| Moments | `moments.jsonl` | P2, fight briefs |
| Outcomes | `outcomes.jsonl` | Gaps, graveyard |
| Mechanism atoms (effect + engine) | `mechanisms.jsonl` | P3, ideation |
| Proof records | `proofs.jsonl` | Load-bearing filter |
| Check records | `checks.jsonl` | Audit |
| Transfer atoms | `transfers.jsonl` | Ideation, future target domains |
| Episode records (M6) | `episodes.jsonl` | Rollup, analysis, episode generation |
| Intra-title links (M6) | `links.jsonl` | Information economy, setup/payoff, episode generation |
| Pattern cards (M7) | `patterns.jsonl` | Ideation, gap reports |
| Idea cards | `ideas.jsonl` + `build/reports/ideas.md` | Kingsley |
| Elite archive | `archive.jsonl` | Kingsley, ideation |
| Gap report | `build/reports/gaps.md` (derived) | Kingsley, ideation |

## Promises
- **P-01** Every record traces to a title, pass, prompt version, model, and run.
- **P-02** Every P1 field carries a confidence and a verification status; low-confidence fields carry a reason.
- **P-03** Outcomes, sensory fields, and moment locators are always web-verified or explicitly marked `unresolved`.
- **P-04** No off-vocabulary value enters canonical data silently.
- **P-05** Every idea card names its closest existing title and argues why it is not a clone.
- **P-06** A gap is reported as "open" only with coverage and graveyard checks attached.
- **P-07** Canonical data rebuilds all derived outputs deterministically.
- **P-08** No transcripts, subtitles, dialogue, or copied text are stored. Paraphrase only.
- **P-09** Every title declares its scope; every pass stays inside it.
- **P-10** Every idea card carries its own engine and traces the consequences of its transformation.
- **P-11** Episode records exist only for in-scope episodes with a fetched source. Never from recall alone.
- **P-12** Every show-level atom carries its episode support status and whether its explanation is settled.

## Non-promises
- Not a catalog of anime facts. Completeness for any single title is not a goal.
- Episode coverage is sampled (key episodes), not exhaustive.
- Recall-only fields are labeled, not guaranteed correct.
- The taste judge is advisory. Kingsley's rating is final.

## Competency questions (starter set)
Every field, module, vocabulary entry, and bridge concept must trace to at least one CQ (enforced; see 04). The field→CQ mapping lives in `ontology/competency_questions.yaml` under `requires:`. In M1 the agent generates a coverage table; an orphan field is resolved by adding an approved CQ or deleting the field.

**Gap analysis**
- **CQ-G01** Which gate × cost-of-power combinations have zero titles, given adequate coverage?
- **CQ-G02** For each empty cell: untried, or tried by a mixed/flop title, and what was its recorded failure reason?
- **CQ-G03** Which unserved appetites (and the borrowed templates and broken rules that served them) appear in hits but in only one title's load-bearing atoms?
- **CQ-G04** Which progression types have never been paired with a given fight medium?
- **CQ-G05** Which load-bearing patterns appear in ≥2 non-anime titles and 0 anime titles? *(imported lanes)*
- **CQ-G06** Which load-bearing anime patterns never appear in Western media? *(export lanes)*
- **CQ-G07** Where is coverage too thin to trust a zero?
- **CQ-G08** Which tone × premise-engine combinations are unused in battle anime?
- **CQ-G09** Which source mediums, demographics, and adaptation-fidelity levels cluster among hits vs. flops, with confounders shown?

**Ideation**
- **CQ-I01** Which load-bearing transfer atoms share a bridge concept but come from different media?
- **CQ-I02** Which pairs of load-bearing atoms both appear in hits but never co-occur?
- **CQ-I03** For a chosen theme (`core_question`), which power gates have never embodied it?
- **CQ-I04** What is the nearest existing title to a candidate idea, by structural overlap and logline/premise similarity?
- **CQ-I05** Does a candidate's key combination match a flop's load-bearing combination?
- **CQ-I06** Which information-economy patterns (central mystery × knowledge gap × reveal cadence) have never been used with a visible power counter?
- **CQ-I07** Which relationship structures (`power_is` = paired/collective; core bond, rival, mentor, team structure) are unused in battle anime?
- **CQ-I08** Which comedic engines from Western/adult animation have never been paired with a power ladder?
- **CQ-I09** Which film structures (act structure, runtime compression, set pieces, closure) could compress into a single anime arc or cour?
- **CQ-I10** Which character and world structures (want vs. need, flaw and its condition, moral line and its condition, opposition and its logic, stakes/clock, world rules) recur in hits' load-bearing atoms?
- **CQ-I11** Which engine atoms from hits (goal, constraint, strategy, cost, dilemma) have never been combined with a given gate or cost of power?
- **CQ-I12** For a transfer pattern, which variable details have only ever taken one value across the corpus?

**Episodes and moments**
- **CQ-E01** Which moment types recur across the most iconic fights, and what mechanism and primary feeling explain each?
- **CQ-E02** Which pilot structures (function, end hook, information shift) precede hits vs. flops? *(answered from pilot episode records, M6)*
- **CQ-E03** For an iconic fight, what are its power rules, choreography, and visual signature? *(fight brief)*
- **CQ-E04** Which series engines (episodic vs. serialized, reset, cliffhanger cadence, season arc shape) pair with hits in each medium?
- **CQ-E05** Does each title's engine run in ordinary (control) episodes, or only in highlight episodes?
- **CQ-E06** How far apart are setups and payoffs, and which setups stay unresolved?
- **CQ-E07** Which show-level atoms are episode-backed, mixed, or contradicted?
- **CQ-E08** Which decision shapes (options, rejected alternative, expected vs. actual outcome) recur in hits' key episodes?

## Quality bars
| Bar | Target |
|---|---|
| P1 enum-field agreement across two runs (gold titles) | ≥ 0.80 |
| P3 load-bearing verdict agreement across two runs | ≥ 0.70 |
| Model load-bearing recall vs. Kingsley's blind annotation | ≥ 0.60 |
| Web correction rate per field | Tracked (shows where recall is weak) |
| Share of load-bearing atoms that are episode-backed (M6+) | Tracked; should rise as episodes are added |
| Blind review vs. baseline | ANIMEDEX wins a majority of greenlights |
| Blind review lift, M6 vs. M5 | Reported |
