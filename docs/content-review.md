# Content review (spec 013)

Every pilot concept is reviewed twice before students use it:

1. **Self-review** (gate for spec 013, one PR per subject): `uv run app content check --root ../content --strict`
   is clean, then a fresh AI subagent that never saw the authoring conversation gets only the review pack, the
   concept folders and the checklist below, solves every item at seed 1 and reports findings. Findings are fixed
   (or answered with a reason in the PR), then the concept moves to `ai-reviewed`.
2. **Teacher review** (pilot gate, spec 014): the review pack goes to a subject teacher (maths, physics; Python by
   a computer-science teacher if available). Their notes come back as fixes in normal content PRs; the concept
   moves to `teacher-reviewed`. The pilot doesn't start until every row is `teacher-reviewed`.

Make a pack with `make review-pack` (all courses) or
`cd backend && uv run app content review-pack --course maths-9-10`. It writes `review-packs/<course>.html`
(gitignored): open it in a browser, print it or save it as PDF. **It contains every answer and hidden test**:
send it to reviewers only, never to students.

## Checklist

For every concept, check each item at every sample seed in the pack:

- [ ] **Correct**: the answer is right for every sample seed (solve it yourself first).
- [ ] **Sensible numbers**: no awkward decimals or huge values unless intended; units and significant figures right.
- [ ] **Syllabus**: matches the CBSE scope and NCERT (rationalised) notation for the class; nothing NCERT removed.
- [ ] **Unambiguous**: exactly one defensible answer; the prompt says what form or precision is wanted.
- [ ] **Distractors**: wrong MCQ options are real student mistakes, tagged with the right misconception.
- [ ] **Explanations teach**: they show the method, not only the result.
- [ ] **Worked example matches**: each KP's worked example prepares the student for that KP's questions.
- [ ] **Reading level and context**: Class 9–10 English, Indian context (₹, km/h, metric), no real people,
      schools or brands.
- [ ] **Time**: `expected_minutes` is realistic for a Class 9–10 student (XP depends on it).
- [ ] **Python**: the solution is idiomatic beginner code; tests cover edge cases (empty input, zero, negatives).

Record findings per concept in the PR (or, for teachers, in the pack's "Reviewer notes" boxes).

## Status

Status: `draft` → `ai-reviewed` → `teacher-reviewed`, or `changes-requested`. Teacher reviewers are recorded by
role and school code only (e.g. "maths teacher, ABC"), never by name or contact details.

| Course | Concept | Status | AI review | Teacher reviewer | Teacher review | Notes / PR |
|---|---|---|---|---|---|---|
| maths-9-10 | polynomials-basics | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | algebraic-identities | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | factorisation-of-polynomials | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | linear-equations-two-variables | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | pair-of-linear-equations-graphical | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | pair-of-linear-equations-algebraic | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | quadratic-equations-solving | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| maths-9-10 | nature-of-roots | ai-reviewed | 2026-11-11 | | | spec 013 PR 1 |
| physics-9-10 | distance-and-displacement | draft | | | | |
| physics-9-10 | speed-and-velocity | draft | | | | |
| physics-9-10 | acceleration | draft | | | | |
| physics-9-10 | motion-graphs | draft | | | | |
| physics-9-10 | equations-of-motion | draft | | | | |
| physics-9-10 | forces-and-inertia | draft | | | | |
| physics-9-10 | momentum-and-second-law | draft | | | | |
| physics-9-10 | third-law-and-momentum-conservation | draft | | | | |
| python-basics | variables-and-types | draft | | | | |
| python-basics | conditionals | draft | | | | |
| python-basics | loops | draft | | | | |
| python-basics | functions | draft | | | | |
| python-basics | strings | draft | | | | |
| python-basics | lists | draft | | | | |
| python-basics | dictionaries | draft | | | | |
| python-basics | list-algorithms | draft | | | | |
