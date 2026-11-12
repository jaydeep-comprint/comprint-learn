# Spec 014: Privacy — tutor consent, data export, erasure, audit log

Status: implemented (browser check and actionlint pending)
PRD link: docs/PRD.md#mvp-scope-v1 (item 12) · Constraints → Minors' data

Roadmap line 014 ("Hardening") was split while specifying (Nov 2026): **014 = privacy** (this spec), **015 = operations**
([spec 015](015-operations-hardening.md): error tracking, backups, load test, security hardening and review). The
teacher content review and the legal review are no longer spec gates: they live in `docs/pilot-readiness.md`.

## Summary
A school records, per student, that a parent or guardian signed the AI-tutor consent form; the tutor is locked for
a student until then, and withdrawing consent locks it again and wipes that student's chat text at once. A school
admin can download everything stored about one student as a JSON file and can erase a student: the account is
deactivated at once and anonymised after 7 days. Every one of these actions is written to an audit log that admins
can read.

## Decisions from the interview (Nov 2026)
| Topic | Decision |
|---|---|
| How consent is verified | **School-attested.** The app prints a notice + form; the school collects signatures on paper and keeps them; staff mark the student in the app. We store no parent data at all. |
| What consent gates | **Only the AI tutor.** Students can sign in and learn without it. |
| What the form covers | **The AI tutor only** (chat text sent to DeepSeek, servers in China). App use is treated as the school's own educational activity: the school is the data fiduciary and we process on its instruction. |
| Teacher AI summaries | **Unchanged**: every enrolled student is included as a pseudonym, with or without tutor consent. |
| Who records consent | Any teacher of the school (the app has no per-class staff permission: `class_teacher` gives no extra access), from a class's Students tab; admins also from the school-wide Students page. |
| Withdrawal | Tutor locked + that student's tutor message text nulled immediately. Learning data untouched. |
| Erasure | **Anonymise, keep learning rows.** Admin UI; deactivated now, anonymised by a scheduled job after 7 days unless cancelled. Only tutor chat text is wiped from the kept rows. |
| Erased student visibility | Nowhere per-student: new status `erased`, enrolment and assignment links deleted, student page 404. |
| Export | Admin UI, one student → one JSON file. A CLI exports a whole school. |
| Scheduler | `app privacy run-due` (idempotent CLI) + a daily GitHub Actions workflow, active once production secrets exist. |
| Audit log | Append-only `audit_event`, admin-readable. |

**Assumptions the legal review must confirm** (recorded in `docs/pilot-readiness.md`, not blocking this spec):
1. Learning without parental consent is lawful because the school is the data fiduciary for classroom activity.
2. A teacher's tick is acceptable evidence of *verifiable* parental consent when the school keeps the signed form.
3. Pseudonymised class statistics sent to DeepSeek for teacher summaries need no parental consent.
4. Anonymised learning rows (including submitted answers and code, which are kept) are no longer personal data.

If the review rejects 1, the fix is a second gate on sign-in; if it rejects 4, erasure must also null
`attempt.response`. Both are designed to be small follow-ups (see Technical design → Extension points).

## User stories
- As a teacher, I want to print the consent forms for my class and tick off the students whose forms came back, so
  that they can use the AI tutor.
- As a teacher, I want to withdraw a student's consent when a parent changes their mind.
- As a student without consent, I want to know why the tutor is locked and what to do about it.
- As a school admin, I want to download everything stored about a student when a parent asks for it.
- As a school admin, I want to erase a student and still be able to undo a mistaken request for a week.
- As a school admin, I want to see who recorded consent, exported data or erased a student, and when.

## Behaviour

### Tutor consent
- Consent is **per student**, not per class: one current state on `app_user` (`tutor_consent_at`,
  `tutor_consent_by`, `tutor_consent_form`). Null `tutor_consent_at` = no consent. History lives in `audit_event`.
- Every existing and newly created student starts with **no consent**. After this ships, the tutor is locked for
  everyone until staff record consent (intended; called out in the PR description).
- **Record**: staff select one or more students and confirm a dialog: "I confirm the school holds a signed consent
  form (version {form}) from a parent or guardian of each selected student." Sets the three columns
  (`tutor_consent_form` = the current notice version) and writes one `consent_recorded` audit event per student.
  Recording for a student who already has consent is a no-op for that student (no new event, columns unchanged).
