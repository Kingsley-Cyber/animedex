# M0 Gap Report: ANIMEDEX v1.1

| | |
|---|---|
| Date | 2026-09-26 |
| Spec | `docs/implementation/` v1.1 (CHANGELOG 2026-09-26) |
| Author | Claude Code (claude-opus-5-5) |
| Code changed | None |
| Cost | $0 (no model or web calls) |
| Status | **Approved at G0, 2026-09-26.** Decisions and changes: `reports/M0_REPORT.md` (G0 outcome), `CHANGELOG.md` v1.2 |

## 1. Verdict
- **No ANIMEDEX code exists.** The repo holds only the v1.1 spec. A search of the home folder found no code that mentions ANIMEDEX or the anime atom graph.
- **The only earlier artifacts are three v0 design documents** in the read-only mirror of the ChatGPT project "IDEAS ANIME". They describe layer extractors L0–L13, JSON Schemas, a critic prompt, a SQLite/DuckDB build, and a taste rubric, as prose only.
- **07's expected reuse list (canonical JSONL, schemas, atomic writes, critic, DuckDB build, cache keys) has nothing to port.** Every component in 03 is a new build. REUSE / ADAPT / REPLACE below classify each **v0 design idea**, not code.
- **The build runs under URCP** (your `universal-repository-control-plane` repo), per your instruction. The repo is adopted, `harness doctor` is OK, and M0–M5 plus gates G0/G1/G4 are tracked in Beads (§8).
- **Decisions:** 4 needed during M1, 5 can wait (§11). One is a real doc conflict (G-1). 8 smaller gaps get defaults I'll apply unless you object (§7).

## 2. What was audited
| Location | Contents | Finding |
|---|---|---|
| `/Users/king/Desktop/Ideation` | 14 spec files at root + `animedex-implementation-docs.zip` (same 14 under `docs/implementation/`) | Byte-identical (`cmp`). No git, code, data, or config before M0. |
| `~/.codex/.chatgpt-projects/g-p-6ab73a43f23481919350fe48ad32eb85/sources/` (ChatGPT project "IDEAS ANIME", read-only mirror) | **v0-A** `animedex_design.md` · **v0-B** `anime-atom-graph-research-architecture.md` · **v0-C** `ANIME_GRAPH_SPEC.md` | Design prose only (Appendix A). |
| `~/Downloads/animedex_design.md` | Same file as v0-A | Duplicate. |
| Home folder, Library and caches excluded | Code and config files (`.py .toml .yaml .json .jsonl .sql .sh Makefile`) mentioning animedex, anime_graph, anime-atom, atom_graph | 0 hits (`rg` exit 1 = no match). Codex session logs: 0 hits. |
| Codex app state | Thread "Design anime semantic extraction" (2026-09-26) | Ran inside the read-only mirror. Design conversation, no code. |
| GitHub `Kingsley-Cyber` (13 repos) | Names and descriptions | No ANIMEDEX repo. `universal-repository-control-plane` (URCP) is the harness for this build, not a code source (§8). |

**Legend:** **REUSE** keep the v0 idea as is (still new code) · **ADAPT** keep the idea, reshape it to 03–05 · **REPLACE** v1.1 supersedes it · **NEW** no v0 counterpart · **DROP** v0 element with no v1.1 home.

## 3. Components vs 03 (repo layout)
Code today is "none" for every row.

