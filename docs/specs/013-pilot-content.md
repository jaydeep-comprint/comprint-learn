# Spec 013: Pilot content slices

Status: draft
PRD link: docs/PRD.md#mvp-scope-v1 (item 2: "First content is a 6–8 concept slice of each of …")

## Summary
Each pilot course grows from 3 to **8 concepts**: Maths (algebra: polynomials, linear equations, quadratics),
Physics (motion and Newton's laws) and Python basics (functions, strings, lists, dictionaries, list algorithms).
New concepts are richer than the spec 003 samples (4 KPs, deeper pools, 2–3 practice items), and the existing
9 concepts get larger pools and a second practice item. A new `app content review-pack` command renders a course
to one HTML file with every answer, so content can be reviewed by people who don't read YAML. 013 ships after a
**self-review** (strict validator + an independent AI subject review); the **subject-teacher review** is tracked
per concept in `docs/content-review.md` and becomes a pilot gate in spec 014.

## User stories
- As a student, I want enough concepts in each subject to study for weeks, with fresh questions when I retry a KP.
- As a teacher, I want the course to match the CBSE chapters I teach, so I can mark chapters covered (spec 012)
  and assign them (spec 010).
- As a subject teacher reviewing content, I want one readable document per subject with questions, sample numbers,
  answers and explanations, so I can check it without the app or the repo.
- As the team, we want a record of which concept was reviewed by whom and when, so the pilot doesn't start on
  unreviewed content.

## Behaviour

### Syllabus basis
Follow the current CBSE syllabus as taught from the **current (rationalised) NCERT textbooks** for Classes 9–10.
Topics NCERT removed (e.g. the Class 9 remainder theorem) are not authored. Indian context: ₹, km/h, metric units,
neutral first names or none, Class 9–10 English reading level. No real people, schools or brands.

### Course structure (final state)
Chapter order comes from `course.yaml`; concept order from `chapter.yaml`. Existing ids are unchanged. **New** and
existing concepts are marked N / E. Weights are `encompassing_weight` (may be tuned while authoring, ±0.2, with
the reason in the commit message).

**`maths-9-10`**, chapters `[polynomials, linear-equations, pair-of-linear-equations, quadratic-equations]`

| Chapter (grade) | Concept | Prereqs (weight) | KPs |
|---|---|---|---|
| `polynomials` (9) "Polynomials" | N `polynomials-basics` | none | terms, coefficients and degree · value of a polynomial p(a) · zeros of a polynomial · adding, subtracting and multiplying polynomials |
| | N `algebraic-identities` | polynomials-basics (0.5) | (x ± y)² and x² − y² · (x + a)(x + b) · (x + y + z)² · cube identities incl. x³ + y³ + z³ − 3xyz |
| | N `factorisation-of-polynomials` | polynomials-basics (0.5), algebraic-identities (0.5) | factor theorem (is x − a a factor? find k) · splitting the middle term · factorising with identities · factorising cubics with the factor theorem |
| `linear-equations` (9) | E `linear-equations-two-variables` | (unchanged) | (unchanged, 3 KPs) |
| `pair-of-linear-equations` (10) | E `pair-of-linear-equations-graphical`, E `pair-of-linear-equations-algebraic` | (unchanged) | (unchanged, 3 KPs each) |
| `quadratic-equations` (10) "Quadratic equations" | N `quadratic-equations-solving` | factorisation-of-polynomials (0.6), linear-equations-two-variables (0.2) | recognising a quadratic equation and checking roots · solving by factorisation · the quadratic formula · word problems |
| | N `nature-of-roots` | quadratic-equations-solving (0.6) | the discriminant · nature of roots from D · finding k for equal / real roots · "is it possible?" applications |

**`physics-9-10`**, chapters `[motion, force-and-laws-of-motion]`

| Chapter (grade) | Concept | Prereqs (weight) | KPs |
|---|---|---|---|
| `motion` (9) | E `distance-and-displacement`, E `speed-and-velocity`, E `acceleration` | (unchanged) | (unchanged, 3 KPs each) |
| | N `motion-graphs` | speed-and-velocity (0.6), acceleration (0.5), maths-9-10/linear-equations-two-variables (0.2) | distance–time graphs (slope = speed) · velocity–time graphs (slope = acceleration) · area under a v–t graph = displacement · reading and comparing graphs of non-uniform motion |
| | N `equations-of-motion` | acceleration (0.8), motion-graphs (0.3), maths-9-10/linear-equations-two-variables (0.2) | s = ut + ½at² · v² = u² + 2as · choosing the right equation · braking and stopping-distance problems |
| `force-and-laws-of-motion` (9) "Force and laws of motion" | N `forces-and-inertia` | acceleration (0.3) | balanced and unbalanced forces (net force along a line) · first law and friction · inertia and mass · identifying the forces in everyday situations |
| | N `momentum-and-second-law` | forces-and-inertia (0.5), acceleration (0.6) | momentum p = mv · F = ma · force as rate of change of momentum (F·t = Δp) · units and combined problems |
| | N `third-law-and-momentum-conservation` (title "Newton's third law of motion") | momentum-and-second-law (0.7) | action–reaction pairs · why the pair doesn't cancel · equal forces, unequal effects (recoil as a = F/m: gun, jumping from a boat) · third law with F = ma. *Changed under decision 5: rationalised NCERT Class 9 deleted §9.6 Conservation of Momentum; the id is kept.* |

Cross-course edges stay light (decided): only to `maths-9-10/linear-equations-two-variables`, weight ≤ 0.3, so
physics never waits on Class 10 maths. No edges to the new maths concepts.

**`python-basics`**, chapters `[basics, functions-and-data]` (no grade)

| Chapter | Concept | Prereqs (weight) | KPs |
|---|---|---|---|
| `basics` | E `variables-and-types`, E `conditionals`, E `loops` | (unchanged) | (unchanged, 3 KPs each) |
| `functions-and-data` "Functions and data" | N `functions` | variables-and-types (0.4), conditionals (0.3) | def and calling · parameters and return values · return versus print · local variables and default arguments |
| | N `strings` | loops (0.4), variables-and-types (0.3) | indexing incl. negative indices · slicing · string methods (upper, lower, strip, replace, find, split) · looping over a string and counting |
| | N `lists` | loops (0.5) | creating and indexing · changing a list (append, insert, remove, pop, len) · looping over a list to total or build a new list · slicing and `in` |
| | N `dictionaries` | lists (0.4), strings (0.3) | create and look up (`KeyError`, `get`) · add, update, delete · looping over `items()` · counting with a dictionary |
| | N `list-algorithms` | lists (0.6), functions (0.5), conditionals (0.3) | linear search (index or −1) · max / min by hand · filtering and counting matches · nested loops (pairs, 2-D lists) |

**Existing concepts' prerequisites are not changed** (adding a prereq would change frontiers of students who
already started them). New concepts only add edges pointing at existing ones.

