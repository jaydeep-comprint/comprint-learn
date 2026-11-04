# Spec 005: KP flow + knowledge graph

Status: draft
PRD link: docs/PRD.md#mvp-scope-v1 (item 5; Phase 1 of docs/ROADMAP.md)
Builds on: [spec 004](004-learn-layer.md) (Learn layer). Research: [COMPETITOR-INSIGHTS](../research/COMPETITOR-INSIGHTS.md) (Math Academy).

## Summary
Each knowledge point (KP) in a lesson is now followed by its **questions**, served one at a time: 2 right in a row
passes the KP, and 3 wrong in a row (or 5 questions without passing) fails it. A failed KP ends the lesson. It reopens
with new questions once the student has done other work or the next day comes. A **second** fail at the same KP sends
the student to a short review of the KP's key prerequisites, and to relearning a prerequisite if that review fails too.
A concept is **learned** when every KP passes, and "learned" replaces 004's "finished" as the gate that opens dependants
(the knowledge frontier). The course page gets a **Map** view: a React Flow graph with 4 states, a KP progress fill
on each node, and click-to-highlight of prerequisites. To make this run end to end, 005 builds the server graders
for **numeric, expression and MCQ** items. Code items stay out of KP draws until 006.

## User stories
- As a student, I want to practise straight after each worked example and get the solution after every answer, so I
  learn from mistakes while the example is fresh.
- As a student, I want a failed step to come back later with different questions, so a bad moment doesn't block me
  and I can't just memorise answers.
- As a student who keeps failing the same step, I want to be sent back to the earlier idea it depends on, so I fix the
  real gap.
- As a student, I want to choose what to learn next from everything I've unlocked, and see on a map how concepts
  connect and which ones I still need.
- As a teacher, I want to preview a lesson's questions without anything being stored.
- As our team, I want every answer, seed, KP outcome and remediation stored (ARCHITECTURE decision 16), so 008 can
  award XP (and negative XP for failed KPs) and 010 can show fail rates.

## Behaviour

### Terms
- **KP session**: one try at one KP: a run of questions ending in `passed` or `failed`.
- **Remediation review**: a short question session on a key prerequisite concept, created by repeated KP fails.
- **Open KP**: a KP whose questions the student may start now (rules below).

### Lesson steps (replaces 004's step list)
`intro` → `check` → for each active KP in position order: `kp:<slug>` (worked example) → `kpq:<slug>` (questions).
- Navigation is as in 004 (Back always works; jump up to furthest reached + 1), plus: **Next on a `kpq` step is
  enabled only once that KP is passed**, and the step indicator doesn't allow jumping past an unpassed `kpq` step.
- The server refuses to start KP n's questions until KP n−1 is passed (409 `kp_order`) and, if the concept has a
  check, until the check is answered (409 `check_first`).
- 004's `lesson_progress.finished_at` rule is kept as-is ("Learn layer read": check answered + all `kp:` steps seen)
  for analytics only. It **no longer gates anything**. `kpq:` steps are recorded in `seen_steps` like any other step,
  but `finished_at` doesn't need them.
- **Resume**: opening an in-progress lesson goes to the first step that isn't done: an active KP session resumes at
  its `kpq` step with the *same* current question. A failed KP that isn't open yet shows the **waiting panel**
  (UI). Otherwise the lesson resumes at `last_step`, as in 004.
- **Learned concept**: opens in review mode (all `intro`/`check`/`kp:` steps readable, and each `kpq:` step shows
  "Passed ✓" with no questions). Re-practice belongs to reviews (007).

### KP questions: serving
- **Pool** = the KP's active items of kind `kp_question` whose type is `numeric`, `expression` or `mcq`. Code (and any
  multistep) items are skipped until 006. Pool order for a student is `shuffled_order` over item ids, seeded by
  `(student_id, kp_id)` (stable, like the 004 option shuffle).
