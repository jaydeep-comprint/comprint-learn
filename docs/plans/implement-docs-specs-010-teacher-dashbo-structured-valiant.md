# Plan: Spec 010 — Teacher dashboard + assignments

## Context
ROADMAP 010 / PRD item 10. The class page becomes a tabbed teacher dashboard: Overview, Students (roster + heatmap),
Assignments and Settings. There is a new per-student page (graph with Progress/Memory modes, activity, tutor
transcripts). Teachers assign 1–10 concepts with a due date to the class or chosen students, and students see an
"Assigned by your teacher" card with a Focus path. The spec (`docs/specs/010-teacher-dashboard-assignments.md`) is
fully decided, so this plan maps it onto the code.

Branch: `feat/010-teacher-dashboard-assignments`. The untracked spec and the `docs/PRD.md` edit go into the first
commit.

## Key findings that shape the design
- **Every frontier helper is hard-wired to `scope.user.id`**: `frontier.load` (`services/frontier.py:272`),
  `_passes` (:370), `_practice_passed` (:257) and `open_remediations` (:172). The assembly in `load` (≈:322-366) is
  pure apart from promotion (:359-364). `concept_status` (:49), `complete` (:267) and `kp_flow.is_open`
  (`kp_flow.py:135`) are already pure.
- **The content side is shared and already batched.** `learn._graph(scope)` (`learn.py:218`), `active_kps`
  (`frontier.py:190`) and `practice_concepts` do not depend on the student. `learn.build_outline` (:90) and
  `_ancestors` (:114) are pure. `_Graph.outline(course_slug)` puts cross-course ancestors under their anchor's chapter.
- **Some stats are already batched by student list:** `xp.roster_stats` (`xp.py:800`), `srs.due_count`
  (`srs.py:661`) and `quiz.last_quiz_stats` (`quiz.py:680`). All three are used by `tenancy.list_class_students`
  (`tenancy.py:561`). Supporting helpers: `srs.retrievability(stability, last_review, at)` (:122), the IST helpers
  (`kp_flow.IST` :79, `srs.ist_day` / `ist_midnight`, `xp.ist_date` / `ist_week_start`) and `xp.streak_from_days`.
- **Tutor threads** (`TutorSession`, `models/learning.py:660`) have no concept column. The concept comes from
  `item_id → Item.concept_id / kp_id`. When listing, hide messages with status `pending/error/late` (`tutor.HIDDEN`).
  Reuse `tutor._messages` / `_thread_out` where they fit.
- **Tenancy**:
  - `scope.get(SchoolClass, id)` gives a 404 for unknown or other-school ids.
  - `tenancy._get_writable_class` (:587) raises 409 `class_archived`. Its message is "…Unarchive it to make changes.";
    reuse it.
  - `Enrollment` has no status column (a row means enrolled), and the roster does not filter on user status.
  - Each subject has at most one active course (`uq_course_subject_active`). Look it up via `graph.courses` by subject.
- **Errors**: `ApiProblem(422, code, msg)` / `conflict(...)` / `not_found()` / `forbidden()` from `app/core/errors.py`.
  Student-only reads call `learn._require_student` (403 `forbidden` for staff).
- **Tests**:
  - There is **no query-counter helper yet**, so add one.
  - Seed helpers to use: `db_seed.seed_school`, `learn_helpers.world` / `learn_concept` / `answer_kp`, and
    `review_helpers.seed_learned` / `set_card`.
  - Add the new tables to `TENANT_TABLES` (`conftest.py:74`) and `test_rls_db.py`.
- **Frontend**:
  - Staff routes are eager (`routes.tsx:61-67`).
  - `CourseMap` treats "all statuses null" as staff preview (`CourseMap.tsx:82`).
  - `ConceptPanel.Action` always renders learner links.
  - There is no Tooltip component (use `Popover`) and no msw (`test/render.tsx` `routeFetch`).
  - `QuizBanner` is the "hide on error" pattern for `AssignedCard`.
  - `ClassDetailPage.tsx` holds `TeachersRow` (60-106), `StudentRows` (108-217) and the header actions (262-302).

