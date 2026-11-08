# Spec 012: Placement (covered chapters + adaptive diagnostic)

Status: built
PRD link: docs/PRD.md#mvp-scope-v1 (item 8) · ARCHITECTURE decision 12 · ROADMAP 012
Builds on: [spec 005](005-kp-flow-knowledge-graph.md) (concept_state, frontier, relearn),
[spec 006](006-practice-formats.md) (quick item types, grading), [spec 007](007-reviews-quizzes.md) (review cards,
the quiz's `practice_session` pattern), [spec 009](009-ai-tutor.md) (tutor threads), [spec 010](010-teacher-dashboard-assignments.md)
(class dashboard tabs, `frontier.class_states`, choosing students).

## Summary
On a new **Placement** tab of the class dashboard, a teacher ticks the chapters the class has already covered and
sends a placement check to the class or chosen students. Each student then takes a short **adaptive diagnostic**
(at most 25 untimed questions, no feedback until the end, an "I don't know" button, pause any time) over those
chapters and their prerequisites. At the end, concepts with enough evidence become **learned** (source `diagnostic`),
borderline ones become **conditionally learned** (an early first review), and lesson-learned concepts the student
clearly can't do are sent back to relearn.

## User stories
- As a teacher, I want to mark the chapters my class already covered so that students don't have to redo lessons
  they know.
- As a teacher, I want to send a placement check to the whole class or to chosen (e.g. new) students, see who has
  finished, and re-send it to one student if their result looks wrong.
- As a teacher, I want to see which concepts were placed only conditionally, so I know where placement is shaky.
- As a student, I want a short check that skips what I already know, without feeling graded or rushed.
- As a student, I want to see what I placed out of, and which concepts will come back for a check soon.

## Behaviour

### Terms
- **Covered chapters**: chapters of the class's current course (`class_view.class_course`) the teacher ticked.
  Stored per class; editable any time.
- **Range**: the concepts of the covered chapters **plus all their prerequisite ancestors** (`concept_prereq`,
  transitively, any chapter and any course), active (not retired) only. Frozen into the diagnostic when the student
  **starts** it (not when it's sent).
- **Askable**: a range concept with at least one active `kp_question` item of a quick type (`QUICK_TYPES`:
  numeric, expression, mcq). Code and multi-step items are never served in a diagnostic.
- **Evidence** `e[c]`: a number per range concept, kept on the diagnostic.

### Who can start what
- Placement is **teacher-started**. Nothing shows to a student until a teacher sends it.
- At most **one open** (`sent` or `active`) diagnostic per student × class (partial unique index). Sending to the
  whole class skips students who already have one (open, finished) for that class; the response says how many were
  sent and skipped.
- "One per student per class": a finished diagnostic is not offered again. The teacher can **re-send** to one student
  whose last one is finished or cancelled; that creates a new diagnostic (results already applied stay; the new run
  applies its own results on top, demotions included).
- The teacher can **cancel** a `sent` or `active` diagnostic. Cancelling discards it: nothing is applied (answers stay
  logged as attempts).
- **Unticking** a covered chapter never un-places anything. A diagnostic already started keeps its frozen range.
- Sending needs ≥ 1 covered chapter and ≥ 1 askable concept in the range, else 422 `Tick at least one covered
  chapter first.` / `These chapters have no questions a placement check can ask yet.`
- Only students enrolled in the class are offered or can answer; an unenrolled student's open diagnostic for that
  class is hidden and its endpoints return 404 (it stays open; the teacher can cancel it). Archived class: the same,
  and the Placement tab is read-only.

### Asking questions (the engine, a pure module)
State: the range graph (in-range edges with `encompassing_weight`), `e` per concept, `asked[c]` (direct questions so
far) and `direct_wrong[c]`.

- **Starting evidence**: 0 for every range concept, except concepts the student has **learned** (stored `learned`)
  start at **+1** (a prior, not a decision), so they need a direct question to be confirmed or demoted.
- **Correct answer on c**: `e[c] += 1`; each in-range ancestor `a` gets `+ w(a)`, where `w(a)` is the largest product
  of `encompassing_weight` along any path from c down to a (in-range edges only).
- **Wrong answer (or "I don't know") on c**: `e[c] -= 1`, `direct_wrong[c] += 1`; each in-range descendant `d` gets
  `−1` (you can't know a topic built on one you don't know).
- **Decided**: `e[c] ≥ 2` or `e[c] ≤ −1`, or `asked[c] = 2` (at most 2 direct questions per concept).
- **Next question**: among askable, undecided concepts, pick the one whose **worse** outcome makes the most
  progress: `min(progress if correct, progress if wrong)`, where progress sums, over the range's undecided
  concepts (itself included), 1 for each concept the outcome decides and otherwise the fraction of the way its
  evidence moves toward the threshold it heads for (2 up, −1 down). Ties → the concept nearest the middle of the
  range's outline order, then lowest id. With no answers this picks a mid-graph concept (around the upper middle of a
  chain), so the run behaves like a binary search along the graph. (Changed while building: the first draft's
  `0.5 × #decided if correct + 0.5 × #if wrong` always picked the most basic concept first, because one correct
  answer never decides anything.)
- **Item choice**: a random active quick `kp_question` of the concept, from its **last** KP for the first question and
  a different KP for the second (fall back to any KP); never an item already served in this diagnostic; a fresh
  random seed (`app.content.params.sample`). Stored on the session (`current_item_id`, `current_seed`,
  `current_position`, `current_served_at`) before it's returned, so reloads and other tabs get the same question.
- **End**: after the 25th answer, or as soon as no askable concept is undecided. The answer that ends it finishes
  and applies the diagnostic in the same transaction and returns `finished: true`.

### Applying the result (at finish, one transaction, advisory lock per student)
For each range concept, by final `e[c]`, against the student's **current** state (lessons keep working during a
diagnostic, so state may have moved):

