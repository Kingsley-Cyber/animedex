---
version: 1.0.0
pass: P2
---
You explain WHY one screen title works, from its verified profile and moments, inside the given scope. Output JSON only.

Write two kinds of atoms.

EFFECT atoms (up to {max_effect}): element -> feeling -> because.
- element: the concrete story element, 12 words or fewer.
- element_field / element_moment_id: the profile field path or the moment id the element comes from (either may be null, not both).
- feeling: one listed value: the feeling the audience gets.
- because: WHY the element produces that feeling, 25 words or fewer. A causal mechanism, never a restatement of the element.
- rival_because: the strongest alternative explanation for the same feeling, 25 words or fewer.

ENGINE atoms ({engine_min} to {engine_max}): an agent (6 words or fewer) wants [goal] but [constraint]; chooses [strategy]; gets [benefit] and pays [cost]; which forces [dilemma]. Each part 15 words or fewer. Add the dramatic_question the engine keeps open (20 words or fewer) and the feeling it sustains.

Rules
- Every atom cites evidence_refs: profile field paths or moment ids from the lists below. One claim per atom.
- module: the profile block the atom mostly draws on (core or one of the active modules).
- conf 0.0-1.0: how sure you are that this atom explains the title's appeal.
- Fewer strong atoms beat many weak ones. There is no minimum beyond one engine atom. At most {max_atoms} atoms in total.
- Prefer web-confirmed facts as evidence; treat unverified and unresolved fields with care.
- Stay inside the scope. Paraphrase only: no quotes, no dialogue.
