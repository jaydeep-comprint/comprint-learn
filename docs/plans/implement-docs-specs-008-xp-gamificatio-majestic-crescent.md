# Plan: Spec 008 — XP & gamification

## Context
Spec `docs/specs/008-xp-gamification.md` (PRD item 7, built before 007). Students earn XP when a KP try, a brush-up
review or a practice item **ends by an answer**. The work adds an append-only `xp_event` ledger, a daily goal per
subject with an `xp_day` snapshot, a streak, a header chip, popover and toast, an opt-in class leaderboard, and a
teacher Motivation card plus roster columns. Branch: `feat/008-xp-gamification`. The uncommitted spec, ROADMAP and PRD
edits come along with it.

## Key findings that shape the design
- All three session kinds end through one shared function, `kp_flow.answer_in_session`
  (`backend/app/services/kp_flow.py:748`). It sets `session.status` at :828. It doesn't commit; its callers do:
  `answer` :1006, `remediation_answer` :1338 and `practice.practice_answer` (`services/practice.py:206`).
- Callers can still change the outcome after `answer_in_session` returns. When the question pool is empty, `answer`
  forces "passed" (:1034) and `remediation_answer` does the same (:1385). So **the award goes in each caller**, after
  the outcome is final and before `commit()`, not inside `answer_in_session`. These are still the answer ending the
  session, so they earn XP. Bulk closes earn nothing because they never reach these hooks:
  - `_end_active_kp_sessions` called from `current_question`
  - `close_review_sessions`
  - `mark_learned`
  - the empty pool in `remediation_question`
- Resends and stored results all go through `_stored_result` (:670). That is where the existing event is attached.
- Staff and "Practise again" go to `preview_answer` / `preview_question` and write nothing, so they earn 0 for free.
- Unrelated to the roster: `Enrollment` has no status column (an enrollment is active if it exists), and archiving is
  `SchoolClass.archived_at`. Every teacher in an org can GET and PATCH any class (`StaffScope`), so "staff who can view
  the class" means `StaffScope` plus `scope.get`.
- Errors: `ApiProblem(422, "goal_invalid", "...")` from `app/core/errors.py`. Students-only checks follow the pattern
  in `learn._require_student` (`services/learn.py:312`).

## Backend

### 1. Migration `alembic/versions/0007_xp.py` (down_revision `0006_practice_formats`)
- It follows the 0005 helpers (`_enum`, `_tenant`, `_content_fk`, `_tenant_fk`, explicit `ix_<table>_org_id`) and
  enables RLS on each new table.
- New enums: `xp_reason` (kp, remediation, practice) and `xp_grade` (perfect, passed, partial, poor, rushed).
- `xp_event`:
  - `id` is a bigint identity.
  - Columns: `org_id`, `student_id`, `session_id` (nullable), `reason`, `concept_id`, `subject` (`class_subject`),
    `amount`, `grade`, `base_minutes`, `answered`, `rushed_count`, `hints`, `day`, `created_at`.
  - `session_id` has a composite FK `(session_id, org_id)` → `practice_session`, and a unique index on it
    `WHERE session_id IS NOT NULL`.
  - CHECK on `amount` between −100 and 500. Index on `(org_id, student_id, day)`.
- `xp_day`: PK `(student_id, day, subject)`, plus `org_id` and the student FK. Columns `xp` int, `goal` smallint null
  (CHECK 5–60), `met_at` and `updated_at`.
- `student_goal`: PK `(student_id, subject)`, plus `org_id` and the student FK. `goal` has CHECK 5–60 and `% 5 = 0`.
  It also has `updated_at`.
- `school_class` gains `daily_goal smallint NOT NULL DEFAULT 15` (with the CHECK) and
  `leaderboard_enabled boolean NOT NULL DEFAULT false`.
- Downgrade reverses all of it.

### 2. Models
- `models/learning.py`: `XpReason` and `XpGrade` StrEnums via `_pg_enum`, and the `XpEvent`, `XpDay` and
  `StudentGoal` models using `TenantMixin` and `_student_fk`.
- `models/tenancy.py`: two new `SchoolClass` columns.

### 3. `app/services/xp.py`
**Pure functions** (no DB):
- `PositionXp(expected_minutes: Decimal, correct: bool, time_ms: int)`.
- `is_rushed(p)`: true when the item was wrong and `time_ms < max(5000, 0.15 × min × 60000)`.
- `session_xp(kind, outcome, positions, hints, first_try=True) -> XpCalc(amount, grade, base_minutes, rushed_count,
  answered)`. It follows spec steps 1–5:
  - It uses `Decimal` with `ROUND_HALF_UP`.
  - It applies the floor of 1 for positive awards and the minimum −1 penalty.
  - `partial` applies only to kp and remediation.
  - Practice is `perfect` only when `first_try` is true.
- `ist_week_start(now)`, using `kp_flow.IST`.
- `streak_from_days(days: Mapping[date, bool], today) -> (days, today_met)`. A day with only null-goal rows counts as
  unmet.
- `day_met(rows)`: true when at least one row has a goal and every row with a goal has `met_at`.

