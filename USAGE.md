# Using ANIMEDEX

ANIMEDEX turns a list of shows into cards for new anime ideas. You add titles, then ask for ideas.

## 1. Add titles

1. Make a text file with one show per line. When a show has more than one version, put the year in parentheses:

   ```text
   Hunter x Hunter (2011)
   Berserk (1997)
   Frieren: Beyond Journey's End
   ```

2. Run:

   ```bash
   make backfill LIST=my_list.txt
   ```

3. Open `build/reports/backfill.md`. It shows which version it picked for each line. If a pick is wrong, add the year to that line and run again, or fix the title in `corpus/titles.yaml`.

- **Batches:** each run fully studies up to 8 titles. That takes about an hour and stays inside your plan limits. Run the same command again for the next batch.
- **Pauses:** if a run says "Paused", a plan limit or the call cap was reached. Run the same command later. Finished work is kept.
- **Mix:** add a few flops and some non-anime shows. The report suggests some when your list is all hits or all anime.

## 2. Get ideas

```bash
make ideas
```

Cards appear in `build/reports/ideas.md`, best first. Each card shows:
- the premise;
- its engine: what the hero wants, what stands in the way, and what it costs;
- what is new, and how it plays differently from the closest existing show;
- a pre-mortem: how it could fail, and the fix;
- which taste criteria (T1–T5) it meets, with evidence.

Run `make ideas` again to keep improving. Each run adds a generation and keeps the best card in each slot of the idea grid.

## Long runs

- `make batch FILE=my_batch.yaml` runs a batch file (titles and their steps; Claude can write one for you) in the background, up to 3 titles at once. It keeps running if you close the chat or the terminal.
- `make status` shows how far it got, in plain words. For an older batch: `make status NAME=my_batch`.
- If it pauses on a plan limit, run the same `make batch FILE=...` later. It continues where it stopped; finished steps are kept.

## Optional

- **Blind review:** `make packet` writes a review packet to `eval/blind/`. It mixes ANIMEDEX cards with two baselines so you can rate them blind.
- **Census:** `make census` counts which power-system ideas already exist across about 500 popular anime and donghua, so "never done" claims hold up.
- **Gold titles:** their details stay hidden until you say "annotations done" or "annotations waived".

## Cost

Everything runs on your Claude and ChatGPT subscriptions. No API keys are used. Each run is capped at 40 model calls, with a pause between calls. The "cost" figures in the logs are the plans' own estimates, not bills.

## If something goes wrong

- **"Paused":** run the same command later.
- **"not logged in":** run `claude auth login` or `codex login`, and choose your subscription, not an API key.
- **Anything else:** tell Claude what the command printed.
