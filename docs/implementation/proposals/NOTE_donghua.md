# Plan note: donghua (approved by Kingsley, 2026-09-27)

- **What:**
  - New medium `donghua` (Chinese animation).
  - New `anime_production.source_medium` value `manhua`.
  - `anime_production` stays anime-only, so donghua titles never get that module.
  - Donghua is animated, so the `sensory` module activates for it, as it does for other animation.
- **Where:** `ontology/vocab.json` 1.3.0 (medium and source_medium enums; sensory activation rule) and `config/settings.yaml` (`verify.medium_labels.donghua`). Docs: 00, 02, 04.
- **When:** at the M2→M3 boundary, together with v1.3, before any donghua title runs.
- **Census:** donghua is included. The catalog query covers Chinese-origin animation, and those entries map to medium `donghua`.
- **Partners:** for anime titles, donghua counts as a non-anime cross-medium partner. The cross-medium rule itself is unchanged.
- **Queue:** the 10 donghua titles in `corpus/queue/donghua.txt` go into the census once this lands, and are deep-indexed after priority 1.