**DB functions** (all take `OrgScope`):
- `award_for_session(scope, session, outcome, concept_id) -> XpAwardOut`:
  - It loads the session's attempts with `kp_flow._session_attempts` and gets per-position correctness from
    `position_results`.
  - Time is the sum of `time_taken_ms` per position. `expected_minutes` comes from the current `Item` rows, and hints
    are the sum of `hints_used`.
  - `first_try` (practice only) means no earlier failed practice session for this concept had
    `current_item_id == item`.
  - Subject: concept → course → subject.
  - It inserts the event with `ON CONFLICT DO NOTHING RETURNING`. If the insert returns nothing, it reads the existing
    event. It then upserts `xp_day` with the same `now`.
- `_effective_goals(scope, student_id) -> {subject: (class_goal, own_goal, effective)}`:
  - Goals come from enrollments joined to active classes (`archived_at IS NULL`), taking `max(daily_goal)` per subject.
  - `student_goal` is left-joined in.
  - A deactivated student gets no goals, though they can't be answering anyway.
- `_upsert_days(...)`:
  - One `INSERT ... ON CONFLICT (student_id, day, subject) DO UPDATE` per affected subject: the event's subject plus
    every subject with a goal.
  - The update does `xp = xp_day.xp + excluded.xp` and `goal = GREATEST(xp_day.goal, excluded.goal)` (Postgres
    `GREATEST` ignores NULLs).
  - It also does `met_at = COALESCE(xp_day.met_at, CASE WHEN new_xp >= new_goal THEN :now END)`.
- `goal_met_today` is derived, so no extra column is needed: the event's day is met **and** the latest `met_at` on its
  goal rows equals `event.created_at`. The upsert writes `met_at` with the event's own timestamp. The derivation is
  stable on resend.
- `event_out(scope, session_id)` for the resend path.
- `summary(scope) -> XpSummary`:
  - `today` comes from today's rows, plus subjects that have a goal but no row yet (xp 0).
  - The streak is computed from 400 days of rows.
  - Weekly and lifetime totals are summed from `xp_event` and floored at 0 for display.
  - `leaderboards` lists enrolled active classes with the switch on.
- `set_own_goal(scope, subject, goal | None)`:
  - It raises 422 `goal_invalid`, `goal_below_class` or `no_class_for_subject` as the spec words them.
  - It upserts or deletes the `student_goal` row.
  - It raises today's rows with `goal = GREATEST(goal, effective)` and re-checks `met_at` the same way.
- `raise_today_goals(scope, class_id, new_goal)`, used when a teacher raises a class goal.
- `leaderboard(scope, class_id)`:
  - Students get 404 unless they are enrolled, the switch is on and the class isn't archived. Staff get
    `StaffScope`-level access.
  - Rows are active enrolled students with that week's XP in the class subject, floored at 0.
  - Order: XP descending, then `lower(display_name)`. Ranks are competition-style (1, 1, 3).
  - `student_id` appears for staff only.
- `roster_stats(scope, class_id, student_ids) -> {id: (week_xp, streak)}` uses two batched queries.

### 4. Hook the award into the answer paths
- `kp_flow.answer` (:1038): when the outcome is passed or failed, set
  `out.xp = await xp.award_for_session(scope, session, outcome, ctx.concept.id)` before `commit()`.
- `kp_flow.remediation_answer` (:1388): the same, with `rem.prereq_concept_id`.
- `practice.practice_answer`: the same on pass and fail, on the normal (non-preview) path only.
- `kp_flow._stored_result`: if the session has ended and the attempt is the ending one
  (`attempt.position == session.current_position` and the item is done), set
  `out.xp = await xp.event_out(scope, session.id)`. This covers resends from every caller, including
  `_answer_from_other_session` and the not-due remediation path.
- `schemas/kp.py`: add `AnswerResult.xp: XpAwardOut | None = None`.

### 5. Schemas, routes and tenancy
- `app/schemas/xp.py`: `XpAwardOut`, `XpSummary` (and its parts), `GoalIn` and `LeaderboardOut`.
- `app/api/v1/xp.py`, registered in `router.py`:
  - `GET /me/xp` and `PUT /me/goals/{subject}`, both students only and returning `forbidden()` to staff as the learn
    routes do.
  - `GET /classes/{id}/leaderboard` with `Scope`.
- `schemas/tenancy.py`:
  - `ClassPatch` gains `daily_goal: int | None = Field(ge=5, le=60, multiple_of=5)` and
    `leaderboard_enabled: bool | None`. A bad goal gets the standard 422.
  - `ClassOut` gains both fields.
  - `ClassStudentOut` gains `week_xp` and `streak_days`.
- `services/tenancy.py`:
  - `patch_class` sets the new fields. When `daily_goal` rises, it calls `xp.raise_today_goals` before the commit.
  - `_class_out` returns the new fields.
  - `list_class_students` merges in `roster_stats`.
