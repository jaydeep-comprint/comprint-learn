# Spec 008: XP & gamification

Status: implemented (Nov 2026)
PRD link: docs/PRD.md#mvp-scope-v1 (item 7)
Builds on: [spec 005](005-kp-flow-knowledge-graph.md) (`practice_session` outcomes, IST day boundary),
[spec 006](006-practice-formats.md) (practice sessions, code/multistep). **Built before spec 007**: 007 adds review
and quiz XP to the same ledger and reads lifetime XP for the "quiz every ~150 XP" trigger.

## Summary
Students earn XP when a KP try, a brush-up review or a practice item ends. XP is about the minutes of focused work
(`expected_minutes` × a performance multiplier). Rushing and guessing earn a small penalty, and repeats earn nothing.
Each enrolled subject has a daily goal: the teacher sets it per class and the student can raise their own. A single
streak counts the days on which every goal was met. A header chip shows the streak and today's XP, and a toast
explains each award. Teachers set the goal, can switch on a weekly class leaderboard and see XP in the class roster.
Course progress still counts concepts learned, never XP.

## User stories
- As a student, I want to see XP right after I finish a part or a problem, with a reason when it's low or negative,
  so I know effort counts and rushing doesn't pay.
- As a student, I want a daily goal per subject and a streak, so I come back every day.
- As a student, I want to set a higher goal for myself than my teacher's.
- As a teacher, I want to set my class's daily goal and choose whether a class leaderboard is on, so competition
  stays my decision (students are minors).
- As a teacher, I want each student's XP this week and their streak in the roster.
- As our team, I want an append-only XP ledger with the reason and inputs for each award, so 007 can trigger
  quizzes, 010 can flag negative XP and low XP per minute, and we can tune the rules from data.

## Behaviour

### What earns XP
- XP is awarded **once per `practice_session`**, at the moment an answer **in that session** ends it (passed or
  failed): kinds `kp`, `remediation` (brush-up review) and `practice`. Exactly one `xp_event` is written per session
  that ends this way, **including amount 0** (for the ledger and the toast).
- Sessions closed as a side effect (for example `_end_active_kp_sessions` when the KP passed in another tab, or a
  remediation resolved by a relearn) earn nothing and get no event.
- The **Learn layer earns nothing**: not reading, and not the misconception check.
- **Practise again** (006: an unscored preview of a learned concept) stays stateless and earns **0**. The UI labels it
  "Practice only, no XP". Staff previews never earn XP.
- A **relearn** (KPs reset after a failed brush-up) earns full XP again, because the KP sessions are new and real.
- Sessions that ended before 008 is deployed get **no backfill**. Every student starts at 0.