- **Choosing the next item** (deterministic given the student's history):
  1. Never an item already served in this session, while unserved ones remain.
  2. Prefer items this student has **never** answered for this KP (any session), then the least recently answered.
  3. Ties broken by the shuffled pool order.
  4. If every item has been served in this session (tiny pools), param items may be served again, but fixed items
     never repeat within a session.
- **Seeds**: every serve of a param item draws a fresh seed (`secrets.randbelow(2**31)`), so a retry or a repeated item
  has new numbers. Prompts are rendered server side with `params.render(prompt, params.sample(item, seed))`.
- The served question (item, seed, position) is stored on the session before it's returned, so reloads and other tabs
  get the **same** question. Re-rolling by reloading is impossible.
- If the current item is retired mid-session, the next GET serves a replacement at the same position.

### KP questions: pass / fail rule (Math Academy)
Answers within one KP session, in order:
- **Pass**: the last 2 answers are correct (minimum 2 questions).
- **Fail**: the last 3 answers are wrong, **or** 5 answers have been given without passing.
- Otherwise serve another question. Examples: `CC` pass@2 · `WCC` pass@3 · `CWCC` pass@4 · `WWCC` pass@4 ·
  `WWW` fail@3 · `CWWW` fail@4 · `WCWCW` fail@5 · `CWCWC` fail@5.
- Implemented as a pure function `kp_outcome(results: Sequence[bool]) -> "active" | "passed" | "failed"`.
- The session's outcome is final. A failed session's negative XP is applied by spec 008 (005 stores the outcome
  only, with no XP).

### After each answer
- The response carries `correct`, the **correct answer for this student's numbers** (numeric: formatted value + unit;
  expression: LaTeX; MCQ: the positional id), the rendered `explanation_md` (if authored), the misconception `title`
  for a tagged wrong MCQ option, an optional `note` (e.g. "Give 3 significant figures"), and the session status.
- The student then presses **Next question**, or **Continue** on pass/fail. Showing the answer leaks nothing, because
  the next question is always another item or another seed.

### KP passed / failed
- **Pass**: `kp_progress.status = passed`, `passed_at` set. If it was the concept's last unpassed active KP, the
  concept becomes **learned** (`concept_state.status = learned`, `learned_at`, `source = lesson`), and the lesson shows
  the learned screen with the newly unlocked concepts.
- **Fail**: the lesson ends and the **failed screen** shows. `kp_progress.status = failed`, `fail_count += 1`,
  `failed_at = now`, `reopen_at = next 00:00 Asia/Kolkata` (fixed timezone for the CBSE pilot; a per-school timezone is
  out of scope). KPs already passed in this concept stay passed.
- **Reopening** (Math Academy's "do other tasks, then retry"): a failed KP is **open** when every remediation it
  triggered is resolved **and** at least one of these holds:
  - `now >= reopen_at`;
  - since `failed_at` the student passed a KP session in a **different** concept;
  - since `failed_at` the student passed a remediation review.
  Reopening is computed on read, so nothing is scheduled. A reopened KP starts a new session at its `kp:` worked
  example (shown again, and the student moves on to the questions).

### Remediation (2nd fail and every fail after it)
- On a fail that brings `fail_count` to ≥ 2, create one **remediation** per active key prerequisite of the KP
  (`kp_key_prereq`; borrowed cross-course concepts included). Skip a prerequisite that already has an unresolved
  remediation for this KP. A KP with no key prerequisites just follows the normal reopen rule.
- **If the key prerequisite is currently learned** → a remediation **review** is due: 3–5 mixed questions drawn
  round-robin across the prereq's active KPs (each KP's pool chosen by the same serving rules, fresh seeds). It is
  judged on the trend:
  - **Pass**: ≥ 3 answers, at least 2 of the last 3 correct, and the last one correct.
  - **Fail**: the last 3 are wrong, or 5 answers without passing.
  - Examples: `CCC`/`CWC`/`WCC` pass@3 · `CCWC` pass@4 · `WWW` fail@3 · `CCWWC` fail@5.
  - Pure function `review_outcome(results) -> "active" | "passed" | "failed"`.
- **Review passed** → remediation `resolved` (outcome `review_passed`).
- **Review failed** → **relearn**: the prereq's `concept_state` goes back to `in_progress` (`learned_at` cleared,
  `relearn_count += 1`), and all of its `kp_progress` rows reset to `not_started` with `fail_count` 0 (attempt history
  kept). The remediation stays open (outcome `relearn`) until the prereq is learned again, then it resolves.
- **If the key prerequisite isn't learned** at that moment (e.g. it's already being relearned) → the remediation
  starts in `relearn` straight away.
