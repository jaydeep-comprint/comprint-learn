# Spec 001: Scaffold

Status: draft
PRD link: docs/PRD.md#mvp-scope-v1 (Phase 0 of docs/ROADMAP.md)

## Summary
Set up the monorepo (`backend/`, `frontend/`, `content/`) so a developer can run `make dev` and see a web page
that reports whether the API and the hosted Supabase Postgres database are reachable. `make check` becomes the real,
fast, offline quality gate (lint, types, tests for both apps), and GitHub Actions runs it on every PR.

## User stories
- As a developer, I want `make dev` to start the API and the web app together so that I can work on a feature end to end.
- As a developer (and the Claude Stop hook), I want `make check` to run every lint, type and unit test in well under a
  minute, with no network access, so that it is a reliable gate after every change.
- As a developer, I want `make test-db` to prove the app can talk to a real Postgres so that DB wiring is tested
  without slowing down `make check`.
- As a reviewer, I want CI to run the same `make check` on every PR so that "works on my machine" isn't the only signal.

## Behaviour

### Configuration (backend, pydantic-settings)
- Settings are read from environment variables, then `backend/.env` (env vars win). Fields:
  | Name | Required | Default | Notes |
  |---|---|---|---|
  | `DATABASE_URL` | yes | – | Supabase **Session pooler** string (port 5432) |
  | `TEST_DATABASE_URL` | no | unset | Second Supabase project, used only by `make test-db` / CI |
  | `SUPABASE_URL` | no | unset | Not used yet (auth arrives in spec 002); documented now |
  | `ENVIRONMENT` | no | `development` | `development` \| `test` \| `production` |
  | `CORS_ORIGINS` | no | `[]` | Comma-separated list; dev uses the Vite proxy so it is empty |
  | `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | no | `5` / `5` | Kept small: Supabase pooler has a connection cap |
- URL normalisation (one pure function, `normalize_db_url(raw: str) -> tuple[str, dict]`, unit tested):
  - `postgresql://…` and `postgres://…` → `postgresql+asyncpg://…`.
  - `postgresql+asyncpg://…` is accepted unchanged.
  - Any other scheme (e.g. `mysql://`, `postgresql+psycopg://`) → settings validation error:
    `DATABASE_URL must be a postgres URL (postgresql://...)`.
  - A `sslmode` query parameter (asyncpg rejects it) is removed from the URL and mapped to asyncpg `connect_args`
    (`require`/`verify-*` → `ssl="require"`, `disable` → no SSL). If no `sslmode` is given and the host is not
    `localhost`/`127.0.0.1`, default to `ssl="require"`.
  - Other query parameters are preserved; the password is never logged (use `URL.render_as_string(hide_password=True)`
    if the URL is ever printed).
- If `DATABASE_URL` is missing, the API fails at startup with: `DATABASE_URL is not set. Copy backend/.env.example to
  backend/.env and fill it in.` (Tests set a dummy value in `conftest.py`, so `make check` needs no `.env`.)

### Database layer
- One async engine (`create_async_engine`, `pool_pre_ping=True`, pool sizes from settings) created lazily on first use;
  disposed on app shutdown (FastAPI lifespan). Creating the engine must not open a connection.
- `get_session()` FastAPI dependency yields an `AsyncSession` from an `async_sessionmaker(expire_on_commit=False)`.
- `Base = DeclarativeBase` subclass in `app/db/base.py` with a naming convention for constraints (so Alembic
  autogenerate produces stable names). No tables in this spec.

### Health endpoint: `GET /api/v1/health`
- Runs `SELECT 1` through the session with a 3-second timeout.
- Success → `200 {"status": "ok", "db": "ok"}`.
- Any DB error or timeout → `503 {"status": "error", "db": "error"}`. No exception text, host or URL in the response.
  The exception is logged server-side at WARNING with its class name only (no URL/credentials).
- No auth, no org scoping (it touches no tenant data). Response model is a Pydantic schema `HealthResponse`.

### Migrations (Alembic)
- `backend/alembic/` created from the async template; `env.py` reads the URL from settings (via
  `normalize_db_url`), never from `alembic.ini`, and sets `target_metadata = Base.metadata`.
- One empty baseline revision `0001_baseline` so `make migrate` proves the plumbing (creates `alembic_version`).
- `make migrate` = `alembic upgrade head` against `DATABASE_URL`.

### Frontend
- Vite + React + TypeScript (strict). Tailwind (v4 via `@tailwindcss/vite`), React Router, TanStack Query.
- Dev server proxies `/api` → `http://localhost:8000`, so no CORS needed locally. `VITE_API_BASE_URL` (default
  empty = same origin) prefixes API calls for deployed builds.
- `src/lib/api.ts`: a tiny `apiGet<T>(path)` fetch wrapper that throws on non-2xx.
- Home route `/` shows a "Learning App" heading and a `HealthStatus` component using `useQuery(['health'])`:
  - loading → "Checking API…"
  - 200 → green "API: ok · Database: ok"
  - 503 → amber "API: ok · Database: unreachable"
  - network error / API down → red "API: unreachable" plus a "Retry" button (calls `refetch`).
  - No auto-retry storm: `retry: 1`, no polling.