### Quality bar
Enforced by `make content-check` (now strict) and `backend/tests/test_pilot_content.py`:

| | New concepts | Existing concepts |
|---|---|---|
| KPs | exactly 4 | keep 3 (a 4th KP would re-open learned concepts) |
| KP pool weight (fixed = 1, params = 2) | ≥ 10 per KP | topped up to ≥ 10 per KP with new items (new ids) |
| Quick checks per KP (numeric / expression / mcq) | ≥ 2 (brush-ups, quizzes and placement draw only these) | same |
| MCQ share of a pool | ≤ 30% (existing warning, now failing under strict) | same |
| Practice items | 2–3, maths/physics: param `multistep`; Python: `code` | add a 2nd item |
| Images | as needed, hand-written SVG in `img/` | unchanged |
| Misconception check | 1 MCQ (existing rules) | unchanged |

- Every KP has a worked example `.md`; every concept an `intro.md` (short: the Learn layer is "kept short").
- `expected_minutes` is realistic for a Class 9–10 student (XP depends on it): quick checks 0.5–2, multi-step 4–10,
  code 5–15.
- **Python has no free-text answer type**: "what does this print" items with a number use `numeric`; text output
  uses `mcq` (within the 30% cap) or a small `code` task. Code KP questions count 1 in the pool like any fixed item.
