# Spec 010: Teacher dashboard + assignments

Status: draft
PRD link: docs/PRD.md#mvp-scope-v1 (item 10; the leaderboard switch from item 7)
Builds on: [spec 002](002-auth-tenancy.md) (classes, enrolment, "teachers see the whole school"),
[spec 005](005-kp-flow-knowledge-graph.md) (KP sessions, remediations, frontier, CourseMap),
[spec 007](007-reviews-quizzes.md) (review cards, retrievability, last quiz),
[spec 008](008-xp-gamification.md) (XP ledger, Motivation card, roster columns),
[spec 009](009-ai-tutor.md) (tutor threads, hints, safety flags; transcripts are read here).

## Summary
The class page becomes a teacher dashboard with four tabs: **Overview** (weakest concepts, at-risk students,
misconception spread, hint use, flagged tutor chats, time in practice), **Students** (roster + a concept heatmap),
**Assignments** and **Settings** (daily goal, leaderboard switch). A teacher can open any student to see their
knowledge graph with a memory view, why they're at risk, recent activity, assignments and tutor transcripts.
Teachers **assign** one or more concepts with a due date to the whole class or chosen students; assigned students see
an "Assigned by your teacher" card at the top of their home with the path to the target (Focus Mode). Assignments set
priority and never cap what a student can learn.

## User stories
- As a teacher, I want to find my class's 3 weakest concepts in under a minute and assign one with a due date.
- As a teacher, I want to see which students are at risk and why, so I can help them this week.
- As a teacher, I want to see which misconceptions my class holds and who holds them.
- As a teacher, I want a class heatmap (students × concepts) and, per student, their graph with how well they
  remember each learned concept.
- As a teacher, I want to read a student's tutor chats and see flagged ones, and see how much they rely on hints.
- As a teacher, I want to assign targets to a re-teach group, not only the whole class.
- As a student, I want to see what my teacher assigned, when it's due, and what to do next to get there, while still
  being free to learn anything else on my frontier.

## Behaviour

### General
- Every teacher (staff) in the school can view every class's dashboard and every student in it, and create, edit and
  delete assignments in any class (spec 002: teachers see the whole school; `class_teacher` grants nothing extra).
- **Students in scope** of a class view = active enrolment in the class **and** account status active. Invited or
  deactivated students and removed enrolments are left out of every stat, list, heatmap row and at-risk check.
- **Class course** = the active course of the class's subject. All concept analytics use that course's concepts;
  cross-course prerequisites appear only in Focus paths and the per-student graph's prerequisite edges.
