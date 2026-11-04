# Spec 006: Practice formats

Status: draft
PRD link: docs/PRD.md#mvp-scope-v1 (item 4; Phase 1 of docs/ROADMAP.md)
Builds on: [spec 005](005-kp-flow-knowledge-graph.md) (KP flow, graders for numeric / expression / MCQ, `practice_session`).

## Summary
Every practice format now works end to end:
- Numeric answers take a **unit**: any dimensionally correct unit is accepted and converted.
- **Multi-step problems** are answered one step at a time.
- **Python tasks** run in the browser (Pyodide in a Web Worker, CodeMirror editor). Hidden tests are checked by
  the server without their expected values ever leaving it.
- Code and multi-step items join the KP question pools.
- Each lesson ends with a required **Practice** step (one multi-step problem or implementation). A concept is
  *learned* only when every KP is passed **and** its practice is passed.

## User stories
- As a physics student, I want to give an answer with its unit (and get credit for 0.5 km when the book says
  500 m), so units become part of my answer, not decoration.
- As a student, I want long problems broken into steps, with the right value shown after each step, so one slip
  doesn't wreck the rest of the problem.
- As a Python student, I want to write real code in the browser, run it against examples as often as I like, and
  submit when I'm ready.
- As a student, I want each concept to end with a real problem or implementation, so "learned" means I can apply
  it, not just answer short questions.
- As a teacher, I want to preview these formats without anything being stored.
- As our team, I want every step answer, unit, submitted code and test result stored (decision 16), so 008 can
  award the most XP for implementations and 010 can show where students struggle.

## Behaviour

### Numeric answers with units (all numeric items and numeric steps)
- When the answer spec has a `unit`, the input is a **number box plus a unit box**; with no `unit`, it's the
  number box only (as in 005). The number rules from 005 are unchanged: accepted forms, notes, `,` rejected, and
  the 200-character limit.
- **Unit parsing** (server side): free text up to 40 characters, through `app.content.units.parse_unit` plus an
  alias table:
  - Aliases: `kmph`, `kph`, `km/hr` → `km/h`; `mps` → `m/s`; `sec`, `secs` → `s`; `hr`, `hrs` → `h`; `kgs` → `kg`;
    `Ω` → `ohm`.
  - Unicode `²`/`³` become `^2`/`^3`; `·` and a space between units become `*`. Matching is case-sensitive, so `N`
    and `n` differ and `ms` is milliseconds.
- **Grading in the student's unit**: let `f` be the factor from the student's unit to the authored unit.
  - If `f` isn't a pure number (wrong dimension) → wrong, note "That unit doesn't measure {quantity}". The
    quantity name comes from the authored unit's dimension (speed, length, time, mass, force, …), else
    "that quantity".
  - If the unit box is empty → wrong, note "Add a unit, e.g. {authored unit}". An unparseable unit → wrong, note
    "Couldn't read that unit".
  - Otherwise the answer is converted into the student's unit, `v' = v / f`, and the 005 mode is applied to
    (input, `v'`). Sig figs are counted on what the student typed.
  - **Example**: answer 26.67 km/h at 3 s.f. In m/s, `v' = 26.67 ÷ 3.6 = 7.4083…`, which rounds to `7.41`. So
    `7.41 m/s` is correct, `7.40 m/s` is wrong, and `7.4 m/s` is wrong with "Give 3 significant figures".
  - In `exact` mode, if `v'` isn't a finite decimal in the student's unit → wrong, note
    "Give it in {authored unit}".
- `display_answer` stays the value in the authored unit (`26.7 km/h`).
- Stored `response`: `{"raw": "<number>", "unit": "<unit text>"}`.