- Every MCQ has ≥ 1 distractor tagged with a course misconception. New misconceptions go into the course's
  `misconceptions.yaml` with a student-facing `title` and a teacher-facing `description`. Expected new ones
  (at least): maths `square-of-sum` ((a + b)² = a² + b²), `degree-counts-terms`, `factor-sign` (x − a factor ⇒
  p(−a) = 0), `divides-by-variable` (dividing by x and losing the root 0), `discriminant-sign`; physics
  `motion-needs-force`, `action-reaction-cancel`, `mass-is-weight`, `slope-vs-area`, `graph-is-path`; Python
  `index-starts-at-one`, `slice-includes-end`, `print-is-return`, `strings-are-mutable`, `append-returns-list`,
  `dict-key-vs-value`.
- Diagrams: hand-written SVGs following content/README.md's SVG rules (d–t / v–t graphs, force arrows). Graph
  questions with params describe the numbers in text or a table; an image can't follow the student's numbers.
- Optional HTTPS YouTube links in intros are allowed, not required.

### Review pack (`app content review-pack`)
```
cd backend && uv run app content review-pack [--root ../content] [--course ID ...] [--out <repo>/review-packs] [--seeds 3]
make review-pack                        # all courses, default options
```
- Loads and validates the tree like `content check` (refuses on errors; prints warnings), then writes one
  self-contained `<out>/<course-id>.html` per course. `review-packs/` is gitignored. No DB access.
- **Contents, in course order**: a header (course title, generation date, `git rev-parse --short HEAD` if
  available, counts); the course's misconceptions (id, title, description); then per chapter (title, grade) and
  concept: title, summary, prerequisites with weights, `intro.md`, the misconception check, each KP (title, key
  prereqs, worked example, then its items), then practice items.
- **Per item**: id, kind, type, Bloom, expected minutes, pool weight; for param items, the params/constraints/derived
  as written **and** the prompt, answer and explanation rendered for seeds 1…N (`app.content.params.sample` +
  `render`, the same code students get); fixed items once. MCQ: every option, the correct one marked, each
  distractor's misconception title. Multi-step: each step's prompt and answer. Numeric: value, unit, mode,
  sig figs / tolerance. Expression: value, variables, `sympy_mode`. Code: starter, solution, every test (visible and
  hidden) with expected values, time limit.
- **Rendering**: Markdown and KaTeX are rendered in the browser by pinned scripts from jsDelivr (marked, KaTeX
  auto-render, Mermaid; versions as in `frontend/package.json` where they exist), so no new Python dependency.
  Content text is embedded as JSON in a `<script type="application/json">` block and rendered from there (no HTML
  string-building from content). Images are inlined as `data:` URIs so the file can be emailed.
- Print CSS: each concept starts a new page, and each concept ends with an empty "Reviewer notes" box, so a teacher
  can print it or save a PDF and annotate.
- Deterministic: the same tree and options give the same file except the header's date/sha.

### Review process and tracking
`docs/content-review.md` (new) holds:
1. The **review checklist**: answer correct for every sample seed; numbers sensible (no awkward decimals unless
   intended); units and sig figs right; matches the CBSE/NCERT scope and notation; no ambiguity (one defensible
   answer); distractors are real mistakes and tagged correctly; explanation teaches, not just states; worked example
   matches the KP's questions; reading level and Indian context; expected minutes realistic; Python: solution is
   idiomatic beginner code, tests cover edge cases.
