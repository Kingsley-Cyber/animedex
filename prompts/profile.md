---
version: 1.0.0
pass: PROFILE
---
You do two jobs in one answer for ONE title, inside its scope. First gather documented facts from the web (part 1 below: the same rules as the GATHER pass). Then, from those facts and nothing else, fill the profile and the cast (part 2 below: the same rules as the INTERPRET pass). Output one JSON object with facts, characters, reception, profile and cast.

- Give every fact an id: facts F1, F2, ...; character facts C1, C2, ...; reception verdicts R1, R2, .... Cite those ids, and the reception_api ids listed in the input (A01, ...), in the profile's evidence and in the outcome's signals. A field with no cited fact is your interpretation and says so through its confidence.
- The outcome comes from reception facts only (R.. verdicts and A.. numbers). With none, leave it null.
- Stay within the search and fetch limits in the input. Paraphrase only; no quotes, no dialogue lines. Never open myanimelist.net pages.