## Backend build order (each step testable before the next)

### 1. Frontier refactor: batched, read-only states (`services/frontier.py`)
- Split `load` into two parts:
  - **`_fetch_student_rows(scope, student_ids, kp_ids)`** runs a fixed number of `student_id IN (...)` queries:
    ConceptState, KpProgress, open remediations, passes and passed practice sessions. It returns them grouped by
    student.
  - **`build(content, rows, prereqs, now) -> Frontier`** is pure and holds today's assembly code.
- Parametrise `open_remediations`, `_passes` and `_practice_passed` with `student_ids`. `_passes` gets
  `GROUP BY student_id, concept_id`.
- `load(scope, …, promote=True)` becomes fetch for `[scope.user.id]`, then `build`, then the same promotion. Its
  behaviour does not change, and the existing tests are the regression check.
- Add **`effective(frontier)`**. It returns a frontier where every in-progress concept that is `complete()` counts as
  learned. Ready/locked are then recomputed from that effective learned set. It is pure and never writes.
- Add **`class_states(scope, student_ids, concept_ids, prereqs) -> dict[sid, Frontier]`**: one content load, one
  fetch, then `build` + `effective` per student.

### 2. Data model + migration
- `models/learning.py` (with `TenantMixin`, `_tenant_fk`, `_student_fk`-style FKs and `uq (id, org_id)`):
  - **`Assignment`**: `id`, `class_id` (FK → school_class), `due_date`, `note` (CHECK `char_length(note) <= 200`),
    `all_students` (default true), `created_by` (FK → app_user), `created_at`, `updated_at`, `deleted_at`. Partial
    index `(org_id, class_id) WHERE deleted_at IS NULL`.
  - **`AssignmentConcept`**: PK `(assignment_id, concept_id)`, `org_id`, `position`. Composite FK → assignment with
    ON DELETE CASCADE; content FK → concept.
  - **`AssignmentStudent`**: PK `(assignment_id, student_id)`, `org_id`. Cascade FK → assignment; composite FK →
    app_user.
- Export all three from `models/__init__.py`.
- `alembic/versions/0010_assignments.py`: copy the local helpers from 0009, enable RLS on all 3 tables, downgrade in
  reverse.
- Add the 3 tables to `TENANT_TABLES` and `test_rls_db.py`.

### 3. Pure rules
**`services/dashboard.py`**
- Constants: `AT_RISK_KP_FAIL_RATE=0.10`, `AT_RISK_MIN_KP_TRIES=5`, `AT_RISK_XP_PER_MIN=0.5`,
  `AT_RISK_MIN_ACTIVE_MIN=30`, `AT_RISK_WEAK_CARDS=2`, `WEAK_R=0.7`, `STRONG_R=0.9`, `INACTIVE_DAYS=7`,
  `MIN_STUDENTS_RANKED=3`, `MIN_OFFERED=3`.
- `window_bounds(window, now)`: the IST-midnight start for 7d/30d, None for all.
- `memory_band(r)`.
- `heat_state(view, frontier)`: the 5 states. Stuck means a waiting KP or an open remediation; the reason gives a
  remediation priority over a waiting KP.
- `rank_weakest(stats, course_order)`.
- `at_risk_rules(inputs) -> list[Reason]`: takes a small dataclass of per-student numbers and returns code + detail
  text as in the spec.
- `misconception_rows`.

**`services/assignments.py`**
- `assignment_status(targets, learned_at_by_concept, states, created_at, due_date, today)`: returns done_early /
  done_on_time / done_late / overdue / in_progress / not_started, plus `done_at`.
