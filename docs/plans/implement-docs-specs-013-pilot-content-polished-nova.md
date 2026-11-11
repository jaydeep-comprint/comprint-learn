# Plan: Spec 013, PR 3 (`feat/013-pilot-content-python`)

## Context
Spec 013 (`docs/specs/013-pilot-content.md`) grows each pilot course to 8 concepts. PR 1 (maths + tooling) and
PR 2 (physics, #17) are merged. This PR does **Python only**: a new chapter `functions-and-data` with 5 concepts,
top-ups to the 3 existing concepts, any DB tests the new content breaks, the self-review gate, and it marks
spec 013 as done. No code, engine or UI changes.

Authoring works like maths and physics did: I write `lists` as the model concept (`dictionaries` and
`list-algorithms` build on it, and it shows every Python item pattern), then one subagent per remaining concept
(4 in parallel). I read every file before committing it.

## Python-specific authoring rules (go in every brief)
- **Code items can't have params**, so a fixed code question adds 1 to the pool. Each KP reaches weight ≥ 10 mostly
  with param `numeric` "What does this program print?" items (answer expression with `floor`, `ceiling`, `%` …,
  as in `loops/concept.yaml`), plus 1–2 code questions (2–5 min) and at most 30% MCQ by count.
- **Params are numbers only.** String questions get variety from numeric params (an index, a slice bound, a count, a
  repeat) inside a fixed string; text output is an `mcq` or a small `code` task (no free-text type).
- Numeric answers: integers, or "as a decimal" when they might not be (fractions are rejected). No `unit`.
- Code tests: `{args, expected}` (JSON: lists, not tuples; dict keys come back as strings) or
  `{stdin?, expected_stdout}`; ≥ 3 tests with ≥ 1 visible, edge cases hidden (empty list/string, not found, ties);
  stdlib only; idiomatic beginner solutions (no comprehensions or lambdas unless the KP teaches them). Starters
  define `entry` and run without error.
- Practice: 2–3 `code` items (`create`/`apply`, 5–15 min). Quick checks 0.5–2 min. Every MCQ has a distractor tagged
  with a course misconception.
- Indian context (₹, marks, cricket scores, neutral first names or none), Class 9–10 reading level.
- Scan rendered prompts over 50 seeds (`review_pack.pack_data(seeds=50)`) for impossible values: index out of
  range, empty slices, `range` with no values.

## Steps

### 0. Branch
`git switch main && git pull` → `git switch -c feat/013-pilot-content-python`. `docs/drafts/` stays untracked.

### 1. Scope check (decision 5)
Python has no CBSE grade, so no syllabus search is needed. Check that each KP from the spec table stays inside the
spec's scope (no f-strings, files, classes, `input()` beyond simple stdin tests) and fits a beginner who knows only
`basics`.

### 2. Course skeleton (me)
- `content/python-basics/course.yaml`: `chapters: [basics, functions-and-data]`.
- New `02-functions-and-data/chapter.yaml` (title "Functions and data", no grade,
  `[functions, strings, lists, dictionaries, list-algorithms]`).
- `misconceptions.yaml`: add `index-starts-at-one`, `slice-includes-end`, `print-is-return`,
  `strings-are-mutable`, `append-returns-list`, `dict-key-vs-value` (student `title` + teacher `description`).
  Subagents report extra misconceptions; I add them so no two agents edit one file.
- `backend/tests/test_pilot_content.py`: `PILOT_COURSES` gains `"python-basics": 8` (fails until the content is done).

### 3. Model concept: `lists` (me)
Prereq loops 0.5. 4 KPs from the spec (creating and indexing · append/insert/remove/pop/len · looping to total or
build a new list · slicing and `in`); each pool weight ≥ 10, ≥ 2 quick checks, MCQ ≤ 30%; key prereq `loops` on the
looping KP; 2–3 code practice items; short intro, a worked example per KP. Iterate on
`cd backend && uv run app content check --root ../content --strict` and
`uv run pytest tests/test_pilot_content.py -k lists`, then the 50-seed scan.

### 4. Four concepts in parallel (subagents, `general-purpose`)
`functions`, `strings`, `dictionaries`, `list-algorithms`. Each brief: the spec table row (prereqs, weights, KPs),
the quality bar and minute bands, the rules above, `content/README.md`, `lists` and `loops` as models, the
misconception ids, "write only inside your concept folder; report proposed misconceptions; run strict check +
the pilot test for your concept until both are clean". `dictionaries` and `list-algorithms` depend on `lists`
only through prereqs, so they can run alongside.

### 5. Top-ups of the existing concepts (me)
`variables-and-types`, `conditionals`, `loops`: +2 pool weight per KP (one new param `numeric` quick check each,
ids `kp1-q6` …) and one new code practice item each (`practice-2`, 5–15 min). Prereqs and existing items unchanged.

### 6. Read, fix, commit
I read every new file, run strict check + pilot test, then commit: skeleton first, one commit per concept, top-ups
in one commit.

### 7. DB tests
- `test_practice_api_db.py` uses `python-basics/variables-and-types`; a failed code task is served again, so a 2nd
  practice item shouldn't break `test_code_practice_retry_prefill_then_pass`, but confirm. If any test assumes a
  single practice item, look the served item up instead (as PR 2 did for multistep retries).
- `test_courses_api_db.py` already derives counts from the tree.
- Run `make test-db` alone (shared, slow DB) and fix any test relying on Python having 3 concepts or 1 chapter by
  looking up by id.

### 8. Self-review gate and closing spec 013
- Strict check → `content OK: 3 courses, 24 concepts …`, no warnings; `cd backend && uv run mypy`; `make check`;
  `make test-db`.
- Dev DB: `alembic current` (head), `make content-import ARGS=--dry-run`, then `make content-import` twice (second:
  no changes).
- `make review-pack`; open `review-packs/python-basics.html` (code blocks, starters, solutions and hidden tests
  show; print preview); ask the user for a screenshot if Chrome can't open the file.
- Independent AI review: a fresh `general-purpose` subagent gets only the pack path, the Python concept folders and
  the checklist in `docs/content-review.md`; it solves every item at seed 1 and runs each solution against its
  tests mentally/with `python3`. Fix findings (one commit per chapter), then set the 8 Python rows to
  `ai-reviewed`, 2026-11-11, "spec 013 PR 3". All 24 rows are then `ai-reviewed`.
- Spec 013 `Status: done (Nov 2026)`; tick the verification boxes it now meets; ROADMAP 013 row marked done if
  the roadmap tracks status.
- Update the `content-authoring-grading-traps` memory with any new Python traps.
- `reviewer` subagent on the diff vs the spec, then `/ship`.

## Verification
- `cd backend && uv run pytest tests/test_pilot_content.py tests/test_content_validate.py tests/test_content_review_pack.py`
- `cd backend && uv run mypy`; `make check`; `make test-db`
- Strict content check clean for 24 concepts; content import idempotent on the dev DB
- `review-packs/python-basics.html` inspected
- Browser check by the user (Chrome can't reach localhost): as a Python student, open one new concept (Learn → KP
  questions incl. a code question → code practice task); the Python knowledge graph shows 8 nodes over 2 chapters
  at desktop and phone width; as a teacher, the assignment dialog shows "Functions and data".
