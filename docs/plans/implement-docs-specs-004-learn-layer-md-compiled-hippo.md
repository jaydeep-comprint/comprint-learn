# Plan: build spec 004 (Learn layer)

Spec: `docs/specs/004-learn-layer.md` · Branch: `feat/004-learn-layer` (from `main` at a23da50; carry the
uncommitted spec + PRD link into the first commit)

## Context
Specs 001–003 gave us tenancy and a global, imported content graph, but students still land on a stub home page.
004 is the first student-facing feature: courses from their classes, a course outline that borrows cross-course
prerequisites, and a lesson (intro → one-shot server-graded MCQ check → worked example per KP) with resume, a
"finished" gate, and time-per-step logging. Teachers get a write-nothing preview. It also introduces the first
learning-state tables (`attempt`, `lesson_progress`, `study_time`) later specs build on.

## Ground rules
- `make check` after every step, output shown; `make test-db` for DB steps. Deps only via `pnpm add` (lockfiles
  hook-protected). No backend deps needed.
- Every new route depends on `Scope` (`get_org_scope`, `app/api/deps.py`); no new `GLOBAL_CONTENT` exemptions.
  Tenant rows are read/written only via `scope.select(...)` / `scope.new(...)`; content rows read globally.
- Answers: the lesson GET builds the check only from `ItemPublic.from_row` (`app/schemas/content.py`);
  `CheckResult` is the only shape carrying `correct_option` / `explanation_md` / misconception `title`.

## Steps
1. **Validator rule + importer `asset_path`**
   - `app/content/validate.py` `_check_concept`: misconception check must be `type: mcq` and have no `params`
     (two exact error messages). Tests in `tests/test_content_validate.py`; `content/README.md` documents the rule.
   - `app/models/content.py` `Concept.asset_path: Text, server_default ''`; importer (`app/content/importer.py`
     concept `_Desired.fields`) writes `<course>/<chapter-folder>/<concept>` derived from `LoadedConcept.dir`
     relative to the content root. Confirm `_sync` refreshes changed fields without a version bump when the hash is
     unchanged (spec 003 behaviour for derived columns); adjust if not.
2. **Models + migration 0004**
   - `app/models/learning.py`: `AttemptContext` (`learn`), `StudyActivity` (`learn`) via `_pg_enum`; `Attempt`,
     `LessonProgress`, `StudyTime` with `TenantMixin`, composite FK `(student_id, org_id)` → `app_user(id, org_id)`
     (pattern from `Enrollment`), content FKs with `RESTRICT`, partial unique index `(student_id, item_id) WHERE
     context = 'learn'`, index `(org_id, student_id, created_at)`, check `active_seconds BETWEEN 1 AND 600`.
     Export from `app/models/__init__.py`.
   - `alembic/versions/0004_learn.py`: enums, tables, `concept.asset_path`, `ENABLE ROW LEVEL SECURITY` each;
     downgrade reverses. Extend `tests/test_rls_db.py`; `test_migrations_db.py` drift test must pass.
3. **Pure outline + helpers** (`app/services/learn.py`, top section, no DB)
   - `build_outline(own: list[ConceptKey], prereqs: Mapping[id, set[id]], sort_key: Mapping[id, tuple]) ->
     list[(concept_id, placed_before_own_id)]`: ancestors closure by DFS; for each own concept in order, the
     not-yet-placed borrowed ancestors are topologically sorted (Kahn + heap on `(subject, chapter pos, concept
     pos)`) and inserted before it. Own concepts are never moved.
   - `status_of(concept, progress, prereqs)` per spec rules (in progress/finished never re-lock).
   - `shuffled_order(option_ids, student_id, item_id)`: `random.Random(sha256(...))` shuffle, stable.
   - `tests/test_learn_outline.py` covering every case listed in the spec's verification.
