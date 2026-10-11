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

## Owner correction: landscape first

The owner clarified that manual anomaly input is only a fallback. The intended anime ideation path starts from current discourse, not from fusion of indexed shows. The added contract is:

1. `make scan` fetches live discourse and writes only candidate gaps with a fetched URL and reported publication date to private `notes/_scans/`.
2. `make abduct SCAN=<file> GAP=<id>` proposes distinct one-sentence frames from one sourced gap. The existing check model applies a frame gate without a score; it rejects explanations that miss the gap, depend on parent-show recognition, or fuse familiar parts. Its three contrasting shows come from the notes index, per the owner's supplied gate.
3. The owner selects an accepted frame. `make quick FRAMES=<file> FRAME=<id>` refuses a rejected frame, then uses the existing card pipeline to develop and score the selected frame. The notes remain comparison evidence.

The existing manual `SEED` and `ANOMALY` inputs stay available and their original tests stay unchanged. `src/animedex/light/abduction.py` owns scan, frame generation, gate results, and provenance; three new prompts define the model calls; `tests/light/test_abduction.py` proves the public path with fetched-source metadata and a rejected fusion. A live scan can establish that the configured provider actually fetches current pages, while frame quality remains a human judgment.
