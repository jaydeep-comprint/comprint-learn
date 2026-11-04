# Plan: implement spec 006 (practice formats)

Spec: `docs/specs/006-practice-formats.md` · Branch: `feat/006-practice-formats` (new, from `main`). The first commit
holds the spec and the PRD change that are currently uncommitted.

## Context
005 shipped the KP flow, but it serves only numeric, expression and MCQ items, and numeric answers have no unit box.
006 makes every format work end to end:
- units on numeric answers (converted and graded in the student's unit);
- multi-step problems answered one step at a time;
- Python tasks run in Pyodide in the browser, with hidden expected values checked on the server;
- code and multi-step items in KP pools;
- a required **Practice** step that gates "learned".

The spec already has a full technical design. This plan orders the work, names what to reuse, and settles the details
the spec leaves open.

What exploration found:
- No sample KP pool holds a multi-step item yet. Every Python KP has one fixed code item. Each of the 9 sample concepts
  has exactly one practice item: 6 multi-step (physics and maths) and 3 code (Python).
- The code item's `public` has no `time_limit_ms` and no hidden-test inputs (`hashing.split_item`).
- `units.py` has no aliases and no conversion. A space between units (`km h^-1`) doesn't parse today.
- The harness's `same` lives in a string run by `python -I` (`content/code_runner.py:29`), so it can't import `app`.
- The frontend has no worker, no CodeMirror and no CSP. jsdom has no `Worker`.

## Decisions on details the spec leaves open
1. **int/float fidelity across JS.** `JSON.parse` turns `2.0` into `2`, which would break the `1` vs `1.0` type
   strictness and change the args passed to Python.
   - Code test `args` and visible `expected` go to the client as **JSON text** (`json.dumps` on the server). The
     worker reads them with Python's `json.loads`.
   - The worker returns `{"json": "<json.dumps(got, allow_nan=False)>"}`. The server parses that text with Python and
     stores `{"value": <parsed>}`, so the stored shape matches the spec.
   - A value that can't be serialised comes back as `{"error": "returned a value that can't be compared"}`.
2. **One ordered `tests[]` list** in the code question instead of separate `visible_tests` / `hidden_inputs`. Each
   entry is `{visible, args, stdin?, expected?, expected_stdout?}` in authored order, and the `expected*` fields
   appear on visible tests only. `outputs[i]` then lines up with authored test `i` with no index mapping. The spec's
   API section gets updated to match.
3. **Hidden inputs and `time_limit_ms` are built from `item.answer.spec`** in the question builder, keeping only
   `args`/`stdin`. `split_item` (and so the content hashes) stays unchanged. A JSON-key-walk test proves no
   `expected`/`expected_stdout` leaks.
4. **One `compare` source.**
   - `app/grading/code.py` defines `same(a, b)` and `lines(text)` using only the stdlib.
   - `code_runner.HARNESS` splices in `inspect.getsource(same)` and `inspect.getsource(lines)`.
   - The bool loophole is fixed in both places at once: `True` no longer matches `1.0` (the spec asks for strict
     `1` / `True` / `1.0`).
   - The worker's **Run** ✓/✗ needs the same rule in the browser. A copy lives in `frontend/src/features/code/compare.py`
     (imported `?raw`), and a backend test asserts its function bodies equal the backend source.
5. **`code_runner.run_outputs(spec, source)`** (new): the harness also records each test's output in the client
   shape. Tests use it to produce honest outputs from the reference solution (the spec's `grade_code` test, and
   `learn_helpers.response_for` for code items now that Python KP sessions serve them).
6. **Unit conversion.**
   - `convert_factor(student, authored)` is `sympy.physics.units.convert_to(parse(student) / parse(authored), SI
     base units)`. A pure number is the factor `f`; anything else means a wrong dimension.
   - The quantity name comes from `dimsys_SI.get_dimensional_dependencies(...)`, matched against a small map
     (length, time, mass, speed, acceleration, force, energy, power, pressure, frequency, voltage, current,
     resistance, charge, temperature, volume).
   - `v' = v / f` uses `sympy.Rational`. In exact mode, "finite decimal" means the reduced denominator has only the
     prime factors 2 and 5. Otherwise `v'` goes to `Decimal` at 60 digits, as `to_decimal` does.
7. **Multi-step results inside a session.**
   - `attempt.correct` on each step row is that step's result.
   - The item result per position is computed: `multistep_outcome` over that position's step rows.
   - A single helper, `_position_results(attempts, items)`, replaces the `[a.correct for a in …]` lists at
     `kp_flow.py:359/441/530/914`, so `kp_outcome`/`review_outcome` and the dots see one bool per item.
   - The current step is the count of step rows at `current_position`. `body.step` must equal it, or the API returns
     409 `step_order`, or the stored result for a step already answered.
   - Only after the last step does the session move on (`_serve`) or end.
8. **Practise again** (a learned student): `GET …/practice/question?again=1` takes the staff path (a random item and
   `preview_seed`), and the POST with `item_id`/`seed` writes nothing. Without `again`, a learned student gets 409
   `practice_passed`.
9. **Relearn after a failed review** resets KPs only. The earlier passed practice session still counts, as the
   spec's rule says literally ("has a passed practice session"). Noted in ARCHITECTURE.
10. **Pyodide loading.**
    - A module worker loads `https://cdn.jsdelivr.net/pyodide/v<PINNED>/full/pyodide.mjs` with a dynamic `import()`
      (`/* @vite-ignore */`).
    - Before implementing, I'll check the pinned version on jsDelivr and confirm it is at least 2 weeks old. It goes in
      one constant, `PYODIDE_VERSION`.
    - The progress bar is staged (script loaded, runtime ready, environment set up) because `loadPyodide` doesn't
      report bytes.
    - Before user code runs, the worker removes `js`, `pyodide`, `pyodide_js` and `micropip` from `sys.modules` and
      installs a `sys.meta_path` finder that raises "That module isn't available here".
11. **Dependencies.** `codemirror`, `@codemirror/lang-python`, `@codemirror/state` and `@codemirror/view`, at exact
    versions checked with `pnpm view <pkg> time` to be at least 2 weeks old. The backend gets none.

## Phase 1: pure grading (no DB)
- **`app/grading/units.py`**:
  - `normalise(text)`: the alias table, `²`/`³` to `^2`/`^3`, `·` and spaces between units to `*`, case-sensitive.
  - `parse_student_unit` (normalise, then `content.units.parse_unit`).
  - `convert_factor`, `quantity_name`.
  - `content/units.py` exports what these need.
- **`app/grading/numeric.py`**:
  - `grade_numeric(spec, values, response, unit=None)` adds the unit branch, with the notes "Add a unit, e.g. …",
    "Couldn't read that unit", "That unit doesn't measure …" and "Give it in …".
  - Sig figs are counted on what the student typed. `display_answer` stays in the authored unit.
- **`app/grading/multistep.py`**:
  - `grade_step(answer, i, values, response, unit, shown)` reuses `grade`, taking the step's spec from
    `answer.spec.steps[i]`.
  - `multistep_outcome(results)` is true when at least ceil(0.75·n) steps are correct and the last step is correct.
  - MCQ steps get `ShownOptions` from `public.steps[i].options`, shuffled with the same per-student seed as items,
    using `(item.id, i)` as the key.
- **`app/grading/code.py`**:
  - `same`, `lines`, `compare(test, output)`.
  - `grade_code(answer, outputs) -> CodeGrade{correct, per_test}`, which also caps and validates the outputs.
- **`app/grading/__init__.py`**: dispatch with `unit`. `GRADABLE_TYPES` becomes `QUICK_TYPES` (numeric, expression,
  MCQ: used for reviews) plus `ALL_TYPES`.
- **`content/code_runner.py`**: splice in the shared `same`/`lines`, and add `run_outputs`.
- **Tests**:
  - `tests/test_grading_units.py`, `tests/test_grading_multistep.py` and `tests/test_grading_code.py`, covering every
    case in the spec's Verification list. That includes "every sample multi-step item passes with its own answers
    over 20 seeds" and "the reference solution's outputs pass", both run offline through the content loader.
  - The existing `test_content_code_runner.py` stays green, plus a new bool-vs-float case.

## Phase 2: content validator and docs for content
- **`app/content/validate.py`**:
  - Each KP needs at least 1 numeric/expression/MCQ item (error).
  - The "≥ 2 gradable" rule now counts every type, and its message drops "until spec 006".
  - Code items need `time_limit_ms` ≤ 5000.
  - Authored units must parse through the student normaliser too.
- **`tests/content_fixtures.py`**: add a `code_item` fixture. Update `test_content_validate.py`: the three 005 message
  assertions, plus the new rules.
- **`content/README.md`**: units and aliases, multi-step/code in KP pools, the review-pool rule, and the note that
  hidden-test inputs (never expected values) now reach the client.
- `make content-check` stays green on the sample.

## Phase 3: data model and migration `0006_practice_formats.py`
- **`app/models/learning.py`**:
  - New enum values: `AttemptContext.practice` and `SessionKind.practice`.
  - `PracticeSession.concept_id`: content FK, the extended `kind_links` CHECK, and the partial unique
    `uq_practice_session_active_practice (student_id, concept_id) WHERE status='active' AND kind='practice'`.
  - `Attempt.step smallint not null default 0`, and `uq_attempt_session_id_position_step` replacing
    `uq_attempt_session_id_position`.
  - The context CHECK now includes `practice`.
- **Migration** in the style of 0005:
  - Enum `ADD VALUE` inside `autocommit_block()`.
  - Downgrade deletes the practice rows, restores the constraints and recreates the enum types (the 0005 pattern).
  - RLS is unchanged: no new tables.
- **Tests**: `test_migrations_db.py` round-trips 0006, and the models still match.

## Phase 4: backend services and API
- **`app/schemas/kp.py`**:
  - `QuestionPublic.type` covers all five types, with `unit_required`.
  - Multi-step adds `steps[]`, `step` and `step_results[]`.
  - Code adds `code{entry, starter, prefill, time_limit_ms, tests[]}`.
  - `AnswerIn` adds `unit`, `step`, `code` and `outputs`. `response` defaults to `""`.
  - `AnswerResult` adds `step_result`, `item_done`, `tests[]` and `solution`.
  - Size checks: 422 `invalid_response` (oversized fields, or the wrong output count) and 422 `invalid_unit_field`.
- **`app/services/kp_flow.py`**:
  - `_pool(scope, kp_id, types)`: KP sessions use every type, reviews only the quick types.
  - `_question` builds the multi-step steps (prompts rendered with the attempt's values) and the code block.
  - `_answer_in_session` branches by type: one row per step for multi-step, a code row with
    `response={code, outputs, verdicts}`.
  - `_stored_result` handles steps and code.
  - The conflict target is `(session_id, position, step)`.
  - Retired mid-session: re-serve at the same position and drop that position's step rows.
  - `solution` is returned for code in KP sessions.
- **`app/services/practice.py`** (new):
  - `practice_question` and `practice_answer`, reusing `_serve`, `_question` and `_answer_in_session` with
    `judge = lambda r: "passed"/"failed"` on the single item.
  - Gates: `practice_locked`, `practice_passed` and `again`.
  - The code-retry rule: the same item, with `prefill` set to the last submitted code.
  - Multi-step retries call `choose_next_item` over the concept's practice items, ordered by `(student, concept)`.
  - `_on_practice_passed` calls `frontier.mark_learned` and computes unlocked concepts, as `_on_kp_passed` does.
    Factor the shared "learned → unlocked" tail into one helper.
  - `solution` only after a pass.
  - Staff and `again` previews write nothing.
- **`app/services/frontier.py`**:
  - `load()` adds 2 queries: concepts with an active practice item, and concepts with a passed practice session.
  - `ConceptView.practice` is `none`, `pending` or `passed`, plus `parts_passed` and `parts_total`.
  - `next_part`: the first KP not passed, else `practice` if it's pending.
  - Promote-on-read requires practice.
  - `_on_kp_passed` no longer marks a concept learned while practice is pending.
- **`app/services/learn.py`**:
  - `lesson_steps(..., has_practice)` appends `practice`.
  - `Lesson.practice{status, active}`.
  - `record_progress` logs the `practice` step as `StudyActivity.practice`.
  - Home and outline get `parts_passed` / `parts_total`, and home lists "Practice left" concepts under in progress.
- **`app/api/v1/kp.py`**: `GET/POST /concepts/{course}/{concept}/practice/question|answer` on `Scope`. The
  route-scoping test needs no new exemptions.
- **Tests**:
  - New `tests/test_practice_api_db.py`, covering everything in the spec's list.
  - `learn_helpers`: `response_for` for multi-step steps and code (outputs via `run_outputs`), `answer_practice`, and
    `learn_concept` that also passes Practice.
  - Update `test_kp_api_db.py` and `test_learn_api_db.py` (learned needs practice, steps end with `practice`).
  - Python KP sessions now serve code items, so check those tests still pick answers through the helper.

## Phase 5: frontend
- **Dependencies**: CodeMirror (decision 11). Add `/// <reference lib="webworker" />` in the worker file.
- **`src/features/code/`**:
  - `pyodideWorker.ts`: `load`, `run {code, entry, tests, time_limit_ms}`, then `progress` and `result`. It handles
    the import blocker, the 10,000-character cap with "(output truncated)", JSON-text outputs and `compare.py` for
    Run.
  - `usePython.ts`: `status` (`loading(stage)`, `ready`, `error`), `run(tests)`, a per-test watchdog that terminates
    the worker, marks `timeout` on the rest and restarts it, and `retry()`. The `Worker` factory can be injected so
    tests can swap it.
  - `CodeEditor.tsx`: CodeMirror 6 (Python, line numbers, indent, Ctrl/Cmd+Enter, Esc-then-Tab hint).
  - `CodeQuestion.tsx`: Run, Submit, the results panel (hidden rows never show expected), the phone tip, and the
    load error with Retry.
- **`src/features/learn/`**:
  - `unitPreview.ts`: the same alias table, display only.
  - `UnitInput.tsx`. `NumericInput` gets the unit box when `unit_required`.
  - `MultistepQuestion.tsx`: the stem, finished steps, "Step k of n" and the final summary.
  - `PracticeStep.tsx`:
    - pass → `LearnedScreen`;
    - fail → Try again (code keeps the editor);
    - learned → "Passed ✓" plus Practise again (`again=1`).
- **Edits**:
  - `QuestionStep.tsx`: explicit dispatch; the answer becomes a typed body instead of a string.
  - `PracticeRunner.tsx`: step-aware submit. A multi-step position stays until `item_done`.
  - `api.ts` and `lib/types.ts`: the new shapes, `AnswerBody` with unit/step/code/outputs, and the practice
    hooks/keys.
  - `LessonPage.tsx`: the practice step, gating (locked until every KP passes), removing "Finish lesson", and the
    `initialIndex` resume at `practice`.
  - `StepIndicator.tsx`: a `Practice` label with ✓.
  - `StudentHome.tsx`, `CoursePage.tsx`, `graph/mastery.ts`, `ConceptNode.tsx` and `ConceptPanel.tsx` use
    `parts_*`. `RemediationPage` keeps working through `PracticeRunner`.
- **Tests (vitest)**: every item in the spec's frontend list, plus the `usePython` watchdog with a fake worker.
  Update `inputs.test.tsx`, `pages.test.tsx`, `StudentHome.test.tsx` and `mastery.test.ts` for the new fields.

## Phase 6: docs and review
- **`docs/ARCHITECTURE.md`**:
  - the learned rule with practice;
  - `practice_session` kind `practice` / `concept_id`;
  - `attempt.step`;
  - decision 6 refined;
  - the JSON-text detail;
  - Pyodide in the stack table.
- **The spec**: status → implemented, and the API note for decision 2.
- Run the `reviewer` subagent against the spec (plus `security-reviewer` for the hidden-test and outputs path), fix
  what they find, then `/ship`.

## Verification
- **Each phase:** `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, and `make check`. Show the output.
- **Single files:** `cd backend && uv run pytest tests/test_grading_units.py tests/test_grading_multistep.py tests/test_grading_code.py`.
- **Database:** `make test-db` (needs `TEST_DATABASE_URL`) for `test_practice_api_db.py`, the updated KP/learn tests,
  RLS, and the migration round-trip.
- **Manual:** `make migrate && make content-import && make dev`, then the spec's manual script:
  - physics `0.5 km` / `5 s`, and the speed-and-velocity practice passing 3 of 4;
  - Python `loops`: load, Run, an infinite loop, a failing hidden test, then a pass;
  - a 375 px phone;
  - a teacher preview writing no rows.

  Use the `run` / claude-in-chrome skills for screenshots and paste the notes.