- `focus_path(targets, prereqs, frontier, sort_key)`: ancestors via `learn._ancestors`, keep the unlearned ones,
  order with `learn.build_outline`.
- `next_step(path)`: the first in-progress step; when it is stuck by `review_due`, set `brush_up_id`; skip steps that
  are only waiting; otherwise take the first ready step.
- `learn.py`: make `_graph`, `_ancestors` and `_Graph` public through thin wrappers (`graph()`, `ancestors()`). Keep
  the old names so existing callers don't change.

### 4. Dashboard DB service + API
**Shared per-request loader `_class_ctx(scope, class_id)`**
- Class via `scope.get`, then the graph and the class course (none means empty states).
- In-scope students: enrollment join + `AppUser.status == active`.
- Course concept ids in course order, then `frontier.class_states`.
- Every endpoint then runs a fixed set of grouped queries, each filtered by `student_id IN (...)` and concept ∈
  course.

**Endpoints**
- **`overview`**:
  - KP tries: kp sessions ended passed/failed `EXISTS attempt`, grouped by concept and student.
  - At-risk inputs: grouped 7-day KP tries, negative `xp_event` counts, net XP in the subject, `study_time` minutes,
    card retrievability over cards on concepts with a non-retired dependant, overdue assignments (from step 5's
    batched status) and last activity.
  - Misconceptions: chosen counts from `attempt.misconception_id`, and offered counts from items whose `answer` (or
    multistep steps) tags it. Offered is computed in Python over the course's items, joined with questions-answered
    counts.
  - Hint use: `Σ hints_used`, chat count from `tutor_message` (role student, status pending/ok) and questions answered
    as distinct `(session_id, position)` plus learn attempts.
  - Flagged threads, the practice share, and the next 3 assignments due.
- **`concepts`** (all ranked) and **`concept_detail`**:
  - Per KP: tries, fail rate and hints.
  - Per item: prompt from `item.public` (template unrendered), answers, % correct and average time.
  - Misconceptions offered on its items, and students by state with the stuck reason.
  - The response schema has no field that could carry `answer`.
- **`misconceptions`**: the full list with expansions. Each expansion has the distractor text only (looked up from
  `item.public` option texts by the chosen option id in `attempt.response`) and student names.
- **`heatmap`**: chapters of the course (the client filters by grade); cells aligned to the flattened order.
- **Student routes** (all start with an enrollment check and 404 without one; a deactivated student is allowed):
  - `student_detail`: reuse `xp.roster_stats`, `srs.due_count` and `quiz.last_quiz_stats` with `[sid]`.
  - `student_outline`: `graph.outline(course)` plus a single-student `class_states` (read-only), with state, memory
    and KPs per concept.
  - `student_activity`: ended sessions with `before` as the cursor, limit 50, joined to `xp_event` and attempt
    aggregates. Concepts outside the class course are filtered out.
  - `tutor_threads` / `tutor_thread`: threads via `Item.concept_id` ∈ course; 404 when the thread belongs to another
    student.
- **Roster**: `tenancy.list_class_students` adds `at_risk: list[str]` from the batched at-risk function. Add it to
  `ClassStudentOut`.

**Schemas and routes**
- `schemas/dashboard.py`: the shapes exactly as in the spec.
- `api/v1/dashboard.py`: `StaffScope`, `window: Literal["7d","30d","all"] = "7d"`. Register it in `router.py`.

### 5. Assignments DB service + API
- **CRUD**: create, patch, delete and get, all on `_get_writable_class` (409 when the class is archived; the GET
  reads are allowed).
- **Validation**, in this order:
  - 1–10 concepts after de-duplication, else 422 `assignment_invalid`.
  - The due date must be from today (IST) to today + 180 days, checked only when it changes.
  - The note is trimmed, an empty note becomes null, and it can be at most 200 characters.
  - Every ref must be in the active class course and not retired, else 422 `concept_not_in_course`. No course at all
    gives the same error.
  - Every `student_ids` entry must be enrolled and active, else 422 `students_not_in_class`.