| 03 component | v0 source | Status | Gap to close (03–05) |
|---|---|---|---|
| `pyproject.toml`, `Makefile`, `README.md` | v0-A tree (`make extract/verify/build/eval/render`) | ADAPT | Targets become 05's: `validate`, `build`, `clean-build`, `test`, `eval`, `smoke`, `schemas`. |
| `.env.example`, `config/settings.yaml` | — | NEW | 05 placeholders + pricing table and matcher model (G-17). |
| `corpus/titles.yaml` | v0-A `show_meta.json` | ADAPT | Add scope block and role tags; tiers hit/solid/mediocre/flop → hit/mixed/flop. |
| `ontology/vocab.json` | v0-A ontology (enums, field_specs, proposal_queue, changelog) | ADAPT | 04 shape: `enum` + `alternate_labels` + `cq_refs` per field; semver `1.1.0`. |
| `ontology/bridge.json` | v0 L2 structural concepts | ADAPT | 9 concepts, each with a definition and `cq_refs`. |
| `ontology/competency_questions.yaml` | v0-A Q1–Q25 | REPLACE | 01's G01–G09, I01–I12, E01–E08 with `requires:`. |
| `ontology/proposals/`, `migrations/` | v0-A proposal queue + migration scripts | REUSE | Same door: off-vocab → proposal file, store `other`. |
| `schemas/` | v0-A: JSON Schema is the source, pydantic generated from it | REPLACE | Direction flips: pydantic is the source; `make schemas` generates JSON Schema. |
| `prompts/p1_what.md`, `p1_modules/*.md` | v0 per-layer prompts + v0-B extraction "constitution" | REPLACE | One P1 call: core + active modules + moments. |
| `prompts/verify_web.md` | — (v0 banned recall; its "verify" checked entailment against a source pack) | NEW | |
| `prompts/p2_why.md`, `p3_proof.md`, `p4_transfer.md` | — | NEW | |
| `prompts/check_critic.md` | v0-B critic (ACCEPT/REVISE/REJECT/NEEDS_ADJUDICATION; falsify, not improve) | ADAPT | Add `CONTESTED`, `scope_leak`, `circular`, and explanation test → REVISE. |
| `prompts/ep_evidence.md`, `rollup_match.md` | — | NEW (M6) | Not in V1. |
| `prompts/ideate_{generate,judge}.md` | v0-A recipes A–C + 0–2 × 5 rubric (pass ≥ 6/10) | REPLACE | Six operators; T1–T5 with required evidence; H1 consequence test; lexicographic fitness. |
| `src/animedex/cli.py`, `config.py` | — | NEW | typer; every 05 command, later stages stubbed. |
| `models/` | v0-C pydantic `StructuralAtom` sketch | REPLACE | One model per 04 record. |
| `providers/` | — (v0 has cost estimates only) | NEW | `complete(system, user, json_schema, params) -> (json, usage)`; `openai_compatible`, `anthropic`, `mock`. |
| `embeddings/` | v0-A local sentence-transformers | ADAPT | Local OpenAI-compatible `/v1/embeddings` over httpx (no torch); mock = deterministic hash vectors. |
| `search/` | v0-B INGEST source packets (store text + checksum) | REPLACE | `search(query)`, `fetch(url)`; text transient, never stored. |
| `pipeline/canonicalize` | v0-A `canonicalize.py` (entity resolution, dedupe, vocab mapping) | ADAPT | No cross-show entity resolution; alternate-label normalization; within-title atom dedupe; coverage ledger. |
| `pipeline/p1 … p4`, `check` | v0 EXTRACT + CRITIC | see §5–6 | |
| `pipeline/ep`, `rollup` | v0-C granularity roll-up rules | REPLACE (M6) | Not in V1. |
| `store/` atomic writes | v0-A temp file → validate → swap | REUSE | Temp file + rename (06 CANON). |
| `store/` cache | v0-A key = (content hash, prompt hash, model) | ADAPT | 05 key with `upstream_hash` and the support-count exclusion (AC-06). |
| `build/` | v0-A: SQLite primary, DuckDB secondary, Parquet cache | ADAPT | DuckDB only. |
| `analyze/` | v0-A `gap.py` (empty cell, graveyard vs. untried, orphaned mechanics) | ADAPT | Coverage-adequacy gate, lanes, CQ answers to `build/cq_answers/`. |
| `ideate/` | v0-A `recombine.py`, `taste.py`, `nearclone.py` (Jaccard 0.55 flag, cosine 0.75 flag) | REPLACE | MAP-Elites archive; gates at 05's thresholds. |
| `data/{raw,candidates,quarantine,canonical}` | v0-A `canonical/shows/{id}/layer_NN.jsonl` + `derived/` + `views/` | ADAPT | One file per record type, not per show per layer. |
| `eval/{gold,agreement,regression,blind}` | v0-A gold set, Cohen's κ, regression on prompt diffs | ADAPT | 01's bars replace v0's tiered convergence bars; blind baseline review is NEW. |
| `tests/` | — | NEW | |
| v0 LINK pass + `edge.schema.json` | v0-A 13 cross-show edge types | REPLACE | No cross-show edge store (§6, L13). |