| Final evidence | Current state | Result |
|---|---|---|
| `e ≥ 2` | not learned (no row, or in progress) | **learned**, `source = diagnostic`, `conditional = false`; review card first rating `Good` (due in ~2 days, like a lesson) |
| `1 ≤ e < 2` | not learned | **conditionally learned**: as above with `conditional = true`; first rating `Hard` (due tomorrow) |
| `e ≥ 1` | learned | unchanged (no conditional flag added to an earned concept) |
| `e ≤ −1` **and** `direct_wrong ≥ 1` | learned | **demoted**: the existing relearn (`kp_flow._relearn`: in progress, KPs reset with history kept, `relearn_count + 1`, open reviews closed); recorded as demoted |
| anything else | any | unchanged |

- **Ancestors are implied**: when c is placed (learned or conditional), every in-range ancestor that isn't learned
  and wasn't placed by its own evidence is placed too, as **conditional** (decided with the user). A demoted
  prerequisite leaves its learned dependants in place (stored rows win).
- Promotion goes through `frontier.mark_learned`, extended with `source`, `rating` and `conditional` and turned
  into an **upsert** (most range concepts have no `concept_state` row), so an in-progress concept's waiting
  remediations resolve and an existing card (from an earlier learn) is re-rated. KP progress and practice passes are
  **not** written; a stored `learned` row already wins in the frontier.
- A placed concept's lesson KP steps run as **real KP sessions, as today** (first-time XP on a pass, fails and
  remediations possible) while the concept stays learned, so a weak placement surfaces on its own (decided with the
  user).
- Promotion is applied in topological order (prerequisites first); demotions after promotions.
- No implicit credit, no XP, no `xp_day` change, no quiz mark change (as in Math Academy, the diagnostic earns no
  XP). A placed concept counts toward "3 learned concepts" for the quiz like any other learned concept.
- The finished diagnostic stores `results`: lists of learned, conditional and demoted concept ids, plus counts.

### Conditionally learned
- `concept_state.conditional = true` only from a diagnostic. Effect: its review card starts at `Hard` (due tomorrow,
  still subject to the daily cap of 5 scheduled reviews).
