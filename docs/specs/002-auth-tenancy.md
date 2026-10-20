# Spec 002: Auth & tenancy

Status: implemented (feat/002-auth-tenancy)
PRD link: docs/PRD.md#mvp-scope-v1 (item 1; Phase 0 of docs/ROADMAP.md)

## Summary
Schools (orgs) are created by our team with a CLI. A school admin invites teachers by email; teachers create classes and
create student accounts (display name only, no email) with printable username + temporary-password slips. Everyone signs
in through Supabase Auth; FastAPI verifies the JWT and every tenant-owned query goes through one org-scoping dependency,
so a teacher in school A can never see anything in school B (tested). Ships with a polished, responsive app shell.

## User stories
- As our team, I want `uv run app org create ...` so that I can onboard a pilot school and its first admin in one step.
- As a school admin, I want to invite teachers by email, make them admins, and deactivate them.
- As a teacher, I want to create a class (e.g. "9A Maths"), paste a list of names to create student accounts, and print
  login slips, so that a whole class can start in one period.
- As a teacher, I want to add existing students to another class (e.g. 9A Physics) without new accounts.
- As a teacher, I want to reset a student's forgotten password, since students have no email.
- As a student, I want to sign in with my school code, username and password, and set my own password the first time.
- As any user, I want a clean app shell that works on a phone and a lab desktop.

## Behaviour

### Identity and roles
- Auth provider: **Supabase Auth** (same project as the DB). Our `app_user.id` = the Supabase auth user id (`sub`).
- One school per user. `role` is `teacher` or `student`. `is_admin` (bool) is allowed only for teachers (DB check
  constraint); an admin who doesn't teach is still a `teacher`. "Staff" below = role `teacher` (admin or not).