- **Withdraw**: staff select students and confirm: "The AI tutor will be locked for these students and their tutor
  chat text will be deleted now. This can't be undone." For each student with consent: null the three columns, null
  the `text` of all their `tutor_message` rows that aren't purged yet (`purged_at = now`; counts, tokens, status
  and flags stay, exactly like the 180-day purge), write `consent_withdrawn` (meta: `messages_purged` count).
  No-op for students without consent.
- Consent can be recorded again later (new event, new timestamp). Purged text does not come back.
- Only students with status `active` or `deactivated` and no pending erasure can have consent recorded; others in
  the request → 422 `consent_not_allowed` listing the ids, nothing saved (all-or-nothing, max 200 ids per request).
- Recording is allowed for any student of the school, enrolled or not (admins use the school-wide page for
  students with no class).
- **The gate** (server side, `app/services/tutor.py`):
  - `GET` thread: returns as today plus `consent: bool`. Existing messages are still returned (after a withdrawal
    their text is null and they render as "This message was removed", the same as purged messages today).
  - Hint and chat requests without consent → 403 `{"code": "tutor_consent_required", "message": "The AI tutor needs
    a consent form from your parent or guardian. Ask your teacher."}`. Checked inside Tx 1 under the existing
    per-student advisory lock, before any row is written; nothing is sent to DeepSeek.
  - A reply arriving after a withdrawal (Tx 2): consent is re-read first, before the existing "question answered"
    check. If it is gone, the reply and the student row are stored with `text = null`, `purged_at = now`, status
    `late`; no hint is charged; the client gets 403 `tutor_consent_required` (this wins over 409
    `question_answered`).
  - `TUTOR_ENABLED=false` or no API key still wins: `enabled: false` hides the tutor for everyone as today.
- Hints already charged before a withdrawal stay on the attempts (XP history is not rewritten).
- Teachers' views of tutor use (hint usage card, flagged chats, per-student threads) are unchanged; messages with
  null text show "removed".

### The notice and form
- One source: `backend/app/privacy/notice.md` (Markdown with YAML front matter `version: "2026-11-v1"`,
  `title`). It says, in Class 9–10 parent-readable English: who runs the app, what the tutor is, what is sent
  (the question, the student's attempts and what they type; no name, username or school), where (DeepSeek, servers
  in China), retention (180 days, or at once on withdrawal), that the tutor never gives answers, that consent is
  optional and the student can use everything else without it, how to withdraw (tell the class teacher), and how
  to ask for a copy or erasure of the student's data (tell the school). The text is a draft for the legal review;
  bumping `version` is how a reviewed text ships.
- A new version does **not** invalidate consent recorded on an older one. The roster shows the form version, so a
  school can re-collect if the legal review says it must.
- `GET /api/v1/privacy/notice` returns `{version, title, body_md}` to any signed-in user.
- **Printing**: "Print consent forms" on the class Students tab opens `/classes/:id/consent-forms`: one A4 page per
  selected student (default: every active student without consent): school name, class name, student display name,
  the notice, and lines for parent/guardian name, relationship, signature and date, plus the form version in the
  footer. Nothing typed on paper is entered into the app.
- `/privacy` (any signed-in user, linked from the account menu): the same notice plus a short "What this app
  stores about you" section (static, in `notice.md` under a second heading).

### Export (right of access)
- `GET /api/v1/students/{id}/export` (admin only; teachers 403) returns
  `Content-Disposition: attachment; filename="student-{username}-{YYYY-MM-DD}.json"`, `Cache-Control: no-store`.