- **Subject filter**: every per-student number in a class view (at-risk rules except `inactive`, stats block,
  activity list, hint use, tutor threads, memory cards) counts only work on **concepts of the class course**; XP is
  filtered by `xp_event.subject` = the class subject (as 008's roster does). A maths teacher sees maths.
- **Removed students**: unenrolling still hard-deletes the `enrollment` row (spec 002), so a removed student is simply
  not in the class: 404 on their class student routes, absent everywhere. Their data stays on their account and
  reappears if they are re-enrolled.
- **Window** for analytics (picker on Overview and concept detail): `7d` (default), `30d`, `all`. `7d` = today (IST)
  and the 6 days before, from IST midnight; `30d` likewise. Stored in the URL (`?window=30d`). States ("now") — the
  heatmap, stuck counts, memory, assignment status — ignore the window.
- Teacher reads **never write** learning state: the dashboard computes statuses read-only (`frontier.load(...,
  promote=False)` semantics), counting an in-progress concept whose KPs and practice are all complete as learned, the
  same as `frontier.complete`.
- All dashboard queries are batched per endpoint (a fixed number of queries, no per-student loops). Budget: a class of
  60 students and a 40-concept course returns each endpoint in < 500 ms on the dev database.

### Concept statuses (heatmap and student graph)
Per student × concept, one of:
| State | Rule |
|---|---|
| `locked` | `frontier.concept_status` = locked |
| `ready` | ready (every direct prerequisite learned, not started) |
| `in_progress` | in progress, not stuck |
| `stuck` | in progress **and** (a KP of it is failed and not open (waiting), **or** an open remediation exists for one of its KPs) |
| `learned` | learned (stored, or complete per above); carries a **memory band** |

**Memory band** of a learned concept with a review card: retrievability `srs.retrievability(stability, last_review,
now)`: `strong` ≥ 0.9, `fading` 0.7–0.9, `weak` < 0.7. Learned concepts without a card (no gradable KP items) have
band `none`.

### Weakest concepts
- For each concept of the class course: **KP tries** = `practice_session` rows of kind `kp` for a KP of that concept,
  by in-scope students, status passed or failed, `ended_at` in the window. **Fail rate** = failed / ended.
- A concept qualifies when ≥ **3 distinct students** ended a KP try in the window.
- Rank: fail rate desc, then **stuck now** (students in state `stuck`) desc, then course order. Overview shows the top
  5 with fail rate, students tried, stuck now and % learned, plus an **Assign** button. "Show all" lists every
  concept of the course (unqualified ones show "Not enough tries yet" and sort last).
- Empty state: "Not enough practice yet to rank concepts. Check back after a few lessons."

### Concept detail (sheet opened from a weakest-concept row or a heatmap column header)
- Window-scoped: per KP: title, tries, fail rate. Per item (KP questions, practice items): a short prompt (from
  `item.public`, params left as template placeholders), answers, % correct, average time. Misconceptions of this
  concept (as in the next section).
- Now: student lists by state (stuck with reason "Waiting to retry" / "Brushing up X", in progress, learned, ready,
  locked counts). Buttons: **Assign this concept**.
- Never shows answer keys, correct option ids or solutions (`item.answer`).

### Misconception spread
- From `attempt.misconception_id` (MCQ distractors and Learn misconception checks) by in-scope students in the window.
- Per misconception of the class course: **chosen** = attempts with that `misconception_id`; **offered** = attempts on
  items whose answer spec has an option tagged with it (computed server side from `item.answer`); **rate** =
  chosen / offered; **students** = distinct students who chose it. Qualifies at offered ≥ 3.
- Overview lists the top 5 by students desc, then rate desc; "Show all" opens the full list. A row shows the
  misconception title, its concept, "chosen in 40% of answers (6 students)". Expanding it shows, per item, the
  prompt and the **chosen distractor's text only**, and the names of the students who chose it. **Assign** prefills
  the concept.
- Empty state: "No misconceptions picked up yet."

### At-risk rules (ARCHITECTURE decision 15, made concrete)
Always over the last 7 IST days (independent of the window picker). Constants in `app/services/dashboard.py`
(`AT_RISK_*`) so the pilot can tune them. A student is **at risk** if any rule fires; each firing rule is listed with
its numbers.
| Code | Fires when | Shown as |
|---|---|---|
| `kp_fail_rate` | failed KP tries / ended KP tries > 10 %, with ≥ 5 ended | "Failed 3 of 12 KP tries" |
| `negative_xp` | any `xp_event` with amount < 0 | "Lost XP for rushing (2×)" |
| `low_xp_rate` | net XP / active minutes < 0.5, with ≥ 30 active minutes (`study_time`, all activities) | "0.3 XP per active minute" |
| `falling_memory` | ≥ 2 review cards with retrievability < 0.7 on concepts that are a prerequisite (`concept_prereq.prereq_id`) of an active concept | "Weak memory: Linear equations, Ratios" |
| `overdue_assignment` | an assignment of theirs is overdue (below) | "Overdue: Pair of linear equations (due 3 Nov)" |
| `inactive` | no `attempt` and no `study_time` row in the 7 days, and enrolled in the class ≥ 7 days | "No activity for 7 days" |

`inactive` replaces "5 school days" with 7 calendar days, since the app has no school calendar (decided while
specifying). Overview lists at-risk students ordered by number of rules desc, then name; the Students tab shows an
"At risk" badge per row with the reasons in a tooltip/popover.

### Hint use and flagged chats
- **Hint use** (window): per in-scope student, charged hints (Σ `attempt.hints_used`), tutor chat messages (student
  rows, status pending/ok), questions answered, and **hints per 10 questions**. Overview card: class hints per 10
  questions and the top 3 students by hints per 10 questions (min 5 questions). Per concept hints appear in concept
  detail.
- **Flagged chats** (window): tutor threads of in-scope students containing a `flagged` message. Overview card shows
  the count and a list (student, concept, date) opening the thread. No notifications (out of scope).

### Time in practice
Overview shows the class's share of active time in practice vs learn (window, from `study_time.activity`), the PRD's
"≥ 60 % in practice" metric: "Practice 64 % · Learn 36 %".

### Per-student page
`/classes/:id/students/:studentId` (404 if the student has no enrollment in the class; a deactivated but still
enrolled student renders with a "Deactivated" badge).
- **Header**: name, at-risk reasons (or "On track"), XP this week, streak, reviews due, last quiz.
- **Stats (7 days)**: active minutes split learn/practice, KP fail rate, hints per 10 questions, concepts learned
  (course total).
- **Graph**: the class course as the student sees it (`CourseMap`), with a toggle **Progress** (the 5 states above,
  stuck shown as the existing waiting styling plus a marker) / **Memory** (learned nodes coloured by band; others
  greyed). The side panel shows KP statuses, fail counts, next review date and band. No Start/Continue buttons.
- **Assignments**: each of the student's assignments in this class with status (below) and next concept.
- **Recent activity**: last 50 ended sessions (KP try, brush-up, practice, review, quiz), newest first, with concept,
  outcome, XP (from `xp_event`), hints, questions answered, duration, date. "Load more" (cursor `before`).
- **Tutor threads**: threads (newest first) with concept / KP title, date, hints charged, chat count and a flag icon;
  opening one shows the messages in order (student text, "Asked for a hint", tutor reply, status labels for
  refused/safety/error). Purged text shows "Removed after 180 days". Read-only.

### Assignments
- An assignment belongs to one class: **1–10 concepts** of the class course, a **due date** (today IST to today + 180
  days), an optional **note** (≤ 200 chars, shown to students) and an **audience**: the whole class (default) or
  chosen students (1+ actively enrolled students of the class).
- Title (derived, not stored): the first concept's title, "+ N more" if more.
- The audience is evaluated live: whole-class assignments apply to students enrolled later; a student removed from
  the class (or from the chosen list) loses it. Deactivated students drop out.
- **Per student status** (computed on read, never stored):
  - **Done** when every active target concept is learned (the state above). `done_at` = the latest `learned_at` among
    them. `done_early` if `done_at` < the assignment's `created_at` ("Already learned"), `done_on_time` if `done_at`'s
    IST date ≤ due date, else `done_late`.
  - Otherwise `overdue` if today (IST) > due date, else `in_progress` if any target or path concept is started or
    learned since creation, else `not_started`. Progress = targets learned / targets.
  - A target relearned after a failed review (back to in progress) makes the assignment not done again; that's
    intended — the student must learn it again.
- Teachers can **edit** every field (targets, due date, note, audience) and **delete** an assignment (soft delete:
  `deleted_at`; it disappears for students and from at-risk). No undo in the UI.
- Retired target concepts are ignored. If none remain the teacher sees "Content no longer available" and students
  don't see it.
- Archived class: its assignments are hidden from students and from at-risk; the teacher can view but not create or
  edit (409 `class_archived`).

### Focus Mode (student)
- `GET /me/assignments` returns the student's assignments that are not deleted, in non-archived classes where they're
  actively enrolled and in the audience, excluding those **done more than 7 days ago** (by `done_at`) and
  `done_early` ones. Order: overdue first, then due date asc, then created asc.
- **Path** per assignment = the unlearned targets plus all their unlearned ancestors (transitive prerequisites, may
  cross courses), ordered as in `learn.build_outline` (prerequisites first). Each step: title, course, status
  (`in_progress`, `ready`, `locked`, waiting flag), and whether it is a target.
- **Next** = the first path step that's in progress and not waiting, else the first ready one, else none ("Waiting:
  retry tomorrow, or learn something else"). Its button links to the lesson.
- Assignments **never cap**: everything else on home, course pages and the map stays as it is.
- Done (within 7 days): the card shows "Done ✓" with the date and no path.

### Errors
- `POST/PATCH /classes/{id}/assignments`: 422 `assignment_invalid` with a message: "Pick 1 to 10 concepts.", "Pick a
  due date from today up to 6 months ahead.", "Notes can be up to 200 characters."; 422 `concept_not_in_course`
  ("These concepts aren't in this class's course."); 422 `students_not_in_class` ("Some students aren't in this
  class."); 409 `class_archived` ("This class is archived."). Unknown or other-school ids: 404.
- `GET /classes/{id}/students/{sid}…` where the student has no enrollment row in the class: 404.
- Staff-only routes called by students: 403 (existing `require_staff`). `/me/assignments` by staff: the existing
  student-only error.

### Precise rules (decided while specifying, builder check)
- **Transcripts**: any teacher of the school can read, through a class dashboard, the student's tutor threads on
  concepts of that class course. This narrows spec 009's note ("teachers of the student's classes may read
  transcripts") to the class subject; the tutor notice "Your teacher can read this chat" stays true.
- **Class subject changed** (`PATCH /classes/{id}` `subject`): assignment targets outside the new class course are
  treated like retired targets ("Content no longer available" when none remain). The subject change isn't blocked.
- **No active course** for the class subject: dashboard endpoints return empty states (no concepts); assignment
  create/edit returns 422 `concept_not_in_course`.
- **Complete but not promoted** concepts count as learned for their own state **and** for their dependants'
  ready/locked (teacher reads use an "effective learned" set). Their `done_at` contribution is `learned_at`, or if
  null the latest `kp_progress.passed_at` / passing practice session `ended_at`. `/me/assignments` is a student read
  and promotes and commits like `learn.student_courses`.
- **KP try** = a `kp` session that ended passed/failed **with at least one attempt row** (side-effect closes such as
  `kp_flow._end_active_kp_sessions` are excluded).
- **Question answered** = a distinct `(session_id, position)` plus each `learn`-context attempt. A multistep item counts
  once and is correct only when every step is. Hints per 10 questions is null when there are 0 questions.
- **Concept detail items**: attempts on the concept's items in every context (`learn`, `kp`, `remediation`,
  `practice`, `review`, `quiz`); the Learn check item is listed with the rest. Answers = questions answered (above);
  avg time = sum of step times. `ConceptDetail.kps[]` also carries `hints`.
- **Misconception "offered"** = a question answered (above) whose item has, in its answer spec or any multistep step,
  at least one option tagged with the misconception; counted once per question, all contexts. A misconception's
  **concept** is the concept of the items it was chosen on most (ties: course order); if never chosen, the concept
  of the items that offered it most. Concept detail lists every misconception offered on its items.
- **`falling_memory`** counts cards of concepts that are learned, not retired, in the class course and have at least
  one non-retired dependant (`concept_prereq`). Retrievability is computed at request time (`now`), not IST midnight.
- **Stuck reason** priority: an open remediation beats a waiting KP. Labels: `review_due` → "Brushing up X",
  `relearn` → "Relearning X", waiting KP → "Waiting to retry".
- **Assignment status**: `done` counts every done student (on time, late and already learned); `done_late` and
  `already_learned` are subsets. `in_progress` = not done and any target is in progress or learned, or any path
  concept is in progress; else `not_started` (no "since creation" rule). `AssignmentSummary.active` = not deleted and
  due date ≥ today (IST).
- **Focus path**: walk all ancestors of the targets (through learned ones, so an unlearned concept above a learned one
  after a relearn is included), keep the unlearned ones, order with `learn.build_outline` (targets in course order).
  Step `status` is `in_progress | stuck | ready | locked`. **Next** = the first `in_progress` step; if it is stuck by
  a `review_due` remediation, `next.brush_up_id` is set and the button goes to the brush-up; if it is only waiting,
  skip to the next candidate; else the first `ready` step; else null.
- **PATCH**: omitted fields are unchanged; `student_ids: null` means whole class (use `model_fields_set`). The due
  date is validated only when it changes. DELETE on an archived class is 409 `class_archived`. Duplicate concepts are
  de-duplicated silently; retired or out-of-course concepts are 422 `concept_not_in_course`. "6 months" = 180 days.
  The note is trimmed and an empty note becomes null.
- **Done more than 7 days ago** = `done_at` older than 7 × 24 h. Teachers see `student_ids` as stored (inactive or
  removed students marked in the UI); an assignment whose live audience is empty shows "No students" with total 0.
- Two classes of the same subject with assignments give one card per assignment (expected).
- A concept outside the class course on `/classes/{id}/concepts/...` is 404.
- The query-count test also covers the roster's new `at_risk` (reusing `xp.roster_stats`, `quiz.last_quiz_stats`,
  `srs.due_count`); `class_states` needs batched versions of `frontier._passes` and `open_remediations` (which use
  `scope.user.id`), with a **parity test** against `frontier.load` for one student over seeded states.

