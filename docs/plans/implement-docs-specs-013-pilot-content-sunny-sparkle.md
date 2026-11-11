# Plan: Spec 013, PR 2 (`feat/013-pilot-content-physics`)

## Context
Spec 013 (`docs/specs/013-pilot-content.md`) grows each pilot course to 8 concepts. PR 1 (maths + tooling:
review pack, strict `make content-check`, `backend/tests/test_pilot_content.py`, `docs/content-review.md`)
is merged (#16). This PR does **physics only**: 5 new concepts, a new chapter, top-ups to the 3 existing
concepts, the DB tests the new physics content breaks, and the self-review gate. Python is PR 3, in a fresh
session. No code, engine or UI changes.

Authoring like maths (user decision): I write `motion-graphs` as the model concept, then one subagent per
remaining concept (4 in parallel). I check and read each one before committing it.

## Steps

### 0. Branch
`git switch main && git pull` → `git switch -c feat/013-pilot-content-physics`. `docs/drafts/` stays untracked.

### 1. Syllabus check (decision 5)
Use WebSearch to check that the rationalised NCERT Class 9 "Force and Laws of Motion" still covers conservation of
momentum and recoil, and that Class 9 "Motion" covers graphs and the three equations of motion. If something
was removed, swap that KP for another in-scope topic from the same chapter and note it in the PR.

### 2. Course skeleton (me)
- `content/physics-9-10/course.yaml`: `chapters: [motion, force-and-laws-of-motion]`.
- `01-motion/chapter.yaml`: `concepts: [distance-and-displacement, speed-and-velocity, acceleration,
  motion-graphs, equations-of-motion]`.
- New `02-force-and-laws-of-motion/chapter.yaml` (grade 9, title "Force and laws of motion",
  `[forces-and-inertia, momentum-and-second-law, third-law-and-momentum-conservation]`).
- `misconceptions.yaml`: add `motion-needs-force`, `action-reaction-cancel`, `mass-is-weight`,
  `slope-vs-area`, `graph-is-path` (title + teacher description). The subagents may propose more in their
  report; I add those myself, so two agents never edit the same file.
- `test_pilot_content.py`: `PILOT_COURSES` gains `"physics-9-10": 8` (it fails until the content is done, which is expected).

### 3. Model concept: `motion-graphs` (me)
Prereqs speed-and-velocity 0.6, acceleration 0.5, maths-9-10/linear-equations-two-variables 0.2. 4 KPs from
the spec table, each pool weight ≥ 10, ≥ 2 quick checks, MCQ ≤ 30%; 2–3 param `multistep` practice items;
hand-written SVG d–t / v–t graphs in `img/` for fixed items only (param graph questions give their numbers in text or a
table). Iterate on `uv run app content check --root ../content --strict` and
`uv run pytest tests/test_pilot_content.py -k motion-graphs`; scan rendered prompts over ~50 seeds for
`1x`, `+ -`, `- -` and awkward decimals (review_pack `_item`).

### 4. Four concepts in parallel (subagents, `general-purpose`)
`equations-of-motion`, `forces-and-inertia`, `momentum-and-second-law`,
`third-law-and-momentum-conservation`. Each brief contains: the spec table row (prereqs and weights, KPs), the
quality bar and `expected_minutes` bands, `content/README.md`, `motion-graphs` and `acceleration` as models,
the available misconception ids, the **grading traps** from memory (numeric answers reject fractions, so ask for
"as a decimal"; a `unit` answer needs the prompt to ask for the unit; sig-fig/tolerance choice; no "v =" in
answers; quick checks 0.5–2 min), Indian context (₹, km/h, neutral names), `g = 10 m/s²` or 9.8 stated in
the prompt, and "write only inside your concept folder; report proposed misconceptions". Each subagent runs strict check +
the pilot test for its concept until both are clean.

### 5. Top-ups of the existing concepts (me)
`distance-and-displacement`, `speed-and-velocity`, `acceleration`: +2 pool weight per KP (one new param quick
check each, new ids such as `kp1-q6`) and one new param `multistep` practice item each (`practice-2`). Prereqs and
existing items stay unchanged.

### 6. Read, fix, commit
I read every new concept file (YAML, Markdown, SVG), run strict check + pilot test, then make one commit per concept
(skeleton commit first; top-ups in one commit).

### 7. DB tests the physics content breaks (decision 11)
- `test_learn_api_db.py::test_physics_student_courses_and_outline` hard-codes `total == 4` and the outline
  order `[DIST, LIN, SPEED, ACCEL]`. Derive the expected total and order from `load(DEFAULT_CONTENT_ROOT)` (physics
  concepts plus the borrowed LIN), and keep the `LIN` before `SPEED` check. Update `ready` only if it changes
  (`forces-and-inertia` needs acceleration, so it won't be ready).
- `test_courses_api_db.py` physics graph already derives counts from the tree (PR 1).
- Run `make test-db` alone (shared DB) and fix any other test that relied on physics having 3 concepts
  (quiz/review/dashboard use the physics student), looking concepts up by id instead.

### 8. Self-review gate
- `cd backend && uv run app content check --root ../content --strict` → `content OK: 3 courses, 19 concepts…`,
  no warnings; `make check`; `make test-db`.
- Dev DB: `alembic current` (head), `make content-import ARGS=--dry-run` (new chapter/concepts/items), then
  `make content-import` twice (second: no changes).
- `make review-pack`; open `review-packs/physics-9-10.html` (file://); check KaTeX, SVGs, answers and print
  preview; screenshot one concept, or ask the user if Chrome can't open it.
- Independent AI review: a fresh `general-purpose` subagent gets only the pack path, the physics concept folders
  and the checklist in `docs/content-review.md`, and solves every item at seed 1. Fix its findings (one commit per
  chapter), then set the 8 physics rows to `ai-reviewed`, 2026-11-11, "spec 013 PR 2".
- `reviewer` subagent on the diff vs the spec, then `/ship`.

## Verification
- `cd backend && uv run pytest tests/test_pilot_content.py tests/test_content_validate.py tests/test_content_review_pack.py`
- `cd backend && uv run mypy`; `make check`; `make test-db`
- Strict content check clean; content import is idempotent on the dev DB
- `review-packs/physics-9-10.html` inspected
- Browser check by the user (Chrome can't reach localhost): as a physics student, open one new concept (Learn →
  KP → practice multistep); check the physics knowledge graph shows 8 nodes over 2 chapters at desktop and phone width; as a
  teacher, check the placement chapter list and the assignment dialog show "Force and laws of motion".
