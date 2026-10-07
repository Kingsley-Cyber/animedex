# ANIMEDEX

An anime ideation workflow that starts with candidate gaps in live discourse. `scan` fetches current discussion. The main `abduct` command retrieves indexed premises, runs three reasoning lenses, compares and revises candidate frames, then gates out parent-dependent fusions before a human selects a frame to build. Study notes and Kingsley's steering rules check the resulting idea cards; they are comparison evidence, not the source of the premise.

- **How to use it:** `USAGE.md`.
- **For Claude, Codex, or another IDE agent:** `AGENTS.md` and `python3 scripts/animedex_agent.py tools` provide the same repo-owned workflow and tool commands.
- **What changed and why:** `docs/AUDIT.md` and `docs/implementation/DECISIONS.md`.
- **The old heavy pipeline** (gather, interpret, verify, atoms, proofs, critic, patterns): tag `heavy-final`; `legacy/README.md` says how to run it for the gold titles.

## Commands
| Command | What it does |
|---|---|
| `make ingest LIST=<file>` | Study shows: one Sonnet call with web per three shows writes `notes/<slug>.json` |
| `make scan` | Fetch live anime discourse and save cited candidate gaps in `notes/_scans/` |
| `make abduct SCAN=<file> GAP=G1` | Retrieve note premises, reason from three lenses, compare and revise frames, then gate out fusions before scoring |
| `make quick FRAMES=<file> FRAME=F1` | Build cards from a selected frame that passed the gate |
| `make quick SEED="..." [SHOWS="a, b"] [N=6]` | Idea cards: research (only when needed), generate, check, prior art; at most 4 calls |
| `make diagnose TEXT="..."` | Check your own concept against the notes and `steering/rules.yaml` (2 calls) |
| `make analyze` | Lanes and gaps from the notes, read in place by DuckDB |
| `make export` | Spreadsheets: `build/exports/notes.csv` and `cards.csv` |
| `make review` / `make review-report` | The blind packet's rating page, and its report |
| `make data-push` / `make data-pull` | Back up or restore the private data repo |
| `make test` / `make lint` | Offline tests (mock providers, no network) and lint |

## Where things live
`notes/` is the one store. Notes, quick cards (`build/quick/`), diagnoses (`data/diagnose/`), the steering rules and your seeds are private: git-ignored here and mirrored to `Kingsley-Cyber/animedex-data` by `make data-push`. Model calls go through the `claude` and `codex` subscription CLIs; no API keys.