## UI / UX

### Teacher: class page with tabs
Nested routes under `/classes/:id` (`ClassLayout` with header + tab bar; tabs are links so they deep-link). The
param stays `:id`, and `/classes/:id/slips` (SlipsView) stays outside the layout. The layout header keeps the class
name, subject/grade, `TeachersRow`, View course and Add students; Edit and Archive move to Settings (decided while
specifying). Flagged chats open the student page with the thread pre-opened (`?thread=<id>`). "Assignments due soon"
= the next 3 with due date ≥ today, plus an "N overdue" badge; the Assignments tab's "Past" section = due date before
today. The assignment dialog lists only the class course's own concepts, from the existing outline endpoint with
borrowed cross-course concepts filtered out. In the student graph, Progress mode keeps the existing map styling (stuck
= the existing waiting styling); Memory mode uses the heatmap's three learned shades, so "heatmap matches the map" in
the manual check is about states, not colours.
- **Overview** (`/classes/:id`, default): window picker (7 d / 30 d / All) top right. Cards in this order:
  1. **Weakest concepts** (top 5 table: concept, fail rate, tried, stuck now, % learned, [Assign]). Row click → concept
     detail sheet.
  2. **At-risk students** (name, reason chips; click → student page). Empty: "No one is at risk this week. 🎉".
  3. **Misconceptions** (top 5, expandable).
  4. **Hint use** + **Flagged chats** (side by side on desktop).
  5. **Time in practice** + **Assignments due soon** (next 3 with done counts; link to tab).
  Skeletons while loading, an error card with "Try again" per card (one failing query doesn't blank the page).
  Empty class: "Add students to see how your class is doing." with the existing Add students button.
- **Students** (`/classes/:id/students`): the existing roster (with an At-risk column) and, below, the
  **heatmap**: rows students (sticky first column with names), columns concepts grouped by chapter (header: short
  title, % learned), defaulting to chapters of the class's grade with a "All chapters" toggle (decided while
  specifying). Cell colours: locked (muted), ready (outline), in progress (amber), stuck (red with a dot), learned
  (green; strong/fading/weak as three shades plus an icon for colour-blind users). A legend above. Cell hover/tap
  shows "Asha · Linear equations · Learned, memory fading". Column header click → concept detail; row → student page.
  Horizontal scroll on narrow screens.
