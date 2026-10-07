# Anomaly input for the light quick path

Owner request, 2026-10-06: steer ANIMEDEX toward the anomaly-led ideation described in the supplied design document.

## Contract

`make quick ANOMALY="..."` accepts a user-observed contradiction. Each generated card states a distinct explanatory hypothesis and builds a story from it. The existing CHECK pass rejects a card whose hypothesis does not explain the observation. The private report shows the observation, hypothesis, verdict, and reason. `make quick SEED="..."` keeps its current behavior.

The observation is labeled user-supplied and unverified. This change uses the existing research, generation, check, and conditional prior-art calls, notes store, steering rules, and call cap.

## Files and verification

- `Makefile`, `src/animedex/cli.py`: expose one input choice at the public command.
- `src/animedex/light/quick.py`, `prompts/ingest.md`, `prompts/generate.md`, `prompts/check.md`: carry the anomaly through the existing passes and report.
- `USAGE.md`: show the command and its trust boundary.
- `tests/light/test_anomaly_quick.py`: exercise the public command through the report, including rejection of an unrelated explanation. Existing tests remain untouched.

Verification: `make test`, `make lint`, and `harness validate` must pass before merge. A live creative-quality judgment still belongs to the owner; this change proves the pipeline's behavior with the mock provider.