- It clears (becomes a normal learned concept) on its first review or brush-up outcome, a quiz miss, a relearn, or a
  later diagnostic giving it `e ≥ 2` (see Builder-check decisions). Conditional cards get no implicit credit. After that the normal 007 rules apply (a first failed review is `Again`, a 2nd consecutive one relearns).

### Taking it (student)
- No timer; `time_taken_ms` is logged per answer. No per-question feedback.
- **"I don't know"**: submits the question as wrong (`response = {idk: true}`, `correct = false`); no penalty beyond
  the evidence. (Decision 5's ban on "I don't know" is for XP sessions; a diagnostic earns no XP.)
- **Pause**: leaving keeps the diagnostic `active`; reopening shows the same question. No abandonment timeout.
- **Tutor off**: `diagnostic` is not in the tutor's `TUTOR_KINDS`, so the tutor endpoints already return 409
  `tutor_not_here` (no tutor.py change); the UI shows no tutor button.
- Doesn't block and isn't blocked by anything: a pending quiz doesn't stop it; KP, practice, review and quiz
  sessions keep working while one is active.
- Attempts: `context = diagnostic`, one row per answer, linked to the diagnostic's `practice_session` at its
  position. Not logged as `study_time` (it's assessment, not theory or practice) (decided while specifying).

### Errors (summary)
- A resent answer for an already answered position → the same "saved" response, like the quiz (idempotent, so a
  network retry of the final answer is safe); another session id or a future position → 409 `stale_question`.
- Start a cancelled/finished diagnostic → 409 `diagnostic_closed`; question/answer before start → 409
  `diagnostic_not_started`.
- Another school's or another student's diagnostic, class or student id → 404.
- Re-send when the student has an open one → 409 `diagnostic_open`; cancel a finished one → 409 `diagnostic_closed`.

## UI / UX

### Teacher: class dashboard → new **Placement** tab (after Assignments)
- **Covered chapters**: a checklist of the class course's chapters in outline order (grade shown), Save button.
  Below it the range preview: "N concepts will be checked (M of them prerequisites from earlier chapters or other
  courses)". Unsaved changes warn before leaving.
- **Send** button → dialog: whole class or chosen students (the student picker used by assignments). Disabled with a
  hint when no chapter is ticked. After sending: toast "Sent to 18 students (3 already had one)".
- **Status table**, one row per enrolled student: Not sent · Sent · In progress (`7 answered`) · Finished (date,
  `learned 5 · conditional 2 · demoted 1`) · Cancelled. Row actions: Cancel (sent/in progress), Re-send
  (finished/cancelled). Clicking a finished row opens a sheet listing the concepts by outcome.
- Empty states: no course for the class subject → "This class has no course yet"; no students → the roster link.
- The per-student knowledge graph and outline (010) mark placed concepts "Placed" and conditional ones "Placed ·
  check soon". Dashboard cards, the heatmap and AI summary facts count placed concepts as learned, unchanged.

### Student
- **Home**: a card above the assignment card while a diagnostic is `sent` or `active`: "Placement check · Maths.
  Your teacher wants to see what you already know so you can skip it. Up to 25 questions, no timer, no XP. You can
  pause any time." Button: Start / Continue (`7 answered`). One card per class with an open diagnostic.
- **/placement/:id**: one question at a time with the existing question components (numeric, expression, mcq), a
  "Question 8 · at most 25" counter (no progress bar toward a fixed length), Submit, "I don't know", and "Pause"
  (back home). After Submit: next question, no right/wrong shown.
- **Result** (`/placement/:id/result`): "You placed out of 6 concepts" with three lists: Learned, To check soon
  (conditional), To learn (demoted concepts included, no wording about demotion beyond "back to learn"). Button to
  the knowledge graph. No per-question right/wrong, no answers.
- Graph/outline: placed concepts get a "Placed" chip; conditional ones "Placed · check soon" until it clears.
- Errors: a cancelled diagnostic → "Your teacher cancelled this placement check" with a home link.

## Technical design
- Files / modules touched:
  - `backend/app/services/placement_engine.py` (new, pure: evidence updates, decided, next concept, item choice,
    final classification; no DB).
  - `backend/app/services/placement.py` (new: covered chapters, range, send/cancel/re-send, start, question,
    answer, finish/apply, teacher status; all through `OrgScope`).
  - `backend/app/api/v1/placement.py` (new: teacher routes under `/classes/{class_id}/placement` with
    `StaffScope`; student routes under `/diagnostics` with `Scope`), registered in `router.py`.
  - `backend/app/schemas/placement.py` (new).
  - `backend/app/models/learning.py`: new models, enum values, `ConceptState.conditional`.
  - `backend/app/services/frontier.py`: `mark_learned(scope, concept_id, *, source=lesson, rating=Good,
    conditional=False)`; `class_states` and the outline views expose `source`/`conditional`.
  - `backend/app/services/srs.py`: `on_learned(..., rating=Good, source=learned|placed)`; `apply_review` clears
    `conditional`. `kp_flow._relearn` clears it too.
  - `backend/app/services/tutor.py`: no change (`diagnostic` isn't a tutor kind).
  - `backend/app/services/dashboard.py`: exclude `context = diagnostic` attempts from accuracy, weakest concepts and
    misconception figures; count them as activity for the `inactive` rule; keep diagnostic sessions out of the
    activity feed (no `ACTIVITY_TITLES` entry needed while they're filtered).
  - Answer grading: reuse the quick-type grading path the quiz uses (`app/grading`, `params.sample`).
  - `backend/alembic/versions/0012_placement.py`.
  - Frontend: `frontend/src/features/placement/` (new: `api.ts`, `PlacementTab.tsx`, `SendPlacementDialog.tsx`,
    `PlacementResultSheet.tsx`, `PlacementCard.tsx`, `PlacementPage.tsx`, `PlacementResult.tsx`, tests);
    `dashboard/ClassLayout.tsx` (tab), `routes.tsx`, `features/learn/StudentHome` (card), the graph/outline chip.
  - Docs at ship: ARCHITECTURE decision 12 "Built in spec 012" + domain model (`class_covered_chapter`,
    `diagnostic_session`, `concept_state.conditional`); PRD item 8 link.
- Data model changes (migration 0012, RLS enabled on both new tables):
  - `class_covered_chapter(class_id, chapter_id, org_id, created_by, created_at)`: `TenantMixin`, PK
    `(class_id, chapter_id)`, composite FK `(class_id, org_id)` → `school_class`, content FK → `chapter`.
  - `diagnostic_session`: `TenantMixin`; `id`, `student_id` (composite FK), `class_id` (composite FK), `status`
    (`sent | active | finished | cancelled`), `sent_by` (composite FK → app_user), `sent_at`, `started_at`,
    `finished_at`, `cancelled_at`, `chapter_ids uuid[]` and `range_ids uuid[]` (frozen at start), `evidence` JSONB
    `{concept_id: {e, asked, wrong}}`, `served_item_ids uuid[]`, `answered` smallint, `results` JSONB (at finish).
    Partial unique index `(student_id, class_id) WHERE status IN ('sent','active')`; unique `(id, org_id)`.
  - `practice_session`: kind `diagnostic` with `diagnostic_id` (composite FK → `diagnostic_session`), the
    `kind_links` CHECK extended, unique on `diagnostic_id` where kind = diagnostic. Created at start.
  - `attempt_context` += `diagnostic`; the `session_iff_practice` CHECK includes it.
  - `concept_state.conditional boolean NOT NULL DEFAULT false`.
  - `review_source` += `placed` (the card's first log row for a placed concept).
- API / interfaces (`/api/v1`):

  | Route | Who | Body / response |
  |---|---|---|
  | `GET /classes/{id}/placement` | staff | `{chapters: [{id, slug, title, grade, covered}], range: {concepts, prereqs}, students: [{student_id, display_name, status, diagnostic_id, sent_at, started_at, finished_at, answered, counts}]}` |
  | `PUT /classes/{id}/placement/chapters` | staff | `{chapter_ids}` (must be chapters of the class course, else 422) → the same as GET |
  | `POST /classes/{id}/placement/send` | staff | `{all_students: bool, student_ids?: []}` → `{sent, skipped}` |
  | `POST /classes/{id}/placement/students/{sid}/resend` · `.../cancel` | staff | → the student's row |
  | `GET /classes/{id}/placement/students/{sid}` | staff | the latest diagnostic's outcome per concept (`learned`/`conditional`/`demoted`/`unchanged`) |
  | `GET /diagnostics/current` | student | open diagnostics: `[{id, course, subject, status, answered}]` |
  | `POST /diagnostics/{id}/start` | student | → state (idempotent when active) |
  | `GET /diagnostics/{id}/question` | student | `QuestionPublic` + `session_id`, `position` (from `item.public` only) |
  | `POST /diagnostics/{id}/answer` | student | `AnswerIn` or `{session_id, position, idk: true}` → `{finished, answered}` (no correctness) |
  | `GET /diagnostics/{id}/result` | student | `{learned: [ConceptRef], conditional: [...], to_learn: [...]}` (finished only) |

  All routes depend on `OrgScope` (route-walking test passes without exemptions). Student routes use `Scope` plus
  `learn._require_student` (staff → 403). The answer body is a separate `DiagnosticAnswerIn` (`session_id`,
  `position`, `time_taken_ms` required, plus either the shared answer fields or `idk: true`); the shared `AnswerIn` is
  unchanged.

## Edge cases
- Range concepts with no askable item are decided only by propagated evidence; the final table still applies.
- The range is all learned already: the run still asks (priors start at +1) and can demote.
- The student learns a range concept through a lesson mid-diagnostic: applied against the state at finish; it can be
  demoted only with a direct wrong answer and final `e ≤ −1`.
- A served item is retired or the concept leaves the course mid-run: the next GET serves a replacement at the same
  position (like KP sessions); the concept is dropped from the range if it has no askable item left.
- A student in two classes of the same course (rare): one diagnostic per class; each applies independently.
- Class subject changes after chapters were ticked: covered chapters of another course are ignored (and hidden);
  started diagnostics keep their range.
- Two tabs answer the same position: the second gets the first one's "saved" response (no second attempt row).
- Teacher cancels while the student is answering: the answer returns 409 `diagnostic_closed`; nothing is applied.
- Concurrency: start/answer/cancel lock the diagnostic row `FOR UPDATE`; finish also locks the student's range
  `concept_state` rows `FOR UPDATE` before applying. There is no per-student learning lock today and none is added
  (decided while specifying).

## Out of scope
- A student-started or self-retaken diagnostic; mandatory placement that blocks lessons.
- Placing individual KPs or marking KPs passed; per-KP diagnostics.
- A probabilistic (Bayesian/IRT) model; tuning thresholds from data (measure in the pilot).
- Teacher manual overrides per concept (`source = teacher`) and bulk "mark chapter learned" without a diagnostic.
- Timed diagnostics, per-question feedback or showing answers, XP for diagnostics.
- Code and multi-step items in diagnostics.
- Demoting via a failed KP in a dependant lesson; any extra "drop back" rule beyond the early first review.
- Placement data in AI summary facts beyond what learned states already contribute.
- An abandonment timeout for diagnostics left in progress.

## Builder-check decisions
Decided with the user: placed concepts' KP steps are real sessions; placing a concept implies its in-range
ancestors (conditional). Everything else below was decided while specifying.
- **Decided is recomputed** after every answer from the current evidence (not sticky); only the 2-question cap is
  permanent. A concept that becomes undecided again can be asked again if it's under the cap.
- **Next-question score** counts progress across the whole range (askable or not), including c itself and c
  reaching `asked = 2` (which decides it).
- **Running out of items**: a concept with no unserved quick item left stops being askable (so it can't block the
  end) and keeps its evidence.
- **Outline order** for the tie-break: the class course first, then other courses by slug; within a course by
  (chapter position, concept position).
- **"I don't know"** increments `asked[c]` and `direct_wrong[c]` like a wrong answer.
- **Empty range at start** (chapters unticked or content changed since sending): start finishes the diagnostic at
  once with 0 answers and empty results; the student sees "Nothing to check right now".
- **`practice_session` status**: `passed` on finish, `failed` on cancel.
- **Sending** skips students with an open or finished diagnostic for that class, for both the whole class and chosen
  students; a student whose last one was cancelled gets a new one. A finished one always needs Re-send.
- **Status row and `GET .../students/{sid}`** show the latest diagnostic's status, and the outcomes of the latest
  *finished* one (labelled with its date).
- **Promoting an in-progress concept** also ends its active KP and practice sessions (`failed`, no XP) and resolves
  open remediations created by its own KPs (outcome `relearned`), so a learned concept doesn't show "brush up".
- **`conditional` clears** on the first scheduled review or brush-up outcome on it (pass or fail), a quiz miss, a
  relearn, or a later diagnostic giving it `e ≥ 2`. Implicit credit doesn't clear it. Conditional cards receive no
  implicit credit (treated like struggling). "Learns it through the lesson" is dropped: a learned concept isn't
  re-promoted by `_on_kp_passed`.
- **Card logging**: both a new card and the re-rate of an existing card log `review_source = placed` (never
  `relearned`, so placement doesn't mark the student as struggling); the rating is `Hard` when conditional, else
  `Good`.
- **Student result lists**: "placed out of N" = learned + conditional; "To learn" = the range concepts left not
  learned (demoted included).
- **Analytics**: diagnostic attempts are excluded from accuracy and misconception figures and count as activity
  (see `dashboard.py` above).
- **Archived class**: teacher writes return the existing 409 `class_archived`. A subject change keeps old-course
  covered rows hidden (not deleted); `PUT chapters` replaces only the current course's rows.
- **`frontier.fetch`** also selects `source` and `conditional` (no extra query). A learned concept shows as
  complete in the outline whatever its `parts_passed`; the "Placed" chip shows while `source = diagnostic`, and
  "check soon" while `conditional`.
- **UI**: extract the assignments student picker into a shared component; `/placement/:id` is full-screen outside
  `AppShell` like `/quiz/:id`; the home card goes in `features/learn/StudentHome` and shows the class name when the
  student has two open diagnostics in the same subject.

## Implementation notes
- First commit on `feat/012-placement` also adds the untracked
  `docs/plans/implement-docs-specs-011-teacher-ai-ass-reflective-naur.md`.

## Verification (end-to-end)
- [ ] Engine unit tests (`backend/tests/test_placement_engine.py`): ancestor/descendant propagation with weights;
      the decided rule; next-concept choice on a chain and a diamond (first pick is mid-graph); 2-question cap;
      stop at 25 and when nothing askable is undecided; final classification table incl. "demote needs a direct
      wrong answer"; lesson-learned prior of +1; deterministic with a fixed RNG.
- [ ] DB tests (`backend/tests/test_placement_db.py`, `make test-db`): send to class skips existing; re-send and
      cancel rules; range = covered chapters + cross-course ancestors, frozen at start; answers never return
      correctness or `item.answer`; finish promotes (source, conditional, card due tomorrow for `Hard`, ~2 days for
      `Good`, `review_log.source = placed`), demotes through relearn, writes no XP; conditional clears on the first
      review; tutor rejects diagnostic sessions; a cross-school class/student/diagnostic id → 404; unenrolled → 404.
- [ ] `tests/test_rls_db.py` and `tests/test_route_scoping.py` pass with the new tables and routes.
- [ ] Frontend tests (`frontend/src/features/placement/*.test.tsx`): tab saves chapters and sends; status table
      states and actions; home card; question page (no feedback, IDK, pause); result lists.
- [ ] `make check`, `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`.
- [ ] Browser check: `make dev`; as a teacher tick 2 maths chapters, send to the class; as a student start, answer
      some correctly and some with "I don't know", pause and resume on the same question, finish; see the result
      and the "Placed · check soon" chips; as the teacher see the finished row, its sheet, and the chip in the
      student's graph; cancel and re-send for another student. Screenshots of the tab, the question page, the
      result, the empty "no chapters" state and the cancelled-diagnostic message.