- **PATCH** uses `model_fields_set`; `student_ids: null` means the whole class (delete the student rows).
- **`class_assignments(ctx)` / `assignment_detail`**:
  - Per assignment: the live audience = in-scope students ∩ (all, or the chosen rows).
  - Targets = non-retired concepts in the current class course.
  - Statuses come from `class_states` plus `learned_at`. When `learned_at` is null, use the fallback: the latest
    `kp_progress.passed_at` or passing practice `ended_at`.
  - Assignments whose targets are all gone show "Content no longer available" (a flag in the summary).
  - A batched `overdue_by_student(ctx)` feeds the at-risk check and the roster. Only non-deleted assignments in a
    non-archived class count.
- **`my_assignments(scope)`** (student):
  - Checked with `_require_student`.
  - Active enrollments in non-archived classes, filtered to the audience.
  - One `frontier.load` (promote) over the union of the target and ancestor ids, then commit, as
    `learn.student_courses` does.
  - Leave out deleted assignments, those done more than 7 × 24 h ago, `done_early` ones and those without targets.
  - Order: overdue first, then due date, then created.
- **Files**: `schemas/assignments.py` and `api/v1/assignments.py` (`/classes/{id}/assignments…` with `StaffScope`;
  `/me/assignments` with `Scope`).

### 6. Test infrastructure
- `tests/query_count.py`: a context manager that hooks `before_cursor_execute` on `engine.sync_engine` and counts
  statements.

## Frontend build order
1. **`lib/types.ts`**: types for every new response. `ClassStudent.at_risk`.
2. **APIs**:
   - `features/dashboard/api.ts`: keys under `["classes", id, "dashboard", …]`, `staleTime` 60 s, window read from
     `useSearchParams`.
   - `features/assignments/api.ts`: its mutations invalidate `["classes", id]` and `["me", "assignments"]`.
3. **Routing**:
   - `routes.tsx`: `/classes/:id` becomes `ClassLayout` with children:
     - index → `OverviewTab`
     - `students` → `StudentsTab`
     - `students/:studentId` → `StudentPage`
     - `assignments` → `AssignmentsTab`
     - `settings` → `SettingsTab`
   - `/classes/:id/slips` stays outside the layout. The tabs and the student page are lazy routes.
4. **Split `ClassDetailPage.tsx`**:
   - `ClassLayout` gets the header (name, subject/grade, View course, Add students), `TeachersRow`, and the tab links
     (`NavLink`s styled like tabs).
   - `StudentRows` moves to `StudentsTab`. Names become links to the student page, and there's an At-risk badge with
     a Popover listing the reasons.
   - Edit/Archive and `MotivationCard` move to `SettingsTab`.
   - Export the shared pieces from `features/classes` rather than duplicating them.
5. **Overview cards**, each with its own skeleton and an error card with "Try again":
   - `WindowPicker`, `WeakestConcepts`, `AtRiskList`, `MisconceptionList`, `HintUseCard`, `FlaggedChats`,
     `PracticeShare`, and Assignments due soon.
   - `ConceptDetailSheet` (Sheet, full screen on mobile).
   - An empty-class state.
6. **`Heatmap`**:
   - A table with a sticky first column, `overflow-x-auto`, and chapter header groups.
   - A grade filter toggle and a legend.
   - Shade plus icon per state and band.
   - A Popover on cells with an aria-label that has the full text.
7. **Graph changes** (`CourseMap`, `ConceptNode`, `ConceptPanel`):
   - New props `mode?: "progress" | "memory"`, `readOnly?: boolean`, and per-concept `state` / `memory` on the
     teacher outline type.
   - `readOnly` forces the non-staff legend and hides the panel `Action`. The panel shows KP statuses, fail counts,
     next review and band.
   - Memory mode fills learned nodes with the heatmap's shades and greys the rest.
   - The existing student/staff behaviour is unchanged.
