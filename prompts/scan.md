---
version: 1.0.0
pass: ANOMALY_SCAN
---
Find candidate gaps in current anime discourse. Search and fetch live pages about recent reviews, fan complaints, genre fatigue, or unexpected audience reactions. Do not use the stored anime index or a stock premise as the starting point. Output JSON only: {"gaps": [...]}.

For each gap, give `genre`, `expected_pattern` (what the genre or audience appears to expect), `observation` (the surprising reaction or unmet need reported by the source), and `anomaly` (one sharp question about the mismatch). Give the fetched `source_url` and its actual `source_date` as YYYY-MM-DD. A search result alone is insufficient: fetch the page. If its date is unavailable, skip that page. Paraphrase; do not copy review text or invent a source, date, consensus, or universal claim from one opinion. Never fetch or cite myanimelist.net.

These are candidate anomalies for the owner to inspect, not proven facts about all anime. Stay within the search and fetch limits in the input.