- **Assignments** (`/classes/:id/assignments`): "New assignment" button; table of assignments (title, due,
  audience "Whole class" / "4 students", progress "18/25 done · 3 overdue", menu: Edit, Delete with
  `ConfirmDialog`). Past-due assignments in a collapsed "Past" section. Row → detail sheet: per-student status
  (Done on time / Done late / Already learned / x of y / Not started / Overdue) and next concept. Empty: "No
  assignments yet. Assign a concept from Overview or here."
- **Settings** (`/classes/:id/settings`): the existing `MotivationCard` (daily goal, leaderboard switch +
  table), and class edit/archive actions moved from the header if they live there today.
- **Assignment dialog** (create/edit; also opened by Assign buttons, prefilled): concept multi-select grouped by
  chapter with a chapter "select all" checkbox and a counter "3 of 10"; due date (`<input type="date">`, min today
  IST); audience radio "Whole class" / "Choose students" (checklist of active students with search); note textarea
  with counter. Inline validation and server errors via `FormError`.
- **Student page** (`/classes/:id/students/:studentId`): sections as in Behaviour; the graph is lazy-loaded as on
  the student course page; "Back to class" link.
- **Phones (360 px)**: desktop-first, but usable: cards stack, tables become stacked rows, the heatmap scrolls
  horizontally with the name column sticky, sheets are full screen.