8. **`StudentPage`**:
   - Header (badges and reasons), stats, the lazy `CourseMap` with the Progress/Memory toggle, assignments.
   - `ActivityList` with "Load more".
   - `TutorThreads`: a list plus a thread view; `?thread=` opens it.
9. **Assignments**:
   - `AssignmentsTab`: table, a collapsed Past section, a menu (Edit, Delete with `ConfirmDialog`), and the empty
     state.
   - `AssignmentDetailSheet`.
   - `AssignmentDialog`:
     - Concepts grouped by chapter from `/courses/{slug}/outline`, with borrowed concepts filtered out by course
       prefix, a chapter select-all, and the "n of 10" counter.
     - Date input with `min` = today (IST).
     - Audience radio, plus a student checklist with search.
     - Note with a counter, and `FormError`.
     - Opened prefilled from the Assign buttons.
10. **`AssignedCard`** in `StudentHome` between `QuizBanner` and `TodaysReviews`. It returns null when there's no data
    or on error. It shows the path (max 5 + "+ N more"), Continue via `lessonPath` / `brushUpPath`, the waiting text,
    and Done ✓.

## Tests (new)
**Backend, no DB**
- `test_dashboard_rules.py` and `test_assignment_rules.py`: every case in the spec's Verification list, plus
  `frontier.build` / `effective` cases.

**Backend, DB**
- `test_dashboard_db.py`, as the spec lists:
  - A seeded class of 4 students.
  - Overview numbers, and the exclusions.
  - The no-write check (`concept_state` count unchanged).
  - Parity between `class_states` and `frontier.load`.
  - Query counts equal for 4 vs 40 students, on every dashboard endpoint and the roster.
  - No `answer` keys.
  - 404s.
- `test_assignments_db.py`: CRUD errors (422/409), audience, late enrolment, `/me/assignments` filtering and order,
  and overdue → roster `at_risk`.
- Extend `test_tenant_isolation_db.py` with another school's class, assignment, student and thread ids. Route scoping
  needs no allowlist change.

**Frontend (vitest)**
- `Heatmap`, `WindowPicker`, `AtRiskList`, `MisconceptionList`, `AssignmentDialog`, `AssignedCard` and `CourseMap`
  memory mode (the node fill/label for a weak band).
- Update `StudentHome.test.tsx` and any `ClassDetailPage`-based tests for the new layout.

## Docs at the end
- ARCHITECTURE:
  - Domain model: `assignment`, `assignment_concept`, `assignment_student`.
  - Decisions 13 and 15 made concrete, including the `inactive` rule.
  - Boundaries: teacher reads are read-only and use `class_states`.
- ROADMAP: "010 done".
- Spec status → done.
- CLAUDE.md gotcha: `frontier.class_states` for teacher reads; never call `load` with `promote=True` for staff.

## Verification
1. `cd backend && uv run pytest tests/test_dashboard_rules.py tests/test_assignment_rules.py` and the existing
   frontier/kp/learn tests (to catch refactor regressions); `uv run mypy`.
2. `make test-db` (needs `TEST_DATABASE_URL`): the new DB tests plus `test_rls_db`, `test_route_scoping` and
   `test_tenant_isolation_db`. Timing check: seed 60 × 40 in the dashboard test, assert < 500 ms per endpoint as a
   soft log.
3. `cd frontend && pnpm typecheck && pnpm vitest run`; `make check`.
4. `make migrate`, `make dev`, then the manual flows 1–8 of the spec. My memory notes that Claude in Chrome couldn't
   reach localhost before, so I'll try once. If that fails, I'll ask you to click through Overview, heatmap, the
   student page (both modes), the assignment dialog and the AssignedCard at desktop and 360 px, plus the empty
   states, and to share screenshots.
5. The `reviewer` subagent against the spec, then `/ship`.
