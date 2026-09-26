# Completion Report — M<n>: <name>

- **Date:**
- **Agent / model:**
- **Commit tag:** `m<n>-complete`

## Summary
<3 sentences max: what was built, whether it passes, what's next.>

## Acceptance criteria
| AC | Status (pass / fail / partial) | Evidence (test name, file, or metric) |
|---|---|---|
| AC-xx | | |

## Tests
- `make test`: <passed> / <failed> / <skipped> (every skip justified below)
- `make validate`: pass / fail
- Clean-rebuild determinism: pass / fail

## Metrics
| Metric | Value | Bar |
|---|---|---|
| Tokens per title (by pass) | | — |
| Cost per title | | Budget cap |
| P1 enum agreement | | ≥ 0.80 |
| P3 load-bearing agreement | | ≥ 0.70 |
| Load-bearing recall vs. gold | | ≥ 0.60 |
| Engine match vs. gold | | Tracked |
| Load-bearing atoms per title | | 3–8 |
| CHECK reject rate | | < 0.30 |
| Contested atoms | | Tracked |
| Web correction rate (top 5 fields) | | Tracked |
| Episodes indexed / unsourced (M6+) | | Tracked |
| Status transitions and promotions (M6+) | | Tracked |
| Episode-backed share of load-bearing atoms (M6+) | | Tracked |
| Cost per episode and per re-run (M6+) | | Budget cap |
| H1 failure rate (M5+) | | Tracked |
| Blind review result / lift (M5+) | | Beats baseline |

## Changes to prompts, vocab, or config
| File | Old version → new | Why |
|---|---|---|

## Deviations from spec
<Anything built differently from 03–05, and why.>

## Ontology proposals pending review
<List with proposed value, field, and example.>

## NEEDS_ADJUDICATION and unsettled CONTESTED items
<List with atom ID and the critic's reason.>

## Decisions needed from Kingsley
<Numbered, each answerable in one line.>

## Known issues and risks

## Next milestone readiness
- [ ] All ACs pass
- [ ] Report filed
- [ ] Tagged commit pushed