2. A **table, one row per concept** (all 24): course, concept id, status (`draft` → `ai-reviewed` →
   `teacher-reviewed`, or `changes-requested`), AI review date, teacher reviewer (role and school code, e.g.
   "maths teacher, ABC"; no personal contact details), teacher review date, notes / PR link.

**Self-review (gate for 013, per subject PR)**:
1. `cd backend && uv run app content check --root ../content --strict` clean; `make check` and `make test-db` green;
   `make content-import` into the dev DB twice, the second run reporting no changes.
2. **Independent AI subject review**: generate the pack, then give a fresh `general-purpose` subagent the pack path,
   the concept folders and the checklist only (not the authoring conversation). It independently solves every item
   at seed 1 and checks the checklist; findings are fixed (or answered with a reason in the PR), then rows move to
   `ai-reviewed` with the date.

**Teacher review (pilot gate, not 013)**: the pack is sent to a subject teacher per subject (maths, physics;
Python by a computer-science teacher if available). Their notes come back as fixes in normal content PRs; rows move
to `teacher-reviewed`. Spec 014 / the ROADMAP pilot gate requires every row `teacher-reviewed`.

## UI / UX
No app UI changes. Things that change on screen only because there is more content:
- The knowledge graph (spec 005) shows 8 nodes per course over 2–4 chapters; check its layout on phone width.
- Placement's chapter list (spec 012), the assignment dialog (spec 010) and the student home outline show the new
  chapters.
- The review pack is a standalone HTML file: readable on a laptop, printable on A4.

## Technical design
- **Files / modules touched**:
  - `content/maths-9-10/`: `course.yaml`, `misconceptions.yaml`, new `00-polynomials/` and `03-quadratic-equations/`
    folders (folder prefixes are for humans only; renumbering existing folders is not needed), 5 new concept folders;
    existing concept YAMLs (new items + 2nd practice item).
  - `content/physics-9-10/`: `course.yaml`, `misconceptions.yaml`, `01-motion/chapter.yaml` + 2 concept folders, new
    `02-force-and-laws-of-motion/` with 3; existing concepts topped up.
  - `content/python-basics/`: `course.yaml`, `misconceptions.yaml`, new `02-functions-and-data/` with 5; existing
    concepts topped up.
  - `backend/app/content/review_pack.py` (new): `build_review_pack(bundle: ContentBundle, course_id: str, *,
    seeds: int) -> str` (images resolved from `bundle.root`) (pure; returns HTML) and a small HTML template (string constant or
    `review_pack.html` beside it).
  - `backend/app/cli.py`: `@content_app.command("review-pack")`.
  - `Makefile`: `review-pack` target; `content-check` runs the checker with `--strict` (the CLI default stays
    non-strict; decided while specifying).
  - `.gitignore`: `/review-packs/`.
  - `backend/tests/test_content_review_pack.py` (new, offline): built from `tests/content_fixtures.py`.
  - `backend/tests/test_pilot_content.py` (new, offline): loads the real tree (`DEFAULT_CONTENT_ROOT`) and asserts
    the quality bar above (`PILOT_COURSES` = course id → expected active concept count; each subject PR adds its
    course, so the final state is all three at 8).
  - `docs/content-review.md` (new), `content/README.md` (mention the review pack, that `make content-check` is strict, and the pilot
    bar), `docs/ROADMAP.md` (013 "Done when" → self-review; 014 gains "every concept teacher-reviewed"),
    `docs/PRD.md` (Decided: content review line).
  - DB tests that import the real tree (`tests/learn_helpers.py` users, e.g. `test_placement_db.py`,
    `test_quiz_db.py`, `test_courses_api_db.py`, `test_assignments_db.py`, `test_learn_api_db.py`): if one hard-codes counts or positions that
    the new content changes, make the test independent of the count (look up by id) instead of shaping the content
    around the test.
- **Data model changes**: none. New rows come through the existing importer; chapter reordering changes `position`
  only (no version bump).