### Student: Assigned card
On `StudentHome`, below `QuizBanner` and above `TodaysReviews`: a card "Assigned by your teacher" listing each
assignment: title, class name, due ("Due Fri 8 Nov" / "Overdue since 3 Nov" in warning colour / "Done ✓ 6 Nov"),
note, progress "1 of 2 concepts", the path as a compact step list (✓ for learned targets is not shown — only remaining
steps, max 5 then "+ N more"), and a **Continue: <concept>** button (or the waiting message). Hidden when the list is
empty or fails to load (it never blocks home).

## Technical design
- Files / modules touched:
  - Backend (new): `app/services/dashboard.py` (pure: `memory_band`, `heat_state`, `rank_weakest`,
    `at_risk_rules`, `misconception_rows`, window bounds; DB: `class_states` (batched statuses for many students,
    read-only), `overview`, `heatmap`, `concept_detail`, `misconceptions`, `student_detail`, `student_outline`,
    `student_activity`, `tutor_threads`, `tutor_thread`); `app/services/assignments.py` (pure: `assignment_status`,
    `focus_path`; DB: CRUD, `class_assignments`, `assignment_detail`, `my_assignments`); `app/schemas/dashboard.py`,
    `app/schemas/assignments.py`; `app/api/v1/dashboard.py`, `app/api/v1/assignments.py` (registered in
    `router.py`).
  - Backend (changed): `services/frontier.py` (factor the per-student status logic so `class_states` reuses it for
    many students without writing; keep `load` behaviour unchanged), `services/learn.py` (expose the graph/outline
    helpers the dashboard reuses: `_graph`, `build_outline`, `_ancestors` become public or get thin wrappers),
    `services/tenancy.py` (roster rows gain `at_risk: list[str]`), `schemas/tenancy.py` (`ClassStudentOut.at_risk`),
    `models/learning.py` (new models), `tests/test_route_scoping.py` (new routes are scoped; none global).
  - Migration `alembic/versions/0010_assignments.py`, RLS enabled on each new table.
  - Frontend (new): `src/features/dashboard/{api.ts, ClassLayout.tsx, OverviewTab.tsx, WindowPicker.tsx,
    WeakestConcepts.tsx, AtRiskList.tsx, MisconceptionList.tsx, HintUseCard.tsx, FlaggedChats.tsx, PracticeShare.tsx,
    ConceptDetailSheet.tsx, StudentsTab.tsx, Heatmap.tsx, SettingsTab.tsx, StudentPage.tsx, ActivityList.tsx,
    TutorThreads.tsx}`, `src/features/assignments/{api.ts, AssignmentsTab.tsx, AssignmentDialog.tsx,
    AssignmentDetailSheet.tsx, AssignedCard.tsx}`.
  - Frontend (changed): `routes.tsx` (nested class routes, student page), `features/classes/ClassDetailPage.tsx`
    (split into the tabs; roster moves to StudentsTab), `features/graph/{CourseMap,ConceptNode,ConceptPanel}.tsx`
    (optional `mode: "progress" | "memory"`, `memory` data, `stuck` state, `readOnly` panel without actions),
    `features/learn/StudentHome.tsx` (AssignedCard), `lib/types.ts`.
  - Docs: ARCHITECTURE domain model (`assignment`, `assignment_concept`, `assignment_student`), decisions 13 and 15
    (concrete rules, the `inactive` rule), boundaries (teacher reads are read-only); ROADMAP note "010 done".
