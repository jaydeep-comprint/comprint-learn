# Spec 004: Learn layer

Status: implemented (feat/004-learn-layer)
PRD link: docs/PRD.md#mvp-scope-v1 (item 3; Phase 1 of docs/ROADMAP.md)

## Summary
A student sees the courses of their classes, opens a course page that lists its concepts in order (with prerequisites
from other courses pulled in, Math Academy style), and works through a concept's **lesson**: the intro, then the
misconception check (one MCQ, graded server side, with an explanation), then one worked example per KP. Content renders
Markdown, KaTeX, images and Mermaid, and works on phones and lab desktops. A concept is **finished** once the check is
answered and every worked example has been opened; a concept opens only when all of its prerequisites are finished.
The app resumes where the student left off, stores the check attempt, and logs time spent per step. Teachers can preview
any lesson without anything being stored.

## User stories
- As a student, I want to see my courses on my home screen with a "Continue" button, so that I can pick up straight away.
- As a student, I want a course page that shows which concepts I've finished, which I can start, and what I need to
  finish before a locked one opens.
- As a student, I want a short lesson: an intro, a quick check that tells me if I fell for a common mix-up, and a worked
  example per step of the idea, readable on my phone with proper maths and diagrams.
- As a student taking Physics but not Maths, I want the Maths concepts Physics depends on to appear in my Physics
  course, so that I'm never stuck behind something I can't reach; if I already finished them in Maths, they count.
- As a student, I want the app to remember where I stopped in a lesson.
- As a teacher, I want to open the lessons my students see (and try the check) without affecting any data.
- As our team, I want the check attempt and time-per-step logged from day one (ARCHITECTURE decision 16; PRD
  "≥ 60% of time in practice" metric).

## Behaviour

### Which courses a student sees
- A student's courses = the active course (spec 003: one per subject) for the subject of each **non-archived** class
  they are enrolled in, deduplicated, ordered by subject. A class whose subject has no active course contributes nothing.
- No classes (or none with a course) → empty state (see UI).

### Course outline and borrowed concepts
- A course's **outline** = its own active concepts in order (chapter position, then concept position) **plus borrowed
  concepts**: the full transitive closure of prerequisites that live in other courses (and *their* prerequisites, any
  course), so every ancestor of an own concept is in the outline. This mirrors Math Academy's "foundations": a course
  includes everything it depends on.
- Placement (deterministic): walk own concepts in order; immediately before each one, insert its not-yet-placed
  borrowed ancestors in topological order (ancestors first; ties broken by home course subject, then chapter position,
  then concept position). A borrowed concept is shown inside the chapter of the own concept it was placed before.
- Borrowed concepts look like any other concept: **no "From Maths" label**. They keep their identity (home course),
  so progress is shared: finishing `maths-9-10/linear-equations-two-variables` from the Physics course also finishes it
  in Maths, and vice versa.
- Retired concepts never appear. Edges come from `concept_prereq` (active concepts only, as spec 003 guarantees).