## 4. Data contracts vs 04
| v0 shape | 04 record | Status | Change |
|---|---|---|---|
| ShowMeta | title profile (`titles.jsonl`) + corpus entry | ADAPT | Adds scope, `medium`/`format` enums, `modules_active`. |
| Generic atom `{layer, field, value, value_kind, evidence, confidence, status}` | P1 field value `{value, condition, conf, uncertainty_reason, source, verification, source_ref, epistemic}` | ADAPT | Fields live inside the profile, not as separate atoms. |
| `value_kind` factual/interpretive (v0-A); 4 epistemic classes (v0-B) | `epistemic`: observed / derived / interpretive / external_metric | REUSE (v0-B) | Same four classes. |
| `evidence_ref {source_id, locator, quote_hash}` | `source_ref` (URL) + atom `evidence_refs` (field paths, moment IDs, episode IDs) | ADAPT | No source registry, no quote hashes. |
| provenance `{model, prompt_hash, run_id, extracted_at}` | 04 provenance block | ADAPT | Adds pass, prompt/schema/vocab versions, `cache_key`. |
| Atom ID `slug#hash8` | `{title_id}.m.{nnn}` and siblings | REPLACE | |
| Granularity (franchise … beat) | title scope + moment locator (+ M6 episodes) | REPLACE | |
| `status` proposed/verified/rejected | `verification` enum + CHECK verdicts + quarantine | REPLACE | |
| Outcome fields + `failure_attribution` enum | `outcomes.jsonl` (label, signals, confounders, `failure_reason` text) | ADAPT | Failure cause becomes free text (§6, L12). |
| Ontology schema | `vocab.json` + `bridge.json` + `proposals/` + `migrations/` | ADAPT | |
| Edge | — (M6 `links.jsonl` is intra-title only) | REPLACE | |
| — | mechanisms, proofs, checks, transfers, coverage, ideas, archive (+ M6 episodes, links; M7 patterns) | NEW | |

## 5. Passes vs 05
| v0 stage | v1.1 stage | Status | Change |
|---|---|---|---|
| INGEST (v0-B source packets) | VERIFY search/fetch (+ M6 EP) | REPLACE | v1.1 drafts from recall and web-checks flagged fields; v0 banned recall outright. |
| EXTRACT × 14 layers | P1 WHAT | REPLACE | One call per title; verify list attached. |
| CRITIC (entailment vs. pack) | VERIFY (P1 fields vs. web) + CHECK (P2 atoms, P3 proofs) | ADAPT | One stage splits into two. |
| ADJUDICATE | CHECK `NEEDS_ADJUDICATION` → your queue | REUSE | |
| CANONICALIZE | CANONICALIZE | ADAPT | See §3. |
| LINK | P3 contrast + P4 bridge + DuckDB joins (+ M6 links) | REPLACE | |
| DERIVE | BUILD + ANALYZE (+ M6 ROLLUP derived fields) | ADAPT | |
| — | P2 WHY: effect atoms with `rival_because`; 1–3 engine atoms | NEW | |
| — | P3 PROOF: contrast, explanation test, ablation | NEW | |
| — | P4 TRANSFER: neutral pattern + essential / variable / failure conditions | NEW | |
| — | IDEATE: MAP-Elites, operators, consequence tracing, gates, judge | NEW | |

## 6. Layer extractors → P1 fields and P2–P4
Fields are the union of v0-A/B/C. "→ P2" means the idea survives only as a P2 atom, not as a P1 field.