- Data model changes (tenant-owned: `TenantMixin`, composite FKs, RLS on):
  - `assignment`: `id` uuid PK; `class_id` (composite FK `(class_id, org_id)` → `school_class`); `due_date` date;
    `note` text null (CHECK length ≤ 200); `all_students` boolean NOT NULL default true; `created_by` (composite FK →
    `app_user`); `created_at`, `updated_at`; `deleted_at` timestamptz null. Index `(org_id, class_id)` where
    `deleted_at IS NULL`.
  - `assignment_concept`: PK `(assignment_id, concept_id)`; `org_id`; composite FK `(assignment_id, org_id)` →
    `assignment` ON DELETE CASCADE; `concept_id` FK → `concept` (content); `position` smallint.
  - `assignment_student`: PK `(assignment_id, student_id)`; `org_id`; composite FKs to `assignment` (cascade) and
    `app_user`. Rows exist only when `all_students` is false (enforced in the service).
- API / interfaces (all under `/api/v1`, staff routes depend on `OrgScope` + `require_staff`; concepts are referenced
  by `course/concept` refs, as elsewhere):
  - `GET /classes/{id}/overview?window=7d|30d|all` → `ClassOverview {window, students_in_scope, weakest:
    [ConceptStat] (top 5), at_risk: [AtRiskRow], misconceptions: [MisconceptionStat] (top 5), hints: HintUse,
    flagged: [FlaggedThread], practice_share: {learn_seconds, practice_seconds}, assignments_due: [AssignmentSummary]
    (next 3)}`. `ConceptStat {concept, title, chapter, tries, students_tried, fail_rate|null, stuck_now,
    learned_pct}`. `AtRiskRow {student_id, display_name, reasons: [{code, detail}]}`.
  - `GET /classes/{id}/concepts?window=` → `[ConceptStat]` (all concepts, ranked).
  - `GET /classes/{id}/concepts/{course}/{concept}?window=` → `ConceptDetail {kps: [{title, tries, fail_rate}],
    items: [{prompt, kind, type, answers, correct_pct, avg_seconds}], misconceptions: [MisconceptionStat], students:
    {stuck: [{student_id, display_name, reason}], in_progress: [...], learned: [...], ready: int, locked: int}}`.
  - `GET /classes/{id}/misconceptions?window=` → `[MisconceptionStat {id, title, concept, chosen, offered, rate,
    students, items: [{prompt, chosen_text, student_names: [str]}]}]`.
  - `GET /classes/{id}/heatmap` → `{chapters: [{title, grade, concepts: [{concept, title, learned_pct}]}], students:
    [{student_id, display_name, cells: [{state, band|null}]}]}` (cells aligned to the flattened concept order).
  - `GET /classes/{id}/students/{sid}` → `StudentDetail {display_name, status (user status), at_risk, week_xp,
    streak_days, reviews_due, last_quiz, stats: {learn_seconds, practice_seconds, kp_fail_rate, hints_per_10,
    learned, total}, assignments: [StudentAssignmentRow]}`.
  - `GET /classes/{id}/students/{sid}/outline` → the existing `Outline` shape plus per concept `state` (5 states),
    `memory: {band, retrievability, next_due}|null` and `kps: [{title, status, fail_count, reopen_at}]`.
  - `GET /classes/{id}/students/{sid}/activity?before=<iso>` → `[ActivityRow {kind, concept, title, outcome, xp|null,
    hints, answered, seconds, ended_at}]` (≤ 50).
  - `GET /classes/{id}/students/{sid}/tutor` → `[ThreadRow {id, concept, kp_title, created_at, hints_used,
    chat_count, flagged}]`; `GET /classes/{id}/students/{sid}/tutor/{thread_id}` → `{messages: [{role, kind, text|null,
    status, purged, created_at}]}`. The thread must belong to that student (else 404).
  - `GET /classes/{id}/assignments` → `[AssignmentSummary {id, title, concepts: [{concept, title}], due_date, note,
    all_students, student_ids, counts: {done, done_late, already_learned, overdue, in_progress, not_started, total}, active: bool}]`.
  - `POST /classes/{id}/assignments` `{concepts: [ref], due_date, note?, student_ids: [uuid] | null}` →
    `AssignmentSummary` (201). `PATCH /classes/{id}/assignments/{aid}` (any subset) → `AssignmentSummary`. `DELETE
    …/{aid}` → 204. `GET …/{aid}` → `AssignmentSummary` + `students: [{student_id, display_name, status, done_at,
    learned, total, next: {concept, title}|null}]`.
  - `GET /me/assignments` (student) → `[MyAssignment {id, title, class_name, course (class course slug, the
    `:course` of lesson links), due_date, note, status, done_at, learned, total, path: [{concept, course, title,
    status, waiting, target}], next: {concept, course, title, brush_up_id|null}|null}]`.
  - `GET /classes/{id}/students` rows gain `at_risk: [code]`.
