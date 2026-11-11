# Plan: implement spec 014 (Privacy: tutor consent, export, erasure, audit log)

## Context
Spec 014 (`docs/specs/014-privacy-consent-export-erasure.md`, untracked on main) is PRD item 12. The pilot can't run
with minors until the AI tutor (chat text goes to DeepSeek, servers in China) is gated on parental consent and a
school can answer access and erasure requests. The spec is fully decided, including a "Decided while specifying"
list. This plan maps it onto the code and closes the gaps the exploration found.

**Branch and PRs**: `feat/014-privacy` from main. **PR 1** = consent + notice + audit log (steps 1–6); **PR 2** =
export + erasure + jobs (steps 7–11), on the same branch after PR 1 merges.
- The first commit carries the pending docs: spec 014/015, `docs/pilot-readiness.md`, and the PRD, ROADMAP and
  content-review edits. `docs/drafts/` stays untracked.
- Shared test DB: never run `make test-db` in parallel.

### Where the code differs from what the spec assumes (handled below)
1. **Status filters.** `tenancy.list_students` (`tenancy.py:253`), `list_class_students` (:561), `_get_student` (:121),
   `placement._student_row` (:371), `placement.cancel` (:395) and `cli.list_orgs` (:90) don't filter by status.
   - Class rosters, the dashboard (`class_view.load`), the leaderboard, the picker and teacher-AI facts all join
     `Enrollment`, so deleting the enrolments at completion hides erased students there.
   - The school-wide list, `_get_student` and `org list` need an explicit `status != erased`.
2. **Every existing tutor DB test will hit the new consent 403.** Add a `grant_consent(session, student_id)` seed
   helper in `tests/db_seed.py` and call it in the tutor test fixtures, and in any other test that drives the tutor
   (eval/teacher-AI flagged-chat seeds).
3. **No advisory-lock helper.** The tutor lock is raw SQL at `tutor.py:320`. Extract it as
   `tutor.lock_students(session, ids)` (sorted ids) and reuse it in withdrawal and erasure completion.
4. **No test counter on the fake AI client.** "No model call" is asserted with `len(db_app.tutor.requests) == 0`.
   `FakeSupabaseAdmin` (`tests/fakes.py:13`) needs a `fail_delete: dict[id, status]` hook.
5. **Frontend gaps.**
   - Missing pieces: a download helper, a tooltip component (use a `title` attribute), filter chips (use the
     `aria-pressed` toggle pattern from `WindowPicker.tsx`) and an admin nav "section" (push the item next to
     Teachers, as `nav.ts:14` does).
   - The slips view reads an in-memory store, not the URL. The consent print view reads `?students=` and fetches
     its own data, as the spec says.
   - `StudentPage` doesn't read `useMe()` today; add it for the admin parts.

## PR 1: consent, notice, audit

### Step 1: Model + migration `0013_privacy`
- `app/models/tenancy.py`:
  - `UserStatus.erased`.
  - New `AppUser` columns: `tutor_consent_at/by/form`, `erase_requested_at/by`, `erase_due_at`, `erased_at`.
  - Composite FKs `(tutor_consent_by, org_id)` and `(erase_requested_by, org_id)` → `app_user(id, org_id)`.
  - The 3 CHECKs from the spec and a partial index on `erase_due_at`.
- New `app/models/audit.py`: `AuditAction` (StrEnum, `_pg_enum`) and `AuditEvent(TenantMixin)` with the spec's
  columns, composite FKs for actor and target, and both indexes. Export it from `models/__init__.py`.
- `alembic/versions/0013_privacy.py` (down_revision 0012):
  - `ADD VALUE 'erased'` inside `autocommit_block`, and the enum created with `create_type=False`.
  - Use the `_pair_fk` pattern and enable RLS on `audit_event`.
  - Downgrade: erased rows → `deactivated`, drop the CHECKs, columns, table and enum; leave the `user_status` value
    in place.
- Tests: `conftest.TENANT_TABLES += audit_event`; extend `test_rls_db.py`; add a round trip in
  `test_migrations_db.py` with one erased row, which comes back as deactivated.

