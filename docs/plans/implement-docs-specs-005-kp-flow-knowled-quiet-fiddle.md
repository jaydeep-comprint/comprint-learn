# Plan: implement spec 005 (KP flow + knowledge graph)

Spec: `docs/specs/005-kp-flow-knowledge-graph.md` · Branch: `feat/005-kp-flow-knowledge-graph` (already checked out, clean)

## Context
004 shipped the Learn layer (intro, check, worked examples), where "finished" gates the concepts that depend on it. 005 adds the
main practice loop:
- KP questions served one at a time and graded server side. 2 right in a row passes; 3 wrong or 5 without passing fails.
- Fail → reopen later. A second fail → remediation (review, then relearn).
- `concept_state` "learned" replaces "finished" as the frontier gate.
- A React Flow Map view.

The spec already has a full technical design. This plan orders the work, names what to reuse, and resolves the
implementation details the spec leaves open.

## Decisions on details the spec leaves open
1. **Enum values inside the migration.** Alembic runs each migration in a single transaction (`alembic/env.py:38`),
   and Postgres refuses to use a value that `ALTER TYPE … ADD VALUE` added in the same transaction. The new `attempt`
   CHECK (`context IN ('kp','remediation')`) uses those values, so the `ADD VALUE` statements must run inside
   `op.get_context().autocommit_block()`. Downgrade can't drop enum values, so it recreates the type (rename the old
   type, create the new one, alter the column `USING`, drop the old type). It must first delete any kp/remediation
   attempts, or refuse.
2. **Sampling from a DB row.** `params.sample()` takes the schema `Item`. Add `params.sample_answer(answer_doc, seed)`
   in `app/content/params.py`. It rebuilds the minimal schema object from `item.answer["params"|"constraints"|"derived"]`
   and calls `sample`, so `sample` stays the one implementation. Fixed items get `{}` values.
3. **Parsing student input.** `params.parse` gains a `max_exponent` keyword (default stays 1000). Grading passes 100
   and a 200-character limit, as the spec requires.
4. **The 1 s simplify budget.** A SymPy thread can't be interrupted, and signals only work in the main thread.
   - `app/grading/expression.py` runs `simplify`/`count_ops` in a module-level single-worker `ProcessPoolExecutor`
     with `future.result(timeout=1)`.
   - On timeout the pool is shut down (`cancel_futures`, kill the worker) and recreated lazily. The answer then goes
     to the numeric fallback: 5 random points per variable, tolerance 1e-9.
   - Grading is called through `asyncio.to_thread` so the event loop never blocks.
5. **Rounding.** Numeric grading uses `decimal.Decimal` with `ROUND_HALF_UP`, so s.f. counting and rounding are exact.
   `display_answer` formats the value to the spec's sigfigs (or `format_number`), and in `×10^n` form when
   `sci_notation` is set. The "feed `display_answer` back" test then holds for every mode.
6. **Delivery.** Logical commits on the current branch, in the phase order below. `make check` is green at the end of
   each phase.

## Phase 1: grading (pure, no DB)
- `app/grading/__init__.py`: `GradeResult{correct, display_answer, note, misconception_id}`, plus
  `grade(item_type, answer_doc, values, response) -> GradeResult` dispatching on type. `InvalidOption` raises → 422.
- `numeric.py`:
  - A regex parser for the accepted forms (sign, decimals, `e`/`E`, `×10^`, `x10^`, `*10^`) that rejects `,`.
  - A s.f. counter that handles the ambiguous trailing zeros (`270`).
  - Modes `exact`, `sigfig` (strict), `tolerance` (rel/abs), and the `sci_notation` check, with the notes from the spec.
  - The value comes from `params.evaluate(spec.value, values)`.
- `expression.py`:
  - Preprocess: `^`→`**`, then insert implicit `*` for number·name, name·`(`, `)`·`(` and `)`·name. Be careful
    that whitelisted function names like `sin(` don't get a `*`.
  - Then `params.parse(…, names=variables+pi/E, max_exponent=100)`.
  - Modes: `exact` (structural `==`), `equivalent`, `simplified`. Substitute params/derived into the answer first.
- `mcq.py`: move `_ShownOptions` from `app/services/learn.py:469` here as `ShownOptions`, and update `learn.py` to
  import it. MCQ grading maps positional id → authored id → `answer["correct"]` and `answer["misconceptions"]`.
- Tests: `tests/test_grading.py`, every case in the spec's Verification list. The "every pool item in the sample
  content is graded correct with its own `display_answer` over 20 seeds" test loads the bundle through the content
  loader, so it runs offline.

## Phase 2: pure flow logic
In `app/services/kp_flow.py`, with no DB:
- `kp_outcome(results)` and `review_outcome(results)`.
- `next_midnight_ist(now)`, using `zoneinfo("Asia/Kolkata")`.
- `choose_next_item(pool_ids_in_shuffled_order, last_answered_at: Mapping[id, datetime], served_this_session: set, param_ids: set) -> id | None`.
- `is_open(progress, unresolved_remediations, events_since_fail, now)`, where `events_since_fail` is two booleans:
  passed a KP in another concept, and passed a remediation review.