- Privacy: responses carry display names and ids only (no usernames outside the existing roster). Nothing here is
  sent to an AI model or logged with names. Transcript reads are not audited in v1 (see Out of scope).
- Caching: frontend TanStack Query `staleTime` 60 s for dashboard queries; assignment mutations invalidate
  `["classes", id, ...]` and `["me", "assignments"]`. No server cache or materialised tables in v1.

## Edge cases
- A class with no students / no activity: every card shows its empty state; heatmap shows "No students yet".
- A student in two classes of the same subject: appears in both dashboards with the same data; sees both classes'
  assignments.
- A student enrolled in a class whose course has concepts from other courses as prerequisites: heatmap shows only the
  class course; the student graph shows the course outline as the student sees it (cross-course prerequisites
  included, as in spec 005).
- A target concept's prerequisite is in another course the student has no class for: it's still reachable (spec 005
  `outline` includes ancestors), so it appears in the path and its lesson opens.
- A target already learned by everyone: the assignment is created; all students are "Already learned"; nobody sees a
  card.
- The due date is today: not overdue until IST midnight.
- An assignment edited after some students finished: statuses recompute; adding a new target can make a done student
  in progress again.
- A concept in progress but only waiting (failed KP, cooldown) is `stuck`; Focus "Next" skips it and shows the waiting
  message if nothing else is startable.
- A quiz is pending (spec 007 blocks new KP sessions): the Continue button still links to the lesson, which shows the
  existing quiz-pending panel.