| v0 layer | v1.1 home | Status | Dropped |
|---|---|---|---|
| **L0 Thematic:** root question/theme; theme claim; power, gate, and character embodiment | `core.core_question`; theme claim → P2 effect `because`; embodiment → P2 `element_ref` + judge coherence gate (theme ↔ mechanic) | ADAPT | — |
| **L1 Hierarchical:** world condition, institution, power system, gate, protagonist role, initial hook, clock, stakes | `core.world_rules`; `power_combat.power_source`; `power_combat.gate`; `core.logline_hook`; `core.stakes_clock`; protagonist role → P2 engine `agent` + `constraint` | ADAPT | Separate institution field |
| **L2 Structural:** borrowed pattern, broken rule, served appetite, progress counter, power cost, fantasy promise | `core.borrowed_template`, `core.broken_rule`, `core.unserved_appetite`, `power_combat.visible_counter`, `power_combat.cost_of_power`, `core.primary_feeling` + `core.premise_engine`; five become bridge concepts | REUSE | — |
| **L3 Procedural:** acquisition/eligibility, activation, training, advancement, progression shape, resource, cost, failure condition, combat rule, counterplay, rank system, ceiling, exception | `power_combat.gate` (training → `trained`), `.progression`, `.power_source`, `.cost_of_power`, `.ranking_ladder`, `.signature_technique`, `.fight_medium` | ADAPT | Failure condition, counterplay, ceiling, exception → P2 engine `constraint` / `cost` / `dilemma` when they drive the story |
| **L4 Character:** want, need, flaw, fear, moral line, identity, antagonist goal / logic / theme | `core.want_vs_need`, `core.flaw` + condition, `core.moral_line` + condition, `core.central_opposition`, `core.opposition_logic` | ADAPT | Fear, identity, antagonist theme → P2 engine atoms |
| **L5 Relational:** relationship type, power dependency, authority and emotional direction, rivalry axis, team function, collective power | `relationships.core_bond`, `.rival`, `.mentor`, `.team_structure`, `.power_is`; bridge `bond_as_power` | ADAPT | Emotional direction |
| **L6 Information economy:** knowledge-state transitions (knows, suspects, question opened, clue, false belief, reveal, question closed); open mysteries; reveal cadence; episode-end hook | `core.central_mystery`, `core.knowledge_gap`, `core.reveal_cadence`; bridge `information_asymmetry`; M6: `info_shift`, `end_hook`, `reveals` links | REPLACE | Per-scene transition graph |
| **L7 Episodic:** event functions, arc shape, first-episode hook, beat pattern, escalation cadence | `series_engine.*` (arc shape → `season_arc_shape`; escalation → `cliffhanger_cadence`); `film.*`; M6: pilot record (CQ-E02), `episode.function` | REPLACE | Beat pattern (beat level; M8 at the earliest) |
| **L8 Sensory:** combat medium, power visualization, choreography, color motif, sound motif, camera, movement geometry, impact, silhouette, environment, tempo | `power_combat.fight_medium` (moved out of sensory); `sensory.power_visual_signature`, `.choreography_style`, `.color_motif`, `.sound_motif`, `.animation_signature` | ADAPT | Camera, movement geometry, impact, silhouette, environment, tempo (02 non-goal: per-scene audiovisual analysis) |
| **L9 Valence:** audience feeling, per-atom payload, character feeling, valence/arousal/dominance | `core.primary_feeling`; `feeling` on every P2 atom (12-value enum) | ADAPT | VAD scores, character feeling |
| **L10 Moment:** moment exists, popularity, reason | `moments.jsonl` (3–5: description, locator, `moment_type`, `why_it_hit`); P2/P3 test the reason | ADAPT | Popularity and clip metrics (no engagement data in V1) |
| **L11 Context:** release date, source medium, genre environment, saturation, production and distribution context, what the title pushed against | `year`; `anime_production.source_medium`; `outcomes.confounders` (studio, budget, source popularity, platform, release context); pushback → `core.broken_rule` | ADAPT | Contemporary comparisons, computed saturation |
| **L12 Outcome:** tiers, reception and longevity metrics, confounders, failure attribution (enum + confidence) | `outcomes.jsonl` label / signals / confounders / `failure_reason`; `core.outcome` (always verified) | ADAPT | Failure-cause enum becomes ≤ 25-word text, so the graveyard can show a cause but not filter by it. Flagged for M7 calibration; no change proposed. |
| **L13 Associative:** 13 cross-show edge types | `shares_*` → DuckDB joins + Jaccard; `counterexample_to`, `solves_problem_of` → P3 contrast + T5 evidence; `serves_same_appetite_as` → bridge concepts (CQ-I01); `inverts` → operators `reverse_incentive` / `change_rule`; intra-title → M6 links | REPLACE | Stored cross-show edges |

**v0 enum remap** (reference for prompt authors; no v0 data exists, so nothing migrates):
- gate: birthright → innate · training → trained · inheritance → inherited · contract → contract · system_ui → system_granted · artifact → artifact · ritual → death_or_ritual · infection → mutation · consumption, hybrid → `other` (likely early proposals)
- progression: linear_ladder, rank_promotion → linear · lateral_toolkit, skill_mastery → lateral · branching_tree, class_change, hybrid → hybrid
- cost_of_power: stamina, backlash → physical_toll · lifespan → lifespan · memory → memory · sanity → identity_or_humanity · moral → moral · consumable → resource · collateral → `other` · none → none

**New in v1.1 with no layer behind it:** rival explanations and the explanation test (P2/P3), engine atoms, ablation, the `CONTESTED` state, transfer conditions (P4), title scope, consequence tracing in ideation.

