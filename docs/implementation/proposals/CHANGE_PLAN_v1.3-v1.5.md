# Change plan: v1.3 (outcome failure_level), v1.4 (request A: MCP + commentary), v1.5 (request B: Studio)

- **Status:** awaiting Kingsley's approval (gate). No doc or code changes for these requests have been made.
- **Received:** change request B (Studio) and the two items from the G1 note (outcome `failure_level`; restore two satire fields inside B).
- **Missing:** change request A (MCP + commentary). Its paste slot was empty, so every A-dependent point below is marked *pending A*.
- **Numbering:** v1.2 is taken by the G0 amendments. Proposed: **v1.3** = `failure_level` (small, lands first), **v1.4** = request A, **v1.5** = request B. The file you asked for as `v1.2-v1.3_CHANGE_PLAN.md` is this one.
- **Code blast radius:** from `harness impact` with codegraph at `d2b82b3`, all rated LOW risk.
  - Episode/Outcome models (`models/evidence.py`): 25 files.
  - `FieldValue` (`models/common.py`): 29 files.
  - VERIFY stage (`pipeline/verify.py`): 8 files.

## Landed separately: v1.2.1, G1a providers (owner decision, inside M2)
Kingsley ruled that the switch to subscription CLIs is a G1a decision and can land inside M2. It changes providers, config and budget wording, not data contracts. See CHANGELOG v1.2.1.
- **Interaction with this plan:**
  - v1.4 request A (MCP): the MCP server never calls a model, so it is unaffected.
  - v1.5 Studio: EPGEN/EPCHECK model slots use the same CLI providers and call caps.
  - EPCHECK should sit on `codex_cli` so the checker family differs from the generator family, as CHECK does now.
- Numbering is unchanged: v1.3, v1.4, v1.5 still follow v1.2.1.

## 1. Impact map

### v1.3 — outcome failure_level (premise | execution | external | unknown)
| Doc | Sections | Change |
|---|---|---|
| 01 | CQ-G02, CQ set | G02 asks whether the recorded failure was premise-level or execution-level; new CQ-I14: which execution-level failures offer a T5 "retold better" lane |
| 04 | Outcome record; vocab table | `failure_level` (required when label is mixed/flop; null for hits) + `failure_evidence` (≤25 words, sourced); new vocab field `outcome.failure_level` |
| 05 | VERIFY; ANALYZE; IDEATE gate 3; T5 evidence | VERIFY records the level with a cited source. The graveyard warns on **premise** failures only. **Execution** failures become T5 lane evidence. External/unknown: listed, no warning |
| 06 | Graveyard rows (ANALYZE, IDEATE) | Match premise-level failures only |
| 08 | AC-23 (M4, not started) | Reworded to the premise-only rule; new AC for sourced `failure_level` on every mixed/flop outcome |

### v1.4 — request A (MCP + commentary): *pending A*
Expected touchpoints once the text arrives:
- **02** interface: CLI + MCP.
- **03** MCP server; transient sources.
- **04** commentary records, if stored.
- **05** commands and MCP tools.
- **06** write scopes; read-only index.
- **10** execution rules.

### v1.5 — request B (Studio)
| Doc | Sections | Change |
|---|---|---|
| 00 | Mission, definition of done | Studio as the downstream consumer; a Studio milestone in the definition of done |
| 01 | Roles, inputs, outputs, promises, CQs | Kingsley as showrunner. Owner transcripts (transient) and dated web seeds as inputs. `studio/<show_id>/` outputs. New promises: the studio never writes the index; generation never edits a bible; topical items carry `as_of` + `shelf_life`; no invented real-person quotes. Studio CQs, including the satire CQ |
| 02 | In scope; non-goals | Studio (M8). Scoped exceptions for owner transcripts and generation passes (conflicts 2 and 4) |
| 03 | Flow, storage tiers, layout, providers, principles | Studio branch that reads the index; `studio/` tier (committed, owner-editable, versioned); `src/animedex/studio/`; studio prompts; EPCHECK on a different model family |
| 04 | Contracts, IDs, vocab table, lens, invariants | See the contracts table below |
| 05 | Commands, stages, config, prompt contracts | `animedex studio {create, promote, seed, extract-seeds, generate, check, approve, refresh}`; stages SEED, EPGEN, EPCHECK, CANON; `studio:` config (models, caps, transcript folder) |
| 06 | Controls, decision rights | Bible immutability, the collision step, the six EPCHECK gates, transcripts carry no names, staleness refresh. Canon and bible updates: Kingsley approves |
| 07 | M8 | Expanded to Studio. Needs M5 (idea cards, embeddings) and M6 (indexed episodes). Can run before M7 at your call |
| 08 | New M8 ACs | B's five ACs, the "same schema" AC restated (conflict 6) |
| 09 | Tests and eval | Four failing fixtures; studio gate statistics |
| 10 | Rules | `studio/` changes only via studio commands or Kingsley; transcripts never copied |
| 11 | Failure table | Stale topical episode, strawman, real-person leak, bible drift |
| 12 | Metrics | Studio episodes generated, approved, and gate-failed |

