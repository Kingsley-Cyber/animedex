---
version: 1.2.0
pass: CENSUS
---
You record what is widely known about the power systems and story shapes of titles (screen series and films, or print series: manga, manhwa, webtoons, light novels), from memory. Output JSON only.

For each listed title:
- has_power_system: true if extraordinary abilities or structured combat are central to the story.
- If true, pick one listed value for each of gate, cost_of_power, progression, visible_counter, fight_medium, power_is, and set_structure (how the roster of powers is organized). Use null when you are unsure.
- For every title, whatever has_power_system says: story_engine (the structure that keeps generating story) and mc_archetype (who the protagonist is at the start). Use null when you are unsure.
- borrowed_system: the everyday system its powers borrow (for example a game with levels, an exam, a job, a market, a sport, a social rating, a contract, a card collection, crafting or cooking, a military rank, a ritual), from the listed values. Use none if the powers borrow no everyday system.

These answers are only counted, to see which combinations already exist. Say null rather than guess. Stay with the listed version of each title.
