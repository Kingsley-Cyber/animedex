# G1b proposal: gold mixed/flop picks and all five scopes

- **Status:** proposal awaiting Kingsley's approval (G1b). Nothing here is in `corpus/titles.yaml` yet.
- **Evidence:** fetched 2026-09-26 (MyAnimeList pages, AniList API, review pages). Every number links to its source. Scores drift, so they get re-fetched when the set is frozen.
- **Blind rule:** reception numbers, production facts, and episode counts only. Nothing here describes story, powers, or themes.

## 1. Label rule (new thresholds, your call)
Applied per TV season in scope. MyAnimeList (MAL) and AniList must agree.

| Label | MAL score | AniList mean |
|---|---|---|
| hit | ≥ 8.00 | ≥ 78 |
| mixed | 6.80–7.60 | 65–76 |
| flop | ≤ 6.40 | ≤ 62 |

Anything else is unlabeled. A title is gold-eligible only with **≥ 100k MAL scorers** and **≥ 1 reputable critic source** pointing the same way; otherwise it is "disputed".

The three fixed hits all land in *hit*:

| Title | MAL · scorers | AniList | Critic |
|---|---|---|---|
| Fullmetal Alchemist: Brotherhood | [9.11 · 2.34M](https://myanimelist.net/anime/5114) | [90](https://anilist.co/anime/5114) | [ANN A−](https://www.animenewsnetwork.com/review/fullmetal-alchemist/brotherhood/dvd-part-5) |
| Hunter x Hunter (2011) | [9.03 · 2.01M](https://myanimelist.net/anime/11061) | [89](https://anilist.co/anime/11061) | [ANN B+](https://www.animenewsnetwork.com/review/hunter-hunter-steelbook/blu-ray-1/.109886) |
| Solo Leveling S1 | [8.13 · 743k](https://myanimelist.net/anime/52299) | [80](https://anilist.co/anime/151807) | [Rotten Tomatoes 100% (9 critics)](https://www.rottentomatoes.com/tv/solo_leveling/s01) |
| Solo Leveling S2 | [8.50 · 534k](https://myanimelist.net/anime/58567) | [84](https://anilist.co/anime/176496) | not fetched |

## 2. Recommended picks
| Role | Pick | Backup |
|---|---|---|
| **mixed** | **Sword Art Online (2012)** | Guilty Crown (2011) |
| **flop** | **Big Order (2016)** | Platinum End (2021) |

- **Sword Art Online:** largest sample in the pool; both sites mid-band; two graded ANN reviews, both middling. One 25-episode season. Same studio as Solo Leveling (a production confound to note, not a blocker).
- **Big Order:** the only flop candidate where every signal agrees: low scores on both sites, an F grade for the finale, and two ANN critics' worst of 2016. Tagged Action and Super Power on both sites. 10 episodes.
- **Guilty Crown (backup):** original anime, so there is no reception carry-over from source fans. MAL genres omit Action; AniList includes it.
- **Platinum End (backup):** a failure verdict from ANN, but neither site tags it Action, and the director changed mid-run. If you rule it ineligible, the next option is Hand Shakers (only 44k MAL scorers).

| Candidate | MAL · scorers | AniList | Critic source (paraphrase) | Confounders |
|---|---|---|---|---|
| Sword Art Online (2012) | [7.23 · 2.30M](https://myanimelist.net/anime/11757) | [70](https://anilist.co/anime/11757) | ANN [Blu-ray 1](https://www.animenewsnetwork.com/review/sword-art-online/blu-ray-1) B; [Blu-ray 3–4](https://www.animenewsnetwork.com/review/sword-art-online/blu-ray-3) C+ | A-1 Pictures; light-novel source; large franchise |
| Guilty Crown (2011) | [7.39 · 667k](https://myanimelist.net/anime/10793) | [69](https://anilist.co/anime/10793) | [ANN](https://www.animenewsnetwork.com/review/guilty-crown/bd-dvd-complete-collection/.105926) C+ (animation B+, music A−) | Original anime (Production I.G) |
| Big Order (2016) | [5.35 · 115k](https://myanimelist.net/anime/31904) | [48](https://anilist.co/anime/21445) | ANN [finale](https://www.animenewsnetwork.com/review/big-order/episode-10/.103357) F; [worst of 2016](https://www.animenewsnetwork.com/feature/2016-12-29/the-worst-anime-of-2016/.110468), two critics' #1 | asread; low-rated source manga; anime ended before the manga did |
| Platinum End (2021) | [6.01 · 151k](https://myanimelist.net/anime/44961) | [58](https://anilist.co/anime/127401) | [ANN](https://www.animenewsnetwork.com/this-week-in-anime/2022-04-07/.184417): failure relative to its creators' pedigree | Signal.MD; director changed between halves |

**Also considered:**
- *Flop:* One Punch Man S3, Hand Shakers, Gibiate, Berserk (2016), Tokyo Ghoul:re, and Seven Deadly Sins (2019). Each is too few scorers, disputed, unlabeled, or a sequel season.
- *Mixed:* Akame ga Kill!, The God of High School, Tower of God, Deadman Wonderland, and Fire Force. Each is disputed or unlabeled.
- *Record of Ragnarok:* screened out because it is an ONA, not TV.

## 3. Scopes (numbering = broadcast for all five)
| title_id | Version | Seasons (episodes) | Numbering notes | Exclude |
|---|---|---|---|---|
| `solo_leveling_2024` | A-1 Pictures TV anime, 2024–25 | [1, 2]: S1 = 12, S2 = 13 ([list](https://en.wikipedia.org/wiki/List_of_Solo_Leveling_episodes)) | Broadcast numbers S2 as 13–25 (MAL/AniList use 1–13); recap ep 7.5 excluded | ReAwakening compilation film; the announced *Beyond the System* film ([ANN](https://www.animenewsnetwork.com/news/2026-07-03/solo-leveling-series-gets-solo-leveling-beyond-the-system-anime-film/.239268)); source material past S2 |
| `fullmetal_alchemist_brotherhood_2009` | Bones TV series, 2009–10, adapts the whole manga | [1]: 64 ([list](https://en.wikipedia.org/wiki/List_of_Fullmetal_Alchemist:_Brotherhood_episodes)) | Episodes 1–64; home-video OVAs ignored | Fullmetal Alchemist (2003); Brotherhood OVAs; *Sacred Star of Milos*; 4-Koma Theater |
| `hunter_x_hunter_2011` | Madhouse TV series, 2011–14 | [1]: 148 ([list](https://en.wikipedia.org/wiki/List_of_Hunter_%C3%97_Hunter_(2011_TV_series)_episodes)) | Episodes 1–148 keyed on broadcast number | 1999 series; 2002–2004 OVAs; 2013 films; manga past the anime |
| `sword_art_online_2012` | A-1 Pictures TV series, 2012 | [1]: 25 ([list](https://en.wikipedia.org/wiki/Sword_Art_Online_season_1)) | Episodes 1–25; bonus shorts excluded | Extra Edition; Sword Art Offline; SAO II onward; films; manga versions; light novels vol 5+ |
| `big_order_2016` | asread TV series, 2016 | [1]: 10 ([MAL](https://myanimelist.net/anime/31904)) | Episodes 1–10 | 2015 OVA; manga past the anime |

Solo Leveling: only S1 and S2 have aired as of 2026-09-26. Both clear the hit band on their own, so both are included. S1 alone is the fallback if annotation time is short.

## 4. Not verified
- The source chapter each season ends on (Solo Leveling S1/S2, Hunter x Hunter, Big Order).
- Streaming-platform season splits (everything is keyed on broadcast numbers instead).
- A critic source for Solo Leveling S2.
- Season-level graded reviews for Tokyo Ghoul:re, God of High School, and Tower of God.
- Possible extra exclusions: the FMA 2003 film, the live-action FMA films, the SAO *Ordinal Scale* film.
- The Jikan API failed (504 and stale cache), so MAL values come from the live MAL pages.

## Addendum (2026-09-27): flop swap under the owner's autopilot ruling
- Kingsley has not watched Big Order and asked for the flop to be picked from verified reception data.
- Gold flop is now **Platinum End (2021)**, the backup already verified in this proposal:
  - MAL 6.01 from 151k scorers; AniList 58.
  - ANN judged it a failure relative to its creators' pedigree.
- AniList metadata confirms the scope: TV, 24 episodes, 2021-10-08 to 2022-03-25, Signal.MD, manga source.
- Its nearest neighbor is Future Diary: both are god-candidate battle royales.
- The caveats from section 2 stand: neither site tags it Action, and the director changed mid-run.
- Big Order stays in the corpus as a **non-gold flop**. Its verified reception adds graveyard and revival evidence.
- The annotation template moved with `git mv` (`big_order_2016` → `platinum_end_2021`). Nothing was deleted.

## Addendum (2026-09-27, later): Btooom! takes the mixed slot
- Kingsley has watched Btooom! and asked for it to fill the slot its reception qualifies for.
- Verified reception: [AniList mean 68](https://anilist.co/anime/14345), [ANN B- overall](https://www.animenewsnetwork.com/review/btooom/episodes-1) (episodes 1–7, Theron Martin, 2012-12-19). All three sit in the **mixed** band, and scorers exceed 100k.
- Scope from AniList metadata: Madhouse TV, 12 episodes, 2012-10 to 2012-12, manga source.
- Sword Art Online stays in the corpus as a non-gold mixed title. The two are a natural contrast pair: both are trapped-inside-a-game survival stories with mixed reception.
- The annotation template moved with `git mv` (`sword_art_online_2012` → `btooom_2012`). Nothing was deleted.
- Gold set now: Solo Leveling, Fullmetal Alchemist: Brotherhood, Hunter x Hunter (2011) (hits); Btooom! (mixed); Platinum End (flop).