- Reuse `shuffled_order` from `learn.py:143`. It is generic over ids, seeded by `(student, kp_id)`.
- Tests: `tests/test_kp_flow.py`. Exhaustive sequences up to length 5, plus all the listed examples.

## Phase 3: data model and migration
- `app/models/learning.py`:
  - Add `AttemptContext.kp`/`remediation` and `StudyActivity.practice`.
  - New enums: `ConceptStatus`, `ConceptSource`, `KpStatus`, `SessionKind`, `SessionStatus`, `RemediationState`,
    `RemediationOutcome`.
  - New models `ConceptState`, `KpProgress`, `PracticeSession`, `Remediation`, all on `TenantMixin` with
    `_student_fk(...)`.
  - Composite FKs `(remediation_id, org_id)` and `(session_id, org_id)` need `UNIQUE (id, org_id)` on the target
    tables. Follow the tenancy link-table pattern.
  - `Attempt` gains `session_id` and `position`, a unique `(session_id, position)`, and the CHECK.
- `alembic/versions/0005_kp_flow.py`, in the style of 0004 (`_tenant`, `_content_fk`, explicit names, a `TABLES`
  list, RLS on each table):
  - The partial unique indexes from the spec, created with `postgresql_where=sa.text(...)` literals.
  - The data migration: `INSERT INTO concept_state … SELECT … FROM lesson_progress` (status `in_progress`, source
    `lesson`).
  - Model and migration must match exactly, because `test_migrations_db.py` compares metadata.
- Tests:
  - `tests/conftest.py`: add the 4 tables to `TENANT_TABLES`.
  - `tests/test_rls_db.py`: add them to the explicit set.
  - `test_migrations_db.py`: round-trips 0005 automatically. Add the backfill test to `test_learn_api_db.py`.

## Phase 4: frontier and Learn service changes
- `app/services/frontier.py`: `concept_statuses(scope, concept_ids, graph)` → per concept `{status, kps_passed,
  kps_total, waiting: reopen_at|None, brush_up: bool, open_kp}`.
  - One query each for `concept_state`, `kp_progress` (joined to active KPs), unresolved remediations, and the
    "events since fail" lookups. No N+1.
  - Promote on read: an in-progress concept whose active KPs are all passed becomes learned (the retired-KP edge
    case).
  - A KP with an empty gradable pool counts as passed, with a warning logged.
- `app/services/learn.py`:
  - Replace `lesson_status`/`_finished_map` with `frontier`. The gate becomes learned. Don't re-lock a concept that
    has a row.
  - `lesson_steps` interleaves `kp:<slug>`, `kpq:<slug>`.
  - `_touch_progress` also upserts `concept_state(in_progress)` (`ON CONFLICT DO NOTHING`).
  - The step validator accepts `kpq:`, and `record_progress` logs `practice` for `kpq:` steps.
  - `_maybe_finish` is unchanged and ignores `kpq:`.
  - `student_courses` drops `continue_` and adds `learned`, `brush_up[]`, `in_progress[]`, `ready[]` (max 5) and
    `waiting[]`.
  - The outline adds `kps_passed`/`kps_total`/`waiting`/`brush_up`. The lesson adds `kps[].status|reopen_at`,
    `waiting` and `concept_status`.
  - `concept_locked` statuses use the new names.
- `app/schemas/learn.py` gets the matching shape changes. The progress step `remediation` is posted with the prereq
  concept.

## Phase 5: KP and remediation endpoints
- `app/schemas/kp.py`: `QuestionPublic`, `AnswerIn` (response ≤ 200 → 422 `invalid_response`), `AnswerResult`,
  `KpWaiting`, `RemediationOut`.
- `app/services/kp_flow.py`, DB part:
  - `current_question`:
    - Lock or create the active session. On a partial-unique conflict, re-read the winner.
    - Run the 409 checks in order: `check_first`, `kp_order`, `kp_passed`, `kp_waiting`.
    - Choose an item and draw the seed with `secrets.randbelow(2**31)`.
    - Store `current_*` and `current_served_at` before returning.
    - If the current item is retired, replace it at the same position.
    - The prompt is `params.render(public.prompt, sample_answer(...))`. MCQ options come from `ShownOptions`.
  - `answer`:
    - `SELECT … FOR UPDATE` on the session, then the position check: same position already answered →
      `already_answered`; any other mismatch → 409 `stale_question`.
    - Grade via `to_thread`, insert the attempt (unique `(session_id, position)` with `ON CONFLICT DO NOTHING`, then
      re-read).
    - Clamp `time_taken_ms` to `min(client, now − current_served_at)`, within 0–1.8M.
    - Evaluate `kp_outcome`, then call `_on_kp_passed`, `_on_kp_failed` or choose the next item, all in one
      transaction.
  - `_on_kp_failed`: sets `fail_count`, `failed_at`, `reopen_at`. At fail count ≥ 2 it creates remediations per
    `KpKeyPrereq`: `review_due` if the prereq is learned, else `relearn`. It skips any prereq that already has an
    unresolved remediation for this KP.
  - `remediation_question` / `remediation_answer`:
    - Draw round-robin over the prereq's active KPs.
    - Judge with `review_outcome`. Pass → resolved. Fail → `_relearn`: the prereq goes back to `in_progress`,
      `relearn_count` +1, its `kp_progress` rows are reset, and the remediation moves to `relearn`.
    - When a concept becomes learned, also resolve its `relearn` remediations (`outcome = relearned`).
  - Staff:
    - GET returns a random item plus `preview_seed`.
    - POST requires `item_id`/`seed` and writes nothing.
    - The remediation routes return 403 to staff.