- **Never re-lock**: concepts that are in progress or learned never become locked because a prerequisite is being
  relearned (004 rule). New concepts whose prerequisite is being relearned are locked as usual.
- Remediation reviews don't change the prereq's learned state when passed, and aren't FSRS reviews. Spec 007 will
  fold them into its review queue.

### Concept states and the frontier (replaces 004's statuses)
Per student × concept (`concept_state` row or computed):
- **learned**: row with `status = learned`.
- **in progress**: row with `status = in_progress`. It's created the first time the student opens the lesson (first
  progress POST, as 004 did with `lesson_progress`).
- **ready**: no row, and every direct prerequisite (any course) is learned. **Frontier** = ready ∪ in progress.
- **locked**: otherwise.
- Only `in_progress` / `learned` are stored; `ready` / `locked` are computed (as in 004). `source` is `lesson` in 005;
  012 adds `diagnostic`, and 010 may add `teacher`.
- A learned concept stays learned when content adds a KP. A retired KP no longer counts toward "every KP passed". An
  in-progress concept that gains a KP must pass it too.
- Course progress = learned concepts / outline size (borrowed included; progress is shared across courses as in 004).

### Grading (server side, `app/grading/`; 006 extends it)
All checking is server side. Answer specs never reach the client (CLAUDE.md rule). Inputs are strings, at most 200
characters (longer → 422 `invalid_response`).
- **numeric** (the student types a number only, and the unit is shown next to the box from `public.unit`; unit entry is
  006):
  - Accepted forms: optional sign, digits, optional `.` decimals, optional exponent `e±n`, `E±n`, `×10^n`, `x10^n`,
    `*10^n`. Spaces trimmed, a thousands separator `,` rejected. Anything else → `correct: false` with the note "Enter a
    number, e.g. 12.5 or 3.0e8" (it still counts as an answer, so no "I don't know" loophole).
  - `exact`: the decimal value equals the answer exactly (`8`, `8.0`, `8.00` all correct).
  - `sigfig` (**strict**): the input must have exactly `sigfigs` significant figures **and** equal the answer rounded
    to `sigfigs`. Trailing zeros after a decimal point count. An integer with trailing zeros (`270`) matches if its
    s.f. count is ambiguous and could be `sigfigs`. The right rounded value with the wrong s.f. count → wrong, note
    "Give N significant figures".
  - `tolerance`: `|x − v| ≤ rel_tol·|v|` or `≤ abs_tol`.
  - `sci_notation: true`: the input must also be written as `a×10^n` / `aen` with `1 ≤ |a| < 10`, or it's wrong with
    the note "Write it in scientific notation".
- **expression**: parsed with the app's own safe AST walker (`app.content.params.parse`, never `sympy.parse_expr`,
  which evals), allowed names = the spec's `variables` plus `pi`, `E` and the whitelisted functions. Before parsing:
  `^` → `**`, and implicit multiplication is inserted for number·name, name·`(`, `)`·`(` and `)`·name (`2x`,
  `3(x+1)`, `(x+1)(x-1)`). Unknown name, bad syntax or > 200 chars → wrong, with the note "Couldn't read that
  expression". Params/derived are substituted into the answer value first.
  - `exact`: `sympify` forms equal structurally after automatic canonicalisation (no simplify).
  - `equivalent`: `simplify(student − answer) == 0`, with a fallback numeric check at 5 random points per variable
    (tolerance 1e-9) if simplify times out (budget 1 s per check, run with a time limit).
  - `simplified`: equivalent **and** `count_ops(student) ≤ count_ops(simplify(answer))`. Equivalent but unsimplified
    → wrong, note "Simplify your answer".
- **mcq**: positional ids `"1".."n"` in the order shown, mapped back on the server (reuse `_ShownOptions` from
  `app/services/learn.py`, moved to `app/grading/mcq.py`). Shuffle order = `shuffled_order(student_id, item_id)`.
  Unknown id → 422 `invalid_option`.
- Pure functions: `grade(item_answer_doc, values, response) -> GradeResult{correct, display_answer, note,
  misconception_id}` per type, with no DB access.

### Time logging
- `study_time` gets a new activity `practice`. `kpq:<slug>` steps and remediation sessions (step `remediation`,
  `concept_id` = the prereq) log active seconds with it, using the existing 004 timer and clamp rules. `learn` stays
  for `intro`/`check`/`kp:` steps. This feeds the PRD's "≥ 60% of time in practice" metric.