- Any unknown route renders a minimal "Not found" page with a link home.

### Makefile (repo root)
| Target | Does |
|---|---|
| `make install` | `uv sync` in backend, `pnpm install --frozen-lockfile` in frontend |
| `make dev` | Runs `dev-api` (`uv run uvicorn app.main:app --reload --port 8000`) and `dev-web` (`pnpm dev`) in parallel via `make -j2`; Ctrl-C stops both |
| `make check` | `check-api` + `check-web`; **offline, no DB** |
| `check-api` | `ruff check .`, `ruff format --check .`, `mypy` (strict), `pytest -q -m "not db"` |
| `check-web` | `eslint .`, `prettier --check .`, `tsc -b --noEmit` (or `tsc --noEmit -p`), `vitest run` |
| `make test-db` | `pytest -q -m db`; **fails** (not skips) with a clear message if `TEST_DATABASE_URL` is unset |
| `make fmt` | `ruff format` + `ruff check --fix` (backend), `prettier --write` (frontend) |
| `make migrate` | `alembic upgrade head` (backend) |
- `make check` must finish in < 60 s on a warm machine and must not require `backend/.env`.
- If `frontend/node_modules` is missing, `check-web` fails with `Run 'make install' first.` rather than a stack trace.

### Tests
- pytest marker `db` registered in `pyproject.toml`. A fixture in `tests/conftest.py` skips `db` tests with
  `TEST_DATABASE_URL not set; skipping DB tests (run 'make test-db' with it set)` when the variable is missing; `make
  test-db` sets a flag (e.g. `REQUIRE_DB=1`) that turns this skip into a failure.
- Offline tests (in `make check`):
  - `test_config.py`: `normalize_db_url` cases (postgres/postgresql/asyncpg schemes, sslmode mapping, localhost no-SSL,
    bad scheme rejected, other query params kept).
  - `test_health.py`: with `get_session` overridden by a fake session — `SELECT 1` succeeds → 200 body; raises → 503
    body with no error text leaked; hangs past the timeout → 503.
- DB test (`make test-db` only): `test_health_db.py` points the app at `TEST_DATABASE_URL` and asserts 200 `ok/ok`.
- Frontend: `HealthStatus.test.tsx` (vitest + Testing Library + jsdom, `fetch` mocked) for the ok, 503 and network-error
  states.

### CI: `.github/workflows/ci.yml`
- Triggers: `pull_request`, and `push` to `main`.
- One job on `ubuntu-latest`: checkout → `astral-sh/setup-uv` (Python 3.13, cache) → `pnpm/action-setup` +
  `actions/setup-node` (Node 24, pnpm cache) → `make install` → `make check`.
- Then a `make test-db` step with `env: TEST_DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}`, gated by a prior step
  that writes `present=${{ secrets.TEST_DATABASE_URL != '' }}` to `$GITHUB_OUTPUT` (secrets can't be used directly in
  `if`, and a step's own `env` isn't visible to its `if`). Absent secret → step is skipped, job green.
- Concurrency group per ref with `cancel-in-progress: true`.

## UI / UX
A single unstyled-but-tidy page (Tailwind utilities only, no design system). States as listed under "Frontend". No
real UI design in this spec.

