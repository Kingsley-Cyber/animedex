# ANIMEDEX

Evidence-backed ideation engine for screen stories. It breaks titles into effect atoms (why a story feels good) and engine atoms (why it keeps going), proves which ones matter, and generates anime premises where the map is empty.

- **Spec (source of truth):** `docs/implementation/` (start with `00_GOAL.md` and `CHANGELOG.md`).
- **Owner's operating brief:** `.control/policies/operating-brief.md`.
- **Control plane:** URCP. Start a session with `harness bootstrap --json`; tasks live in Beads (`bd ready`).

## Commands
| Command | What it does |
|---|---|
| `make validate` | Ontology coverage (every field traces to a competency question), canonical data invariants, schemas current |
| `make test` | Full offline test suite (mock provider, no network) |
| `make build` | DuckDB build and exports from `data/canonical/` into `build/` |
| `make clean-build` | `rm -rf build`, rebuild, and verify identical table hashes |
| `make schemas` | Regenerate `schemas/*.schema.json` from the pydantic models |
| `make eval` | Gold-set status and evaluation reports |
| `make smoke TITLE=<id>` | One budget-capped live run through the configured providers |

## Data tiers
Only `data/canonical/` is committed. `data/raw/`, `data/candidates/`, `data/quarantine/`, `data/cache/`, and `build/` are local and rebuildable. Fetched web text is never stored; logs keep the URL and a hash.
