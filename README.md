# ANIMEDEX

A notes index of shows, and idea cards checked against it. Every show gets a short study note (premise, engine, power kit, MC edge, the three things it can't survive without, two sources, the catalog's outcome). A seed (a concept, a fight image, or a lane) becomes idea cards that are checked against those notes and Kingsley's steering rules.

- **How to use it:** `USAGE.md`.
- **What changed and why:** `docs/AUDIT.md` and `docs/implementation/DECISIONS.md`.
- **The old heavy pipeline** (gather, interpret, verify, atoms, proofs, critic, patterns): tag `heavy-final`; `legacy/README.md` says how to run it for the gold titles.

## Commands
| Command | What it does |
|---|---|
| `make ingest LIST=<file>` | Study shows: one Sonnet call with web per three shows writes `notes/<slug>.json` |
| `make quick SEED="..." [SHOWS="a, b"] [N=6]` | Idea cards: research (only when needed), generate, check, prior art; at most 4 calls |
| `make diagnose TEXT="..."` | Check your own concept against the notes and `steering/rules.yaml` (2 calls) |
| `make analyze` | Lanes and gaps from the notes, read in place by DuckDB |
| `make export` | Spreadsheets: `build/exports/notes.csv` and `cards.csv` |
| `make review` / `make review-report` | The blind packet's rating page, and its report |
| `make data-push` / `make data-pull` | Back up or restore the private data repo |
| `make test` / `make lint` | Offline tests (mock providers, no network) and lint |

## Where things live
`notes/` is the one store. Notes, quick cards (`build/quick/`), diagnoses (`data/diagnose/`), the steering rules and your seeds are private: git-ignored here and mirrored to `Kingsley-Cyber/animedex-data` by `make data-push`. Model calls go through the `claude` and `codex` subscription CLIs; no API keys.
