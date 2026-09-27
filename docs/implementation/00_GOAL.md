# 00 — Goal

## Mission
Build **ANIMEDEX**: an ideation engine that breaks screen stories (anime first, plus donghua, Western animation, adult animation, live-action series, and film) and, since v1.9, print stories (manga, manhwa, webtoons, light novels) into evidence-backed atoms of two kinds: **effect atoms** (why a story feels good) and **engine atoms** (why a story keeps going). It finds lanes nobody has built in and generates anime concepts that pass an explicit taste standard. **Episodes act as compounding evidence tied to their show**: every indexed episode strengthens, challenges, or extends what the index believes about that show.

## Why this exists
Asking an LLM for an idea cold returns the nearest strong pattern: a popular show with one change. ANIMEDEX replaces "generate an idea" with "search a map of what works and why, then build where the map is empty."

## The taste standard
A generated concept is elite only if it meets at least one criterion:

| ID | Criterion |
|---|---|
| T1 | Never done before |
| T2 | Done before, but never this exact way |
| T3 | Two ideas nobody knew worked together |
| T4 | "This should have existed years ago" |
| T5 | A known story retold clearly better |

**Hard fail H1:** a popular title with one surface-level change. **Operational test:** if an idea's transformation does not change characters' choices, relationships, or outcomes compared with its closest existing title, it is a surface change.

**Reference bar:** Solo Leveling. It borrowed a system everyone already knew (game leveling), broke one rule (only he can see it), served an unserved appetite (pure solo ascent), and made progress visible.

## Core bets
1. **Depth over breadth.** Four analysis passes over a small lens of fields. A field is added only when idea cards fail in a way that field would fix.
2. **Mechanisms over descriptions.** Effect atoms: `element → feeling → because`. Engine atoms: `goal → constraint → strategy → benefit + cost → dilemma`.
3. **Load-bearing only.** Ablation separates atoms a title can't survive without from decoration. Ideation recombines load-bearing atoms only.
4. **Search before generation.** The index constrains the idea space; the LLM assembles inside it.
5. **Zero is not novel.** An empty cell counts as open only when coverage is adequate and failure data has been checked. Coverage may come from the census: a wide, counts-only scan of about 500 catalog titles (v1.6). "Never done" claims also need a prior-art web check.
6. **Consequences prove novelty.** An idea is only as new as what its change does downstream.
7. **Episodes compound.** Key episodes are evidence for their show's atoms. The index grows more trustworthy with every episode, and spends tokens only when an atom's status actually changes.

## Definition of done
- **V1 (M5):** 5 gold titles run end to end; `rm -rf build/ && make build` reproduces identical answers; in blind review, Kingsley rates ANIMEDEX idea cards above a plain-prompt baseline (same model, no index).
- **V1.1 (M6):** key episodes for the gold titles compound into the show atoms, and a second blind review shows lift over V1 (or a documented reason why not).
- **Then scale** (M7) and repeat the blind review.

## North-star metric
Share of idea cards Kingsley marks **"would greenlight"** in blind review, versus the baseline.

## Out of frame for now
Roblox and ad ideation are future target domains. V1 must not block them (P4 produces domain-neutral atoms; idea cards carry `target_domain`), but V1 does not build them. See 02.
