# Plan: build spec 002 (Auth & tenancy)

Spec: `docs/specs/002-auth-tenancy.md` · Branch: `feat/002-auth-tenancy` (from `main`, clean at 94f109d)

## Context
Spec 001 left an empty scaffold (FastAPI health route, baseline migration, Vite page with health check). Spec 002 adds
the first real feature: Supabase Auth, schools/users/classes/enrolment, and the single org-scoping dependency that makes
"a teacher in school A cannot see anything in school B" true and tested. Every later spec builds on `CurrentUser` +
`OrgScope` + `TenantMixin`, so the choke point must be solid and enforced by a route-walking test.

## Ground rules for the build
- After each step: `make check` and show the output. Small descriptive commits per step on the feature branch
  (`/ship` does the final commit + PR).
- Deps only via `uv add` / `pnpm add` (lockfiles are hook-protected). `.env*` files are hook-protected: I'll print the
  exact lines for `backend/.env(.example)` and `frontend/.env(.example)` and ask you to add them (step 1).
  Note: `.env.example` *is* allowed by the hook, so I'll edit the two example files myself and only ask you for real `.env`.
- Never log names/usernames/emails/passwords; log user ids and exception class names only (existing pattern in
  `app/api/v1/health.py`).
- Reuse: `Base` + naming convention (`app/db/base.py`), `get_session` (`app/db/session.py`), `get_settings` +
  conftest env pattern (`tests/conftest.py`), `db` marker + `_require_test_db`, `ApiError` in `src/lib/api.ts`.

## Steps

### 1. Branch, backend deps, config
- `git checkout -b feat/002-auth-tenancy`.
- `uv add 'pyjwt[crypto]' httpx typer` (httpx moved dev → runtime: `uv remove --dev httpx` first); add
  `[project.scripts] app = "app.cli:main"`; `cryptography` comes via pyjwt[crypto] (also used in tests for EC keys).
- `app/core/config.py`: `supabase_url`, `supabase_service_role_key: SecretStr | None`, `supabase_jwt_secret:
  SecretStr | None`, `app_url` (default `http://localhost:5173`). Runtime accessors raise a clear error if
  `supabase_url`/service key are missing when actually used (so `make check` stays offline). conftest sets dummy
  `SUPABASE_URL`.
- Edit `backend/.env.example`, `frontend/.env.example`; ask you to add real values to `.env` files.

### 2. Pure helpers + JWT verification (offline tests)
- `app/core/usernames.py`: `username_base(display_name)` (first word → lowercase ASCII letters, ≤12, else `student`),
  `candidate(base, digits)` using `secrets`; digits 2 → 3 → 4 escalation.
- `app/core/passwords.py`: built-in wordlist (~300 short common words), `temp_password()` → `word-word-NN` via `secrets`.
- `app/core/auth.py`: `TokenVerifier` with JWKS cache (10 min TTL, refetch once on unknown `kid`), PyJWT
  `aud="authenticated"`, `iss="{SUPABASE_URL}/auth/v1"`, `require=["exp","sub"]`, leeway 30 s; HS256 path when
  `SUPABASE_JWT_SECRET` set. Raises `Unauthenticated` / `AuthUnavailable` (→ 503 `auth_unavailable`). JWKS fetched via
  an injectable httpx client so tests use a fake.
- Tests: `test_usernames.py`, `test_passwords.py`, `test_auth.py` (test EC keypair, all cases in the spec).

### 3. Models, migration 0002, Supabase admin client
- `app/models/tenancy.py`: `TenantMixin` (`org_id` UUID NOT NULL FK, indexed), `Organization`, `AppUser`,
  `SchoolClass`, `ClassTeacher`, `Enrollment`; native PG enums (`user_role`, `user_status`, `class_subject`);
  checks (`is_admin → role='teacher'`, student ↔ username not null & email null, grade in (9,10),
  `code = upper(code)` + regex check — plain unique instead of citext, avoids needing the extension); functional unique
  indexes `(org_id, lower(username))`, `lower(email)`, partial `(org_id, lower(name)) WHERE archived_at IS NULL`;
  `UNIQUE(id, org_id)` on `app_user` and `school_class`; composite FKs on link tables. Import models in
  `app/models/__init__.py` so Alembic metadata sees them.
- `alembic/versions/0002_auth_tenancy.py`: hand-written (matches models) + `DO $$ … ENABLE ROW LEVEL SECURITY` loop over
  every table in `public` incl. `alembic_version`; downgrade drops tables/enums.
- `app/services/supabase_admin.py`: `SupabaseAdmin` Protocol (`invite`, `create_user`, `update_password`, `set_banned`,
  `sign_out`, `delete_user`) + `HttpSupabaseAdmin` (httpx, 10 s timeout, service-role key header, never logs bodies);
  raises `SupabaseAdminError` → 502 friendly message. FastAPI dependency `get_supabase_admin` (overridden in tests).
  `sign_out`: I'll check the current GoTrue admin API at build time and use its per-user session-revoke endpoint.
  If there isn't one, I'll do a brief ban then unban, which invalidates refresh tokens, and note that in the code.
  Either way, access tokens that are still valid are rejected because the API checks status and the flag on every request.
- Fake admin in `tests/fakes.py`.

