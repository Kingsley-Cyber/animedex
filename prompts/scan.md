---
version: 1.0.1
pass: ANOMALY_SCAN
---
Find candidate gaps in current anime discourse. Search using the `as_of` year and fetch pages published during the current airing season about recent reviews, fan complaints, genre fatigue, or unexpected audience reactions. Do not use the stored anime index or a stock premise as the starting point. Output JSON only: {"gaps": [...]}.

For each gap, give `genre`, `expected_pattern` (what the genre or audience appears to expect), `observation` (the surprising reaction or unmet need reported by the source), and `anomaly` (one sharp question about the mismatch). Give the fetched `source_url` and its actual `source_date` as YYYY-MM-DD. Use a permalink to one dated article or discussion thread, not an archive, category page, or search result. Open the page; if its date is unavailable, skip it. Paraphrase; do not copy review text or invent a source, date, consensus, or universal claim from one opinion. Never fetch or cite myanimelist.net.

These are candidate anomalies for the owner to inspect, not proven facts about all anime. Stay within the search and fetch limits in the input.