- Review cards exist only for gradable concepts; a learned concept without one has band `none` (grey "no memory
  data").
- `fail_rate` with tries in the window but fewer than 3 students: shown in "Show all" as "Not enough tries yet".
- Content update changes an item's options: misconception stats use the stored `misconception_id`; `offered`
  uses the current answer spec (documented approximation).
- A purged tutor thread (180 days) still lists with counts; message text is null and shown as removed.
- Two teachers edit the same assignment: last write wins (no locking).

## Out of scope
- Teacher AI summaries and re-teaching notes (spec 011). Placement and teacher "mark learned" (spec 012).
- Teacher actions on a student's state (mark learned, reopen a waiting KP, reset), editing or granting XP.
- Notifications of any kind (email, push, in-app) for assignments, at-risk or flagged chats; reminders.
- An audit log of who read which transcript; teacher replies inside tutor threads.
- A cross-class teacher home, school-wide or cross-school analytics, class comparisons, CSV/PDF export.
- Per-item analytics pages beyond concept detail (v2 "analytics per KP and per question").
- Assigning concepts outside the class course, recurring assignments, assignment templates, a student "dismiss".
- Precomputed/materialised stats, background jobs.
- Badges for assignments, XP bonuses for on-time completion.

## Verification (end-to-end)
- [ ] Unit (`tests/test_dashboard_rules.py`, no DB):
      - `memory_band` at 0.9 / 0.7 boundaries; `heat_state` for each of the 5 states incl. stuck via waiting KP and via
        open remediation, and complete-but-not-promoted counted as learned.
      - `rank_weakest`: min 3 students, fail-rate order, tie by stuck then course order.
      - each `at_risk_rules` code at its threshold (10 % with 5 tries vs 4 tries; 0.5 XP/min with 30 vs 29 minutes;
        2 weak prerequisite cards vs 1 or a weak card on a leaf concept; `inactive` with enrolment < 7 days).
      - window bounds at IST midnight.
- [ ] Unit (`tests/test_assignment_rules.py`): `assignment_status` (done early / on time / late at the IST boundary /
      overdue / in progress / not started; a relearned target undoes done); `focus_path` ordering (prereqs first,
      cross-course ancestor, learned ancestors dropped) and `next` (in progress beats ready; waiting skipped; none).
- [ ] DB (`tests/test_dashboard_db.py`, `make test-db`): seeded class of 4 students with KP tries, a remediation, review
      cards, xp events (one negative), study_time, MCQ attempts with misconception ids, tutor threads (one flagged,
      one purged):
      - overview numbers match the seed; out-of-scope (deactivated, unenrolled) students excluded.
      - heatmap cells and bands; endpoint never writes (row counts of `concept_state` unchanged after a read where
        `frontier.load` would promote).
      - `class_states` parity with `frontier.load` for one student (waiting KP, open remediation, complete-but-not-
        promoted, relearn).
      - a fixed number of queries per endpoint regardless of student count (count via SQLAlchemy event listener, 4 vs
        40 students).
      - concept detail never includes `answer`/correct ids (assert keys); misconception expansion has distractor
        text only.
      - student routes 404 for a student of another class/school; thread of another student 404.
- [ ] DB (`tests/test_assignments_db.py`): create/edit/delete with each 422/409; chosen-student audience; late
      enrolment gets a whole-class assignment; `/me/assignments` filtering (deleted, archived class, removed student,
      done > 7 days, already learned) and order; overdue feeds the roster `at_risk`.
- [ ] `test_route_scoping.py` covers every new route; `test_rls_db.py` passes for the 3 new tables;
      `test_tenant_isolation_db.py` gains cases for a class and assignment of another school.
- [ ] Frontend (vitest): `Heatmap` (legend, cell labels, sticky names), `WindowPicker` (URL param), `AtRiskList`
      reasons, `MisconceptionList` expand, `AssignmentDialog` (chapter select-all, 10-concept limit, date min,
      choose-students, server error display), `AssignedCard` (overdue, done, waiting, + N more, hidden on error),
      `CourseMap` memory mode.
- [ ] `make check` and `make test-db` green; `cd backend && uv run mypy` and `cd frontend && pnpm typecheck` clean.
- [ ] Manual (`make dev`, imported sample content, one school, a maths class with 3 students who have done some
      lessons, including one forced KP fail ×2 and one rushed fail):
      1. As the teacher, open the class: Overview loads; with a stopwatch, name the 3 weakest concepts and click
         **Assign** on one, set a due date 3 days ahead, whole class → saved in < 1 min total.
      2. Switch the window to 30 d and All; the URL changes and numbers update.
      3. At-risk shows the rushing student ("Lost XP for rushing") and the KP-fail student.
      4. Expand a misconception: distractor text and names, no correct answer.
      5. Students tab: heatmap colours match each student's map; open a student → graph Progress/Memory toggle,
         activity, a tutor thread (and the flagged one from Overview).
      6. As a student: home shows "Assigned by your teacher" above reviews with the path and Continue; finish the
         target → card shows Done ✓; the teacher's assignment shows Done on time.
      7. Create a chosen-students assignment for one student; only that student sees it. Set a past due date via DB
         seed → Overdue on the card and `overdue_assignment` in at-risk.
      8. Settings tab: goal and leaderboard switch still work.
- [ ] Browser check: screenshots of Overview, heatmap, student page (both graph modes), assignment dialog, and the
      student AssignedCard at desktop and 360 px, plus the empty states (new class, no assignments).