### Contracts in 04 added or changed
| Contract | Change | Version |
|---|---|---|
| Outcome | + `failure_level`, `failure_evidence` | v1.3 |
| Commentary record(s) | new? | v1.4, *pending A* |
| Episode | split into `EpisodeCore` (function, end_hook, engine_beat, decisions, info_shift, setups, payoffs) + `IndexedEpisode` (today's fields, unchanged) + `StudioEpisodeCard` (core + logline, A/B plots, beat outline, mode, seed_ids, inspirations, as_of, shelf_life) | v1.5 |
| FieldValue.source | + `owner` (authored facts in a bible) | v1.5 |
| ShowBible (+ CastMember, Continuity) | new; versioned; P1 lens profile, 1–3 engine atoms, cast, continuity, inspirations | v1.5 |
| Seed | new: `topical` / `transcript` / `index` | v1.5 |
| CanonEntry | new: approved setups, payoffs, state changes | v1.5 |
| Title lens | restore `comedy_satire.satire_target` and `running_gag_system` (not `comic_roles`) | v1.5 |
| TransientSource (runtime only, never stored) | generalizes today's `TransientText` | v1.4 + v1.5 shared |

## 2. Conflicts and proposed resolutions
1. **B says "update the docs now"; your planning note says plan first.** The planning note is later and more specific, so no docs change until approval.
2. **Transcripts vs 02 ("transcripts: not planned") and P-08.**
   - The system never copies a transcript. It reads your file transiently from one allowlisted folder outside the repo.
   - Seeds keep ≤25-word paraphrases, timestamps, and speaker **roles**.
   - Transcript text is redacted from logs exactly like web pages.
   - 02 gains a scoped exception; P-08 stays true for the repo.
3. **"Episode/beat generation: M8" (02) vs B's beat outlines.** Consistent: B *is* the expanded M8. No conflict beyond wording.
4. **"More than four analysis passes" (02 non-goal) vs SEED, EPGEN, EPCHECK.** Resolution: these are studio generation/check passes, not index analysis passes. The four-pass limit stays for the index; 02 says so.
5. **"Interface: CLI + Makefile only" (02) vs MCP.** Settled by request A (*pending A*).
6. **B's AC "episode cards validate against the indexed-episode schema" can't hold as written.** An indexed episode must carry `source: web`, a fetched URL, `selection_reason`, and P-11's rule that it never comes from recall. A generated card has none of these. Resolution:
   - Split the schema (above) and run analytics on `EpisodeCore`.
   - The AC becomes: "Episode cards validate against the shared episode-core schema".
7. **Bible hand edits vs 10 §5 ("never hand-edit canonical data").** No real conflict: `studio/` is not index canonical data. Bibles are owner-editable and versioned, and each generation pins a `bible_version`. 10 says this explicitly.
8. **`approve_canon` as an MCP tool vs 06 decision rights (Kingsley approves).**
   - If any agent could call it, an agent could approve its own canon.
   - Resolution: the tool files an approval *request*. Approval completes only with your explicit confirmation (CLI or client prompt), recorded as yours.
9. **`extract_seeds(transcript_path)` would read any path.** Restrict it to the allowlisted transcripts folder.
10. **Bible profile provenance.** `FieldValue.source` has no value for authored facts. Add `owner` (verification `not_required`), so clone checks and gap queries run on your shows unchanged.
11. **Restoring the satire fields (index lens) after M2's P1 runs.**
    - Profiles made before v1.5 lack those fields. A migration adds them as null / conf 0 with a reason, then P1 re-runs only on titles with `comedy_satire` active.
    - Of today's 12 titles, likely none or one.
12. **`failure_level` vs the new "never lands mid-milestone" rule.**
    - VERIFY writes outcomes in M2, but v1.3 can only land after M2 closes.
    - Resolution: at the M2→M3 boundary, add an outcome-only VERIFY mode and re-verify the 12 outcomes (about $0.50).
13. **`failure_level` is a judgment.** VERIFY can be wrong about premise vs execution. Resolution: require a sourced `failure_evidence`, allow `unknown`, and let your override win (decision 5).

## 3. Consolidation (build once, share)
1. **One transient-source contract.**
   - `TransientSource {kind: web | transcript | commentary, locator (URL or allowlisted path), sha256, chars, as_of}`.
   - Used by VERIFY, EP, topical and transcript seeds, studio refresh, and request A's commentary.
   - One redaction rule in run logs, one "never stored" test, one ≤25-word paraphrase rule, speakers as roles.
2. **One MCP server, two namespaces.**
   - `index`: read-only. Titles, atoms, transfers, episodes, CQ answers, gaps, ideas.
   - `studio`: write tools scoped to `studio/`, approvals gated per conflict 8.
   - The read-only rule is enforced in the server, not by convention (*details pending A*).
3. **One episode core** shared by indexed episodes and studio cards, so the M6 episode analytics run on your shows unchanged.
4. **One critic stack.**
   - EPCHECK reuses the CHECK machinery: different model family, `strict_model`, the reasons vocabulary.
   - Episode-level H1 reuses the idea judge's consequence test shape.
5. **One web layer.** The Brave adapter, dated queries, and the per-unit search budget serve VERIFY, EP, topical seeds, and `studio refresh`.
6. **One name guard.** The P4 name-leak lists power the transcript "no names" check and the real-person guard.
7. **One approval queue pattern.**
   - Today, ontology proposals are files awaiting your decision.
   - The same pattern carries bible continuity updates from approved canon.
8. **One profile schema.** Bibles use the P1 lens, so clone Jaccard and gap queries work on your shows.

## 4. Versioning and migrations
Today: `schema_version` 1.2.0, `vocab_version` 1.2.1, CQ set 1.2.0.

| Version | Schema | Vocab | CQs | Prompts | Migration |
|---|---|---|---|---|---|
| v1.3 | 1.3.0 | 1.3.0 (+ `outcome.failure_level`) | G02 reworded; + CQ-I14 | `verify_web.md` 1.1.0 | Outcome-only re-verify of every canonical outcome; no data is rewritten by hand |
| v1.4 | *pending A* | *pending A* | *pending A* | *pending A* | *pending A* |
| v1.5 | 1.5.0 | 1.5.0 (seed kind, shelf_life, studio mode, transcript seed type, canon status; lens + 2 satire fields) | + studio CQs (incl. satire) | `p1_modules/comedy_satire.md` 1.1.0; new seed, epgen, epcheck, refresh prompts at 1.0.0 | `ontology/migrations/1.5.0_restore_satire_fields` + targeted P1 re-run. The Episode split is backward compatible (`IndexedEpisode` = today's Episode) |

## 5. Placement
| Piece | Lands | Depends on | ACs |
|---|---|---|---|
| v1.3 docs + models + vocab + VERIFY outcome mode | M2→M3 boundary (after `m2-complete`) | M2 outcomes | new AC for sourced `failure_level` (M3); AC-23 reworded (M4) |
| v1.4 (A) | *pending A* | — | numbered when applied |
| v1.5 docs + models + vocab + lens + CQs | M2→M3 boundary, in the same batch of boundary commits | — | keeps AC-01 and AC-04 true (models for every 04 contract; every field has a CQ) |
| v1.5 stages (SEED, EPGEN, EPCHECK, CANON, refresh, studio MCP namespace) | M8 (expanded) | M5 (idea cards → `promote_idea`, embeddings), M6 (indexed episodes for episode-level H1 and index seeds), M4 (imported lanes), A (MCP server) | B-1…B-5, numbered when applied |

- **Completed milestones are unaffected.**
  - M0 has no ACs.
  - M1's AC-01…AC-08 stay true, because models, vocab, and CQs land together with each doc change and are re-verified at that boundary (AC-08's rule).
- **AC numbering:** new ACs append after AC-42 in landing order. No existing AC is renumbered. Only AC-23 (M4, not started) changes wording.
- **M8 before M7:** allowed at your call; B only needs M6's episode patterns.

## 6. Risks and pushback
1. **Studio before the index proves itself.**
   - 00 says to scale only after beating the baseline.
   - Pushback: start M8 only after blind review #1 (M5) is recorded, even if M8 comes before M7. It can't start before M6 anyway.
2. **Agent-approved canon.** An agent-callable `approve_canon` would bypass your gate (conflict 8). Pushback held.
3. **Real people and topical issues.**
   - The name guard is a heuristic and will miss some.
   - Every episode stays unpublished until your canon approval.
   - Positions are carried by fictional analogs.
   - Quotes attributed to real people are refused outright.
4. **Staleness.** Topical episodes rot. `shelf_life` + `studio refresh` flag it, but a refresh costs a web search.
5. **Cost.** The per-episode cap is $0.25. EPGEN on Opus 5.5 at high effort with a full bible is roughly $0.15, plus EPCHECK. Propose a separate studio per-episode cap (for example $1) at M8.
6. **Bible drift.** Canon approvals plus manual edits change the bible. Every card records the `bible_version` it was generated from; the cache key includes it.
7. **MCP write surface.** Studio writes stay path-scoped with no arbitrary reads. The index namespace can't write, enforced in code with a test.

## 7. Decisions needed (one line each)
1. Paste change request A (MCP + commentary). The plan covers it only after that.
2. Numbering: v1.3 = `failure_level`, v1.4 = A, v1.5 = B?
3. `failure_level` timing: M2→M3 boundary plus an outcome-only re-verify (about $0.50)? *Recommended.*
4. Hits carry `failure_level: null`, mixed/flop require it?
5. May your call override VERIFY's `failure_level` via a `failure_level_override` in `corpus/titles.yaml` (a small corpus contract addition)?
6. Split the episode schema (core / indexed / studio) and restate B's "same schema" AC as "validates against the shared episode core"?
7. `approve_canon` only files a request; approval needs your explicit confirmation?
8. Transcripts are read only from one allowlisted folder outside the repo (name it, e.g. `~/AnimedexTranscripts/`), never copied?
9. `FieldValue.source` gains `owner` for bible facts?
10. Each change's models, vocab, and CQs land with its docs at the M2→M3 boundary; studio stages at M8, which starts only after blind review #1 is recorded?