- `status`: `invited` (teacher who hasn't accepted yet) → `active` → `deactivated` (and back to `active`).
- **Teachers see the whole school** (all classes, all students). Admin-only actions: manage teachers, change `is_admin`,
  deactivate/reactivate any user.

### Personal data (minors)
- Students: `display_name` only (teacher-entered, e.g. "Aarav S."; 1–40 chars, trimmed). No email, DOB, phone, gender,
  roll number. Plus a generated `username`.
- Teachers: `display_name` + `email` (adults; email needed for invites and password reset).
- Never log display names, usernames, emails, passwords or temp passwords. Logs reference user ids only.

### Schools (CLI)
- `uv run app org create --name "Delhi Public School, RK Puram" --code DPS-RKP --admin-email a@x.in --admin-name "Ms Rao"`
  - `code`: 3–12 chars, `[A-Z0-9-]`, stored uppercase, globally unique, immutable. Students type it at login.
  - Creates the `organization` and invites the admin (same flow as a teacher invite, with `is_admin=true`).
  - Errors: duplicate code → `School code DPS-RKP is already taken.`; email already a user anywhere → `That email already
    belongs to a user.`; exit code 1. Idempotency not required, but a failure must leave no half-created org (create
    the auth invite first; if the DB insert fails, delete the auth user).
- `uv run app org list` prints code, name, user counts. That's all the CLI does in this spec.
- The `app` console script (`[project.scripts] app = "app.cli:main"`, Typer) is introduced here; spec 003 adds
  `app content ...` subcommands to it.

### Teacher invites
- Admin: invite (email + display name) → backend calls the Supabase admin invite API with
  `redirect_to = {APP_URL}/accept-invite`, then inserts `app_user(status=invited, role=teacher)` with the returned id.
- Email already in **any** school → 409 `That email already belongs to a user.` (don't reveal which school).
- Resend invite (only while `invited`). Revoke invite = deactivate.
- Teacher opens the link → `/accept-invite` → sets a password (min 8 chars) via supabase-js → first authenticated
  `GET /me` flips `invited` → `active`.
- Staff "Forgot password?" on the login page uses Supabase's email recovery (`/reset-password` page).

### Student accounts (teacher-created)
- Created only inside a class: "Create new students" takes up to **60 names** (one per line; blank lines ignored;
  duplicates within the paste are allowed — they become different users).
- **Username**: lowercase ASCII letters of the first word of the display name (max 12; `student` if none) + 2 random
  digits (3 digits, then 4, if taken), unique per school (case-insensitive). Example: "Aarav S." → `aarav42`. Usernames
  are immutable.
- **Auth email** (internal, never shown): `{username}@{code-lowercase}.students.invalid`, created via the admin API with
  `email_confirm: true` (no email is ever sent).
- **Temp password**: two words from a built-in wordlist of short, common English words + 2 digits, e.g. `tiger-maple-42`
  (cryptographically random via `secrets`). Returned **once** in the create/reset response; never stored by us.
- `must_change_password = true` for new students and after a reset. While true, every API route except `GET /me` and
  `POST /me/password` returns 403 `{"code": "password_change_required"}`; the frontend routes to `/change-password`.
- `POST /me/password` (min 8 chars, max 72) updates the password via the admin API and clears the flag.
- Reset password (any teacher): new temp password, sets `must_change_password`, signs the student out of other sessions
  (admin API `logout`/session revoke), shows a single slip.
- Bulk create is all-or-nothing: if any admin-API call fails, delete the auth users already created in this request and
  return 502 `Could not create accounts right now. Nothing was saved; please try again.`

### Classes
- Fields: `name` (1–40, unique per school among non-archived classes, case-insensitive), `subject`
  (`maths` | `physics` | `python`), `grade` (9 | 10), `archived_at`.
- Any teacher can create, edit, archive/unarchive any class in their school. The creator becomes its first teacher.
- `class_teacher` links teachers to classes for the **"My classes"** default view (with an "All classes" tab). It grants
  no extra access. Any teacher can add/remove co-teachers.
- Enrolment: create new students (above) or **add existing** students (search the school roster by display name or
  username, multi-select). Unenrol removes the link only; the student's account and data are kept.
- Archived classes are read-only (no enrol/create students) and hidden from "My classes" by default.

### Deactivation (admin only)
- Deactivate any user: `status=deactivated`, Supabase admin `ban_duration` set long (`876000h`) so refresh fails; our
  API rejects the user immediately on the next request (status is checked on every request, so a still-valid 1 h access
  token doesn't help). Reactivate reverses both.
- **Last admin protection**: refuse to remove `is_admin` from, or deactivate, the last active admin of a school
  → 409 `A school needs at least one active admin.`

### Auth on the API
- Frontend sends `Authorization: Bearer <supabase access token>` on every `/api/v1` call (except `/health`).
- Verification (`app/core/auth.py`): PyJWT, asymmetric keys from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
  (cached 10 min; on unknown `kid` refetch once), `aud="authenticated"`, `iss="{SUPABASE_URL}/auth/v1"`, `exp` required,
  30 s leeway. If `SUPABASE_JWT_SECRET` is set (legacy projects), HS256 with that secret is accepted instead.
- Errors: missing/invalid/expired token → 401 `{"code": "unauthenticated"}`; valid token but no `app_user` row or
  `deactivated` → 401 `{"code": "unauthenticated"}` (same message, no enumeration); wrong role → 403
  `{"code": "forbidden"}`.

### Org scoping (the choke point)
- `app/api/deps.py`:
  - `get_current_user` → verified token → loads `app_user` by `sub` → `CurrentUser(id, org_id, role, is_admin, ...)`;
    enforces status and `must_change_password`.
  - `require_staff`, `require_admin`, `require_student` (thin wrappers).
  - `OrgScope` (dependency built from `CurrentUser`): `scope.select(Model)` returns `select(Model).where(Model.org_id ==
    org_id)`; `await scope.get(Model, id)` returns the row or raises **404** (never 403: don't reveal that an id exists in
    another school); `scope.new(Model, **kw)` sets `org_id`.
- Every tenant-owned model inherits a `TenantMixin` (`org_id` NOT NULL, FK, indexed). Services take an `OrgScope`, never
  a raw session + id.
- Link tables carry `org_id` with **composite FKs** (`(class_id, org_id) → school_class(id, org_id)`, same for users), so
  the DB itself rejects cross-school links.
- **RLS deny-all**: the migration runs `ALTER TABLE … ENABLE ROW LEVEL SECURITY` (no policies) on every table in
  `public`, including `alembic_version`, so Supabase's Data API (anon/authenticated keys) can read nothing. Our backend
  connects as the `postgres` role, which bypasses RLS.

## UI / UX
Polished, responsive app shell on **shadcn/ui** (Radix + Tailwind, components copied into `src/components/ui`) with
`lucide-react` icons. Neutral palette, light + dark (follows the OS). Works at 360 px wide and on lab desktops.

- **Shell**: top bar (school name, user menu with display name, role badge, "Sign out"). Desktop: left sidebar nav;
  phone: hamburger sheet. Nav by role — Student: Home. Teacher: Classes, Students. Admin adds Teachers.
  Toasts for success/errors; skeleton loaders for lists; empty states with a primary action.
- **`/login`**: tabs **Student** (school code, username, password) / **Staff** (email, password, "Forgot password?").
  School code is remembered on the device (localStorage, wrapped in try/catch). Wrong credentials →
  `Incorrect school code, username or password.` (one message for all cases). The API health line from spec 001 moves
  to a small footer here.
- **`/accept-invite`**, **`/reset-password`**: set-password form (min 8, confirm). Expired/invalid link →
  `This link has expired. Ask your school admin to resend the invite.`
- **`/change-password`**: forced for students with a temp password; can't navigate away except Sign out.
- **Student home** `/`: "Hi Aarav" + "Your courses will appear here soon." (stub until spec 004).
- **`/classes`**: tabs My classes / All classes; cards or table with name, subject, grade, student count, teachers;
  "New class" dialog; "Show archived" toggle.
- **`/classes/:id`**: header (name, subject, grade, teachers with add/remove), student table (display name, username,
  status) with row menu: Reset password, Remove from class. "Add students" dialog with two tabs: **Create new** (textarea,
  live count, "max 60") and **Add existing** (search + checkboxes). After create/reset → **slips view**.
- **Slips view** (`/classes/:id/slips`, in-memory only): one card per student: school name, school code, username, temp
  password, "You'll choose your own password when you first sign in." Print CSS: 8 slips per A4, cut lines. A banner
  warns: `These passwords are shown once. Print or note them before leaving this page.` Navigating away asks to confirm
  (in-app confirm dialog, not `window.confirm`).
- **`/students`**: school roster with search, class chips, Reset password; admin also Deactivate/Reactivate.
- **`/teachers`** (admin): list (name, email, status, admin badge); Invite dialog; Resend invite; Make/Remove admin;
  Deactivate/Reactivate.
- Guards: unauthenticated → `/login`; wrong role → a 403 page with a link home.

## Technical design
- Files / modules touched (new unless noted):
  - Backend
    - `pyproject.toml` (edit): deps `pyjwt[crypto]`, `httpx` (move from dev to runtime), `typer`;
      `[project.scripts] app = "app.cli:main"`. `uv.lock` regenerated by `uv add`, never by hand.
    - `app/core/config.py` (edit): `supabase_url` (required at runtime; dummy in tests), `supabase_service_role_key`
      (secret, `SecretStr`, never logged), `supabase_jwt_secret` (optional, legacy), `app_url` (for invite redirects).
    - `app/core/auth.py` (JWT/JWKS verification), `app/core/passwords.py` (temp password + wordlist),
      `app/core/usernames.py` (username generation)
    - `app/services/supabase_admin.py`: the Supabase admin client, a small `httpx` client behind
      a `SupabaseAdmin` Protocol (`invite`, `create_user`, `update_password`, `set_banned`, `sign_out`, `delete_user`)
      so tests inject a fake.
    - `app/models/tenancy.py` (`Organization`, `AppUser`, `SchoolClass`, `ClassTeacher`, `Enrollment`, `TenantMixin`)
    - `app/api/deps.py` (`get_current_user`, `require_*`, `OrgScope`)
    - `app/api/v1/me.py`, `teachers.py`, `students.py`, `classes.py`; `router.py` (edit)
    - `app/schemas/tenancy.py`, `app/services/tenancy.py` (business rules: last admin, bulk create, enrol)
    - `app/cli.py` (Typer: `org create`, `org list`)
    - `alembic/versions/0002_auth_tenancy.py` (tables, enums, composite FKs, RLS deny-all on all public tables)
    - Tests listed under Verification.
  - Frontend
    - deps: `@supabase/supabase-js`, shadcn/ui deps (Radix packages, `class-variance-authority`, `clsx`,
      `tailwind-merge`), `lucide-react`. Lockfile via `pnpm add` only.
    - `src/lib/supabase.ts` (client from `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`), `src/lib/api.ts` (edit:
      `apiFetch` with bearer token, JSON body, typed `ApiError` carrying `code`; 401 → sign out → `/login`;
      `password_change_required` → `/change-password`)
    - `src/features/auth/` (AuthProvider + `useAuth`, `useMe` query, `RequireAuth`/`RequireRole` guards, Login,
      AcceptInvite, ResetPassword, ChangePassword pages)
    - `src/components/ui/*` (shadcn), `src/components/layout/AppShell.tsx` (+ Sidebar, MobileNav, UserMenu)
    - `src/features/classes/`, `src/features/students/`, `src/features/teachers/` (pages, dialogs, `SlipsView` + print CSS)
    - `src/routes.tsx` (edit), `src/pages/HomePage.tsx` (edit: student stub), `src/pages/ForbiddenPage.tsx`
  - Env: `backend/.env.example` needs `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` (optional),
    `APP_URL`; `frontend/.env.example` needs `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. **A hook blocks editing
    `.env*`**: the implementer must list the exact lines and ask the user to add them.
  - Docs (edit): `docs/ARCHITECTURE.md` (Auth row → Supabase Auth; domain model → `app_user`, `school_class`,
    `class_teacher`; RLS deny-all note), `docs/ROADMAP.md` row 002 ("invite-by-code" → "teacher-created student
    accounts, admin-invited teachers"), `CLAUDE.md` Gotchas (synthetic student emails; services take `OrgScope`).
- Data model changes (migration `0002`):
  - `organization(id uuid pk, name text, code citext/upper unique, created_at)`
  - `app_user(id uuid pk = auth uid, org_id fk, role enum(teacher, student), is_admin bool default false,
    display_name text, username text null, email text null, status enum(invited, active, deactivated),
    must_change_password bool, created_at, updated_at)`; unique `(org_id, lower(username))`; unique `lower(email)`;
    unique `(id, org_id)` (composite FK target); checks: `is_admin → role = teacher`, `role = student ↔ username not
    null and email null`.
  - `school_class(id uuid pk, org_id fk, name, subject enum(maths, physics, python), grade smallint check in (9,10),
    archived_at null, created_by fk, created_at)`; unique `(org_id, lower(name)) where archived_at is null`; unique
    `(id, org_id)`.
  - `class_teacher(class_id, user_id, org_id)` and `enrollment(class_id, student_id, org_id, created_at)`; PKs on the
    pair; composite FKs to `school_class(id, org_id)` and `app_user(id, org_id)`.
  - RLS enabled, no policies, on every table in `public`.
- API / interfaces (`/api/v1`, all JSON; ids are UUIDs):
  | Method + path | Who | Notes |
  |---|---|---|
  | `GET /me` | any | `{id, display_name, role, is_admin, username?, must_change_password, org: {name, code}}`; flips `invited→active` |
  | `POST /me/password` | any | `{new_password}` → 204 |
  | `GET /teachers` | staff | list |
  | `POST /teachers/invite` | admin | `{email, display_name}` → 201 teacher |
  | `POST /teachers/{id}/resend-invite` | admin | 204; 409 if not `invited` |
  | `PATCH /teachers/{id}` | admin | `{is_admin?, status?}`; last-admin rule |
  | `GET /students?q=&class_id=` | staff | roster with class ids |
  | `PATCH /students/{id}` | staff (`status`: admin) | `{display_name?, status?}` |
  | `POST /students/{id}/reset-password` | staff | → `{username, temp_password}` |
  | `GET /classes?mine=&archived=` | staff | with student count + teachers |
  | `POST /classes` | staff | `{name, subject, grade}` → 201 |
  | `GET /classes/{id}` · `PATCH /classes/{id}` | staff | PATCH `{name?, subject?, grade?, archived?}` |
  | `PUT /classes/{id}/teachers/{user_id}` · `DELETE …` | staff | add/remove co-teacher |
  | `GET /classes/{id}/students` | staff | |
  | `POST /classes/{id}/students` | staff | `{display_names: [..≤60]}` → 201 `[{id, display_name, username, temp_password}]` |
  | `POST /classes/{id}/enrollments` · `DELETE /classes/{id}/enrollments/{student_id}` | staff | `{student_ids}`; idempotent |
  Validation errors are 422 with field messages; conflicts 409 with `{code, message}`.

## Edge cases
- Cross-school id in any path or body (class, student, teacher, `student_ids` in enrol) → 404, and nothing changes.
- Enrolling a teacher id as a student, or a deactivated student → 422 `Only active students can be enrolled.`
- Username collisions under concurrency: unique index + retry with a new suffix (max 5 tries).
- Names with only non-ASCII letters (e.g. Devanagari) → username `student42`; display name kept as typed.
- School code typed in lowercase or with spaces at login → trimmed and uppercased before building the auth email.
- Student who forgot their username: teacher sees it in the class table.
- Supabase admin API down/slow (10 s timeout): invites, creates, resets, deactivation → 502 with a friendly message;
  nothing partially saved (deactivation: DB update only after the ban call succeeds).
- Invite link expired: teacher sees the expired message; admin resends.
- Deactivated user with a still-valid access token → 401 on the next request; frontend signs out.
- Removing yourself as the last admin → 409. Admin deactivating themselves when another admin exists → allowed, signed
  out.
- Same browser, shared lab computer: Sign out clears the Supabase session; the remembered school code stays (not
  personal data).
- Supabase free project paused: login fails with `Can't reach the sign-in service. Try again in a minute.`
- JWKS fetch fails and nothing cached → 503 `{"code": "auth_unavailable"}`, not 401 (don't sign users out).

## Out of scope
- Parental consent / DPDP flow, data export and hard delete (spec 014).
- Student self-signup or join-by-code; public signup; parent accounts.
- Users in more than one school; moving a user between schools; renaming a school code.
- Platform super-admin UI (CLI only); SSO / Google sign-in; MFA.
- Real per-org RLS policies (deny-all only); audit log of admin actions.
- Password strength beyond min length; preventing reuse of the temp password.
- Bulk import from CSV files; editing usernames; class rollover / academic years.
- Linking classes to courses (spec 003/010); dashboards and any learning data.
- Rate limiting our own endpoints (Supabase rate-limits auth; tutor limits come in 009).
- Playwright e2e (manual verification below instead).

## Deviations (as built)
- **No `sign_out` in `SupabaseAdmin`.** GoTrue has no per-user admin sign-out; an admin password update already revokes
  all of the user's sessions. Already-issued access tokens are cut off by `app_user.sessions_valid_after`: the API
  rejects tokens whose `iat` is earlier (set on admin reset, in-app password change and deactivation).
- **`invited` → `active` on any first authenticated request**, not only `GET /me` (`app/api/deps.py`), so the status is
  right even if the client's first call is something else.
- **Reset-password slips** open at `/slips` (one student, from the Students page); class slips stay at
  `/classes/:id/slips`.
- **Username collisions**: a per-school advisory lock plus a pre-insert check instead of insert-and-retry. Same result; a
  unique violation that still slips through returns an error instead of retrying.
- Staff resetting their own password via email recovery goes straight to Supabase, so `sessions_valid_after` isn't set:
  access tokens on other devices last until they expire (≤ 1 h).

## Verification (end-to-end)
Offline (`make check`):
- [x] `tests/test_auth.py`: a test EC keypair + fake JWKS → valid token accepted; expired, wrong `aud`, wrong `iss`,
      unknown `kid` (after one refetch), bad signature, missing header → 401; JWKS unreachable → 503; legacy HS256 path.
- [x] `tests/test_deps.py`: deactivated / unknown user → 401; `must_change_password` → 403 on a normal route, allowed on
      `/me` and `/me/password`; student on a staff route → 403; non-admin on admin route → 403.
- [x] `tests/test_route_scoping.py`: walks `app.routes`; every `/api/v1` route except `/health` depends on
      `get_current_user`, and every route with a tenant path param depends on `OrgScope`. Fails naming the route.
- [x] `tests/test_usernames.py`, `tests/test_passwords.py`: generation rules, non-ASCII fallback, entropy/charset.
- [x] `tests/test_cli.py`: arg validation (bad code format) with a fake admin client.
- [x] Frontend vitest: Login (both tabs, error message, school code remembered), `RequireRole` redirects, `apiFetch`
      401 → sign-out and `password_change_required` → `/change-password`, Create-students dialog (count, >60 blocked),
      SlipsView renders one card per student.
DB (`make test-db`, against the test Supabase project, Supabase admin faked):
- [x] Fixture runs `alembic upgrade head` and truncates tables per test.
- [x] `tests/test_tenant_isolation_db.py`: seed school A and B (admin, teacher, 2 classes, 3 students each). As A's
      teacher, call **every** endpoint with B's ids → 404 and B unchanged; every list endpoint returns only A's rows;
      enrolling B's student into A's class → 404; a raw insert of a cross-school `enrollment` → FK error.
- [x] `tests/test_tenancy_db.py`: bulk create (usernames unique, flag set, rollback calls `delete_user` on failure),
      add existing / unenrol idempotent, last-admin rule, archive blocks enrolment, invite → `GET /me` activates.
- [x] `tests/test_rls_db.py`: every table in `public` has `relrowsecurity = true`.
Manual (real Supabase dev project; `make migrate`, `make dev`):
- [x] `uv run app org create --name "Test School" --code TST --admin-email <you> --admin-name "Admin"` → invite email
      arrives; accept → set password → lands in the shell with Teachers in the nav.
- [x] Invite a second teacher (another email), accept, make them admin, then try to remove admin from both → second
      attempt gets "A school needs at least one active admin."
- [x] Create class "9A Maths" (maths, 9); paste 5 names (one in Devanagari) → slips view shows 5 cards; print preview
      shows 8-per-A4 layout. Screenshot it.
- [x] Sign in on a phone-width window as one student (code in lowercase) → forced to `/change-password` → set password
      → student home stub. Screenshot the shell at 360 px and desktop.
- [x] Create "9A Physics", add 2 existing students via search; unenrol one; their account still signs in.
- [x] Reset a student's password → old password fails, new slip works.
- [x] Admin deactivates a student who is signed in elsewhere → their next action signs them out.
- [ ] *(Skipped in the manual pass; covered by `tests/test_tenant_isolation_db.py`.)* Create a second school with the CLI; its teacher sees none of "Test School"'s classes or students; pasting a
      "Test School" class URL shows Not found.
- [x] With the anon key: `curl "$SUPABASE_URL/rest/v1/app_user" -H "apikey: $ANON"` → `[]`.
- [x] `make check` green; `make test-db` green; reviewer subagent + security-reviewer run on the diff.