### Lesson state per student × concept
Status (computed, never stored as such):
- **finished**: `lesson_progress.finished_at` is set.
- **in progress**: a `lesson_progress` row exists without `finished_at`.
- **ready**: no row, and every direct prerequisite (any course) is finished.
- **locked**: not finished/in progress, and some direct prerequisite is not finished. (Transitively locked concepts are
  locked too, since their direct prerequisite can't be finished yet.)
- A concept that is already in progress or finished never becomes locked again (e.g. after a content change adds a
  prerequisite).
- Spec 005 replaces "finished" with "learned" (all KPs passed) as the gate and adds `concept_state`; 012 (placement)
  will be able to mark concepts known. Until then "finished" is the only gate.

### Lesson steps
Steps, in order: `intro` → `check` → `kp:<kp-slug>` for each active KP in position order (Spec 005 will insert the KP's
questions after each worked example). One step per screen.
- **Navigation**: Back always works. Next moves forward one step. A student can jump (via the step indicator) to any
  step up to the furthest step reached + 1. On the `check` step, Next is disabled until the check is answered.
- **Resume**: opening an in-progress lesson goes to `last_step`. Opening a finished lesson starts at `intro` in
  **review mode**: all steps open, the check shows the stored answer and its feedback (no new attempt).
- **Seen steps**: a step counts as seen when it is shown (the client reports it, see Progress API).
- **Finishing**: the server sets `finished_at` (once, never cleared) as soon as a check attempt exists **and** every
  current KP step is in `seen_steps`, whichever request completes the set. The last step's button reads "Finish lesson"
  and shows the finished screen.
- Content edits after finishing: the concept stays finished; the lesson shows the new text. A KP added later doesn't
  un-finish anyone. A retired KP's step simply disappears.

### Misconception check
- Validator rule (new, error): `misconception_check` must be `type: mcq` and have **no `params`** (all sample checks
  already comply). `content/README.md` documents it.
- Options are shown in `public` order, or, if `shuffle` is true, in an order derived deterministically from
  `(student_id, item_id)` so a reload doesn't reshuffle. Staff preview uses authored order.
- **One try**. `POST …/check` with `{option_id, time_taken_ms}`:
  - Unknown option id → 422 `{"code": "invalid_option"}`.
  - Stores one `attempt` (context `learn`, `item_version`, `response = {option, order}`, `correct`, the chosen
    option's `misconception_id` or null, `time_taken_ms` clamped to 0–1,800,000, `hints_used = 0`, `seed = null`).
  - Returns the **result**: `{correct, chosen, correct_option, explanation_md, misconception: {title} | null}`. The
    misconception's student-facing text is its `title` ("Common mix-up: …"); the `description` is teacher-facing and
    never sent.
  - Already answered (unique per student × item × context `learn`) → 200 with the **stored** result and
    `already_answered: true`; nothing new is written (double-submit and two tabs are harmless).
  - Right or wrong, the student continues. No retry.
- The correct option, explanation and misconception are returned **only** in a result (after an attempt, or to staff
  after they pick). `GET` of the lesson returns them only if this student already has an attempt.
- Locked concept → 403 `{"code": "concept_locked", "prereqs": [...]}` (same as GET).

### Time logging
- The client measures **active seconds** per step: time the step is on screen while the tab is visible. It reports
  them when the student leaves the step (Next/Back/jump), and on `visibilitychange → hidden` / `pagehide` (fetch with
  `keepalive: true`, since `sendBeacon` can't carry the auth header).
- The server clamps each report to 0–600 s, drops 0, and appends a `study_time` row. Ids and seconds only; no personal
  data, nothing sent to analytics or AI.
- Review-mode visits are logged too (re-reading is real study time). Staff previews are never logged.

### Teachers (staff preview)
- Any staff user can open any course outline and any lesson (content is global). No locks, no statuses, no resume:
  every step is open and the lesson starts at `intro`.
- The check is answerable: `POST …/check` by staff grades and returns the result but **writes nothing**. No progress or
  time is recorded for staff (the progress endpoint returns 204 without writing).
- Entry point: a "View course" button on the class detail page (course for the class's subject).

### Access rules (students)
- A student may open a concept only if it is in the outline of one of their courses; otherwise 404 `not_found`
  (same as unknown/retired slugs, so nothing leaks).
- Locked → 403 `concept_locked` with the unfinished direct prerequisites `[{id, title, status}]`.

## UI / UX
Existing app shell, shadcn/ui components, Tailwind. Mobile first; desktop gets a wider reading column.

- **Student home** (`/`, replaces the stub): "Hi {first name}", then one card per course: title, a progress bar
  "N of M concepts finished" (M = outline size incl. borrowed), and a primary button **Continue: {concept}**: the most
  recently touched in-progress concept, else the first ready concept in outline order; if everything is finished,
  "Review course". Card click → course page.
  - Empty: "You're not in a class yet. Ask your teacher to add you." Loading: skeleton cards. Error: inline retry.
- **Course page** (`/learn/:course`): title + progress bar; chapters as sections (title + "Class 9/10" badge); each
  concept a row with a status icon (finished ✓, in progress half-ring, ready open circle, locked padlock), title and
  one-line summary. Ready / in-progress / finished rows open the lesson. A locked row opens a **sheet** (bottom sheet on
  phones, dialog on desktop): "Finish these first" listing the unfinished direct prerequisites with their status, each
  linking to its lesson if it is ready or in progress. Staff see the same page without icons or locks.
- **Lesson page** (`/learn/:course/:conceptCourse/:conceptSlug`; `:course` is the outline the student came from, used
  for Back and "next up"): header with back arrow to the course, concept title and a step indicator (labelled dots:
  Intro · Check · 1 · 2 · 3; "Step 3 of 5" text on phones). Content column `max-w-prose`.
  - **Intro**: rendered `intro_md`.
  - **Check**: label "Quick check", prompt, options as large radio cards (≥ 44 px touch targets), Submit (disabled until
    an option is picked; spinner while submitting). After the result: the chosen card turns green (correct) or red, the
    correct card is marked green with "Correct answer", then a panel: "Correct!" or "Not quite", "Common mix-up: {title}"
    if tagged, and the explanation. Then Next.
  - **Worked example k**: "Worked example k of N · {KP title}" + rendered `worked_example_md`.
  - Bottom bar (sticky on phones): Back / Next ("Finish lesson" on the last step).
  - **Finished screen**: "Lesson finished" with the concept title, "Next up: {next ready concept in this outline}"
    (button) or "You've finished every lesson in this course", and "Back to course".
  - Staff: a banner "Teacher preview: nothing is saved".
  - Locked (direct URL): the same "Finish these first" panel as a page. 404: the existing NotFound page.
  - Errors: lesson load failure → error state with retry. Check submit failure → toast "Couldn't submit, try again",
    selection kept. Progress/time post failures are retried once silently and otherwise ignored (never block reading).
- **Markdown rendering** (`<Markdown>` component, used for intro, worked examples, check prompt/options/explanation):
  - GitHub-style Markdown; inline `$…$` and display `$$…$$` maths via KaTeX; display maths scrolls horizontally inside
    its own block on narrow screens, never the page.
  - Images: `img/<file>` sources are rewritten to `{asset_base}img/<file>`; any other source is not rendered (validator
    already forbids them). `max-width: 100%`, `alt` kept, `loading="lazy"`.
  - ```` ```mermaid ```` fences render as diagrams via a **lazily imported** Mermaid chunk (only loaded on pages that
    contain one), `securityLevel: "strict"`, scaled to the column; a render error shows the fence source in a `<pre>`
    with a muted "Diagram couldn't be shown" note.
  - Raw HTML in Markdown is not rendered (no `rehype-raw`). Links (YouTube only, per validator) open in a new tab with
    `rel="noopener noreferrer"`.
- Accessibility: radio group semantics for options, focus moves to the result panel after submit, step indicator is a
  `nav` with `aria-current="step"`, KaTeX MathML output kept for screen readers.

## Technical design
- Files / modules touched:
  - Backend (new)
    - `app/models/learning.py`: `Attempt`, `LessonProgress`, `StudyTime` (all `TenantMixin`), enums `AttemptContext`
      (`learn`; later specs add values), `StudyActivity` (`learn`).
    - `alembic/versions/0004_learn.py`: tables below + `concept.asset_path`; `ENABLE ROW LEVEL SECURITY` on each new
      table.
    - `app/services/learn.py`: `student_courses(scope)`, `outline(session, scope|None, course_slug)` (borrowing +
      placement + statuses), `lesson(scope, concept_ref)`, `record_progress(scope, concept_ref, step, seconds)`,
      `submit_check(scope, concept_ref, option_id, time_taken_ms)`, `concept_status(...)`. Pure helpers for the outline
      algorithm (`build_outline(own, edges, home_order) -> list[...]`) so they are unit-testable without a DB.
    - `app/schemas/learn.py`: `StudentCourse`, `Outline`, `OutlineConcept`, `Lesson`, `LessonStep`, `CheckPublic`,
      `CheckResult`, `ProgressIn`, `ProgressOut`, `CheckIn`, `LockedProblem`. The check is built from
      `ItemPublic.from_row` only; `CheckResult` is the only shape that carries `correct_option`/`explanation_md`.
    - `app/api/v1/learn.py`: routes below; every route depends on `OrgScope` (`get_org_scope`), so they pass
      `tests/test_route_scoping.py` without new exemptions.
  - Backend (edit): `app/content/importer.py` (write `concept.asset_path` = `<course>/<chapter-folder>/<concept>` as a
    derived column, no version bump, per spec 003's deviation for derived columns), `app/content/validate.py` (check
    must be MCQ without params), `app/models/__init__.py`, `app/api/v1/router.py`, `tests/test_rls_db.py` (new tables),
    `tests/test_content_validate.py`.
  - Frontend (new): `src/components/markdown/Markdown.tsx` (+ `Mermaid.tsx` lazily imported, `rewriteImageSrc.ts`),
    `src/features/learn/{api.ts, StudentHome.tsx, CoursePage.tsx, LessonPage.tsx, CheckStep.tsx, StepIndicator.tsx,
    LockedPanel.tsx, FinishedScreen.tsx, useStepTimer.ts}`.
  - Frontend (edit): `src/pages/HomePage.tsx` (render `StudentHome` for students), `src/routes.tsx` (learn routes for
    any signed-in role), `src/features/classes/ClassDetailPage.tsx` ("View course"), `src/lib/types.ts`, `index.css`
    (KaTeX CSS import).
  - Dependencies (via `pnpm add`, never by hand): `react-markdown`, `remark-gfm`, `remark-math`, `rehype-katex`,
    `katex`, `mermaid` (dynamic import only). All already chosen in ARCHITECTURE (Maths rendering, Diagrams).
  - Content/docs: `content/README.md` (check rule); `docs/ARCHITECTURE.md` domain model (`lesson_progress`,
    `study_time`, `attempt.context`, `concept.asset_path`; note that 005 swaps the gate to `concept_state`).
- Data model changes (`0004_learn.py`):
  - `concept.asset_path text not null default ''` (filled by the next import).
  - `attempt` (TenantMixin): `id uuid pk`, `org_id`, `student_id` (composite FK `(student_id, org_id)` →
    `app_user(id, org_id)`), `item_id` FK → `item`, `item_version int`, `context attempt_context`, `seed int null`,
    `response jsonb`, `correct bool`, `misconception_id` FK → `misconception` null, `time_taken_ms int`,
    `hints_used smallint default 0`, `created_at`. Index `(org_id, student_id, created_at)`. Partial unique index
    `(student_id, item_id) WHERE context = 'learn'` (one check attempt).
  - `lesson_progress` (TenantMixin): PK `(student_id, concept_id)`, `org_id`, composite FK on student,
    `concept_id` FK → `concept`, `seen_steps text[] not null default '{}'`, `last_step text not null`,
    `started_at`, `updated_at`, `finished_at null`.
  - `study_time` (TenantMixin): `id bigint identity pk`, `org_id`, `student_id` (composite FK), `concept_id` FK,
    `activity study_activity` (`learn`), `step text`, `active_seconds smallint check 1–600`, `created_at`. Append-only.
- API / interfaces (all under `/api/v1/learn`, `OrgScope` required):
  - `GET /courses` (student) → `[{slug, title, subject, finished, total, continue: {id, title} | null}]`. Staff → 403
    (they use `/courses`).
  - `GET /courses/{slug}/outline` → `{course: {slug, title, subject}, chapters: [{slug, title, grade, concepts:
    [{id: "<course>/<slug>", title, summary, status: "finished"|"in_progress"|"ready"|"locked"|null,
    prereqs: [id]}]}]}` (status null for staff). Unknown/retired → 404; a course outside the student's courses → 404.
  - `GET /concepts/{course}/{concept}` → `{id, title, summary, asset_base: "/content-assets/<asset_path>/", intro_md,
    check: {item_id, prompt, options: [{id, text}]}, kps: [{slug, title, worked_example_md}], steps: ["intro", "check",
    "kp:kp1", …], progress: {seen_steps, last_step, finished_at} | null, check_result: CheckResult | null, preview:
    bool}`. 403 `concept_locked`, 404 as above.
  - `POST /concepts/{course}/{concept}/progress` `{step, active_seconds}` → `{seen_steps, last_step, finished_at}`;
    first call creates the row. Unknown step → 422 `invalid_step`. Staff → 204, nothing written.
  - `POST /concepts/{course}/{concept}/check` `{option_id, time_taken_ms}` → `CheckResult & {already_answered}`.
  - The status computation loads, per request, the student's `lesson_progress` rows for the outline's concepts (one
    query) and the edges (one query); no N+1.

## Edge cases
- Student enrolled in two classes of the same subject → one course card.
- All of a student's classes archived → empty home state; direct lesson URLs 404.
- Physics student who finished `linear-equations-two-variables` in Maths: it shows finished in Physics and
  `speed-and-velocity` is ready.
- Borrowed concept that is a prerequisite of several own concepts: placed once, before the first.
- A borrowed concept's own prerequisites in its home course: also borrowed (closure), placed before it.
- Prerequisite chain authored out of order within a course (B before its prerequisite A): order is as authored; B
  shows locked with A listed. (Validator doesn't enforce order; not in scope.)
- Two tabs submit the check at once: the unique index makes one insert win; the other returns the stored result.
- Progress POST for `kp:x` before the check is answered: allowed (Back/jump rules are client-side); `finished_at` waits
  for the check.
- KP retired after a student saw it: its key stays in `seen_steps` but no longer counts; `steps` omits it.
- Concept retired: disappears from outlines; its lesson URL 404s; rows stay.
- `active_seconds` of 3,000 from a tab left open: clamped to 600. Negative or non-integer → 422.
- Image referenced in Markdown but the import ran before this spec (`asset_path` empty): `asset_base` is empty and
  images don't render; fixed by re-running `make content-import` (documented in the verification).
- Mermaid fails to load (offline) or fails to parse: fallback `<pre>`, the rest of the lesson works.
- Very long display equation on a 360 px phone: scrolls inside its block.
- Teacher opens `/` → still redirected to `/classes`; teacher opens `/learn/...` → preview.
- Deactivated student mid-lesson: next request 401 (spec 002), progress already posted is kept.

## Out of scope
- KP questions, the KP pass/fail flow, remediation, `concept_state`, "learned", the knowledge frontier and the graph UI
  (spec 005). Grading of numeric/expression/multistep/code (006).
- XP for reading or for the check (008 decides; attempts are stored so it can), reviews (007), hints and the AI tutor
  (009), teacher analytics of check results or study time (010), placement marking concepts known (012).
- Retaking the check; step-by-step reveal of worked examples; YouTube embeds (links only); offline/PWA; translations.
- Enforcing that authored concept order respects prerequisites.
- Mermaid/KaTeX syntax linting in the validator.

## Verification (end-to-end)
- [ ] `tests/test_learn_outline.py` (pure): `build_outline` on fixtures: own order kept; cross-course ancestor placed
      before its first dependant; transitive closure (A_maths → B_maths → C_physics pulls in A and B, in that order);
      shared ancestor placed once; ties broken deterministically.
- [ ] `tests/test_learn_api_db.py` (`-m db`, imported sample content):
      - student in a Physics class only → `/learn/courses` lists Physics; its outline contains
        `maths-9-10/linear-equations-two-variables` before `speed-and-velocity`, no course label field.
      - statuses: `distance-and-displacement` ready, `speed-and-velocity` locked; GET its lesson → 403 with prereqs.
      - progress for intro/check/kp steps; resume returns `last_step`; check submit stores one attempt with
        `item_version`, `misconception_id` for a tagged wrong option, and returns explanation + misconception title
        (not description); second submit → `already_answered: true`, still one row; invalid option → 422.
      - `finished_at` set only when the check is answered and all KP steps are seen; then the dependant becomes ready.
      - finishing the Maths concept as a Maths student who is also in Physics → Physics outline shows it finished.
      - lesson GET before any attempt contains none of `correct`, `correct_option`, `explanation`, `misconception`,
        `description`; shuffled option order is stable for one student across two GETs.
      - staff: outline has null statuses, any lesson opens, check returns a result, and no `attempt`,
        `lesson_progress` or `study_time` rows are written.
      - `active_seconds` 3000 → stored 600; 0 → no row.
      - student from school B can't see school A's progress (rows are org-scoped; a B student's outline statuses are
        their own).
      - concept outside the student's courses → 404.
- [ ] `tests/test_content_validate.py`: numeric misconception check → error; MCQ check with params → error (exact
      messages). `make content-check` passes on the sample.
- [ ] `tests/test_route_scoping.py` passes with no new exemptions; `tests/test_rls_db.py` covers `attempt`,
      `lesson_progress`, `study_time`; migration round-trip in `test_migrations_db.py`.
- [ ] `tests/test_content_import_db.py`: import fills `asset_path`; a second import changes nothing.
- [ ] Frontend vitest: `Markdown` renders inline and display KaTeX, rewrites `img/x.svg` to the asset base, drops
      other image sources, ignores raw HTML, adds `rel` to links, renders a mermaid fence via a mocked lazy module and
      falls back on error; `CheckStep` disables Submit until a pick, shows correct/wrong/misconception states;
      `LessonPage` resumes at `last_step`, blocks Next on the unanswered check, shows the finished screen;
      `CoursePage` opens the locked sheet; `useStepTimer` pauses while hidden and caps at 600.
- [ ] `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, `make check` green; `make test-db` green.
- [ ] Manual (paste notes + screenshots): `make migrate && make content-import`, `make dev`; as a student in a Physics
      class on a 375 px viewport and a 1280 px desktop: home card → course page (locked sheet on `speed-and-velocity`)
      → `distance-and-displacement` lesson: intro, wrong check answer (red + misconception + explanation), worked
      examples incl. the path SVG, finish → next up; reload mid-lesson resumes; `linear-equations-two-variables` from
      the Physics page, then `speed-and-velocity` unlocks. Maths lesson shows display maths without page scroll. As a
      teacher: "View course" from the class page, preview banner, check answerable, DB shows no rows for the teacher.
      Check the DB: one `attempt`, `lesson_progress` rows, `study_time` rows with plausible seconds.