## Technical design
- Files / modules touched (new unless noted):
  - `backend/pyproject.toml` (uv project, Python `>=3.13`; deps: fastapi[standard], sqlalchemy[asyncio], asyncpg,
    alembic, pydantic-settings; dev group: ruff, mypy, pytest, pytest-asyncio, httpx), `backend/uv.lock` (generated),
    `backend/.python-version`, `backend/.env.example`
  - `backend/app/__init__.py`, `app/main.py` (app factory `create_app()`, lifespan, CORS, mounts `/api/v1`)
  - `backend/app/core/config.py` (`Settings`, `get_settings()` cached, `normalize_db_url`)
  - `backend/app/db/base.py`, `backend/app/db/session.py` (engine, sessionmaker, `get_session`)
  - `backend/app/api/v1/router.py`, `backend/app/api/v1/health.py`, `backend/app/schemas/health.py`
  - Empty packages to match ARCHITECTURE layout: `app/models/`, `app/services/`, `app/ai/` (each `__init__.py` only)
  - `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`,
    `backend/alembic/versions/0001_baseline.py`
  - `backend/tests/conftest.py`, `tests/test_config.py`, `tests/test_health.py`, `tests/test_health_db.py`
  - `frontend/package.json` (`"packageManager": "pnpm@…"`, `engines.node >=24`), `pnpm-lock.yaml` (generated),
    `vite.config.ts`, `tsconfig*.json`, `eslint.config.js`, `.prettierrc`, `.prettierignore`, `index.html`,
    `.env.example` (`VITE_API_BASE_URL=`)
  - `frontend/src/main.tsx` (QueryClientProvider + RouterProvider), `src/routes.tsx`, `src/index.css`
    (`@import "tailwindcss";`), `src/lib/api.ts`, `src/features/health/HealthStatus.tsx`,
    `src/features/health/HealthStatus.test.tsx`, `src/pages/HomePage.tsx`, `src/pages/NotFoundPage.tsx`,
    `src/test/setup.ts`
  - `content/README.md`: one paragraph: "pre-authored courses live here; format defined in spec 003".
  - `Makefile` (replace placeholder), `.github/workflows/ci.yml`
  - `.gitignore` (edit): add `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `*.tsbuildinfo`
  - `.claude/hooks/format.sh` (edit): use `frontend/node_modules/.bin/prettier` for files under `frontend/`, and
    `uv run --directory backend ruff` for `.py` files under `backend/` (today it looks for a root prettier and a global
    ruff, so it silently does nothing). Leave other paths (e.g. `docs/*.md`) unformatted.
  - `CLAUDE.md` (edit): fill "Commands" with the real commands (see Verification).
  - `docs/ROADMAP.md` (edit): row 001 says "docker-compose Postgres"; change to "hosted Supabase Postgres".
  - `docs/ARCHITECTURE.md` (edit): Database row → "PostgreSQL (hosted Supabase, Session pooler, port 5432)";
    add a "Test DB = separate Supabase project" note.
- Data model changes: none (empty baseline migration only).
- API / interfaces: `GET /api/v1/health` → `HealthResponse { status: "ok" | "error", db: "ok" | "error" }`.

## Edge cases
- Supabase password with special characters (`@`, `#`, `/`): must be percent-encoded in the URL; `.env.example`
  comment says so. `normalize_db_url` must not decode/re-encode the password.
- User pastes the **Transaction pooler** string (port 6543): asyncpg prepared statements break there. Log a WARNING at
  startup if the port is 6543 ("use the Session pooler, port 5432"). Not an error.
- User pastes the Supabase **direct** connection (`db.<ref>.supabase.co`): IPv6-only on free tier, may fail on some
  networks. Works if reachable; no special handling, but `.env.example` recommends the Session pooler.
- API running but DB down / paused (free-tier projects pause after inactivity): health returns 503 within ~3 s; page
  shows "Database: unreachable".
- API not running while the web app is: page shows "API: unreachable" + Retry, no console error loop.
- `make check` on a fresh clone without `make install`: clear message, non-zero exit.
- `make test-db` without `TEST_DATABASE_URL`: fails with a clear message (it was explicitly requested).
- Stop hook runs `make check` after every turn: no network, no DB, no watchers, no interactive prompts.

## Out of scope
- Auth (Supabase Auth/Clerk), users, orgs, tenancy, the org-scoping dependency (spec 002).
- Any domain tables or models beyond the empty baseline migration.
- Content format, validator, importer, the `app` CLI entry point (spec 003).
- Real UI design, layout shell, navigation, theming.
- Docker / docker-compose, local Postgres.
- Deployment, hosting choice, prod env config, Playwright e2e (later specs).
- Pre-commit hooks, Dependabot/renovate, coverage thresholds.

## Verification (end-to-end)
- [ ] Fresh clone, no `backend/.env`: `make install && make check` → exits 0; output shows ruff, mypy, pytest
      (`test_health_db.py` deselected), eslint, prettier, tsc, vitest all passing. Time it: < 60 s warm.
- [ ] Break something on purpose (a type error in `health.py`, a lint error in `HomePage.tsx`) → `make check` exits
      non-zero naming the file; revert.
- [ ] `make test-db` without `TEST_DATABASE_URL` → non-zero with the "not set" message.
- [ ] With `backend/.env` (`DATABASE_URL` = Session pooler) and `TEST_DATABASE_URL` set (second Supabase project):
      `make test-db` → `test_health_db.py` passes.
- [ ] `make migrate` → succeeds; Supabase table editor shows `alembic_version` with `0001_baseline`. Re-run → no-op.
- [ ] `make dev` → `curl -s localhost:8000/api/v1/health` returns `{"status":"ok","db":"ok"}`; open
      `http://localhost:5173` → green "API: ok · Database: ok". Screenshot it.
- [ ] Set `DATABASE_URL` to a wrong password, restart API → curl returns 503 `{"status":"error","db":"error"}` with no
      credentials in the body or logs; page shows amber "Database: unreachable".
- [ ] Stop the API only → page shows red "API: unreachable"; Retry after restarting the API turns it green.
- [ ] Open a PR → CI runs `make check` and is green; `make test-db` step is skipped if the repo has no
      `TEST_DATABASE_URL` secret, and runs + passes once the secret is added.
- [ ] Edit a `.tsx` and a `.py` file via Claude → the format hook reformats them (prettier / ruff).
- [ ] `CLAUDE.md` "Commands" filled in:
      Dev `make dev` · Test single file `cd backend && uv run pytest path/to/test` /
      `cd frontend && pnpm vitest run path/to/test` · Test all `make check` (+ `make test-db`) ·
      Typecheck `cd backend && uv run mypy` / `cd frontend && pnpm typecheck` · Lint/format `make fmt` ·
      Migrate `make migrate`.
