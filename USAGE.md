# Using ANIMEDEX

ANIMEDEX suggests anime or other series ideas from sourced mechanisms, causal hypotheses, scene tests, and prior-art comparisons. Your brief is optional. Source material, preferences, drafts, and verdicts are private data; `make data-push` backs them up to your private data repo.

## Suggest and test ideas

```bash
make ideate BRIEF="dream hopping, sleep traversal, and time distortion" MEDIUM=anime
```

Use `MEDIUM=television` or `MEDIUM=sitcom` for other formats, or run `make ideate` for open suggestions.
`N` uses the configured card count unless you set it. Source mechanisms live in `notes/_materials/`;
ideas and their full test records land in `build/quick/_ideation/`. The generator sees source
mechanisms and your private `steering/ideation.json` preferences. The critic sees the show index.
A suggestion must survive the scene tests and have a sourced prior-art comparison; uncertainty
and rejected candidates stay visible in the report. Those are model judgments, so you decide what to keep.
The source count is a collection target. Only mechanisms tied to opened pages enter the store;
unsupported rows are logged as rejected. Multiple hypotheses can transform the same mechanism.

To test whether the hypothesis method improves your ideas:

```bash
make ideate BRIEF="your brief" MEDIUM=anime COMPARE=1
make review
make ideate-results IDEATION="build/quick/_ideation/<run>.json"
```

Both arms use Terra, the same brief, taste, draft format, and checks. One receives sourced
mechanisms and hypothesis traces; the other drafts directly. Every draft appears in the blind
packet before filtering. Rate and keep/drop every card before reading the detailed run JSON.
Results reveal the arms only after all cards have verdicts. Use `ideate-results` for these
packets; `review-report` reports the older ideation experiment.
If prior-art checking pauses or fails after drafts and scene tests finish, retry that stage with
`python3 scripts/animedex_agent.py ideate --resume "build/quick/_ideation/<run>.json"`.
The saved drafts and tests are kept; this option does not restart generation.
After a scene-test prompt correction, `ideate --recheck "build/quick/_ideation/<run>.json"`
rechecks the same completed drafts and retains the earlier verdicts. The blind packet's cards
and identities are preserved.

## Inspect a live discourse gap

1. `make scan` fetches current discourse. It prints a private scan path and gap IDs, each with a model-extracted publication date and fetched source URL. Inspect the page before treating a gap as a broader pattern.
2. `make abduct SCAN="notes/_scans/<scan>.json" GAP=G1` samples relevant indexed premises, asks independent abductive, deductive, and inductive questions, compares candidate frames, and revises rejected ones once using the gate's reasons. It prints a private frames path and marks each frame ready or rejected. The private record includes the premise chain and a reasoning state graph. The gate needs at least three indexed shows for its contrasts.
3. Pick a ready frame and run `make quick FRAMES="build/quick/_frames/<frames>.json" FRAME=F1`. In this path, only a passing frame can reach card generation and scoring. Read the cards, then decide which frame is worth developing.

The command output provides the actual paths and IDs to use. `make scan` uses live web search through Codex with GPT-5.6 Terra; the later commands use their existing model slots. A scan that cannot cite an opened, dated page stops rather than inventing a gap. The research methods are software adaptations: the controller uses gate feedback rather than a trained critic, the reasoning lenses do not calculate calibrated Bayesian confidence, and frame comparison does not run on quantum hardware.

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
- `make export`: spreadsheets in `build/exports/`: `notes.csv`, `cards.csv`, and `ideation_nodes.csv` / `ideation_edges.csv`. Mechanisms have domain, shape, force, cost, and source fields. `make lookup ID="<node ID>"` traces an idea to its hypotheses and sources. The CSVs are rebuilt views; the private JSON records own the data.

## 6. The blind packet

`make review` opens the rating page for the existing blind packet on this computer; `make review-report` shows the result once every card is rated.

## 7. Back up

```bash
make data-push
```

Rules: one run at a time; model calls use your Claude and ChatGPT subscriptions, and a plan limit pauses a run cleanly (run the same command again later).