## 7. Spec gaps and conflicts
| ID | Where | Issue | Resolution | You? |
|---|---|---|---|---|
| G-1 | 03 storage tiers vs. 03 web sources, 10 §9 and §19, P-08 | **Conflict.** Raw runs keep "every request/response", but VERIFY (and M6 EP) requests carry fetched web text, which must never be stored. | Log requests with fetched text replaced by `{url, sha256, chars}`; gitignore `data/raw/`. | **D1** |
| G-2 | 04 scope | `scope.numbering` has no N/A value and `seasons` means nothing for a film; films can enter V1 as cross-medium partners. | Allow `seasons: []` and `numbering: null` when `format == film`. | **D2** |
| G-3 | 04 provenance | The `pass` enum has no value for the stage that writes `coverage.jsonl` (CANONICALIZE) or for M7's `patterns.jsonl`. | Add `CANONICALIZE` now, `PATTERNS` at M7. | **D3** |
| G-4 | 01 CQs vs. AC-04 | 6 fields have no CQ: `sensory.sound_motif`, `series_engine.episode_template`, `comedy_satire.satire_target`, `.comic_roles`, `.running_gag_system`, and vocab field `transformation.operator`. 01: an orphan gets an approved CQ or is deleted. | 3 CQ extensions + 1 new CQ (Appendix B). | **D4** |
| G-5 | 04/05 vs. 06 decision rights | Idea `status` includes `elite`, and 05 calls archive occupants elites; 06 says only you mark an idea final "elite". | `elite` = MAP-Elites archive occupant; your verdict = `human_rating` + `eval/blind/`. | **D5** |
| G-6 | This prompt vs. 05 config | The packet needs 20 elites; 3 generations × 12 = 36 candidates, so ≥ 56% must clear every gate and land in distinct cells. | Keep generating (same config) until 20 elites or the budget cap. | **D6** |
| G-7 | 09 vs. gates G0–G4 | AC-17 matching is "spot-checked by Kingsley", a human step with no gate. | The spot-check list goes in the M3 report (G3). | **D7** |
| G-8 | Repo state vs. this prompt | Spec sat at the root, not in `docs/implementation/`; the folder was not a git repo. | Done: spec copied byte-identical to `docs/implementation/`; `git init`; repo-local author = Kingsley; adopted under URCP (§8). Root copies and zip untouched. | **D8, D9** |
| G-9 | 03 flow vs. 05 P3 | P3 partner selection reads **canonical** P1 via DuckDB, but CANONICALIZE is drawn after P4. | CANONICALIZE runs after P1 + VERIFY for the batch, then again after P4. | Default |
| G-10 | This prompt vs. 05 | "`make build` reproduces identical CQ answers", but ANALYZE writes the CQ answers. | `make build` = BUILD + ANALYZE's deterministic CQ step (from M4). | Default |
| G-11 | AC-07 | DuckDB files are not byte-stable across rebuilds. | Hash sorted table contents, not the `.duckdb` file. | Default |
| G-12 | 03 and 10 §5 vs. IDEATE | Only CANONICALIZE and ROLLUP may write canonical data, yet IDEATE produces `ideas.jsonl` and `archive.jsonl`. | IDEATE writes candidates; CANONICALIZE promotes them. | Default |
| G-13 | 04 examples vs. eval integrity | 04's illustrative engine and transfer examples describe a gold title. As prompt few-shots they would hand the model the answer and inflate AC-17 and engine match. | Prompts use synthetic worked examples only, never gold or partner titles. | Default |
| G-14 | 05 P1 prompt | The 0.7 threshold is hardcoded in prompt text while config owns it, and a model-built verify list can miss mandatory items (AC-10). | Render the threshold from config; code recomputes the verify list from `conf` + `always_verify`. | Default |
| G-15 | AC-16 vs. 05/06 | AC-16 flags counts outside 3–8; 05/06 define only the > 8 alarm. | Implement AC-16's < 3 flag as written. | Default |
| G-16 | 09 / AC-12 vs. 05 caching | An agreement rerun with identical params hits the cache and returns run 1. | Agreement reruns carry distinct params (temperature > 0, per 09). | Default |
| G-17 | 05 config | USD budget caps need per-model prices; 09's gold matcher has no model slot. | Add `pricing:` and `models.eval_match` to the G1a fill list. | At G1a |

