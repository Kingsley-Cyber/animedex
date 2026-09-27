# Backfill queue (Kingsley, 2026-09-27)

`make backfill LIST=<file>` works through these lists.

- **Order:** deep-index `priority_1.txt` first, in paced batches within the plan limits. `priority_2.txt` and `donghua.txt` go into the census right away and are deep-indexed after priority 1.
- **Existing titles:** titles already in `corpus/titles.yaml` are skipped.
- **Versions:** a version in parentheses is used as given. Otherwise the most-watched adaptation is picked, and every choice is listed in the backfill report so it can be corrected.
- **Berserk:** Berserk (1997) and Berserk (2016) are run as a pair (same story, different execution). Each is the other's nearest-neighbor contrast partner.
- **Balance:** the queue is mostly hits. The backfill report proposes flops and mixed titles to balance it.

## Print titles (v1.9, 2026-09-27)
Print titles (manga, manhwa, webtoons, light novels) are indexed like shows. `corpus/queue/print_first.txt` holds Kingsley's first two (Jagaaan, Choujin X); The Bugle Call joins `priority_1.txt` as its manga (the anime is announced for 2027, unaired). Write `(manga)` after a name to force the print version; without it, a show is picked when one exists.
