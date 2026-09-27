# The heavy pipeline (gold titles only)

The 2026-09-27 audit removed the heavy pipeline from `main`: GATHER, INTERPRET, VERIFY, PROFILE, P2 atoms, P3 proofs, the CHECK critic, P4 patterns, IDEATE (MAP-Elites archive and grid), census, backtest, the MCP server, the canonical JSONL store and its DuckDB build, and their prompts, tests and docs. All of it is intact at the git tag **`heavy-final`** (commit `c6ff602`), and its data is untouched: `data/canonical/`, `data/candidates/`, `eval/` and the data repo (tag `heavy-final` there too).

## Running it for a gold title

The heavy code reads its data from its own checkout, so run it in a separate worktree that shares this checkout's data:

```bash
git worktree add ../animedex-heavy heavy-final
```

```bash
cd ../animedex-heavy && for d in data/candidates data/raw data/cache data/quarantine data/blind data/diagnose; do mkdir -p "$(dirname $d)" && ln -sfn "$PWD/../Ideation/$d" "$d"; done
```

```bash
cd ../animedex-heavy && mv data/canonical data/.canonical_tracked && ln -s "$PWD/../Ideation/data/canonical" data/canonical && uv sync
```

Then any heavy command works there, for example `make run` style commands from its `USAGE.md` (`uv run animedex run --title btooom_2012`), `make ideas`, `make backtest`. The five gold titles are tagged `gold` in `corpus/titles.yaml`.

Rules from that era still apply there: one live job at a time; never edit `data/canonical/` by hand.
