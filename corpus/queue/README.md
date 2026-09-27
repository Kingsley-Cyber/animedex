# Backfill queue (Kingsley, 2026-09-27)

`make backfill LIST=<file>` works through these lists.

- **Order:** deep-index `priority_1.txt` first, in paced batches within the plan limits. `priority_2.txt` and `donghua.txt` go into the census right away and are deep-indexed after priority 1.
- **Existing titles:** titles already in `corpus/titles.yaml` are skipped.
- **Versions:** a version in parentheses is used as given. Otherwise the most-watched adaptation is picked, and every choice is listed in the backfill report so it can be corrected.
- **Berserk:** Berserk (1997) and Berserk (2016) are run as a pair (same story, different execution). Each is the other's nearest-neighbor contrast partner.
- **Balance:** the queue is mostly hits. The backfill report proposes flops and mixed titles to balance it.