- Each answer stores `time_taken_ms` (0–1,800,000, clamped) from when that question was shown.

### Staff preview
- `kpq` steps are answerable: GET returns a random pool item with a random seed, plus that `item_id`/`seed`; POST
  (staff only) sends them back and gets the full result. Writes nothing, and there's no pass/fail tracking. The UI shows
  "Another question". `kp_order`/`check_first`/reopen rules don't apply to staff.
- The Map view for staff shows the graph without states, fills or student panels (node click → "Preview lesson").

### Access rules
Same as 004 (404 outside the student's courses, 403 `concept_locked` with the direct prerequisites that aren't
learned yet, now listing status `learned|in_progress|ready|locked`). KP/remediation endpoints add:
- 409 `kp_order`, 409 `check_first`, 409 `kp_passed` (already passed), 409 `kp_waiting` `{reopen_at,
  remediations: [{id, concept: {id, title}, kind: "review"|"relearn"}]}`.
- A remediation id belonging to another student/school → 404 (`OrgScope` + `student_id`).

## UI / UX
Existing shell, shadcn/ui, Tailwind, mobile first. Builds on the 004 components.

- **Student home** (`/`), with **no auto-pick**: the student chooses. 004's "Continue" button is removed. One card per
  course: title, progress bar "N of M concepts learned", then up to four short lists (each hidden when empty):
  - **Brush up**: due remediation reviews: "Brush up on {prereq}, needed for {concept}" → remediation page. Relearn
    remediations show as "Relearn {prereq}" → that lesson.
  - **In progress**: in-progress concepts with an open KP (or unanswered steps), with KP progress "2 of 3 parts".
  - **Ready to learn**: ready concepts in outline order (first 5, then "See all on the map").
  - **Waiting**: concepts whose next KP is failed and not open: "Retry tomorrow, or after you learn something else".
  - Empty / loading / error states as in 004. If every concept is learned: "You've learned everything in this course".
- **Course page** (`/learn/:course`): a **List | Map** segmented toggle (choice kept in `localStorage`, wrapped in
  try/catch). Default **Map on ≥ 768 px, List below**. The List is 004's list with the new statuses (learned ✓, in
  progress half-ring with "2/3", ready open circle, locked padlock) plus a small clock badge on waiting concepts and
  a "Brush up" badge where a remediation is due. The locked sheet now reads "Learn these first".
- **Map view** (`@xyflow/react`, lazily imported so the list never loads it):
  - Nodes = the outline's concepts (borrowed included). Edges = prerequisite → dependant (arrowheads), drawn only
    between nodes in the outline.
  - **Layout computed by us** (no dagre): layer = longest path from a root among outline concepts. Within a layer, nodes
    are ordered by outline index, top-to-bottom layers (prerequisites above), fixed node size (200×64), with gaps
    48 px horizontal and 72 px vertical. Pure function `layoutGraph(concepts, edges) -> {id, x, y}[]`.
  - **4 states** (colour + icon + text, never colour alone): locked (grey, padlock), ready (blue outline, open circle),
    in progress (amber, half-ring), learned (green, check). **Progress fill**: a bar across the node's bottom edge
    filled to passed KPs / active KPs. Waiting and "brush up" badges as in the list.
  - **Click / tap a node**: it and all its ancestors are highlighted (direct prerequisites and their edges at full
    strength, more distant ancestors at medium), everything else is dimmed to 30%. A **panel** opens (side panel on
    desktop, bottom sheet on phones): title, summary, status, "Part 2 of 3", the prerequisites that aren't learned
    yet (if locked), and a primary button: **Start** / **Continue** / **Review** / **Brush up first** / disabled
    "Locked". Click on the background or Esc → clear.
  - Controls: zoom buttons, fit view on load, pan; no minimap. Nodes aren't draggable. Keyboard: Tab through nodes,
    Enter = select. The List view is the accessible alternative (a link "View as list" is at the top of the Map for
    screen readers).