### 4. Deps (the choke point), schemas, services, routes
- `app/api/deps.py`: `get_current_user` (bearer → verify → load `AppUser` by `sub` → 401 if missing/deactivated;
  flips `invited→active` only in `GET /me`; 403 `password_change_required` unless route opts out via a separate
  `get_current_user_allow_pw_change` dep used only by `/me` and `/me/password`); `require_staff/admin/student`;
  `OrgScope` with `select`, `get` (404), `new`. Error bodies `{"code", "message"}` via an `ApiProblem` exception +
  handler in `main.py`.
- `app/schemas/tenancy.py` (Pydantic v2, trimmed/validated names, ≤60 display names, password 8–72).
- `app/services/tenancy.py`: invite teacher (auth first, DB insert; delete auth user on DB failure), resend, PATCH
  teacher with last-admin rule (`SELECT … FOR UPDATE` on org admins), deactivate (ban call first, then DB), bulk create
  students (all-or-nothing with `delete_user` compensation; username retry ≤5 via savepoint on unique violation),
  reset password, classes CRUD/archive, co-teachers, enrol existing (validates every id via scope → 404; non-student or
  inactive → 422), unenrol idempotent. All take `OrgScope`.
- Routes `app/api/v1/me.py`, `teachers.py`, `students.py`, `classes.py`; register in `router.py`.
- Offline tests: `test_deps.py` (dependency overrides + fake user loader), `test_route_scoping.py` (walks
  `app.routes`, inspects dependant tree for `get_current_user` and `OrgScope` on tenant path params).

### 5. CLI
- `app/cli.py` Typer: `org create` (validate code regex, uppercase; check code/email taken → messages + exit 1; invite
  via admin API, insert org + admin user; delete auth user on DB failure), `org list`. `tests/test_cli.py` with
  `CliRunner` + fake admin (validation paths offline).

### 6. DB tests (`make test-db`)
- `tests/conftest.py` additions: `db_app` fixture → sets `DATABASE_URL` to `TEST_DATABASE_URL`, runs
  `alembic upgrade head` once per session, `TRUNCATE … CASCADE` per test, overrides `get_supabase_admin` with the fake
  and the token verifier with a fake that maps test tokens → user ids.
- `test_tenant_isolation_db.py` (every endpoint with B's ids → 404, B unchanged; lists only A; raw cross-school
  enrollment insert → IntegrityError), `test_tenancy_db.py`, `test_rls_db.py`.

### 7. Frontend foundation
- `pnpm add @supabase/supabase-js lucide-react class-variance-authority clsx tailwind-merge` + needed `@radix-ui/react-*`
  (dialog, dropdown-menu, tabs, label, slot, checkbox, switch, alert-dialog, avatar) + `sonner` (shadcn toast).
- shadcn components hand-copied into `src/components/ui/` (button, input, label, card, dialog, alert-dialog,
  dropdown-menu, tabs, table, badge, checkbox, skeleton, sheet, textarea, sonner, select), `src/lib/utils.ts` (`cn`),
  shadcn neutral theme tokens in `index.css` with dark mode via `prefers-color-scheme`; `@/` path alias.
- `src/lib/supabase.ts`, `src/lib/api.ts` (`apiFetch` with bearer, JSON body, `ApiError{status, code}`, 401 →
  sign out + `/login`, `password_change_required` → `/change-password`; keep `apiGet` for health).
- `src/features/auth/`: AuthProvider/useAuth, useMe, RequireAuth/RequireRole, LoginPage (Student/Staff tabs, school
  code remembered in try/catch localStorage, single error message, paused-project message), AcceptInvite,
  ResetPassword, ChangePassword. `AppShell` (+ Sidebar, MobileNav sheet, UserMenu), ForbiddenPage, student Home stub,
  health line moved to login footer. Routes rewired.

### 8. Frontend features
- `features/classes/` (list with My/All tabs + archived toggle, New class dialog, detail page, teachers add/remove,
  Add students dialog with Create new / Add existing, row menu), `SlipsView` (in-memory state via router state, print
  CSS 8/A4 with cut lines, banner, in-app leave-confirm via `useBlocker`), `features/students/`, `features/teachers/`.
- Vitest: Login, RequireRole, apiFetch, CreateStudents dialog, SlipsView.

### 9. Docs
- `docs/ARCHITECTURE.md` (Auth row, domain model names, RLS deny-all), `docs/ROADMAP.md` row 002, `CLAUDE.md`
  Gotchas (synthetic student emails; services take `OrgScope`), spec status → implemented.

### 10. Finish
- `make check` + `make test-db` (shows output; if `TEST_DATABASE_URL` isn't set I'll stop and ask).
- Run `reviewer` and `security-reviewer` subagents in parallel on the diff vs the spec; fix correctness/security
  findings, re-run checks, list optional ones. Then stop for you to run `/ship`.

## Verification
- Offline: `make check` (ruff, mypy strict, pytest -m "not db", eslint, prettier, tsc, vitest) after every step.
- DB: `make test-db` against the test Supabase project (migrations, isolation, RLS, business rules).
- Manual checklist in the spec (real Supabase dev project: invites, slips print, 360 px shell, anon-key curl) is for
  you to run after `make migrate` + `make dev`; I can drive the browser parts with Claude in Chrome if you want.