### The XP rule (pure function, `app/services/xp.py: session_xp`)
Inputs: session kind, outcome, and one entry per answered **position** (from `kp_flow.position_results` + the attempt
rows): the item's `expected_minutes`, whether the item was correct (multistep: `item_correct`), and its time
(sum of `time_taken_ms` over the position's step rows, already capped by the server). Plus the session's total
`hints_used`.

1. **Base** = Σ `expected_minutes` of the answered items (a KP try that needed 4 questions has a base of 4 items).
2. **Rushed answer** = the item was wrong **and** its time < max(5 s, 0.15 × `expected_minutes` × 60 s).
3. **Grade → multiplier**:

   | Grade | When | Multiplier |
   |---|---|---|
   | `perfect` | passed, every answered item correct | 1.2 |
   | `passed` | passed after a miss | 1.0 |
   | `partial` | failed `kp`/`remediation` session, ≥ half the answered items correct | 0.3 |
   | `poor` | any other failure (practice items are never partial) | 0 |
   | `rushed` | failed **and** rushed answers ≥ min(2, answered items) | −0.25 (penalty, see 5) |

   `rushed` takes precedence over `partial`/`poor`. Correct fast answers are never penalised.
   For practice, a first-try pass with every step/test right is `perfect`. A pass after an earlier failed session
   on the same item is `passed`.
4. **Hint factor, per question** (positive awards only; changed by spec 009): each answered question's
   `expected_minutes` is scaled by max(0, 1 − 0.25 × that question's hints), so base_effective =
   Σ expected_minutes × factor. Unaided questions keep full XP. Spec 009 fills `attempt.hints_used`.
5. **Rounding**: amount = round-half-up(base_effective × multiplier). A positive product is at least **1**. A
   `rushed` penalty is at most **−1**: round-half-up(0.25 × base), negated, minimum magnitude 1. Hints never shrink
   a penalty.
6. The event stores the inputs: `base_minutes`, `grade`, `hints`, `rushed_count`, `answered`. That way the rule can
   be audited and the toast can explain the amount.
- `expected_minutes` is read from the current `item` row at award time (each attempt stores `item_version` for
  audit). A retired item still has its row and is used as is.

### Day, subject, totals
- An event's **day** is the Asia/Kolkata date of the session's end (`kp_flow.IST`). Its **subject** is the subject
  of the session's concept's course. For a brush-up this is the **prerequisite** concept, which may be in another
  course. The event also stores `concept_id`.
- Totals are **net**: negatives subtract. **Displayed** weekly and lifetime totals are floored at 0, while the ledger
  keeps the real negatives (010's at-risk rule reads them).
- **Week** = Monday 00:00 to Sunday 24:00 IST.

### Daily goals (per subject)
- A student **has a goal for a subject** only while they are in an **active class** (not archived, active
  enrollment) of that subject. A student with no class has no goals and no streak, but still earns XP.
- **Class goal**: `school_class.daily_goal`, 5–60 in steps of 5, **default 15**. With several classes of the same
  subject, the **highest** class goal counts.
- **Own goal**: the student may set a goal per subject (`student_goal`). It must be ≥ the class goal and at most 60,
  in steps of 5. Clearing it falls back to the class goal. If the class goal later rises above the own goal, the
  class goal wins (effective = max).
- **Effective goal** = max(highest class goal, own goal).

### Day snapshot and streak
- `xp_day` has one row per student × IST date × subject: `xp` (net, may be negative), `goal` (null = no goal for
  that subject that day) and `met_at`.
- When an event is written, in the same transaction, upsert a row for the event's subject **and** for every subject
  with an effective goal:
  - `xp += amount` (event subject only).
  - `goal = greatest(existing, effective)`. The goal is frozen at the day's first XP, and may be raised later that
    day but never lowered. A null goal becomes the effective goal if the student enrolled that day.
  - `met_at = coalesce(met_at, now() if xp ≥ goal)`. Once met, a day stays met even if a later penalty drops the
    XP below the goal.
- Raising an own goal (or a teacher raising a class goal) also raises **today's** existing rows. A goal that was
  already met stays met.
- A **day is met** when it has at least one row with a goal and every row with a goal has `met_at`.
- **Streak** = consecutive met days ending today (if today is met) or yesterday. An unfinished today doesn't break
  the streak until IST midnight. It is computed on read from the last 400 days of `xp_day`. Past days are never
  re-judged.

### Class leaderboard
- `school_class.leaderboard_enabled`: **off by default**. It can be changed by anyone allowed to `PATCH /classes/{id}`
  today.
- It ranks the class's **active** students (active enrollment, active account) by **this week's XP in the class's
  subject**, floored at 0, highest first, then by display name. Ties share a rank (1, 1, 3). Students with 0 XP are
  listed last.
- **Students** see it only for a class they're actively enrolled in, while it's enabled and the class isn't
  archived. Otherwise they get 404. They see the whole list: rank, display name and weekly XP, with their own row
  marked. Students see no ids or usernames.
- **Staff** who can view the class always see it, whether it's on or off.
- It is never ranked by time spent and never crosses classes or schools.

### Errors
- `PUT /me/goals/{subject}`: 422 `goal_invalid` ("Pick 5–60, in steps of 5."). 422 `goal_below_class` ("Your
  teacher's goal is 15 XP; pick 15 or more."). 422 `no_class_for_subject` ("You're not in a class for this
  subject.").
- `PATCH /classes/{id}` with a bad `daily_goal`: 422 with the existing validation-error format.
- Student-only routes called by staff return the existing student-only error (as the learn routes do).

## UI / UX
### Student
- **Header chip** (AppShell, students only, every student page): a `Flame` icon with the streak count (muted when
  today isn't met yet) and "today XP / total of today's goals" (e.g. `🔥 4 · 22/30`). Skeleton while loading. On
  error it is hidden; it never blocks the page. At phone width it shows the flame and streak only. It must still fit
  at 360 px.
- **Chip popover** (tap or click; new `components/ui/popover.tsx` wrapping `radix-ui` Popover, so no new dependency):
  - Per subject with a goal: "Maths 12 / 15 XP" with a small bar (✓ once met).
  - "Streak: 4 days". If today isn't met: "Meet today's goals to make it 5".
  - "This week: 84 XP".
  - **My goals**: one select per subject (values from the class goal to 60), with the class goal shown as "Teacher:
    15". It saves on change and shows errors inline.
  - **Class leaderboard** links, one per class with it on → `/leaderboard/:classId`.
  - Empty state (no classes): "Join a class to get daily goals."
- **Award toast** (existing `sonner`): shown when an answer result carries `xp`, and the chip refreshes (invalidate
  the `["me","xp"]` query). Copy by grade:
  - perfect: "+6 XP · Perfect ×1.2"
  - passed: "+5 XP"
  - partial: "+1 XP · Partly right"
  - poor: "No XP this time"
  - rushed: "−1 XP · Answers were too fast to be real tries"
  - Hints (later): "· hints used" appended.
  - Plus "Daily goal met 🎉" the first time a day becomes met.
  - A resent or already-answered result never shows a second toast (the same event is returned, and the client
    dedupes by session id).
- **Leaderboard page** `/leaderboard/:classId`: class name, "This week (Mon–Sun)", a table of rank, name and XP with
  your own row highlighted. Empty state: "No XP yet this week." 404 shows "This leaderboard isn't available".
- **Practise again** screens show "Practice only, no XP".
- Course progress bars are unchanged: concepts learned.

### Teacher (ClassDetailPage, until spec 010)
- A **Motivation** card with:
  - a **Daily goal** select (5–60, step 5);
  - a **Class leaderboard** switch, with help text "Students in this class see a weekly XP ranking. Off by default.";
  - the leaderboard table (always visible to staff), with an "Off: students can't see this" badge when disabled.
- **Roster** gains columns **XP this week** (class subject) and **Streak**.

## Technical design
- Files / modules touched:
  - Backend (new): `app/services/xp.py` (pure `session_xp`, `is_rushed`, `ist_week_start`, `streak_from_days`;
    DB `award_for_session`, `summary`, `set_own_goal`, `leaderboard`, `roster_stats`), `app/schemas/xp.py`,
    `app/api/v1/xp.py` (`/me/xp`, `/me/goals/{subject}`, `/classes/{id}/leaderboard`, registered in `router.py`).
  - Backend (changed): `models/learning.py` (new models), `models/tenancy.py` (class columns),
    `services/kp_flow.py` (`answer_in_session` calls `xp.award_for_session` in the same transaction where it sets
    the session status; the stored and resent result path reads the existing event), `services/practice.py` (same
    for practice), `schemas/kp.py` (`AnswerResult.xp`), `schemas/tenancy.py` (`ClassPatch`/`ClassOut` +
    `daily_goal`, `leaderboard_enabled`; `ClassStudentOut` + `week_xp`, `streak_days`), `services/tenancy.py`
    (patch fields + roster stats; raising `daily_goal` raises today's `xp_day` rows for enrolled students),
    `tests/test_route_scoping.py` (new routes are scoped, none are global).
  - Migration `alembic/versions/0007_xp.py` with RLS enabled on every new table.
  - Frontend (new): `src/features/xp/{api.ts, XpChip.tsx, XpPopover.tsx, LeaderboardPage.tsx, awardToast.ts,
    MotivationCard.tsx}`, `src/components/ui/popover.tsx`. Changed: `components/layout/AppShell.tsx` (chip),
    the answer handlers in `features/learn/{QuestionStep,PracticeRunner,RemediationPage}.tsx` (toast),
    `PracticeStep.tsx` ("Practice only, no XP"), `features/classes/ClassDetailPage.tsx` (card + roster columns),
    `lib/types.ts`, and the router (`/leaderboard/:classId`, student guard).
  - Docs: ARCHITECTURE decision 5 (daily goal is per subject, default 15; repeats earn 0; the rush rule) and the
    domain model (`xp_event`, `xp_day`, `student_goal`, class columns). ROADMAP note: 008 shipped before 007.
- Data model changes (all tenant-owned: `TenantMixin`, composite FK `(student_id, org_id)` → `app_user`, RLS on):
  - `xp_event` (append-only): `id` bigint identity; `student_id`; `session_id` (composite FK → `practice_session`,
    **unique** where not null, nullable for 007's quiz events); `reason` enum `xp_reason` (`kp | remediation |
    practice`; 007 adds values); `concept_id` (content FK); `subject` (`class_subject` enum); `amount` smallint
    (CHECK between −100 and 500); `grade` enum `xp_grade` (`perfect | passed | partial | poor | rushed`);
    `base_minutes` numeric(5,1); `answered`, `rushed_count`, `hints` smallint; `day` date; `created_at`. Index
    `(org_id, student_id, day)`.
  - `xp_day`: PK `(student_id, day, subject)`; `xp` int; `goal` smallint null (CHECK 5–60); `met_at` timestamptz
    null; `updated_at`.
  - `student_goal`: PK `(student_id, subject)`; `goal` smallint (CHECK 5–60, `goal % 5 = 0`); `updated_at`.
  - `school_class`: `daily_goal smallint NOT NULL DEFAULT 15` (CHECK 5–60, %5 = 0), `leaderboard_enabled boolean
    NOT NULL DEFAULT false`.
- API / interfaces:
  - `GET /api/v1/me/xp` (student) → `XpSummary {today: [{subject, xp, goal|null, met}], streak: {days, today_met},
    week_xp, total_xp, goals: [{subject, class_goal, own_goal|null, effective}], leaderboards: [{class_id,
    class_name, subject}]}` (`xp`, `week_xp` and `total_xp` are floored at 0).
  - `PUT /api/v1/me/goals/{subject}` (student) `{goal: int | null}` → `XpSummary`.
  - `AnswerResult.xp: XpAwardOut | None = {amount, grade, base_minutes, hints, goal_met_today: bool}`. It is set
    only on the result whose answer ended the session, and on a resend of that answer.
  - `GET /api/v1/classes/{id}/leaderboard` → `{class_name, subject, enabled, week_start, rows: [{rank,
    display_name, week_xp, is_me}]}`. Staff rows also carry `student_id`.
  - `PATCH /api/v1/classes/{id}` accepts `daily_goal`, `leaderboard_enabled`. `ClassOut` returns both.
  - `GET /api/v1/classes/{id}/students` rows gain `week_xp`, `streak_days`.
  - Privacy: events and day rows hold ids, numbers and subject only. Nothing XP-related is logged with names, and
    the leaderboard shows display names to classmates only when the teacher turns it on.

## Edge cases
- The same answer is resent, or two tabs answer at once: the unique `session_id` on `xp_event` means at most one
  award. The losing writer reads the existing event and returns it.
- A session ends just after IST midnight: XP lands on the new day. A session left open earns nothing until it ends.
- A brush-up of a physics prerequisite done from a maths lesson: the XP goes to physics (the prerequisite's subject),
  even if the student has no physics class (then that row's goal is null).
- A student joins their first physics class mid-day: from their next award, today has a physics row with the goal,
  so today needs physics met too. If they never earn again today, today has no physics row and is judged on the
  rows it has.
- A teacher lowers the goal mid-day: today's snapshot is not lowered, and the new goal applies from tomorrow.
  Raising it raises today's rows, and days already met stay met.
- A student is unenrolled mid-week: they drop off that class's leaderboard, and their XP and streak are kept.
  Deactivated students are hidden from leaderboards.
- An archived class's leaderboard is 404 for students. Its goal no longer counts towards the student's goals.
- A penalty pushes today's subject XP below 0: it is shown as 0, and the ledger keeps the negative.
- An item's `expected_minutes` changes in a content update: later awards use the new value, and past events are
  never recomputed.
- A KP try ends by fail after 5 questions, 3 right: 3/5 ≥ half, so `partial` (×0.3). If 2 of the wrong answers were
  rushed, it is `rushed` instead.
- A single-answer practice item, wrong in 3 s, expected 2 min: rushed count 1 ≥ min(2, 1), so −1 XP.
- A code task failed, fixed and resubmitted: the failed session earns 0 (or −, if rushed), and the passing session
  earns `passed` ×1.0.

## Implementation notes
- The award is written by each answer path (`kp_flow.answer`, `kp_flow.remediation_answer`,
  `practice.practice_answer`) once the outcome is final, so an answer that ends a session because the question pool
  ran out (retired content) still earns. The stored-result path (`kp_flow._stored_result`) returns the existing event.
- `goal_met_today` isn't stored: the award and its `xp_day.met_at` share one timestamp, so "the day is met and its
  latest `met_at` is this event's `created_at`" gives the same answer on a resend.
- "Implementation tasks earn the most" holds within the Python course (a first-try code pass, 8 min → 10 XP, beats
  any Python KP try, at most 9). Across courses it doesn't: a maths KP of five 1–3 min items can earn 11.

## Out of scope
- Review and quiz XP, and the 150-XP quiz trigger (spec 007 adds ledger reasons and reads totals).
- The AI tutor and the hint UI (009 fills `hints_used`; the rule here already applies it).
- The at-risk rules and the full dashboard (010; the Motivation card may move there).
- XP for reading or the Learn check. XP for "Practise again". Backfilling past sessions.
- An XP history page or charts, badges, levels, achievements, streak freezes, weekend exemptions, and
  notifications or reminders.
- Leaderboards by time spent, all-time leaderboards, cross-class or cross-school leaderboards, and leagues.
- Teachers editing or granting XP. Per-school timezones (IST fixed, as in 005).

## Verification (end-to-end)
- [ ] Unit (`tests/test_xp_rules.py`, no DB), table-driven over `session_xp`:
      - perfect 2/2 at 1 min each → 2 × 1.2 = 2.4 → **2**.
      - pass after a miss, 4 × 1 min → **4**.
      - KP fail 3/5 right → partial, 5 × 0.3 = 1.5 → **2**.
      - fail 1/3 → **0**.
      - fail with 2 rushed → −0.25 × base, at least −1.
      - fast **correct** answers → no penalty.
      - practice code item 10 min, first-try pass → **12**; failed (not rushed) → **0** (never partial).
      - multistep time = sum of steps.
      - hints 1/2/4 → ×0.75 / ×0.5 / 0, and a positive product rounds to ≥ 1.
      - `is_rushed` at the 5 s floor and at 15%.
      - `streak_from_days` (gap, today unmet, today met, null-goal-only day, a met day that later went negative).
      - `ist_week_start` at the Sunday/Monday IST boundary.
      - **Implementation tasks earn the most**: a passed code item out-earns any KP try in the sample content.
- [ ] DB (`tests/test_xp_db.py`, `make test-db`):
      - ending a KP / brush-up / practice session writes one event and upserts `xp_day` for all goal subjects.
      - a concurrent double answer writes one event.
      - side-effect closes write none.
      - Practise again and staff previews write none.
      - goal snapshot: raise vs lower mid-day.
      - own goal below the class goal → 422 `goal_below_class`.
      - leaderboard: off → student 404, staff 200; on → ranked and tied, own subject only, unenrolled and deactivated
        students hidden; another school's class → 404.
      - roster columns.
      - `test_rls_db.py` passes for the new tables.
      - `test_route_scoping.py` covers the new routes.
- [ ] Frontend (vitest):
      - `XpChip` (loading, unmet and met flame, phone width).
      - `XpPopover` goal select (minimum = class goal, inline error).
      - award toast copy per grade, and no duplicate on resend.
      - `MotivationCard` switch and goal.
      - `LeaderboardPage` (own row highlighted, empty and 404).
- [ ] `make check` and `make test-db` are green. `cd backend && uv run mypy` and `cd frontend && pnpm typecheck`
      are clean.
- [ ] Manual (`make dev`, imported sample content, one school, a maths class with two students):
      1. As a teacher, open the class: goal 15 and leaderboard off by default. Set the goal to 20, switch the
         leaderboard on.
      2. As student A: the chip shows `🔥 0 · 0/20`. Pass a KP perfectly → toast "+N XP · Perfect ×1.2", and the
         chip updates.
      3. As student A: answer a KP wrong within 2 s twice until it fails → toast "−1 XP · Answers were too fast…".
      4. As student A: finish enough to reach 20 → "Daily goal met 🎉", and the flame lights.
      5. As student A: raise your own maths goal to 25 in the popover. Picking 15 shows the inline error.
      6. As student B: earn some XP. Both students see `/leaderboard/:classId` with ranks. The teacher switches it
         off → students get "This leaderboard isn't available", and the teacher still sees it with the "Off"
         badge.
      7. The roster shows XP this week and streak. Practise again on a learned concept shows "Practice only, no XP"
         and gives no toast.
      8. Change the system clock (or seed `xp_day` rows) to confirm that the streak counts yesterday and survives
         an unfinished today.
