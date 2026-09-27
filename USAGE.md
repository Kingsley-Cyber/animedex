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

   Print titles (manga, manhwa, webtoons, light novels) work too: write `Jagaaan (manga)` to force the print version; without the hint, the show is picked when one exists and the print original only when none does.

3. Open `build/reports/backfill.md`. It shows which version it picked for each line. If a pick is wrong, add the year to that line and run again, or fix the title in `corpus/titles.yaml`.

- **Batches:** each run fully studies up to 4 titles at once (the v1.10 fast path: one profile call per title, the critic on 3 titles per call, 4 titles in parallel) and stays inside the 40-call cap: about 12–18 minutes per batch of 4 (3–4.5 minutes per title; 8.4 minutes of model time per title, down from 12.8). Gold titles take the slower full path. Measured times are in `docs/implementation/reports/SPEED_PASS.md`. Run the same command again for the next batch; it continues where it stopped.
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

## 3. Check your own idea

Have a concept of your own? ANIMEDEX can check it the same way it checks its own cards.

```bash
make diagnose TEXT="A courier borrows strangers' courage for one night, and they forget they were ever brave."
```

For a longer idea, put it in a text file and run `make diagnose FILE=my_idea.txt`.

You get one line per check: PASS or FAIL, and why. The checks ask:
- Is it a copy of an existing show?
- Is any part of it new?
- Did a show like it flop, and does your idea avoid that failure?
- Does it reuse names from existing shows?
- Do the hero's choices, relationships and outcomes really change?
- Does the dilemma follow from the cost, and does the cost still hurt five arcs in?
- Which parts carry the idea, and which are decoration?

Every FAIL comes with a fix. The fix names either one of the idea moves (for example "move the cost onto someone else") or the step to work on next (for example "world", or "engine and escalation"). The full report is in `data/diagnose/`. It stays on your computer and in your private backup, never in the public repo. A check takes 3 model calls.

## 4. Chat with the index

Ask Claude about the index in plain words ("which shows make the hero pay with memories?", "what does the index say about Hunter x Hunter's Nen?"). ANIMEDEX answers through an MCP server; it never calls a model itself.

1. In Claude Code, run this once:

   ```bash
   claude mcp add animedex -- uv run --directory /Users/king/Desktop/Ideation animedex mcp
   ```

   For Claude Desktop, add this under `mcpServers` in its config file instead:

   ```json
   "animedex": {"command": "uv", "args": ["run", "--directory", "/Users/king/Desktop/Ideation", "animedex", "mcp"]}
   ```

   For Hermes, or any client that takes one plain command, use the wrapper script:

   ```text
   /Users/king/Desktop/Ideation/bin/animedex-mcp
   ```

2. Ask away. "Add Levius (2019)" indexes a show in the background, "run ideas" starts an ideation run, "check this concept: …" tests your own idea, "status" tells you how far a job got, and "add a note to …" saves your own note on a show or an atom. One job runs at a time; notes and jobs stay in your private backup.

Idea cards stay hidden in chat until you've rated the whole blind packet, so the review stays blind.

## Long runs

- `make batch FILE=my_batch.yaml` runs a batch file (titles and their steps; Claude can write one for you) in the background, up to 3 titles at once. It keeps running if you close the chat or the terminal.
- `make status` shows how far it got, in plain words. For an older batch: `make status NAME=my_batch`.
- If it pauses on a plan limit, run the same `make batch FILE=...` later. It continues where it stopped; finished steps are kept.

## Optional

- **Blind review:** first run `make ideas ARM=baseline_loop`. This makes the first baseline: the same idea loop, but without the index. Then `make packet` writes a review packet to `eval/blind/`. It mixes ANIMEDEX cards with that baseline and with a second one, a single plain request. Both baselines get the same model, taste standard and rules, so you can rate everything blind.
- **Audit:** `make audit` picks 10 facts the index learned and shows the evidence behind each. Mark each one true, plausible or wrong in `eval/audit/`, then run `make audit-report` to see how often it is wrong over time.
- **Census:** `make census` counts which power-system ideas already exist across about 500 popular anime and donghua, so "never done" claims hold up.
- **Statistics:** `make stats` writes one page, `build/reports/stats.md`, with the numbers behind the checks (reliability, empty cells worth filling, how novel each card is, calibration, your ratings, the backtest).
- **Backtest:** `make backtest LIST=held_out.txt` checks whether the index helps predict how shows you haven't indexed were received; the result is in `build/reports/backtest.md`.
- **Gold titles:** their details stay hidden until you say "annotations done" or "annotations waived".

## Cost

Everything runs on your Claude and ChatGPT subscriptions. No API keys are used. Each run is capped at 40 model calls (60 for `make ideas`), with a pause between calls. The "cost" figures in the logs are the plans' own estimates, not bills.

## If something goes wrong

- **"Paused":** run the same command later.
- **"not logged in":** run `claude auth login` or `codex login`, and choose your subscription, not an API key.
- **Anything else:** tell Claude what the command printed.