### Step 2: Audit service
`app/services/audit.py`:
- `record(scope, action, target_id, meta=None, *, actor_id=DEFAULT)`: defaults to `scope.user.id`, uses
  `scope.new`, and never commits (it runs in the caller's transaction). It asserts that the actor is never the
  system scope's nil uuid.
- `list_events(scope, action, target_id, before, limit)`:
  - Keyset on `(created_at, id) < (:ts, :id)` with an opaque `"<iso>_<id>"` cursor.
  - Joins actor and target display names (aliased `AppUser`); an erased target already reads "Erased student".
- Wire in the events from `tenancy`:
  - `_set_status` → `user_deactivated` / `user_reactivated` with `meta.role`.
  - `reset_student_password` → `password_reset`.
  - `_set_status` also gets the reactivation guard: 409 `erasure_pending` when `erase_requested_at` is set (used in
    PR 2, but harmless now).
- Route `GET /api/v1/audit` (`AdminScope`) in a new `app/api/v1/privacy.py`, with schemas in
  `app/schemas/privacy.py`.

### Step 3: Notice
- `app/privacy/notice.md`: front matter `version: "2026-11-v1"` and `title`; a parent-readable body with the
  `[OPERATOR NAME]` and `[CONTACT]` placeholders; and a second H2 "What this app stores about you".
- `app/privacy/__init__.py`: loads it once (`functools.cache`), splits it at the second H2 into
  `body_md`/`stores_md`, and exposes `NOTICE_VERSION`.
- `GET /api/v1/privacy/notice` (any signed-in user).
- Offline test: `version`, the split, and a list of remaining placeholders that is printed but never fails.

### Step 4: Consent service + route
- `app/services/consent.py`:
  - `has_consent(scope, student_id)`.
  - `apply(scope, ids, action)`. It de-duplicates the ids (max 200) and loads all of them with `FOR UPDATE` in id
    order after `tutor.lock_students`.
  - Errors: any id that is missing, a teacher or erased → 404 for the whole request. For `record`, a pending
    erasure → 422 `consent_not_allowed` with `student_ids`.
  - `record`: skip students who already have consent; otherwise set the 3 columns and write `consent_recorded`
    (`meta.form`).
  - `withdraw`: skip students without consent; otherwise null the 3 columns, call
    `tutor.purge_student_text(scope, sid, now)`, and write `consent_withdrawn` (`meta.form`, `messages_purged`).
  - One commit.
- `tutor.purge_student_text(scope, student_id, now) -> int`: an UPDATE of `text = null` and `purged_at = now`
  where `purged_at IS NULL`, scoped by org and student.
- Route: `POST /students/consent` (`StaffScope`) → `list[StudentOut]`. Declare it before `/{id}` routes.
- `StudentOut`, `ClassStudentOut` and `StudentDetail` gain `tutor_consent_at`, `tutor_consent_form` and
  `erase_due_at`; `StudentDetail` also gains `username`. Fill them in the existing builders.

### Step 5: Tutor gate (`app/services/tutor.py`)
- `_reserve`: after the lock and `_question`, a consent check → `ApiProblem(403, "tutor_consent_required", msg)`,
  before any write.
- `_store` (Tx 2): take `lock_students([sid])` first, then re-read consent.
  - If consent is gone: store the student row and the reply with `text=None`, `purged_at=now`, status `late`;
    charge nothing; commit; raise 403. This comes before the `question_answered` check.
- `_close_pending`: null the text and set `purged_at` when consent is gone.
- `get_thread` / `_thread_out`: `consent: bool` via one `app_user` query, present even when `enabled=false`.
  `TutorThread` schema += `consent`.
- Make sure `_run` re-raises the 403 `ApiProblem` (it already re-raises `ApiProblem`).

### Step 6: Frontend, PR 1
- `lib/types.ts`: consent/erasure fields on `Student`, `ClassStudent`, `StudentDetail`, `TutorThread.consent`;
  `AuditEvent` and `Notice` types.
- `features/privacy/api.ts`:
  - Hooks `useNotice`, `useConsentMutation` (invalidates `classes`, `students` and the dashboard student keys) and
    `useAudit` (`useInfiniteQuery`).
- `ConsentBulkBar.tsx`: count, Record / Withdraw / Print, the 200 cap hint, `ConfirmDialog`s with the spec's exact
  wording, toasts.
- `StudentRows.tsx`: a checkbox column (select all), a "Tutor consent" column ("Recorded {date}" with
  `title=form version`, or "Not recorded"), and a "Without consent (n)" toggle chip. `StudentsTab.tsx` hosts the
  bar; the bar is hidden on the empty state.
- `StudentsPage.tsx`: the same column; selection and the bar for admins only.
- `PrivacyCard.tsx` on `StudentPage.tsx` (after Tutor chats): consent state + Record/Withdraw. PR 2 adds the admin
  parts.
- `ConsentFormsView.tsx` at `/classes/:id/consent-forms` (beside the slips routes, staff guard). It reads
  `?students=`, uses the class + roster + notice queries, and renders one `.consent-form` page per student.
  - Default: active students without consent. Empty state: the spec's text. The Print bar is `print:hidden`.
  - `index.css` print block += `.consent-form { break-after: page }`.
- `TutorButton.tsx`: if `enabled && !consent`, a disabled button + the lock note. `TutorPanel.tsx`: a new problem
  kind `consent` that closes the panel (pass `onClose` into `TutorBody`), then refetches the thread so the note
  shows.
- `AuditPage.tsx` at `/audit`, under the admin `RequireRole` group next to `/teachers`; a nav item when `is_admin`.
  It has a table, an action select, "Load more", and the empty state "Nothing recorded yet."
- `PrivacyPage.tsx` at `/privacy`, directly under `AppShell`, with a link in `UserMenu.tsx`.
- Vitest: bulk bar, print view (page per student + empty), tutor lock note, audit page (empty, filter, load more).

### PR 1 tests (backend)
- `test_consent_db.py`: record and withdraw in bulk, no-op repeats, all-or-nothing 404/422, withdraw nulls only
  that student's text and keeps counts, events, concurrent record → one event (two sessions via `asyncio.gather`).
- `test_tutor_api_db.py`:
  - Without consent: hint and chat → 403, zero `tutor.requests`, no rows; the thread has `consent: false`.
  - Withdrawal between Tx 1 and Tx 2, using the fake's `gate`: no text stored, no hint charged, 403.
- `test_audit_db.py`: the PR 1 actions, a rollback leaves no event, pagination with equal `created_at`, filters,
  and a `meta` scan for names, usernames and emails.
- Extend `test_route_scoping.py`, `test_tenant_isolation_db.py` (`_cross_school_calls`: consent, and in PR 2
  export and erasure) and `test_walker_sees_the_routes`.

## PR 2: export, erasure, jobs

### Step 7: Export (`app/services/export.py`)
- `student_export(scope, student_id) -> dict`:
  - `_get_student` (404 for erased); then one query per section, all filtered by `org_id` + `student_id`, joined
    to content for slugs.
  - Assignments: load the graph once and call `frontier.class_states` once over all concepts; include archived
    classes.
  - `ai_summaries`: student-window `teacher_summary` rows; replace the student's own `{Sn}` token with their name
    in `content`, and leave other tokens.
  - Never select `item.answer`, `facts`, `pseudonyms` or token/latency columns.
- Route `GET /students/{id}/export` (`AdminScope`): `audit.record(export_downloaded, source=ui)`, commit, then a
  `JSONResponse` with `Content-Disposition` and `Cache-Control: no-store`.
- `school_export(session, org)` for the CLI.
- `test_export_db.py`: every section present, no rows of another student, a recursive scan finds no
  `answer`/hidden test/explanation values, the query count is equal for 1 and 500 attempts, teacher 403, erased 404.
- Manual check: 20k seeded attempts, time and size recorded in the PR.

### Step 8: Erasure (`app/services/erasure.py`)
- `request(scope, admin, id, confirm_username)`:
  - Errors: a lowercase mismatch → 422 `confirm_mismatch`; already pending → 409 `erasure_pending`.
  - `set_banned(True)`; a `SupabaseAdminError` → 502 with nothing changed.
  - Then set `status=deactivated`, `sessions_valid_after`, the `erase_*` columns (due = now + 7 days) and the
    `erase_requested` event (`due_at`, `was_active`).
- `cancel`: 409 `no_erasure_pending`; clear the columns; `erase_cancelled`.
- `complete_due(session, admin, now) -> (done, failed_ids)`, a loop of one transaction per student:
  1. Claim one due row with `FOR UPDATE SKIP LOCKED`, then take `lock_students`.
  2. Call `delete_user` with a 10 s timeout; a 404 counts as success.
  3. Anonymise: `erased-` + `secrets.token_hex(6)`, `purge_student_text`, delete `Enrollment` and
     `AssignmentStudent`, then `erase_completed` with `actor_id=None` via `OrgScope.system(session, org_id)`.
  4. Commit. On failure: roll back, log the id only, and skip that id for the rest of this run.
- Routes `POST` / `DELETE /students/{id}/erasure` (`AdminScope`).
- Status filters (gap 1):
  - `list_students` and `_get_student` exclude `erased`; deps reject `erased` like `deactivated`.
  - Placement switches to `_get_student`; `enroll_students` treats erased as not found; `org list` counts skip
    erased.
- `test_erasure_db.py`: the spec's checklist, plus absence from the roster, overview, heatmap, leaderboard and
  teacher-summary facts, and a reusable old username.

### Step 9: CLI + workflow + runbook
- `cli.py` `privacy_app`:
  - `run-due`: `complete_due`, then `tutor.purge_text`; prints counts; exit 1 on any failure.
  - `export --org CODE --out DIR`: refuses an `--out` under the repo root (`DEFAULT_CONTENT_ROOT.parent`), under
    any ancestor with `.git`, or a non-empty directory. Writes `school.json` + `students/{username}.json` and one
    CLI event per student.
  - `app tutor purge` stays as is.
- `test_cli.py`: monkeypatched service functions, the exit code, and the path refusals.
- `.github/workflows/privacy-jobs.yml`: cron `30 20 * * *` + `workflow_dispatch`, the `ci.yml` secret-gate step
  (`PROD_DATABASE_URL`), and an `echo "skipped: no production secrets"` branch. Check it with `actionlint` if it's
  installed.
- `docs/runbooks/privacy.md`.

### Step 10: Frontend, PR 2
- `lib/api.ts` `apiDownload(path, fallbackName)`: fetch with `getAccessToken()`, `blob()`, a filename from
  `Content-Disposition`, and a temporary `<a download>`.
- `PrivacyCard` admin parts: Download data (JSON), Erase student…, and when pending "Erasure scheduled for {IST
  date}" + Cancel erasure.
- `EraseDialog.tsx` (`AlertDialog`, type-the-username, disabled until the username matches, inline `FormError`,
  stays open while the request runs).
- `StudentsPage` row menu (admins): Download data, Erase…, Cancel erasure; the "Erasure after {date}" badge
  (`title="Runs nightly"`).
- Vitest: erase dialog.

### Step 11: Docs
- ARCHITECTURE: the domain model (consent columns, `erased`, `audit_event`) and Boundaries (consent gate, what
  erasure keeps).
- CLAUDE.md Gotchas: one line.
- PRD Constraints: the 4 assumptions.
- Tick the spec boxes as they pass.

## Verification
- `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, `make check` (offline), and `make test-db` (not in
  parallel), with the output shown for each.
- New/extended test files as listed per step.
- `reviewer` subagent against the spec, and `security-reviewer` on each PR (export and erasure focus).
- Browser check: Chrome can't reach localhost from this session (memory), so the user runs the spec's browser
  script after `make migrate` + `alembic current`. I prepare the step list and the screenshot checklist.
- After 014: remind the user of the deferred spec 013 browser check and tick its two boxes.