- **API / interfaces**: none new. The review pack reads `ContentBundle` from `app.content.loader.load` and uses
  `app.content.params.sample` / `render` / `format_number`.

### Delivery
Three PRs, each self-reviewed as above:
1. `feat/013-pilot-content-maths`: review-pack CLI + tests, strict `content-check`, `test_pilot_content.py`,
   `docs/content-review.md`, doc updates, then the maths course.
2. `feat/013-pilot-content-physics`.
3. `feat/013-pilot-content-python`; this PR sets spec 013 to shipped.

## Builder-check decisions (decided while specifying)
1. **Strict**: only `make content-check` adds `--strict`; the CLI flag keeps its default. The validator's pool
   thresholds (≥ 6 error, ≥ 8 warning) are unchanged; the pilot bar (≥ 10, ≥ 2 quick checks, KP and practice
   counts) lives only in `test_pilot_content.py`, which tells existing from new concepts with a hard-coded
   `LEGACY` set of the 9 existing concept ids. The MCQ share is counted by item count, like the validator
   (validate.py `_check_pool`).
2. **Top-ups**: every existing KP has weight 8 today, so each gets +2: preferably one param quick check (new id).
   Existing concepts go from 1 to exactly 2 practice items; new concepts have 2–3.
3. **`expected_minutes` ranges** apply to new items only (existing items aren't re-timed: it would bump versions and
   change XP). Code questions inside KPs: 2–5 min; practice code tasks: 5–15.
4. **`key_prereqs`** for new KPs: the direct prerequisites that KP's steps really use (may be `[]`, e.g. a first
   KP that introduces only new ideas). Every new concept has at least one KP with a non-empty list when it has
   prereqs, so remediation has somewhere to go.
5. **Syllabus check before authoring each subject**: confirm each KP against the current CBSE syllabus / rationalised
   NCERT chapter (notably: conservation of momentum and recoil in Class 9 Force and Laws of Motion;
   x³ + y³ + z³ − 3xyz in Class 9 Polynomials; the quadratic formula in Class 10). If a topic was removed, replace
   that KP with another in-scope topic of the same chapter (e.g. third-law examples, more applications) and note it
   in the PR; the concept ids and count stay.
6. **Pack Markdown matches the app's maths handling**: `$…$` / `$$…$$` spans are pulled out before marked runs and
   rendered with KaTeX, then put back (the app uses remark-math + rehype-katex). Raw HTML in content is escaped,
   not rendered (the app never renders it): marked's `html` renderer is overridden to escape. The JSON block
   escapes `<`, `>`, `&` as `\u003c` / `\u003e` / `\u0026`, so `</script>` in content can't end it.
