# Using ANIMEDEX

ANIMEDEX keeps a short study note for every show you add, and turns a seed into idea cards checked against those notes and your steering rules. Everything it writes is private: it goes to your data repo, never the public one.

## 1. Study shows

1. Make a text file with one show per line. Put the year in parentheses when a show has more than one version, and `(manga)` to force the print original:

   ```text
   Hunter x Hunter (2011)
   Berserk (1997)
   Jagaaan (manga)
   ```

2. Run it (about 30 seconds per show, three shows per call; shows that already have a note are skipped):

   ```bash
   make ingest LIST=my_list.txt
   ```

Each show gets `notes/<show>.json`: premise, engine, power kit, MC edge, villain, setting, the three things it can't survive without (each with a reusable pattern), two sources, and the outcome from AniList's numbers (hit, mixed or flop). The lists you already have are in `corpus/queue/`.

## 2. Get idea cards from a seed

A seed is a fight image, a lane, or your own concept:

```bash
make quick SEED="a cold-open feral scaled transformation mid-fight"
```

- Add `SHOWS="Chainsaw Man, Jujutsu Kaisen"` to choose what it's measured against; otherwise it picks 3 to 5 shows itself.
- Add `N=6` to set the number of cards.
- At most 4 calls, under 10 minutes. The cards land in `build/quick/<time>_<seed>.md`, best first, each with its biggest weakness and its sources. Cards that fail the consequence test or your hard rule (R1) are listed as dropped.
- The same seed a second time skips the research call.

## 3. Start from a surprising observation

To start from an observation that surprised you, use `ANOMALY` instead of `SEED`:

```bash
make quick ANOMALY="I expected a stronger hero to remove tension, but each victory makes their allies trust them less"
```

Each resulting card states a possible explanation, then builds a story from it. The check drops cards whose explanation does not account for the observation. ANIMEDEX treats your observation as unverified; you decide whether it is accurate and worth exploring. The existing show comparison, steering rules, consequence test, and prior-art check still apply.

## 4. Check your own concept

```bash
make diagnose TEXT="your concept in a sentence or two"
```

Or put a longer concept in a file and use `FILE=path`. Two calls: it writes your concept as a note, then checks it against the nearest notes and `steering/rules.yaml`. Each failed check comes with a fix. The report is in `data/diagnose/`.

## 5. Look at the index

- `make analyze`: which story-engine lanes the notes cover, which power combinations no note holds (ranked by how surprising the gap is), and unadapted print titles. Report: `build/reports/analysis.md`.
- `make export`: spreadsheets in `build/exports/`: `notes.csv` (one row per show) and `cards.csv` (every quick card).

## 6. The blind packet

`make review` opens the rating page for the existing blind packet on this computer; `make review-report` shows the result once every card is rated.

## 7. Back up

```bash
make data-push
```

Rules: one run at a time; model calls use your Claude and ChatGPT subscriptions, and a plan limit pauses a run cleanly (run the same command again later).