- Test wiring:
  - `tests/test_route_scoping.py`: the new routes are scoped, not global. Bump the path count if needed.
  - `tests/conftest.py`: add `xp_event`, `xp_day` and `student_goal` to `TENANT_TABLES`.
  - `tests/test_rls_db.py`: add the same tables to its expected set.

## Frontend
- `components/ui/popover.tsx`: a shadcn-style wrapper around `import { Popover } from "radix-ui"`. No new dependency.
- `src/features/xp/`:
  - `api.ts`: `xpKeys.me = ["me","xp"]`, `useXpSummary`, `useSetGoal` and `useLeaderboard(classId)`. These use
    `apiFetch` and `retryUnlessClientError`.
  - `XpChip.tsx`:
    - It shows a `Flame` icon (muted until today is met), the streak, and `today xp / sum of today's goals`.
    - It is a Skeleton while loading and hidden on error.
    - Below `sm` it shows only the flame and streak.
    - It is the popover trigger.
  - `XpPopover.tsx`:
    - Per-subject bars and the streak line ("Meet today's goals to make it N+1").
    - The week's XP.
    - Native `Select` goal pickers (class goal to 60, step 5, with a "Teacher: N" hint, saved on change, errors shown
      inline).
    - Leaderboard links, and the empty state.
  - `awardToast.ts`:
    - `showAwardToast(xp, sessionId)` has the copy per grade, adds "· hints used", and adds "Daily goal met 🎉".
    - A module-level `Set` of shown session ids prevents a second toast.
  - `LeaderboardPage.tsx`: the class name, "This week (Mon–Sun)", and a table with your own row highlighted. The empty
    state is "No XP yet this week." A 404 shows "This leaderboard isn't available".
  - `MotivationCard.tsx`: a goal `Select` (5–60) and a `Switch` with the help text. The leaderboard table always shows,
    with an "Off: students can't see this" badge when the switch is off.
- `AppShell.tsx`: render `<XpChip/>` before `UserMenu` when `me.role === "student"`.
- `PracticeRunner.tsx`: after `setResult(next)`, if `!preview && next.xp`, call `showAwardToast(next.xp,
  question.session_id)` and invalidate `["me","xp"]`. KP, practice and brush-up all go through here, so
  `QuestionStep` and `RemediationPage` need no changes.
- `PracticeStep.tsx`: when `again`, show "Practice only, no XP".
- `ClassDetailPage.tsx`:
  - Add `<MotivationCard>` after `TeachersRow`.
  - Add roster columns **XP this week** and **Streak**.
  - Extend the `useUpdateClass` body type.
- `lib/types.ts`:
  - New types `XpAward`, `XpSummary` and `Leaderboard`.
  - `AnswerResult.xp?`.
  - `SchoolClass` gains `daily_goal` and `leaderboard_enabled`; the class-student type gains `week_xp` and
    `streak_days`.
- `routes.tsx`: `/leaderboard/:classId` inside a new `RequireRole access="student"` group, lazy-loaded.

## Docs
- ARCHITECTURE:
  - Decision 5: the daily goal is per subject with a default of 15, repeats earn 0, and the rush rule.
  - Domain model: `xp_event`, `xp_day`, `student_goal` and the class columns.
- ROADMAP: a note that 008 shipped before 007.
- Spec status → implemented, with short implementation notes.

## Tests
- `tests/test_xp_rules.py` (pure, table-driven): every unit case in the spec. The "implementation tasks earn the most"
  check loads `DEFAULT_CONTENT_ROOT` with the content loader. It compares the minimum passed code item (×1.0) with the
  best possible KP try (top 5 items ×1.0, or top 2 ×1.2).
- `tests/test_xp_db.py` (`pytest.mark.db`). It uses `learn_helpers.world` with `answer_kp` and `pass_practice` and
  covers:
  - one event per ended session, with `xp_day` rows for every goal subject
  - one event for a concurrent double answer (`asyncio.gather`) and for a resend
  - no event for side-effect closes, Practise again or staff previews
  - goal raised vs lowered mid-day
  - the three 422s
  - the leaderboard: off/on, ties, own subject only, unenrolled and deactivated students hidden, and 404 for another
    school's class
  - the roster columns
- Frontend vitest:
  - `XpChip.test.tsx`
  - `XpPopover.test.tsx`
  - `awardToast.test.ts`, with the copy per grade and the dedupe
  - `MotivationCard.test.tsx`
  - `LeaderboardPage.test.tsx`
  - plus a toast-on-answer and no-toast-on-again case in `features/learn/pages.test.tsx`

## Verification
- `cd backend && uv run pytest tests/test_xp_rules.py` and `uv run mypy`.
- `cd frontend && pnpm vitest run src/features/xp` and `pnpm typecheck`.
- `make check` and `make test-db` (the latter covers `test_xp_db.py`, `test_rls_db.py` and `test_route_scoping.py`).
- The spec's manual script with `make dev`: steps 1–8 (teacher goal and switch, perfect toast, rushed −1, goal met,
  own goal, leaderboard on/off, roster, streak via seeded `xp_day` rows).
- Then the `reviewer` subagent checks the diff against the spec, followed by `/ship`.