7. **Pinned scripts** (jsDelivr): `katex@0.19.1` (+ its CSS), `mermaid@12.2.0` (ESM), `marked@16.4.2` (the
   lockfile's version). No content uses Mermaid today; load it only if a concept contains a mermaid block.
8. **Answers shown as students see them**: the pack converts each schema `Item` to the stored answer dict the way
   the importer does, then uses the grading display helpers (`app.grading.numeric._display`, made public as
   `display_value` with no behaviour change; `app.grading.expression.answer_expr` + `sympy.latex`). This is a rename,
   not a grading change. MCQ option text is shown as written (the app doesn't render params in options).
9. **Seeds**: the pack uses seeds 1…N; students get random seeds (`secrets.randbelow(2**31)`), so the pack shows
   samples, not the exact numbers a student saw. Said in the pack header.
10. **review-pack CLI**: validates errors-only (prints warnings, refuses on errors); `--out` defaults to
    `DEFAULT_CONTENT_ROOT.parent / "review-packs"`; the git sha is read with `git -C <content root>`, omitted if git
    fails.
11. **Tests that the new content breaks** (each subject PR fixes its own course's): `test_courses_api_db.py`
    (exact chapter/concept counts, physics concept list, `kp_count == 3`), `test_learn_api_db.py` (exact physics
    outline order), `test_placement_db.py` (covered-chapter flags, range counts, "every maths outline concept
    placed"). Make them look up by id or derive expectations from the loaded tree.
12. **DB test runtime**: `world()` imports the real tree (~700 items after 013) in many tests. Measure on PR 1; if
    `make test-db` slows noticeably, cache the import once per test session (import is idempotent) rather than
    switching to a fixture tree.
13. **`docs/content-review.md`** lands in PR 1 with all 24 rows as `draft`.

## Edge cases
- **Students with progress on existing concepts**: new items in their KP pools appear on retries and reviews (same
  KP, more variety); a 2nd practice item means a failed multistep may draw the new one. No concept re-opens, because
  no KP is added to an existing concept and no prereq is added to one.
- **Editing an existing item during review** bumps its version; if what it asks changes, give it a new id and remove
  the old one from the YAML (the importer retires it, per content/README.md).
- **Placement ranges** (spec 012): covered chapters' prerequisite ancestors now include the polynomials chapter for
  quadratics; `range_ids` is frozen per diagnostic, so open diagnostics are unaffected by an import.
- **Quiz and brush-ups** need quick checks: enforced as ≥ 2 per KP.
- **Param items and diagrams**: never put param-dependent numbers in an image.
- **Strict mode on existing content**: it passes today (`content OK: 3 courses, 9 concepts, 153 items`, no
  warnings); keep it that way.
- **Review pack with a broken tree**: errors → exit 1, nothing written; a missing image is already a validator error.
- **Review pack and secrets**: the pack contains answers and hidden tests by design. It's a local, gitignored file,
  never served by the app or put in `content/`.
- **Content and minors' data**: no personal data in content; teacher reviewers recorded by role and school code.

## Out of scope
- The subject-teacher review itself (tracked; a pilot gate in 014).
- Class 10 Polynomials (zeros and coefficients), arithmetic progressions, uniform circular motion, gravitation,
  Python input/output and f-strings, files, classes.
- Any change to engines, grading, answer types, the validator's rules (other than making strict the default) or the
  frontend.
- A content authoring or in-app staff preview UI.
- Translations; videos beyond optional YouTube links.
- Converting the review pack to PDF or Docs automatically (print to PDF from the browser).

## Verification (end-to-end)
- [ ] `cd backend && uv run app content check --root ../content --strict` → `content OK: 3 courses, 24 concepts …`,
      no warnings.
- [ ] `cd backend && uv run pytest tests/test_content_review_pack.py tests/test_pilot_content.py tests/test_content_validate.py`
      green. Review-pack tests cover: answers and hidden tests present; 3 seeds rendered for a param item and once for
      a fixed one; MCQ correct option and misconception titles; images inlined; content text only in the JSON block
      (a `<script>` in a prompt doesn't create a script tag); refusal on a tree with errors; same output twice
      (ignoring the header).
- [ ] `cd backend && uv run mypy` and `make check` green; `make test-db` green (shared test DB, run alone).
- [ ] `make content-import ARGS=--dry-run` lists the new chapters/concepts/items; `make content-import` twice, the
      second reports no changes (after `alembic current` shows head on the dev DB).
- [ ] `make review-pack` writes `review-packs/{maths-9-10,physics-9-10,python-basics}.html`; open each: KaTeX,
      Mermaid and SVGs render, answers show, print preview starts each concept on a new page. Screenshot one concept
      per subject.
- [ ] AI subject review done per subject (fresh subagent, checklist only); findings fixed; all 24 rows of
      `docs/content-review.md` are `ai-reviewed` with dates.
- [ ] Browser check (the user does it; Chrome can't reach localhost): `make dev`, as a student open one new concept
      per subject: Learn (intro, worked examples, check) → KP questions → practice (a multistep in maths/physics, a
      code task in Python). Knowledge graph per course shows 8 nodes and the new chapters (desktop + phone width).
      As a teacher, the placement chapter list and the assignment dialog show the new chapters. Screenshots of each.