### Multi-step problems (practice items, and KP-pool items of type `multistep`)
- One item, steps 2–10, shown **one step at a time**: the problem stem (rendered with this attempt's params),
  the steps answered so far with their results, and the current step's prompt and input. Each step is numeric
  (with a unit box when it has a unit), expression or MCQ, graded by the 005/006 graders.
- **One try per step.** After each step: correct / not quite, the correct value for these numbers, and any note.
  The next step then appears; the problem continues with the correct values (step prompts never depend on the
  student's answers).
- **Item result**: correct when at least `ceil(0.75 × steps)` steps are correct **and** the last step is correct.
  So 2 steps need both; 4 steps need 3 including the last.
- The item's explanation is shown after the last step.
- Each step answer is its own `attempt` row (the same `session_id` and `position`, with `step` = 0..n-1). A
  reload resumes at the first unanswered step with the same seed.
- In a KP session a multi-step item counts as **one** question toward the 2-right / 3-wrong / 5-question rule,
  using the item result.

### Python code questions (KP-pool items and practice items of type `code`)
- **Editor**: CodeMirror 6 with Python highlighting, line numbers and auto-indent. It starts from `starter`; for
  a retried practice task, it starts from the student's last submitted code.
- **Run** (unlimited, never graded or stored): runs the code against the **visible tests** in the browser and
  shows, per test, the input, the expected value and what came back (or the printed output, or the error).
- **Submit** (the graded answer; one per question):
  1. The browser runs the code against every visible test and every **hidden test's input**.
  2. It sends the code and all the outputs.
  3. The server compares every output with the expected values it keeps, using the same comparison as the
     validator's harness: floats close (rel 1e-9 / abs 1e-12), lists and dicts deep, other values same type and
     equal; stdout tests compare lines with trailing spaces stripped.
  - **Correct = every test passes.**
  - The server never trusts the client's own pass/fail. It doesn't run the code: there's no sandbox (decision
    6; a server sandbox is v2).
- **Hidden tests**:
  - The question sends their `args` / `stdin` only. `expected` / `expected_stdout` never reach the client, not
    even after the answer.
  - After Submit, a hidden test shows its input and what the code returned, plus pass/fail. A failing hidden test
    shows "Your result differs from the expected one".
- **Runtime limits** (in the worker):
  - Each test gets the item's `time_limit_ms` (default 2000). Over the limit → the worker is terminated and
    restarted, and that test and any not yet run are reported as `timeout`.
  - Output is capped at 10,000 characters per test.
  - Imports of `js`, `pyodide`, `pyodide_js` and `micropip` raise "That module isn't available here"; the
    standard library is otherwise available.
  - A return value that can't be serialized to JSON (tuples become lists) → that test fails with "returned
    a value that can't be compared".
- **Code size**: at most 20,000 characters (more → 422 `invalid_response`).
- **After Submit in a KP session**: per-test results, then the **reference solution** and the explanation (the
  005 rule: the next question is always another item).
- **After a failed Submit in Practice**: per-test results only, with **no reference solution**. The student fixes
  the code and submits again (see Practice). The solution and explanation appear once the task is passed.
- Stored `response`: `{"code": "<source>", "outputs": [...]}` with one entry per test in authored order
  (`{"value": …}` | `{"stdout": "…"}` | `{"error": "…"}` | `{"timeout": true}`), plus the server's per-test
  verdicts.

### KP pools now serve every format
- The 005 serving rules apply unchanged to **all** active `kp_question` items: numeric, expression, MCQ,
  multistep and code. Code items are fixed (no params), so they follow the "fixed items never repeat within a
  session" rule.
- **Remediation reviews** (005) keep drawing only numeric / expression / MCQ items (quick checks). A KP with
  none of these is skipped in the review round-robin.

### The Practice step (new, required)
- **Steps**: `intro` → `check` → (`kp:<slug>` → `kpq:<slug>`)… → **`practice`**. The `practice` step is added
  only when the concept has at least one active practice item.
- **Order**: Practice opens only when every active KP is passed (409 `practice_locked` otherwise). The step
  indicator shows `Practice` (✓ when passed).
- **Attempt**: one practice item per attempt (a `practice_session` of kind `practice`).
  - The item is chosen with 005's `choose_next_item` over the concept's active practice items (pool order
    seeded by student × concept), with a fresh seed for param items.
  - A multi-step item is answered step by step; a code item takes one Submit.
  - The session passes or fails with the item result.
- **Pass** → the concept becomes **learned** (`concept_state`, `source = lesson`) and the learned screen shows
  what it unlocked.
- **Fail** → the answers / test results are shown, then **Try again** starts a new attempt immediately: no
  cooldown, no remediation, no limit.
  - After a failed **code** task, the next attempt serves the **same item**, with the editor prefilled from the
    last submission.
  - After a failed **multi-step** problem, the next attempt draws the next item, or the same one with new
    numbers if there's only one.
- **Learned rule (replaces 005's)**: a concept is learned when every active KP is passed **and** (it has no
  active practice item **or** the student has a passed practice session for it).
  - Concepts already learned stay learned (no un-learning, as in 005 when content adds a KP).
  - A concept whose last KP is passed but whose practice isn't stays **in progress**. Its next "part" is
    Practice.
- **Progress**: practice counts as one extra part. The home, the outline and the map show
  "parts passed / parts" = KPs passed + practice passed out of KPs + 1 (when the concept has practice). The
  map's mastery shade uses the same fraction.
- **Time**: the `practice` step logs `study_time` with activity `practice`.

### Staff preview
- Every format is answerable by staff:
  - GET returns a random item and seed with `preview_seed`.
  - POST takes `item_id` / `seed` (and `step` for multi-step) and returns the full result.
  - The practice step opens with no KP gate.
- Nothing is written. Code runs in the teacher's browser the same way.

### Access and errors
- As in 005: `OrgScope` on every route, 404 outside the student's courses, and 403 `concept_locked`.
- New errors:
  - 409 `practice_locked`: KPs not all passed.
  - 409 `practice_passed`: already passed. A learned concept opens Practice in review mode with "Passed ✓".
  - 409 `step_order`: a step answered before the previous one.
  - 422 `invalid_response`: oversized code, unit or outputs, or output count ≠ test count.
  - 422 `invalid_unit_field`: a unit sent for a unitless answer.

## UI / UX
Builds on the 005 lesson components; existing shell, shadcn/ui, Tailwind, mobile first.

- **Numeric with unit**: `[ number ] [ unit ]` side by side (the unit box is ~8rem, placeholder = authored unit's
  kind, e.g. "unit, e.g. m/s"), `inputmode="decimal"` on the number, a plain text keyboard on the unit. Under
  the unit box, a live "Read as: m·s⁻¹" preview rendered client side from the same alias table (display only; the
  server decides).
- **Multi-step**: the stem at the top; completed steps as a compact list ("Step 1 ✓ 1.25 h" / "Step 2 ✗ Answer:
  2.50 h"), then the current step with its input and Submit. Header "Step 2 of 4". After the last step: "Problem
  solved ✓" / "Not quite: 2 of 4 steps" plus the explanation. In a KP session the 005 dots show one dot per item.
- **Code**:
  - **Layout**: the prompt on top, then the editor (~16 lines on desktop, resizable), then a toolbar with
    **Run** and **Submit**, then the results panel.
  - **Results panel**: one row per test (✓ / ✗ / ⏱). Visible rows show input, expected and got; hidden rows show
    "Hidden test k", input and got.
  - **Loading**: the first time a code step opens, "Loading Python…" with a progress bar while Pyodide downloads
    (a pinned version from cdn.jsdelivr.net, then browser cached). Run and Submit stay disabled until it's ready.
  - **Errors**: a download failure shows "Couldn't load Python. Check your connection" with Retry.
  - **Phones**: below 768 px, a tip "Easier on a computer or tablet"; nothing is blocked.
  - **Feedback**: Submit shows a spinner while tests run, then while the server checks. Infinite loops show "Took
    too long (over 2 s)" on that test, and the editor stays usable.
  - **Keyboard**: Ctrl/Cmd+Enter runs; the editor traps Tab for indenting, and Esc then Tab leaves it (CodeMirror
    default), which the hint below the editor explains.
- **Practice step**:
  - **Header**: "Practice · {problem title or 'Put it together'}".
  - **On pass**: "Practice passed ✓", then the learned screen.
  - **On fail**: the result, then **Try again** (code: "Fix your code and submit again", with the editor kept).
  - **Learned concepts**: Practice shows "Passed ✓" plus **Practise again**, which opens a fresh, unscored
    preview-style attempt. That writes nothing; it's re-practice without affecting state.
- **Lesson navigation**: Next on the last `kpq` step moves to Practice; "Finish lesson" is replaced by the
  Practice pass. The step indicator gains `Practice` with a ✓.
- **Home / outline / map**: "N of M parts" now includes Practice. Concepts with all KPs passed but practice
  pending are listed under In progress ("Practice left").

## Technical design
- **Files / modules touched:**
  - **Backend (new):**
    - `app/grading/units.py`: alias normalisation; `convert_factor(student_unit, authored_unit)`; the
      dimension → quantity name map.
    - `app/grading/multistep.py`: per-step grading via the existing graders; `multistep_outcome(step_results)`.
    - `app/grading/code.py`: `compare(expected_test, output)` (the harness `same` logic moved into a shared pure
      function, also used by `app/content/code_runner.py`'s harness) and
      `grade_code(answer_doc, outputs) -> CodeGrade{correct, per_test}`.
    - `app/services/practice.py`: practice step services (`practice_question`, `practice_answer`), item choice,
      code-retry rule, `_on_practice_passed`.
  - **Backend (edit):**
    - `app/grading/numeric.py` (unit-aware grade, `GradeResult` gains per-type fields); `app/grading/__init__.py`
      (dispatch for multistep / code); `app/content/units.py` (export `UNITS` dimension helpers).
    - `app/services/kp_flow.py`:
      - Pools include all types; reviews stay on numeric / expression / MCQ.
      - Multi-step positions with steps.
      - The code answer path.
      - The `_question` builder for multi-step steps / code (public parts only) and hidden inputs.
    - `app/services/frontier.py`: the learned rule with practice; `KpView` unchanged; `ConceptView.practice:
      "none" | "pending" | "passed"`; the parts fraction.
    - `app/services/learn.py`: the `practice` step in `lesson_steps`, `practice` study time, and lesson/outline
      fields.
    - `app/schemas/kp.py`, `app/schemas/learn.py`, `app/api/v1/kp.py` (practice routes).
    - `app/content/validate.py`:
      - Every KP needs ≥ 1 numeric / expression / MCQ item, for reviews (error).
      - The 005 "≥ 2 gradable" rule now counts every type.
      - Code items' `time_limit_ms` must be ≤ 5000 for the browser.
    - `app/content/code_runner.py`: import the shared `compare`.
  - **Frontend (new):**
    - `src/features/code/pyodideWorker.ts`: a Web Worker that loads a pinned Pyodide from jsDelivr. Its messages
      are `run {code, entry, tests[{args, stdin}], time_limit_ms}` → `progress` per test and
      `result {outputs[]}`; it blocks banned imports via a meta-path hook.
    - `src/features/code/usePython.ts`: worker lifecycle, a per-test watchdog that terminates on timeout, and
      restart.
    - `src/features/code/CodeEditor.tsx`: CodeMirror 6.
    - `src/features/code/CodeQuestion.tsx`: Run / Submit and the results panel.
    - `src/features/learn/UnitInput.tsx` + `unitPreview.ts`, `src/features/learn/MultistepQuestion.tsx`,
      `src/features/learn/PracticeStep.tsx`.
  - **Frontend (edit):**
    - `QuestionStep.tsx` (dispatch by type), `NumericInput.tsx` (unit box), `PracticeRunner.tsx` (multi-step
      steps, code submit).
    - `LessonPage.tsx` / `StepIndicator.tsx` (the practice step), `StudentHome.tsx` / `CoursePage.tsx` /
      `graph/*` (parts with practice).
    - `api.ts`, `lib/types.ts`.
  - **Dependencies**:
    - Frontend: `codemirror`, `@codemirror/lang-python` and `@codemirror/state` / `view`, via `pnpm add`, at
      exact versions at least 2 weeks old.
    - Pyodide isn't an npm dependency: it's loaded from jsDelivr at a pinned version recorded in one constant.
    - Backend: none (SymPy units are already in).
  - **Docs**:
    - `docs/ARCHITECTURE.md`: the learned rule with practice; `practice_session` kind `practice`;
      `attempt.step`; decision 6 refined (the client runs code, the server compares hidden expected values).
    - `content/README.md`: units in answers and aliases; multistep / code in KP pools; the review-pool rule.
- **Data model changes** (`0006_practice_formats.py`; enum values added in an autocommit block, as in 0005):
  - Enums: `attempt_context` + `practice`; `session_kind` + `practice`.
  - `practice_session`:
    - New column `concept_id uuid null` (FK → `concept`).
    - The `kind_links` check is extended: kp ↔ `kp_id`, remediation ↔ `remediation_id`, practice ↔
      `concept_id`.
    - New partial unique `(student_id, concept_id) WHERE status = 'active' AND kind = 'practice'`.
  - `attempt`:
    - New column `step smallint not null default 0`.
    - The unique constraint `(session_id, position)` is replaced by `(session_id, position, step)`.
    - The context check becomes `(context IN ('kp','remediation','practice')) = (session_id IS NOT NULL)`.
  - No backfill is needed. Learned stays learned; in-progress concepts gain the Practice step.
- **API / interfaces** (under `/api/v1/learn`, `OrgScope` on all):
  - **`QuestionPublic`** (extended):
    - Numeric: `unit`, plus `unit_required: bool`.
    - Multi-step:
      - `steps[]`: `{prompt_md, type, unit, options, variables}`, rendered public parts only.
      - `step`: the current step index.
      - `step_results[]`: `{correct, display_answer, note}` for the steps already answered.
    - Code: `{entry, starter, prefill: str|null, time_limit_ms, visible_tests[{args, expected | stdin,
      expected_stdout}], hidden_inputs[{args | stdin}]}`.
  - **`AnswerIn`** (extended):
    - `unit: str | null` (≤ 40).
    - `step: int | null` (multi-step).
    - `code: str | null` (≤ 20,000).
    - `outputs: list[...] | null` (one per test, each ≤ 10,000 chars).
    - The existing `response` stays for numeric / expression / MCQ, and for each multi-step step.
  - **`AnswerResult`** (extended):
    - `step_result` / `item_done` for multi-step.
    - `tests[] {visible, passed, args | stdin, expected?, got}` for code: `expected` only on visible tests.
    - `solution: str | null`: code, in KP sessions, or after a practice pass.
  - **New routes**: `GET /concepts/{course}/{concept}/practice/question` and
    `POST /concepts/{course}/{concept}/practice/answer`, with the same shapes.
  - **Extended**: the KP and remediation question / answer routes accept the new formats.
  - **Lesson**: `steps` incl. `practice`, `practice: {status: none|pending|passed, active: bool}`.
  - **Outline and home**: concepts gain `parts_passed`, `parts_total`. `kps_passed` / `kps_total` are kept for
    the lesson.

## Edge cases
- **Duplicate submissions**: a double submit of a code answer, or of a multi-step step, is unique on
  `(session_id, position, step)`. One insert wins and the other gets `already_answered`.
- **A tab closed mid multi-step**: resumes at the next unanswered step, with the same seed and the steps answered
  so far.
- **Pyodide unavailable** (blocked CDN, offline): the code question shows the load error with Retry. The KP
  session waits; nothing counts as wrong, because no answer was submitted.
- **Worker crash or out-of-memory** during Submit: an "error" output for the remaining tests. The student can
  submit (graded wrong), or retry Run first; Submit is the commitment.
- **Faked outputs**: a student who crafts outputs by hand (devtools) can pass a code question. This is accepted
  for the MVP (decision 6); the stored code lets 010/v2 spot it.
- **Unit forms**:
  - `kmph`, `km/hr` and `km h^-1` all parse to km/h.
  - `ms` is milliseconds: `5 ms` for a speed → "That unit doesn't measure speed".
  - Unicode `m/s²` works.
- **Unitless answers**: if a unit is sent for an answer spec without one → 422 `invalid_unit_field` (the UI never
  shows the box).
- **Exact mode in another unit**: `8 m/s` as `28.8 km/h` is correct. `10 km/h` as `2.78 m/s` is wrong, with
  "Give it in km/h" (not a finite decimal).
- **Retired content**:
  - A retired practice item mid-session is replaced at the same position, with fresh numbers, on the next GET;
    multi-step steps answered so far are discarded with it.
  - If every practice item is retired, the concept has no practice: learned when its KPs pass (promoted on read).
- **Practice items added later**: a concept learned earlier stays learned. An in-progress concept gains the
  Practice step.
- **Retrying a code task after a fail**: same item, editor prefilled. A different code item is drawn only if
  that one is retired.
- **Huge output** or `print` in a loop: capped at 10,000 characters per test, marked "(output truncated)", and
  compared as truncated (so it fails).
- **Banned imports**: `import js` → that test errors "That module isn't available here".
- **Teachers**: staff answers write nothing, as in 005. "Practise again" on a learned concept writes nothing
  either.

## Out of scope
- XP of any kind, including implementation XP and practice-fail penalties (008), and reviews / FSRS / quizzes
  (007).
- A server-side code sandbox, and cheat-proof grading of code (v2, decision 6). Running tests on the server.
- Languages other than Python; packages beyond the standard library (`micropip`); file I/O tasks; `input()`-driven
  interactive programs beyond the `stdin` tests.
- Hints and the AI tutor on code (009). Partial credit inside a code task. A "Show solution" button before
  passing practice.
- Teacher views of submitted code, test failures or unit mistakes (010).
- Unit systems beyond `app/content/units.py` (no imperial units). Prefix arithmetic the parser doesn't support
  (e.g. `μs`) unless added to `UNITS`.
- Self-hosting Pyodide; offline / PWA.
- Free-response or AI-graded answers; drawing or graphing answers.

## Verification (end-to-end)
- [ ] `tests/test_grading_units.py` (pure):
  - Aliases (`kmph`, `km/hr`, `mps`, `sec`, `m/s²`, `m s^-1`).
  - Conversion grading: `7.41 m/s` for 26.67 km/h at 3 s.f. ✓; `7.4 m/s` ✗ with the note; `500 m` / `0.5 km` for
    500 m exact ✓.
  - Wrong dimension (`5 s` for a speed) ✗ with the quantity note; a missing unit ✗ "Add a unit".
  - `ms` read as milliseconds.
  - Exact mode in a unit where the value isn't a finite decimal ✗ "Give it in …".
- [ ] `tests/test_grading_multistep.py`:
  - `multistep_outcome` on all patterns for 2–5 steps (75% + last rule).
  - Step grading for numeric-with-unit, expression and MCQ steps.
  - Every sample multi-step item passes with its own answers over 20 seeds.
- [ ] `tests/test_grading_code.py`:
  - The `compare` semantics: float tolerance, nested lists / dicts, type strictness (`1` vs `True` vs `1.0`),
    stdout line compare.
  - `grade_code` with outputs from the reference solution (run through `code_runner`) passes for every sample
    code item.
  - A wrong output fails.
  - The output count must match.
  - Hidden `expected` values never appear in `QuestionPublic` or `AnswerResult`; a test walks the JSON keys.
- [ ] `tests/test_practice_api_db.py` (`-m db`, sample content):
  - Practice before the KPs pass → 409 `practice_locked`.
  - All KPs passed → the concept is in progress (not learned), and `practice.status = pending`.
  - Multi-step practice:
    - Step order enforced (409 `step_order`).
    - A reload resumes at the next step with the same prompt.
    - Pass with 3 of 4 including the last → learned, and the dependants unlock.
  - A failed multi-step → Try again draws new numbers.
  - Python concept:
    - A failed code practice → the next attempt is the same item, with `prefill` = the last code.
    - Passing outputs → learned.
    - The solution appears only after the pass.
  - KP sessions serve code and multi-step items:
    - A code KP answer with correct outputs counts as correct.
    - Concurrent double submits → one attempt.
  - Remediation reviews never serve code / multi-step.
  - Staff: practice and code / multi-step answers write no rows.
  - School B → 404 on school A sessions.
- [ ] `tests/test_kp_api_db.py` / `tests/test_learn_api_db.py` updated:
  - Learned now requires practice.
  - The `learn_concept` test helper also passes Practice.
  - Lesson steps end with `practice`.
- [ ] `tests/test_rls_db.py` and `test_migrations_db.py` (0006 round-trip; models match).
  `tests/test_route_scoping.py` passes with no new exemptions.
- [ ] `tests/test_content_validate.py`: a KP with only code items → error; `time_limit_ms` over 5000 → error.
  `make content-check` passes on the sample.
- [ ] Frontend vitest:
  - `unitPreview` alias parsing.
  - `NumericInput` with the unit box (and without it when the answer is unitless).
  - `MultistepQuestion`: one step at a time, results carried forward, the final summary.
  - `CodeQuestion`, with `usePython` mocked:
    - Run doesn't call the API.
    - Submit sends the code and outputs.
    - The results panel never shows an expected value for hidden tests.
    - Timeout and load-error states.
  - `PracticeStep`: pass → learned screen; fail → Try again (code keeps the editor content).
  - `LessonPage`: Next to Practice; Practice locked until the KPs pass.
- [ ] `usePython` watchdog test with a fake worker: a test that never reports is terminated after
  `time_limit_ms` and marked `timeout`, and the worker restarts.
- [ ] `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, `make check` and `make test-db` all green.
- [ ] Manual (paste notes + screenshots): `make migrate && make content-import && make dev`.
  - **Physics student at 1280 px**: a KP numeric question answered as `0.5 km` for 500 m → correct; `5 s` → "That
    unit doesn't measure length". Finish the KPs of speed-and-velocity → the Practice step: the multi-step
    round-trip problem, one step wrong, still passes 3 of 4 → "Concept learned".
  - **Python student**:
    - `loops`: Pyodide loads with a progress bar, then Run shows the visible tests.
    - An infinite loop shows "Took too long" and the editor still works.
    - A wrong Submit shows the failing hidden test with no expected value.
    - Fix it, Submit, pass → the solution is shown → learned.
  - **375 px phone**: the unit box and decimal keyboard; the code tip is shown and the editor is usable.
  - **Teacher**: preview a code question and a practice problem; no DB rows.