4. **Service + schemas + routes**
   - `app/schemas/learn.py`: shapes per spec (`StudentCourse`, `Outline`, `OutlineChapter`, `OutlineConcept`,
     `Lesson`, `CheckPublic`, `CheckResult`, `ProgressIn` (`active_seconds: StrictInt ≥ 0`, clamped server-side),
     `CheckIn`, `ProgressOut`, `LockedPrereq`).
   - `app/core/errors.py`: `ApiProblem` gains optional `extra: dict` merged into the body by the handler in
     `app/main.py` (for `concept_locked` + `prereqs`); helper `concept_locked(prereqs)`.
   - Service functions (`student_courses`, `outline`, `lesson`, `record_progress`, `submit_check`): one query for
     the student's courses (non-archived enrolments → active course by subject), one for active concepts + chapters
     + courses, one for active edges, one for this student's `lesson_progress` over the outline ids — no N+1.
     Access: concept must be in the union of the student's outlines, else 404; locked → 403.
     - `record_progress`: validate step against current steps (422 `invalid_step`); `INSERT … ON CONFLICT
       (student_id, concept_id) DO UPDATE` appending the step to `seen_steps` if absent and setting `last_step`;
       append `study_time` when clamped seconds > 0; then `_maybe_finish`.
     - `submit_check`: unknown option → 422 `invalid_option`; `INSERT … ON CONFLICT DO NOTHING` on the partial
       unique index, then read back the stored attempt (`already_answered` when ours didn't insert); build result
       from `item.answer` (`correct`, `misconceptions`, `explanation`) + `Misconception.title`; upsert
       `lesson_progress` (seen `check`) and `_maybe_finish` (sets `finished_at` once, when an attempt exists and all
       current KP steps are seen).
     - Staff (`scope.user.is_staff`): outline with `status=null`, any lesson, authored option order, check graded
       with no writes, progress → 204.
   - `app/api/v1/learn.py` (prefix `/learn`) registered in `router.py`; `GET /learn/courses` is student-only (403
     for staff, via `require_student` alongside `Scope`).
   - `tests/test_learn_api_db.py`: every bullet in the spec's DB verification list (seeded via `seed_school` +
     imported sample content; `student_ids[0..2]` are maths-only, `[3..5]` physics-only; the "in both" case adds
     an extra `Enrollment` for one physics student into the maths class). `test_content_import_db.py`:
     `asset_path` filled, second import a no-op.
5. **Frontend: Markdown**
   - `pnpm add react-markdown remark-gfm remark-math rehype-katex katex mermaid`.
   - `src/components/markdown/Markdown.tsx` (`assetBase` prop; no `rehype-raw`; custom `img` via
     `rewriteImageSrc.ts`, `a` with target/rel, `code` → `<Mermaid>` for `language-mermaid`; display maths wrapped
     in `overflow-x-auto`), `Mermaid.tsx` lazily importing `mermaid` (`securityLevel: "strict"`, fallback `<pre>` +
     note), KaTeX CSS in `index.css`. Vitest per spec (mermaid module mocked).
6. **Frontend: learn feature**
   - `src/features/learn/api.ts` (TanStack Query keys/hooks; progress post with `keepalive`, one silent retry),
     types in `src/lib/types.ts`.
   - `StudentHome` (in `HomePage` for students), `CoursePage` (status icons, locked `Sheet` bottom on mobile /
     `Dialog` on desktop via existing `components/ui`), `LessonPage` + `StepIndicator`, `CheckStep`, `LockedPanel`,
     `FinishedScreen`, `useStepTimer` (visibility-aware, cap 600, flush on step change / `visibilitychange` /
     `pagehide`). Staff preview banner; no timing/progress posts for staff.
   - `routes.tsx`: `/learn/:course` and `/learn/:course/:conceptCourse/:conceptSlug` under `AppShell`, any role.
     `ClassDetailPage`: "View course" button (course for the class's subject, from `GET /courses`).
   - Vitest per spec (`CheckStep`, `LessonPage`, `CoursePage`, `useStepTimer`) using `src/test/render.tsx` fetch mock.
7. **Docs** — `docs/ARCHITECTURE.md` domain model (`lesson_progress`, `study_time`, `attempt.context`,
   `concept.asset_path`; 005 swaps the gate to `concept_state`); CLAUDE.md gotcha if one emerges; spec status.
8. **Verify** — `uv run mypy`, `pnpm typecheck`, `make check`, `make test-db`; manual run per spec (migrate +
   content-import, 375 px and 1280 px, student + teacher flows, DB row checks) with notes; then `reviewer` +
   `security-reviewer` subagents; stop for `/ship`.

## Interpretation notes (record as deviations if they stick)
- Progress/check on a locked concept → 403 `concept_locked` (same as GET).
- Submitting the check also marks `check` seen and creates the `lesson_progress` row if missing, so finishing never
  depends on a separate progress post.
- Outline tie-break uses subject enum order for "home course subject".

## Verification
- `cd backend && uv run pytest tests/test_learn_outline.py tests/test_content_validate.py tests/test_route_scoping.py`
- `cd backend && uv run pytest -m db tests/test_learn_api_db.py tests/test_rls_db.py tests/test_migrations_db.py
  tests/test_content_import_db.py` (needs `TEST_DATABASE_URL`)
- `cd frontend && pnpm vitest run src/components/markdown src/features/learn`
- `make check`, `make test-db`, then the manual end-to-end checklist in the spec.
