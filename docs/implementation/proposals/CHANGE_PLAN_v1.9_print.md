# Change plan v1.9: print media (manga, manhwa, webtoon, light novel)

**Owner instruction (2026-09-27):** "Add manga, manhwa, webtoon, and light_novel as mediums. Gather from AniList's manga data plus Wikipedia and wikis, the same way as anime. Scope by chapters or volumes. Animation-only modules stay off for print titles. Outcome gains an adaptation signal (adapted / announced / none). Add one CQ: which popular print titles in each lane have no screen adaptation. Index Jagaaan and Choujin X as the first two, then queue the rest of my list." This overrides "no new fields after v1.8" for exactly these fields (D-046).

**Status:** in progress on branch `v1.9/print`. Vocab 1.6.0, schema 1.5.0 (additive: older records keep their form).

## What changes
| Area | Change |
|---|---|
| Vocab `medium` | `+ manga, manhwa, webtoon, light_novel` ("print media"). Country KR → manhwa, JP → manga, format NOVEL → light_novel; a KR or JP entry whose catalog links name a webtoon platform → webtoon. |
| Scope | Print titles scope by `numbering: chapters` or `volumes` (new `scope.numbering` values) with an optional `range: [first, last]` (null = everything published so far, dated in `version`); `seasons` stays `[]`. Screen rules unchanged. |
| Locators | `MomentLocator` and `TurningPointLocator` gain `chapter` and `volume`. A print title's moment or turning point needs a chapter or a volume; screen titles keep season + episode. |
| Modules | Animation-only modules stay off for print: `anime_production` (already anime-only) and `sensory` (rule gains `medium not in print`). `series_engine` stays on for serialized print (its cadence fields read as chapter cadence). No new module. |
| Outcome | `adaptation: {status: adapted | announced | none, screen_title, catalog_ref, source_ref}` for print titles, null for screen titles. Computed in GATHER from the catalog's relations (an ADAPTATION relation to an ANIME entry that has aired → adapted; not yet released → announced; none → none), never from recall. |
| Catalog | AniList search and lookups by media type; `chapters`/`volumes` in the query; relation nodes carry `status`. `resolve` searches anime first, then print when nothing screen matches; a hint in parentheses (`manga`, `manhwa`, `webtoon`, `light novel`) forces print; `(YYYY)` still picks a year. |
| Reception | AniList manga numbers and MAL manga numbers (MAL API `/manga/{id}`, Jikan `/manga/{id}`), same label rule; page URLs on the manga side. |
| GATHER / INTERPRET / VERIFY | Prompts speak of "title" not "screen title", with a print paragraph (chapters and volumes, serialization, no episodes). GATHER's field list drops inactive modules' fields for the entry. Fact and character locators carry chapter/volume for print. |
| Partners (P3) | For anime titles, `cross_medium` still means Western or live action (print excluded). For print titles, `nearest_neighbor` is the same medium and `cross_medium` is any screen medium. A print title and its own screen adaptation pair as nearest neighbours when both are in the corpus. |
| Census | `animedex census --print-top N` counts the most popular print titles (AniList manga + novels, JP and KR) with their adaptation status from the catalog (deterministic). `CensusEntry` gains `adaptation`. |
| CQ | `CQ-P01`: which popular print titles in each story-engine lane have no screen adaptation (census rows: print medium, adaptation none, grouped by story_engine, ranked by popularity). Registered in `analyze/cq.py`; the census table gains `adaptation`. |
| Name-leak | Medium words gain `chapter(s)`, `volume(s)`, `light novel`, `novel`. |

## Not changed
No new lens fields, modules, operators or ideation changes. Ideation treats print titles like any title: their atoms and patterns enter the pool through the same P2–P4 stages.

## Acceptance (added to 08)
- AC-58: a print corpus entry validates only with `numbering` chapters or volumes and `seasons: []`; its profile activates no animation-only module (test).
- AC-59: a print title's moments and turning points carry a chapter or volume; a screen title's still carry season and episode (test).
- AC-60: `resolve("Jagaaan")` yields a manga entry with a chapter/volume scope; `resolve("Berserk (1997)")` still yields the anime (test with a fake catalog).
- AC-61: a print outcome carries `adaptation` from the catalog; CQ-P01 answers from the census and a clean rebuild reproduces it (test).

## Order
1. Vocab, models, activation, medium words, schemas (offline, tests).
2. Catalog: search by type, print entries, adaptation status, reception on the manga side (fake-catalog tests).
3. GATHER / INTERPRET / VERIFY prompts and locators; partners (tests).
4. Census `--print-top`, `CensusEntry.adaptation`, CQ-P01, DuckDB column (tests, determinism).
5. Docs 00, 01, 02, 04, 05, 08, 09; CHANGELOG; DECISIONS.
6. Live: Jagaaan and Choujin X (gather-first, then P2–P4); the print census; then the rest of the owner's list.