- `app/api/v1/kp.py`: 4 routes, all on `Scope`. Register it in `router.py`. No new `GLOBAL_CONTENT` entry.
- `app/content/validate.py`: a gradable-pool rule (< 2 gradable items → error; < 5 gradable slots → warning)
  alongside the existing `_check_pool`. Tests go in `test_content_validate.py`.
- Tests: `tests/test_kp_api_db.py` with every scenario in the spec, built on the `_world`/`_get`/`_post` helpers from
  `test_learn_api_db.py`. Move the shared helpers into a small `tests/learn_helpers.py` if that's cleaner. Also update
  `test_learn_api_db.py` for the new statuses and for "finished no longer unlocks".
  - A helper answers correctly by reading `item.answer` server side in the test, using `grading` to produce
    `display_answer`.

## Phase 6: frontend
- `pnpm add @xyflow/react` (via the CLI, never a lockfile edit).
- `src/lib/types.ts` and `features/learn/api.ts`:
  - Types and hooks `useKpQuestion`, `useSubmitKpAnswer`, `useRemediationQuestion`/`Answer`.
  - Query keys under `learnKeys`. Invalidate the lesson, outline and courses on pass/fail.
- New in `features/learn/`:
  - `QuestionStep` (dots, prompt via `Markdown`, inputs, submit spinner, result panel with focus).
  - `NumericInput` (`inputmode="decimal"`, unit suffix), `ExpressionInput` (live KaTeX preview through the existing
    `katex`), `ResultPanel`.
  - `FailedScreen`, `WaitingPanel`, `LearnedScreen` (replaces `FinishedScreen`), `RemediationPage`.
  - MCQ reuses the radio-card markup from `CheckStep` (extract a shared `OptionCards` if that's simpler).
- Edits:
  - `LessonPage`: `kpq` steps, Next gated on a passed KP, resume logic, waiting/failed/learned screens, and 409 panels.
  - `StepIndicator`: `1✎` labels, ✓ on passed steps, can't jump past an unpassed `kpq`.
  - `StudentHome`: the four lists, no Continue.
  - `CoursePage`: the List|Map toggle (`localStorage` in try/catch, default by `useMediaQuery("(min-width: 768px)")`)
    and a lazy `CourseMap`.
  - `StatusIcon` (half-ring for in progress), `LockedPanel` ("Learn these first"), `paths.ts`, and the
    `routes.tsx` `/learn/brush-up/:id` route.
- `features/graph/`:
  - `layoutGraph.ts`: longest-path layers, outline order, 200×64 nodes, 48/72 gaps.
  - `highlight.ts`: ancestors split into direct and distant.
  - `ConceptNode`: state colour, icon and text, progress bar, badges.
  - `ConceptPanel`: a side panel or bottom `Sheet`.
  - `CourseMap`: fit view, zoom controls, not draggable, Esc/background clear, a "View as list" link, and staff mode.
- Tests (vitest, `routeFetch` style): `layoutGraph`, `highlight`, `QuestionStep`, `NumericInput`, `ExpressionInput`,
  the `LessonPage` cases, `CoursePage` (toggle and lazy map), and the `StudentHome` lists. Update `pages.test.tsx`
  fixtures.

## Phase 7: docs
- `docs/ARCHITECTURE.md` domain model: `practice_session`, `remediation`, the `concept_state` states, the new
  `attempt` columns, `practice` activity, and the gate is now learned.
- `content/README.md`: code items aren't drawn until 006, and the pool rule.
- Spec status → implemented.

## Verification
- After each phase: `cd backend && uv run mypy`, the related `uv run pytest tests/test_grading.py tests/test_kp_flow.py …`,
  and `cd frontend && pnpm typecheck && pnpm vitest run src/features/...`. I'll show the output.
- At the end: `make check` and `make test-db` (needs `TEST_DATABASE_URL`). Run `test_kp_api_db.py`,
  `test_learn_api_db.py`, `test_rls_db.py`, `test_migrations_db.py` and `test_route_scoping.py` explicitly.
- Manual run, per the spec's checklist: `make migrate && make content-import && make dev`, then use the `run` skill /
  Chrome at 1280 px and 375 px as a Physics student and as a teacher. Collect screenshots.
- Then use the `reviewer` subagent to check the diff against the spec, before `/ship`.