- Allowed for `active` and `deactivated` students, including one with a pending erasure. `erased` → 404.
- Writes an `export_downloaded` audit event before the body is returned.
- Content (`export_version: 1`, generated-at timestamp, all times ISO 8601 UTC):
  - `student`: id, display name, username, status, created_at; `school`: name, code.
  - `consent`: current state + the student's consent audit events (action, at, form version; actor as display name).
  - `classes`: name, subject, grade, enrolled_at.
  - `concepts`: per concept (course slug + concept slug + title): status, source, learned_at, relearn_count,
    conditional; KP progress; lesson progress.
  - `attempts`: item ref (course/concept/item slug), item_version, context, step, correct/result, `response` as
    stored, time taken, hints used, seed, created_at.
  - `study_time`: rows as stored (concept, step, activity, seconds, at).
  - `practice_sessions`, `remediations`, `xp_events`, `xp_days`, `goals`, `review_cards`, `review_log`,
    `quizzes` (+ items), `diagnostics` (status, counts, `results`), `assignments` that target the student
    (concept slugs, due date, note, computed status).
  - `tutor`: threads with messages (role, kind, status, flagged, text or `null` + `purged_at`, created_at).
  - `ai_summaries`: per-student teacher summaries about them (created_at, window, guarded content with the
    student's own token replaced by their name; other tokens left as tokens).
- **Never included**: `item.answer`, hidden tests, explanations, other students' data, internal token/latency
  counts, `teacher_summary.facts`/`pseudonyms`.
- Built in one transaction with a fixed number of queries (one per section, no per-row queries, the same count
  for one class or five); the `export_downloaded` insert is the only write and commits before the body is
  returned (no audit row = no download).
- CLI: `uv run app privacy export --org CODE --out DIR` writes `school.json` (school, classes, teachers: display
  name, email, role, status) and one `students/{username}.json` per non-erased student, same shape. Refuses to
  write into a directory inside the repo. Writes one `export_downloaded` event per student with a null actor and
  `meta.source = "cli"`.

### Erasure
- **Request** (`POST /api/v1/students/{id}/erasure`, admin only, body `{"confirm_username": "..."}`): the username
  must match (case-insensitive) → else 422 `confirm_mismatch`. In one flow: ban the Supabase auth user (existing
  `set_banned`; DB changes only after it succeeds, 502 otherwise, as deactivation today), set `status =
  deactivated`, `sessions_valid_after = now`, `erase_requested_at = now`, `erase_requested_by`, `erase_due_at = now
  + 7 days`; write `erase_requested`. Already pending → 409 `erasure_pending`. Already erased → 404.
- While pending the student is an ordinary deactivated student (visible to staff, greyed, with an "Erasure on
  {date}" badge) and can't sign in. Export still works.
- **Cancel** (`DELETE /api/v1/students/{id}/erasure`, admin only): clears the three `erase_*` columns, writes
  `erase_cancelled`. The student **stays deactivated**; the admin reactivates them with the existing switch.
  Nothing pending → 409 `no_erasure_pending`.
- Reactivating a student with a pending erasure (`PATCH /students/{id}` `status: active`) → 409
  `erasure_pending` "Cancel the erasure first."
- **Completion** (`app privacy run-due`, for every student with `erase_due_at <= now` and status `deactivated`),
  per student:
  1. Delete the Supabase auth user (`delete_user`; a 404 from Supabase counts as done). On any other failure, skip
     this student, report it, exit non-zero at the end; the next run retries.
  2. In one transaction: `display_name = 'Erased student'`, `username = 'erased-' + 12 random hex chars` (not
     derived from the id; the old username becomes free), `status = erased`, `must_change_password = false`,
     consent columns nulled, `erase_*` columns cleared, `erased_at = now`; null the text of all their
     `tutor_message` rows (`purged_at = now`); delete their `enrollment` and `assignment_student` rows; write
     `erase_completed` (null actor).
- **Kept after erasure** (by decision): the `app_user` row (anonymous), attempts including `response`, study time,
  concept/KP/lesson state, practice sessions, remediations, XP rows, goals, review cards and logs, quizzes,
  diagnostics, tutor message metadata, and `teacher_summary` rows (their `pseudonyms` still hold the now-anonymous
  id; on read the token renders as "a student no longer in this class", as for any removed student).
- **An erased student appears nowhere per-student**: not in rosters, the Students page, heatmap rows, at-risk
  lists, leaderboards, assignment pickers or new AI summary facts. `GET` of their student page, export, consent or
  erasure endpoints → 404. Their token is rejected with 401 like a deactivated user's.
- Erasure is not offered for teachers (out of scope).

### Audit log
- `audit_event`: append-only, one row per action. No names, usernames, emails or free text are stored in it: only
  ids, the action and a small `meta` JSON of counts/versions.
- Actions written:
  | Action | Written by | `meta` |
  |---|---|---|
  | `consent_recorded` / `consent_withdrawn` | consent endpoint | `form`, `messages_purged` (withdraw) |
  | `export_downloaded` | export endpoint, CLI | `source`: `ui` \| `cli` |
  | `erase_requested` / `erase_cancelled` / `erase_completed` | erasure endpoints, `run-due` | `due_at` (request) |
  | `password_reset` | `tenancy.reset_student_password` | |
  | `user_deactivated` / `user_reactivated` | `tenancy._set_status` (students and teachers) | `role` |
- The event is written in the same transaction as the change it records.
- `GET /api/v1/audit` (admin only): newest first, keyset-paginated (`before` cursor, `limit` ≤ 100), optional
  filters `action` and `target_id`. Each row: id, action, at, actor `{id, display_name}` or `null` ("System"),
  target `{id, display_name}` (an erased target shows "Erased student"), `meta`.
- Rows are never updated or deleted by the app. No retention job in this spec.

### Privacy jobs
- `uv run app privacy run-due` does, in order: (1) completes due erasures, (2) the 180-day tutor text purge
  (`tutor.purge_text`, unchanged; `app tutor purge` stays as an alias). Prints counts; idempotent; exit code 1 if
  any erasure failed.
- `.github/workflows/privacy-jobs.yml`: daily at 20:30 UTC (02:00 IST) and `workflow_dispatch`. Runs the command
  with `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` from repository secrets `PROD_DATABASE_URL`,
  `PROD_SUPABASE_URL`, `PROD_SUPABASE_SERVICE_ROLE_KEY`. It uses the same "is the secret present" gate step as
  `ci.yml` and does nothing when they are unset (deployment is out of scope; until then the command is run by
  hand, and `docs/runbooks/privacy.md` says so).

### Decided while specifying (builder check, Nov 2026)
- **Locking** (decided while specifying): withdrawal and erasure completion take the tutor's per-student advisory
  lock (`tutor:{student_id}`, ids in sorted order) and then lock the `app_user` rows in id order. Tutor Tx 2 takes
  the same advisory lock before re-reading consent, and `_close_pending` nulls the pending row's text when consent
  is gone. So no chat text can be written after a withdrawal commits.
- **Gate order** (decided while specifying): tutor disabled (503) → advisory lock → `_question` (404 / 409
  `tutor_not_here`) → consent (403) → the existing checks → `_ensure_thread`. `consent` is always present on the
  thread, also when `enabled` is false. `get_thread` reads it with one extra `app_user` query.
- **Consent request errors** (decided while specifying): ids are de-duplicated. Any id that is unknown, in another
  school, a teacher or erased → 404 for the whole request (as `enroll_students` does). A pending erasure → 422
  `consent_not_allowed` with `student_ids`, for `record` only; `withdraw` is allowed for any non-erased student.
- **Permission** (decided while specifying): `POST /students/consent` is staff-wide on the server. Showing the bulk
  bar on the school Students page to admins only is a UI choice, not a security boundary.
- **Audit actor** (decided while specifying): `audit.record(scope, action, target_id, meta, *, actor_id=...)`
  defaults to `scope.user.id`; the CLI and `complete_due` build `OrgScope.system(session, org_id)` per school and
  pass `actor_id=None` (the system scope's zero uuid must never be written).
- **Audit cursor** (decided while specifying): events of one request share a `created_at`, so the cursor is opaque
  (`"<created_at ISO>_<id>"`), ordered `(created_at DESC, id DESC)` with a row-value comparison; `next_before` is
  null on the last page.
- **Erasure request and status** (decided while specifying): the request calls `set_banned(True)` itself, always
  (also for an already deactivated student), does not go through `_set_status`, and writes only `erase_requested`
  with `meta.was_active`; no `user_deactivated` event.
- **`run-due` transactions** (decided while specifying): one transaction per student: claim one due row with `FOR
  UPDATE SKIP LOCKED`, call `delete_user` with the lock held (the one place an HTTP call runs inside a transaction;
  10 s timeout; `SupabaseAdminError.status == 404` = success), anonymise, commit. On failure roll back that
  student, log the id only, continue, exit 1. `FakeSupabaseAdmin` gains a way to fail `delete_user` with a status.
- **Other places an erased student could surface** (decided while specifying): `placement._student_row` and
  `placement.cancel` switch to `tenancy._get_student` (404 for erased); `enroll_students` treats an erased id as
  not found; `app org list` leaves erased rows out of its student counts. The frontend `UserStatus` type does not
  gain `erased` (erased users are never returned).
- **Export, assignment statuses** (decided while specifying): load the graph once, call `frontier.class_states`
  once for this student over all concepts and compute statuses in Python, so the query count does not depend on
  the number of classes. Assignments of archived classes are included.
- **Notice API** (decided while specifying): returns `{version, title, body_md, stores_md}`, split at the second
  H2 of `notice.md`. The printed form uses `body_md` only; `/privacy` shows both.
- **Operator name** (decided while specifying): `notice.md` carries the placeholders `[OPERATOR NAME]` and
  `[CONTACT]`; replacing them is a line in `docs/pilot-readiness.md`. A unit test lists remaining placeholders
  without failing `make check`.
- **Unenrolled students** (decided while specifying): the student page exists only inside a class, so the school
  Students page row menu gains, for admins: Download data, Erase…, Cancel erasure (the same `EraseDialog`).
  `StudentDetail` (`schemas/dashboard.py`) gains `username`, `tutor_consent_at`, `tutor_consent_form`,
  `erase_due_at` for the Privacy card.
- **Print view** (decided while specifying): the route sits outside `ClassLayout`, like slips. `students` is a
  comma-separated id list (absent = every active student without consent); unknown ids are ignored, students who
  already have consent are still printed if asked for. One page per student needs a new print rule
  (`.consent-form { break-after: page }`); the slips grid CSS is not reused.
- **Selection** (decided while specifying): neither roster table has row selection today; add it to
  `StudentRows.tsx` and `StudentsPage.tsx`. Selection is capped at 200 with a hint (no chunking: the request is
  all-or-nothing).
- **Dates** (decided while specifying): `erase_due_at` is exactly request time + 7 days. The UI shows its IST date
  as "Erasure after {date}" with the tooltip "Runs nightly".
- **Downgrade** (decided while specifying): sets `status = 'deactivated'` for erased rows (they stay anonymised
  and banned), drops `audit_event` and `audit_action`, leaves the enum value; a round-trip test includes one
  erased row.
- **CLI export path** (decided while specifying): `--out` is refused when it resolves under the repo root (the
  anchor `DEFAULT_CONTENT_ROOT` uses in `cli.py`) or under any ancestor holding `.git`, or is a non-empty
  directory.
- `docs/runbooks/` does not exist yet; this spec creates it.

## UI / UX
- **Class → Students tab** (`frontend/src/features/dashboard/StudentsTab.tsx`): a new "Tutor consent" column:
  "Recorded {date}" (tooltip: form version) or "Not recorded". Row checkboxes with a bulk bar: **Record consent**,
  **Withdraw consent**, **Print consent forms**. A filter chip "Without consent ({n})". Empty class: existing empty
  state, bulk bar hidden.
- **School Students page** (`features/students/StudentsPage.tsx`, staff): the same column; the bulk consent
  actions for admins only. Students with a pending erasure show an "Erasure on {date}" badge. Erased students are
  absent.
- **Student page** (`features/dashboard/StudentPage.tsx`): a "Privacy" card. For every teacher: consent state with
  Record/Withdraw. For admins also: **Download data (JSON)**, and **Erase student…** (danger) → dialog explaining
  the 7 days and what is kept ("learning records stay without a name"), with a type-the-username field; when
  pending: "Erasure scheduled for {date}" + **Cancel erasure**.
- **Consent forms print view** (`/classes/:id/consent-forms?students=...`): modelled on `features/slips`
  (print stylesheet, one page per student, a Print button hidden in print). Empty selection → "Every student in
  this class already has consent recorded."
- **Tutor button** (`features/tutor/TutorButton.tsx`, student): when the thread says `enabled && !consent`, the
  button is disabled with the lock note under it: "The AI tutor needs a consent form from your parent or guardian.
  Ask your teacher." If a request returns `tutor_consent_required` mid-session (withdrawn meanwhile), the panel
  closes and the same note appears.
- **Audit log** (`/audit`, admins; nav item under the existing admin section next to Teachers): a table (When ·
  Who · Action · Student/Teacher · Details), action filter, "Load more". Empty: "Nothing recorded yet."
- **`/privacy`**: the notice rendered with the existing Markdown component.
- Loading and error states use the existing patterns (`FullPageSpinner`, `FormError`, toasts). Consent dialogs use
  `ConfirmDialog`; `EraseDialog` is its own `AlertDialog` (input, button disabled until the username matches,
  inline `FormError`, stays open while the request runs). Works at phone width (the bulk bar wraps; the audit table scrolls horizontally).

## Technical design
- **Files / modules touched**
  - Backend, new: `app/privacy/notice.md`, `app/privacy/__init__.py` (loads + caches the notice, exposes
    `NOTICE_VERSION`); `app/services/consent.py` (record, withdraw, `has_consent`); `app/services/export.py`
    (`student_export(scope, student_id) -> dict`, `school_export`); `app/services/erasure.py` (request, cancel,
    `complete_due(session, admin, now)`); `app/services/audit.py` (`record(scope, action, target_id, meta)`,
    `list_events`); `app/api/v1/privacy.py` (notice, audit), routes added to `students.py` (consent, export,
    erasure); `app/schemas/privacy.py`; `alembic/versions/0013_privacy.py`;
    `.github/workflows/privacy-jobs.yml`; `docs/runbooks/privacy.md` (how to answer an access or erasure request,
    how to run the jobs by hand).
  - Backend, changed: `app/models/tenancy.py` (`UserStatus.erased`, new `AppUser` columns);
    `app/models/learning.py` or a new `app/models/audit.py` (`AuditEvent`, exported from `models/__init__.py`);
    `app/api/deps.py` (reject `erased` like `deactivated`); `app/services/tutor.py` (gate in `_reserve`/`_run`,
    `consent` on the thread, late-reply handling in `_store`, a `purge_student_text(scope, student_id, now)`
    helper shared by withdrawal and erasure); `app/schemas` tutor thread (`consent: bool`), `StudentOut` /
    `ClassStudentOut` (`tutor_consent_at`, `tutor_consent_form`, `erase_due_at`); `app/services/tenancy.py`
    (`list_students` and `_get_student` exclude `erased`; `_set_status` and `reset_student_password` write audit
    events; reactivation blocked while erasure is pending); `app/cli.py` (`privacy_app`: `run-due`, `export`).
  - Frontend, new: `src/features/privacy/` (`api.ts`, `ConsentBulkBar.tsx`, `ConsentFormsView.tsx`,
    `PrivacyCard.tsx`, `EraseDialog.tsx`, `AuditPage.tsx`, `PrivacyPage.tsx`, tests); routes in the router file
    for `/classes/:id/consent-forms`, `/audit` (admin guard like `/teachers`), `/privacy`.
  - Frontend, changed: `features/classes/StudentRows.tsx` (the roster table used by `StudentsTab.tsx`: consent
    column + row selection), `StudentsTab.tsx`, `StudentsPage.tsx`, `StudentPage.tsx`, `TutorButton.tsx` /
    `TutorPanel.tsx`, `src/lib/types.ts`.
  - Docs: `docs/ARCHITECTURE.md` (domain model: consent columns, `erased`, `audit_event`; Boundaries: the consent
    gate and what erasure keeps), `CLAUDE.md` Gotchas (one line: "student queries must exclude `erased`; use the
    existing roster helpers"), `docs/PRD.md` Constraints (the four assumptions).
- **Data model changes** (migration `0013_privacy`)
  - `user_status` enum: add `erased` (`ALTER TYPE ... ADD VALUE` in its own autocommit block; downgrade leaves
    the value in place, as Postgres can't drop it, and the migration test accepts that).
  - `app_user`: `tutor_consent_at timestamptz null`, `tutor_consent_by uuid null`, `tutor_consent_form text null`,
    `erase_requested_at timestamptz null`, `erase_requested_by uuid null`, `erase_due_at timestamptz null`,
    `erased_at timestamptz null`. Composite FKs `(tutor_consent_by, org_id)` and `(erase_requested_by, org_id)` →
    `app_user(id, org_id)`. CHECKs: consent columns all null or all set, and only for `role = 'student'`;
    `(erase_requested_at IS NULL) = (erase_due_at IS NULL)`; `(status = 'erased') = (erased_at IS NOT NULL)`.
    Partial index on `erase_due_at WHERE erase_due_at IS NOT NULL`.
  - `audit_event` (`TenantMixin`, RLS enabled, no policies): `id uuid pk`, `org_id`, `actor_id uuid null`,
    `action` (Postgres enum `audit_action`), `target_id uuid null`, `meta jsonb not null default '{}'`,
    `created_at timestamptz not null default now()`. Composite FKs `(actor_id, org_id)` and `(target_id, org_id)` →
    `app_user(id, org_id)`. Index `(org_id, created_at desc, id)`; index `(org_id, target_id, created_at)`.
  - `enrollment`, `assignment_student`: no schema change (rows deleted at completion).
- **API / interfaces** (all under `/api/v1`, all through `OrgScope`; added to the route-walking test)
  | Method + path | Who | Body → result |
  |---|---|---|
  | `GET /privacy/notice` | any user | → `{version, title, body_md}` |
  | `POST /students/consent` | staff | `{student_ids[1..200], action: "record" \| "withdraw"}` → `StudentOut[]` |
  | `GET /students/{id}/export` | admin | → JSON attachment |
  | `POST /students/{id}/erasure` | admin | `{confirm_username}` → `StudentOut` |
  | `DELETE /students/{id}/erasure` | admin | → `StudentOut` |
  | `GET /audit?action=&target_id=&before=&limit=` | admin | → `{items[], next_before}` |
  - `GET /tutor/...` thread: `+ consent: bool`. Hint/chat: `403 tutor_consent_required`.
  - CLI: `app privacy run-due`, `app privacy export --org CODE --out DIR`.
- **Extension points** (not built): a sign-in gate would be one more check in `get_current_user` on a second
  consent column; nulling `attempt.response` at erasure is one more `UPDATE` in `erasure.complete_due`.
- **Dependencies**: none new.

## Edge cases
- Staff in school A send a student id of school B to any endpoint → 404; nothing written (tenant isolation test).
- A consent request mixing valid ids with an erased, unknown or teacher id → 422/404, nothing saved.
- Two teachers record consent for the same student at once → one event, one timestamp (row lock; second is a no-op).
- Consent withdrawn while the tutor is replying → the reply is stored without text and the student sees the lock.
- A student with consent is deactivated and later reactivated → consent is kept.
- A student is enrolled in three classes → consent shows in all three rosters; recording it in one shows in all.
- Erasure requested for a student who is mid-quiz or mid-session → sessions are left as they are (never resumed).
- Erasure requested for an already deactivated student → allowed; cancel leaves them deactivated.
- Supabase admin API down at request → 502, nothing changed. Down at completion → that student is retried on the
  next run; other students are still processed.
- The auth user was already deleted by hand in the Supabase dashboard → completion treats 404 as success.
- `run-due` runs twice at the same moment (manual + cron) → each erasure is claimed with `SELECT ... FOR UPDATE
  SKIP LOCKED`; the second run does nothing for that student.
- A username freed by erasure is reused for a new student → no link to the anonymous rows (different id).
- A new student gets a display name of "Erased student" → allowed; it is only a label.
- Export of a student with tens of thousands of attempts → still one response. Measured once by hand with 20k
  seeded attempts and recorded in the PR (target: under 5 s and under 20 MB; if it isn't, stream the `attempts`
  array). Not an automated test: the shared test database is too slow and noisy for timing asserts.
- Export requested for a student whose content was retired → items are named by slug; retired content still
  resolves (content is retired, never deleted).
- An admin erases the student, then opens an old bookmark of the student page → 404 page, not an error.
- Audit page for a school with no events → empty state. An actor who was later deactivated still shows by name.
- A teacher (not admin) calls export/erasure/audit → 403.
- The class leaderboard, assignments' "chosen students" and at-risk lists after completion: the student is gone
  and counts drop by one; an assignment whose only chosen student was erased shows "0 students" and can be deleted.

## Out of scope
- Collecting consent online (parent code, OTP), storing parent names or contacts, uploading scans of forms.
- Gating sign-in or learning on consent; a separate consent for teacher summaries; excluding students from them.
- Hard delete of learning rows; wiping `attempt.response` or teacher summaries at erasure; erasing teachers;
  deleting a whole school; a self-service request form for parents or students.
- A purge or retention job for `teacher_summary` or `audit_event`.
- Export as CSV/ZIP/PDF; export by teachers; export from the student's own account.
- Re-consent prompts when the notice version changes; translations of the notice.
- Deploying anything, and creating the production secrets the workflow needs.
- Error tracking, backups, load test, rate limiting, security headers, CI scanning, the security review (spec 015).
- The legal review and the teacher content review (tracked in `docs/pilot-readiness.md`).

## Verification (end-to-end)
Delivered as two PRs on `feat/014-privacy`: **PR 1** consent + notice + audit log; **PR 2** export + erasure + jobs.

- [x] `cd backend && uv run mypy` and `cd frontend && pnpm typecheck` clean; `make check` green.
- [x] `tests/test_consent_db.py`: record/withdraw (bulk, no-op repeats, all-or-nothing 422), withdrawal nulls only
      that student's message text and keeps counts, audit events written, concurrent record → one event.
- [x] `tests/test_tutor_api_db.py` (extended): hint and chat without consent → 403 and **no model call** (the fake
      client records zero calls) and no rows; thread has `consent: false`; with consent the existing tests pass;
      a withdrawal between Tx 1 and Tx 2 stores no text and charges no hint.
- [x] `tests/test_export_db.py`: the export of a seeded student has every section; a second student's rows never
      appear; a recursive key/value scan finds no `answer`, hidden test or explanation from `item.answer`; query
      count is fixed (`tests/query_count.py`) for 1 and for 500 attempts; teacher → 403; erased → 404.
- [x] `tests/test_erasure_db.py`: request (wrong username 422, ban called before the DB change, 502 leaves no
      change), cancel, reactivation blocked while pending, `complete_due` before/after the due time, auth 404
      treated as success, auth failure retried and reported, anonymised fields, enrolment/assignment links gone,
      attempts kept, token rejected afterwards, erased student absent from `list_students`, class roster,
      dashboard overview, heatmap, leaderboard and teacher-summary facts; old username reusable.
- [x] `tests/test_audit_db.py`: every action in the table writes one event in the same transaction (a rolled-back
      change leaves no event); pagination; filters; no event contains a name, username or email (scan of `meta`).
- [x] `tests/test_tenant_isolation_db.py`, `tests/test_route_scoping.py`, `tests/test_rls_db.py`,
      `tests/test_migrations_db.py` extended for the new routes, table and migration; `make test-db` green.
- [x] `tests/test_cli.py` (offline, service functions monkeypatched): `app privacy run-due` (counts printed, exit
      code 1 on a failure), `app privacy export` (arguments, refuses a path inside the repo or a non-empty
      directory). The real behaviour is covered by the two `_db` files above.
- [x] Frontend vitest: consent bulk bar (select, confirm, optimistic refresh, error), print view (page per
      student, empty state), tutor lock note, erase dialog (button disabled until the username matches), audit
      page (empty, filter, load more).
- [ ] `.github/workflows/privacy-jobs.yml` passes `actionlint` and a `workflow_dispatch` run without secrets ends
      green with "skipped: no production secrets".
- [x] `security-reviewer` subagent on each PR's diff: no high findings open (export and erasure are the focus).
- [ ] Browser check: `make dev` (after `make migrate`; check `alembic current`). As a teacher: print forms for a
      class (print preview screenshot), record consent for two students, withdraw one. As that student: the lock
      note, then the working tutor once consent is back. As an admin: download a student's JSON, request erasure,
      cancel it, request again, run `app privacy run-due` with the due date moved back, confirm the student is
      gone from the roster, heatmap and Students page, and read the audit log. Screenshots of: Students tab with
      the consent column, the print view, the locked tutor button, the Privacy card (idle + pending), the audit
      page, and each at phone width. Also the empty states (class with no students; audit with no events).