## 8. Running the build under URCP
Per your instruction (2026-09-26), `Kingsley-Cyber/universal-repository-control-plane` (URCP v0.1.0-alpha, `b645ea5`) controls this build.

| Item | State |
|---|---|
| URCP clone | `~/Documents/universal-repository-control-plane` at `b645ea5`; `harness` on PATH via `uv tool install --editable` |
| Tools installed (you approved) | mise 2026.9.12, bd 1.3.0 (+ dolt), codegraph 3.17.0 |
| Adoption | `harness adopt .` + `harness setup claude`: `.control/control-plane.yaml` (project id `animedex`), `AGENTS.md`, `CLAUDE.md`, `.gitignore`. `bd init` with embedded Dolt, prefix `animedex`, no git hooks, no Beads section in `AGENTS.md`. |
| Operating brief | Your prompt, verbatim, at `.control/policies/operating-brief.md` (DECLARED/HUMAN), so a fresh session recovers gates and rules without chat |
| `harness doctor` | OK: 8 of 8 required capabilities. Soft gap: no `mise.toml` yet, so the environment lists `python` as missing (M1 adds it). |
| Beads task graph | Epic `animedex-b1o`: M0 `.1` (in progress) → G0 `.2` → M1 `.3` → M2 `.5` (also needs G1 `.4`, deferred until M1 prepares it) → M3 `.6` → M4 `.7` → M5 `.8` → G4 `.9` |
| URCP suite on this Mac | 195 passed, 2 failed. Both failures are test assumptions (one expects graft to be absent; one expects the URCP repo's own `.beads/`), not runtime defects. First recorded macOS run. |

**Spec → URCP mapping**
| Spec | URCP |
|---|---|
| Milestones M0–M5 and their ACs (08) | Beads milestones with acceptance text; AC-level child tasks created at each milestone's plan step |
| Human gates G0–G4 | Beads issues assigned to Kingsley that block the next milestone; G2 and G3 live in milestone acceptance text |
| `make validate`, `make test`, clean rebuild | URCP validators in `control-plane.yaml` (M1, once the Makefile exists); `harness validate` writes proof receipts |
| "Milestone done" | `harness proof status` current at HEAD + completion report (12) + tag |
| 04 data contracts | URCP semantic contracts in `.control/contracts/` (M1), so a model or schema change invalidates proof |
| 10 §14 "stop and ask" | `AGENTS.md`: a spec conflict is a REQUIRES_DECISION |
| Session continuity | `harness bootstrap` / `checkpoint` / `handoff` + Beads, not chat memory |

**URCP gaps found** (URCP issues, flagged as a separate URCP task, not ANIMEDEX decisions):
- The `AGENTS.md`/`CLAUDE.md` generator hardcodes `planning/`. This repo's copies now point at `docs/implementation/`; re-running `harness setup claude` would revert them.
- `harness adopt` has no project-id option, so it used the folder name ("Ideation"). Set to `animedex` by hand.
- The two macOS test failures above.
- Beads cross-machine sync is still blocked (URCP ADR 0002). Single-machine work is unaffected; see D9.

## 9. Notes for G1
- **Gold mixed/flop picks (G1b):** v0 contains model-written analyses of two flops (Taboo Tattoo, Ex-Arm) and of Solo Leveling. Picking a title whose analysis you have already read weakens your blind annotation, so I'll propose picks outside v0 unless you say otherwise.
- **VERIFY budget:** 3 searches (+ 2 for the outcome) cover a mandatory set of outcome + 5 sensory fields + 3–5 locators + low-confidence fields. Expect a high `unresolved` share for sensory fields and locators. P-03 allows it; AC-13's correction-rate report will show it.
- **Toolchain:** Python 3.12 (uv-managed, shared with URCP; the spec requires 3.11+), uv 0.11.12, GNU Make 3.81, git 2.50. System `python3` is 3.9, too old. One new dependency to justify in the M1 report: PyYAML (settings, corpus, and CQs are YAML).

## 10. M1 plan (preview; starts on G0 approval)
| Files | ACs |
|---|---|
| `pyproject.toml`, `uv.lock`, `Makefile`, `.gitignore`, `.env.example`, `config/settings.yaml` | Tooling for AC-01–08; G1a |
| `mise.toml` (python 3.12, uv); URCP validators in `.control/control-plane.yaml`; 04 contracts in `.control/contracts/`; Beads child tasks per AC | URCP proof for every M1 AC |
| `src/animedex/models/` (every 04 record) → `make schemas` → `schemas/` | AC-01 |
| `ontology/vocab.json`, `bridge.json`, `competency_questions.yaml`, coverage table in `make validate` | AC-04 |
| `src/animedex/store/` (JSONL io, atomic write, quarantine, proposals) | AC-02, AC-03, AC-05 |
| `src/animedex/store/cache.py` + run log | AC-06 |
| `src/animedex/providers/`, `embeddings/`, `search/` (interfaces + mocks) | AC-08 |
| `src/animedex/cli.py` (every 05 command; later stages stubbed) | AC-08 |
| `src/animedex/build/` + `make build` / `make clean-build` | AC-07 |
| `tests/{unit,contract,pipeline,fixtures}` | AC-01–08 |
| G1 prep: config fill list, gold mixed/flop proposal with sources, blank `eval/gold/<title>/` templates | G1a–c |

Estimate: about half a day of agent work; the G1 items land partway through.

## 11. Decisions for G0
**Approve this gap report?** (G0 exit. I tag `m0-complete` on approval.)

**Answer now (M1 needs these):**
- **D1.** Raw run logs: replace fetched web text with URL + hash + length, and gitignore `data/raw/`? *Recommended: yes.*
- **D2.** Films: allow `scope.seasons: []` and `scope.numbering: null` when `format == film`? *Recommended: yes.*
- **D3.** Add `CANONICALIZE` to `provenance.pass` now and `PATTERNS` at M7? *Recommended: yes.*
- **D4.** Approve Appendix B's CQ changes (3 extensions + 1 new), or name the orphan fields to delete? *Recommended: approve.*

**Can wait (I'll ask again at that milestone):**
- **D5 (M5).** `status: elite` = archive occupant; your verdict lives only in `human_rating` and `eval/blind/`? *Recommended: yes.*
- **D6 (M5).** If 3 × 12 yields fewer than 20 elites, keep generating (same config) until 20 or the budget cap? *Recommended: yes.*
- **D7 (M3).** AC-17 evidence = LLM-matcher score + your spot-check in the M3 report? *Recommended: yes.*
- **D8 (any time).** Delete the 14 root-level spec copies + zip (byte-identical to `docs/implementation/`)? *Recommended: yes.*
- **D9 (any time).** Git remote: stay local-only, or give a private repo URL? With a remote, Beads tasks travel as a committed `issues.jsonl` export (URCP ADR 0002, option B). *Recommended: local-only for now.*

## Appendix A: v0 artifacts
| ID | Path | Size | Date |
|---|---|---|---|
| v0-A | `~/.codex/.chatgpt-projects/g-p-6ab73a43f23481919350fe48ad32eb85/sources/animedex_design.md` (copy: `~/Downloads/animedex_design.md`) | 38,225 B | 2026-09-25 |
| v0-B | `…/sources/anime-atom-graph-research-architecture.md` | 63,991 B | mirrored 2026-09-26 |
| v0-C | `…/sources/ANIME_GRAPH_SPEC.md` | 37,463 B | mirrored 2026-09-26 |

v0's worked examples for gold titles are not reproduced here, to keep the gold annotation blind (G2).

## Appendix B: drafted CQ changes (D4)
| Change | Text | Gives `cq_refs` to |
|---|---|---|
| Extend CQ-E03 | For an iconic fight, what are its power rules, choreography, visual and animation signature, and color and sound motifs? *(fight brief)* | `sensory.sound_motif` (and firms up `color_motif`, `animation_signature`, `power_combat.power_source`, `.signature_technique`) |
| Extend CQ-E04 | Which series engines (episodic vs. serialized, reset, episode template, cliffhanger cadence, season arc shape) pair with hits in each medium? | `series_engine.episode_template` |
| Extend CQ-I08 | Which comedic engines, comic roles, satire targets, and running-gag systems from Western/adult animation have never been paired with a power ladder? | `comedy_satire.satire_target`, `.comic_roles`, `.running_gag_system` |
| New CQ-I13 | Which transformation operators produce elites, and which mostly fail gates? | vocab field `transformation.operator` |

Implicit mappings I'll use unless you object: `power_combat.power_source` and `.signature_technique` → CQ-E03 ("power rules"); `format` → CQ-E04, CQ-I09; `explanation` → CQ-I02 (eligibility); `scope.numbering` → CQ-E06 (distances need one numbering); `core.logline_hook` → CQ-I04.