- **Lesson page**:
  - The step indicator now shows `Intro · Check · 1 · 1✎ · 2 · 2✎ …` on desktop ("Step 4 of 8" on phones); passed
    question steps get a ✓.
  - **Question step** (`kpq`): header "Practice · {KP title}" and a row of dots for this session's answers (green/red,
    current one hollow). Then the rendered prompt and the input:
    - numeric: a text box with `inputmode="decimal"` and the unit as a suffix label;
    - expression: a text box with a live KaTeX preview of what was typed (client-side rendering only, no grading),
      and the hint "Use ^ for powers, e.g. 3x^2 + 2";
    - mcq: 004's radio cards.
    - Submit is disabled until there's input, with a spinner while submitting.
  - After an answer: a result panel "Correct!" / "Not quite", any note, "Answer: {display}", the misconception title
    if tagged, and the explanation. Then **Next question**, or on pass a banner "Part passed ✓" + **Continue**, or on
    fail → failed screen. Focus moves to the panel.
  - **Failed screen**: "Let's come back to this" + "{KP title} will reopen with new questions tomorrow, or sooner once
    you learn something else." If remediation was created: "First, brush up on {prereq}" (button). Then "Back to
    course" and up to 3 ready concepts to pick.
  - **Waiting panel** (opening a lesson whose next KP isn't open): the same message, with the worked examples still
    readable via the step indicator.
  - **Learned screen** (replaces "Lesson finished"): "Concept learned ✓", "You unlocked: …" (newly ready concepts as
    buttons, or "Nothing new unlocked"), and "Back to course".
- **Remediation page** (`/learn/brush-up/:id`): header "Brush up: {prereq title}", subtitle "Needed for {concept}",
  then question steps like `kpq` (3–5 questions, dots). On pass: "Nice, {KP title} is open again" → button to the
  lesson. On fail: "Let's relearn {prereq} first" → its lesson. The prereq's worked examples are linked ("Look back
  at the lesson", opens the prereq lesson in review mode in the same tab; the session resumes on return).
- Staff: preview banner as in 004; questions show "Another question" instead of dots/pass logic.
- Errors: question load failure → retry state. Submit failure → toast "Couldn't submit, try again", input kept.
  409 on start → the matching panel (waiting / order / check first) rather than a toast.

## Technical design
- Files / modules touched:
  - Backend (new)
    - `app/grading/__init__.py` (`grade(...)` dispatch, `GradeResult`), `app/grading/numeric.py` (parser, s.f.
      counter, modes), `app/grading/expression.py` (preprocess + safe parse + modes with time limit),
      `app/grading/mcq.py` (`ShownOptions`, moved from `services/learn.py`).
    - `app/services/kp_flow.py`: pure `kp_outcome`, `review_outcome`, `choose_next_item(pool, history, served)`,
      `is_open(kp_progress, remediations, events, now)`, `next_midnight_ist(now)`; DB services
      `current_question(scope, ref, kp)`, `answer(scope, ref, kp, position, response, time_taken_ms)`,
      `remediation_question(scope, id)`, `remediation_answer(...)`, `_on_kp_passed`, `_on_kp_failed`, `_relearn`.
    - `app/services/frontier.py`: `concept_statuses(scope, concept_ids)` (one query each for `concept_state`,
      `kp_progress`, open sessions/remediations; no N+1) used by outline, home, lesson and graph.
    - `app/schemas/kp.py`: `QuestionPublic {session_id|null, position, item_id, type, prompt_md, unit|null,
      options|null, variables|null, results: [bool], preview_seed|null}`, `AnswerIn {position, response: str,
      time_taken_ms, item_id?, seed?}`, `AnswerResult {correct, display_answer, explanation_md, misconception,
      note, session_status, already_answered}`, `KpWaiting`, `RemediationOut`.
    - `app/api/v1/kp.py`: routes below, all `OrgScope` (no new `GLOBAL_CONTENT` exemptions).
    - `alembic/versions/0005_kp_flow.py` (below).
  - Backend (edit): `app/models/learning.py` (new models + enum values), `app/services/learn.py` (statuses from
    `frontier.py`, new step list, gate = learned, `concept_state` row created where 004 created `lesson_progress`;
    "finished" fields renamed), `app/schemas/learn.py` (`LessonStatus = learned|in_progress|ready|locked`; outline
    concept gains `kps_passed`, `kps_total`, `waiting: {reopen_at}|null`, `brush_up: bool`; `StudentCourse` drops
    `continue`, gains `learned`, `brush_up[]`, `in_progress[]`, `ready[]`, `waiting[]`; lesson `kps[]` gain `status`),
    `app/content/validate.py` (warning: a KP pool has fewer than 5 gradable slots; error: fewer than 2 gradable
    items), `app/api/v1/router.py`, `tests/test_rls_db.py`.
  - Frontend (new): `src/features/learn/{QuestionStep.tsx, NumericInput.tsx, ExpressionInput.tsx, ResultPanel.tsx,
    FailedScreen.tsx, WaitingPanel.tsx, LearnedScreen.tsx, RemediationPage.tsx}`, `src/features/graph/{CourseMap.tsx
    (lazy), ConceptNode.tsx, ConceptPanel.tsx, layoutGraph.ts, highlight.ts}`.
  - Frontend (edit): `StudentHome.tsx`, `CoursePage.tsx` (toggle), `LessonPage.tsx`, `StepIndicator.tsx`,
    `StatusIcon.tsx`, `LockedPanel.tsx`, `FinishedScreen.tsx` (→ `LearnedScreen`), `api.ts`, `paths.ts`,
    `src/routes.tsx` (`/learn/brush-up/:id`), `src/lib/types.ts`.
  - Dependency: `@xyflow/react` via `pnpm add` (already chosen in ARCHITECTURE). No dagre/elk. Backend: none new
    (SymPy is already in).
  - Docs: `docs/ARCHITECTURE.md` domain model (`kp_session`, `remediation`, `concept_state` stores only in_progress/
    learned, `attempt.session_id`/`position`, `study_activity.practice`, gate is now "learned"); `content/README.md`
    (code items aren't drawn for KPs until 006; pool warning).
- Data model changes (`0005_kp_flow.py`; RLS enabled on every new table; composite FKs `(x_id, org_id)` for links
  between tenant tables):
  - enum values: `attempt_context` + `kp`, `remediation`; `study_activity` + `practice`.
  - `concept_state` (TenantMixin): PK `(student_id, concept_id)`, `org_id`, composite FK on student, `concept_id` FK,
    `status concept_status (in_progress|learned)`, `source concept_source (lesson|diagnostic|teacher)`,
    `learned_at null`, `relearn_count smallint default 0`, `created_at`, `updated_at`.
  - `kp_progress` (TenantMixin): PK `(student_id, kp_id)`, `org_id`, `kp_id` FK → `knowledge_point`,
    `status kp_status (not_started|in_progress|passed|failed)`, `fail_count smallint default 0`, `passed_at`,
    `failed_at`, `reopen_at`, `updated_at`.
  - `practice_session` (TenantMixin; 007 can reuse it for reviews): `id uuid pk`, `org_id`, `student_id`,
    `kind session_kind (kp|remediation)`, `kp_id` FK null (kind kp), `remediation_id` null (composite FK, kind
    remediation), `status session_status (active|passed|failed)`, `current_item_id` FK null, `current_seed int null`,
    `current_position smallint`, `current_served_at`, `started_at`, `ended_at null`. Partial unique `(student_id, kp_id)
    WHERE status = 'active' AND kind = 'kp'` and `(remediation_id) WHERE status = 'active'`. Check: `kind`↔ fk columns.
  - `remediation` (TenantMixin): `id uuid pk`, `org_id`, `student_id`, `kp_id` FK (the failing KP),
    `prereq_concept_id` FK → `concept`, `state remediation_state (review_due|relearn|resolved)`,
    `outcome (review_passed|relearned) null`, `created_at`, `resolved_at null`. Partial unique `(student_id, kp_id,
    prereq_concept_id) WHERE state <> 'resolved'`.
  - `attempt` + `session_id uuid null` (composite FK `(session_id, org_id)` → `practice_session`) + `position smallint
    null`; unique `(session_id, position)`; check `(context IN ('kp','remediation')) = (session_id IS NOT NULL)`.
    `response` = `{"raw": "<input>"}` (MCQ: `{option, order}` as in 004), `seed` set for param items.
  - Data migration: one `concept_state (in_progress, source lesson)` row for every existing `lesson_progress` row, so
    nothing that 004 opened becomes locked. No one is marked learned (no KPs were ever answered).
- API / interfaces (under `/api/v1/learn`, `OrgScope` on all):
  - `GET /concepts/{course}/{concept}/kps/{kp}/question` → `QuestionPublic`. A student gets the active session's current
    question, or the server opens a new session when the KP is open (409s as listed). Staff get a random item + `preview_seed`.
  - `POST /concepts/{course}/{concept}/kps/{kp}/answer` `AnswerIn` → `AnswerResult`. `position` must equal the
    session's current position. A repeat of an answered position → the stored result with `already_answered: true`;
    any other mismatch → 409 `stale_question`. The answer is stored, the outcome evaluated, and on pass/fail
    `kp_progress`/`concept_state`/`remediation` updated in the **same transaction**; on `active` the next question is
    chosen and stored.
  - `GET /remediations/{id}/question`, `POST /remediations/{id}/answer`: the same shapes, for `review_due`
    remediations (409 `not_due` otherwise).
  - `GET /courses` and `GET /courses/{slug}/outline`: extended shapes (see schemas). `GET /concepts/{course}/{concept}`:
    `steps` incl. `kpq:`, `kps[].status|reopen_at`, `waiting|null`, and `concept_status`.
  - Answer shapes are built only from `item.public` + the server-rendered prompt. `display_answer`/`explanation_md`
    appear only in `AnswerResult`.

## Edge cases
- Double submit / two tabs answering the same position: the unique `(session_id, position)` lets one insert win, and
  the other gets `already_answered`. Two tabs opening a KP at once: the partial unique index lets one session exist;
  the loser re-reads it.
- Reload mid-question: same item, same seed, same position. The time is measured from `current_served_at` on the
  server, clamped (the client value is used if it's lower).
- Concept retired mid-session: lesson 404 as in 004. Item retired mid-session: replaced at the same position. KP
  retired: it disappears and no longer blocks "learned"; if every remaining KP is passed, the concept becomes learned
  on next read (the outline service promotes it).
- A KP whose gradable pool is empty (a Python KP with only code items, theoretically): the validator errors. If it
  happens anyway at runtime, the KP is treated as passed automatically and logged as a warning, so the concept isn't
  blocked.
- Fail at 23:59 IST → reopens at 00:00 IST, 1 minute later. This is accepted (same as Math Academy's "next day").
- Student with only one ready concept fails its KP: nothing else to do, so it reopens tomorrow. The home shows it
  under Waiting.
- A key prerequisite borrowed from another course (Physics KP → Maths concept): the remediation review uses Maths items
  and the relearn resets the Maths concept, which shows in progress in both courses.
- A 3rd, 4th… fail: a new remediation each time for any key prereq without an unresolved one.
- A relearned prereq, learned again: its remediations resolve, and the original KP opens via the "passed a KP in a
  different concept" rule.
- Expression input `2x^2+3x` vs answer `x*(2*x+3)`, `equivalent` → correct; `simplified` mode compares op counts.
  Malicious input (`__import__`, `().__class__`, huge `9**9**9`): the AST walker rejects attributes and calls outside the
  whitelist, and powers with exponent > 100 are rejected; on timeout → wrong with "Couldn't read that expression".
- Numeric `0` in `sigfig` mode can't happen (the validator forbids a 0 value). `-0` → treated as 0.
- Staff hit the student-only remediation routes → 403.
- Student in school B passing a session id / remediation id from school A → 404.

## Out of scope
- XP of any kind, including negative XP for failed KPs (008 reads `practice_session` outcomes), streaks, daily goals.
- FSRS reviews, implicit credit, quizzes (007). Remediation reviews here are a standalone 005 mechanism, to be folded
  into 007.
- Code items, multistep problems, unit entry for numeric answers, the Pyodide worker (006).
- Hints and the AI tutor (009). Assignments / Focus Mode and teacher views of KP fail rates or remediations (010).
- Placement marking concepts learned (012). Per-school timezones.
- An auto-picked "next task" (the student chooses, by decision). A minimap, draggable nodes, or a cross-course global
  map.
- Re-practising a learned concept's KPs outside reviews.

## Verification (end-to-end)
- [ ] `tests/test_kp_flow.py` (pure): `kp_outcome` and `review_outcome` on every example sequence above, plus
      exhaustive sequences up to length 5 (never active at 5, never passed before 2); `choose_next_item` (no repeats
      within a session, unseen first, fixed items never repeated, deterministic); `is_open` (cooldown, other-concept
      pass, remediation pass, blocked by unresolved remediation); `next_midnight_ist` around 23:59 / 00:00 / DST-free.
- [ ] `tests/test_grading.py` (pure): numeric exact (`8`, `8.0`, `8.00` ✓; `8.01` ✗), sigfig strict (`26.7` ✓, `26.67`
      ✗ + note, `27` ✗, `270` for 3 s.f. ✓), tolerance, sci notation, bad input (`12,5`, `abc`) → wrong + note;
      expression exact/equivalent/simplified incl. implicit multiplication and `^`; rejection of `__import__`,
      attribute access, `9**9**9`, > 200 chars; MCQ positional mapping and unknown id. Every pool item in the sample
      content graded correct with its own solution over 20 seeds (render the answer via `display_answer`, feed it back).
- [ ] `tests/test_kp_api_db.py` (`-m db`, imported sample content), as a Physics student:
      - `GET question` before the check → 409 `check_first`; KP2 before KP1 passes → 409 `kp_order`.
      - KP1: answer correct twice → passed; the response contains no `answer`/`params`/`solution` before an answer.
      - Reload the GET → same `item_id`/prompt/position; two concurrent POSTs on one position → one row, one
        `already_answered`.
      - KP2: 3 wrong → failed, `reopen_at` = next IST midnight, lesson shows waiting; GET → 409 `kp_waiting`.
      - Pass a KP in another concept → KP2 open; the new session's first question differs from the failed
        session's items (or seeds).
      - Fail KP3 of `speed-and-velocity` twice → a remediation `review_due` for `maths-9-10/linear-equations-two-variables`;
        KP3 blocked; fail the review → the Maths concept is in progress in both the Maths and Physics outlines,
        `speed-and-velocity` stays in progress (not locked); relearn it → remediation resolved, KP3 open.
      - Pass all KPs → `concept_state` learned; `acceleration` becomes ready; `GET /courses` counts learned.
      - Staff: question + answer with `item_id`/`seed` returns a result and writes no rows in `attempt`,
        `practice_session`, `kp_progress`, `concept_state`, `remediation`, `study_time`.
      - School B student → 404 on school A session/remediation ids.
- [ ] `tests/test_learn_api_db.py` updated: statuses are `learned|…`; "finished" alone no longer unlocks dependants;
      migration backfill test: an in-progress 004 lesson stays open after `0005`.
- [ ] `tests/test_rls_db.py` covers `concept_state`, `kp_progress`, `practice_session`, `remediation`;
      `test_migrations_db.py` round-trips 0005; `tests/test_route_scoping.py` passes with no new exemptions.
- [ ] `tests/test_content_validate.py`: KP with < 2 gradable items → error; < 5 slots → warning. `make content-check`
      passes on the sample.
- [ ] Frontend vitest: `layoutGraph` (layers by longest path, stable order, no overlaps); `highlight` (ancestors,
      direct vs. distant); `QuestionStep` (submit disabled until input, result panel states, dots, Next/Continue);
      `NumericInput` unit suffix + `inputmode`; `ExpressionInput` preview; `LessonPage` blocks Next on an unpassed
      `kpq`, shows the failed screen, waiting panel and learned screen; `CoursePage` toggle defaults by viewport and
      lazy-loads the map; `StudentHome` renders the four lists without a Continue button.
- [ ] `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, `make check`, `make test-db` all green.
- [ ] Manual (paste notes + screenshots): `make migrate && make content-import && make dev`. As a Physics student at
      1280 px: home lists Ready concepts → `distance-and-displacement` → intro, check, worked example 1, questions (one
      wrong answer shows the answer + explanation, then 2 right → "Part passed"), … → "Concept learned", unlocks shown.
      Course Map: learned green, ready blue, locked grey; click `acceleration` highlights its chain and opens the panel.
      Fail a KP on purpose (3 wrong) → failed screen; home shows it under Waiting; learn a KP elsewhere → it reopens
      with different numbers. Fail the same KP twice → Brush up appears; complete it. On a 375 px phone: List is the
      default, Map works with the bottom sheet, and numeric input brings up the decimal keyboard. As a teacher: preview
      questions, "Another question", and no DB rows.
