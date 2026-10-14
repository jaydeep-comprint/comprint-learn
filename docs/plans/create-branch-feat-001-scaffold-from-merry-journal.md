# Plan: implement spec 001 (Scaffold) on `feat/001-scaffold`

## Context
The repo has only docs, Claude config and a placeholder `Makefile`. Spec `docs/specs/001-scaffold.md` sets up the monorepo
(FastAPI backend, React/Vite frontend, `content/`). After this work, `make dev` shows a page that reports API and Supabase DB health,
`make check` is a real offline quality gate, and GitHub Actions runs `make check` on PRs. The spec is detailed, so this plan
covers order, decisions and verification rather than repeating the spec.

Environment facts checked:
- uv 0.13, node 24, pnpm 12 are installed. System Python is 3.9, so uv installs 3.13.
- No docker. No `gh`. **No git remote.**
- `protect-files.sh` blocks hand edits to lockfiles. Lockfiles are produced only by `uv` and `pnpm`.
- The Stop hook runs `make check` whenever the tree is dirty, so **each step must leave `make check` green**.

## Steps
After each step I run `make check` and show its output, then make one small commit (CLAUDE.md asks for small, descriptive commits).

**0. Branch.** `git checkout -b feat/001-scaffold` from clean `main`.

**1. Repo hygiene and docs** (the `make check` placeholder stays green)
- `.gitignore`: add `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `*.tsbuildinfo`.
- `content/README.md`: one paragraph.
- `docs/ROADMAP.md` row 001: "docker-compose Postgres" → "hosted Supabase Postgres".
- `docs/ARCHITECTURE.md`: change the Database row and add a test-DB note.

**2. Backend** (`backend/`)
- Create the project with `uv init`/`uv add`: Python `>=3.13`, `.python-version`, deps and a dev group as listed in the spec, which generates `uv.lock`.
- `pyproject.toml` tool config:
  - ruff (line length 100 plus a sensible rule set)
  - mypy `strict = true` with the pydantic plugin
  - pytest with `asyncio_mode = "auto"`, `testpaths = ["tests"]` and the `db` marker registered
- `app/core/config.py`:
  - `normalize_db_url(raw) -> tuple[str, dict]`: parse with `sqlalchemy.engine.make_url`, then remap the scheme. The rebuilt URL must keep the password percent-encoding exactly as given. Also maps `sslmode`, defaults non-localhost hosts to `ssl="require"`, keeps other query params and rejects unknown schemes with the exact error message.
  - `Settings` (pydantic-settings, `env_file=backend/.env`). `CORS_ORIGINS` is parsed from a comma-separated string.
  - `get_settings()` uses `lru_cache`. A missing `DATABASE_URL` raises the exact "DATABASE_URL is not set…" message.
- `app/db/base.py` (Base with a naming convention) and `app/db/session.py`:
  - The engine and sessionmaker are created lazily and cached.
  - `get_session()` is the session dependency and `dispose_engine()` releases the engine.
- `app/schemas/health.py`:
  - `HealthResponse` with `Literal` fields.
- `app/api/v1/health.py`:
  - Runs `SELECT 1` under `asyncio.timeout(HEALTH_DB_TIMEOUT_S)` (3 s; tests monkeypatch it).
  - On any exception it logs `WARNING` with the exception class name only and returns 503.
- `app/api/v1/router.py`.
- `app/main.py`:
  - `create_app()` mounts `/api/v1` and adds CORS only when origins are set.
  - Lifespan startup calls `get_settings()` (missing URL → clear failure) and logs a WARNING if the port is 6543.
  - Lifespan shutdown disposes the engine.
  - A module-level `app = create_app()` lets `fastapi dev app/main.py` find the app.
- Empty packages: `app/models`, `app/services`, `app/ai`.
- Alembic, async template:
  - `env.py` gets the URL and `connect_args` from `normalize_db_url(get_settings().database_url)`. Nothing comes from `alembic.ini`.
  - `target_metadata = Base.metadata`.
  - Add an empty revision `0001_baseline`.
- `.env.example`: comments recommend the Session pooler on port 5432, say special characters must be percent-encoded, and warn that port 6543 breaks.
- Tests:
  - `conftest.py`: sets a dummy `DATABASE_URL`, clears the settings and engine caches, and adds a `db`-marker fixture. The fixture skips when `TEST_DATABASE_URL` is unset, or fails if `REQUIRE_DB=1`.
  - `test_config.py`: all normalisation cases plus the missing-URL message.
  - `test_health.py`: fake sessions for ok, raise and hang, run through httpx `ASGITransport` with `dependency_overrides`. Checks that no error text leaks.
  - `test_health_db.py`: marked `db`, points settings at `TEST_DATABASE_URL`.
- `Makefile`: add `check-api`, `test-db` (fails up front with a clear message if `TEST_DATABASE_URL` is unset, then runs `REQUIRE_DB=1 uv run pytest -q -m db`), `migrate`, and the backend half of `fmt`. `check` = `check-api` for now.

**3. Frontend** (`frontend/`)
- Write `package.json` by hand: `packageManager` pnpm, `engines.node >=24`, scripts `dev`, `build`, `typecheck`, `lint`, `format`, `test`. Then `pnpm add` the deps, which generates `pnpm-lock.yaml`:
  - Runtime: react, react-dom, react-router, @tanstack/react-query.
  - Dev: vite, @vitejs/plugin-react, typescript, tailwindcss, @tailwindcss/vite, eslint plus typescript-eslint and the react-hooks/react-refresh plugins, prettier, vitest, jsdom, @testing-library/react, @testing-library/jest-dom, @types/react, @types/react-dom.
- Config files:
  - `vite.config.ts`: `/api` proxy to `:8000` plus the vitest jsdom config with `src/test/setup.ts`.
  - Strict `tsconfig*.json`, `eslint.config.js`, `.prettierrc`, `.prettierignore`, `index.html`, `.env.example`.
- `src/`:
  - `main.tsx`, `routes.tsx` (`/` and `*`), `index.css`.
  - `lib/api.ts`: `apiGet<T>`, prefixed with `VITE_API_BASE_URL`. Throws an `ApiError` that carries `status`, so a 503 can be told apart from a network failure.
  - `features/health/HealthStatus.tsx`: the four states, `retry: 1`, and a Retry button that calls `refetch`.
  - `pages/HomePage.tsx`, `pages/NotFoundPage.tsx`.
  - `HealthStatus.test.tsx`: covers ok, 503 and network error, plus a Retry click.
- `Makefile`: add `check-web`, which first runs `test -d frontend/node_modules || { echo "Run 'make install' first."; exit 1; }`. `check` = `check-api check-web`. Add the frontend half of `fmt`.

**4. Dev loop, CI, hooks, docs**
- `Makefile`: `install`, `dev` (`$(MAKE) -j2 dev-api dev-web`), `dev-api`, `dev-web`, all `.PHONY`.
- `.github/workflows/ci.yml`, exactly per the spec:
  - Concurrency group per ref with cancel-in-progress.
  - setup-uv with Python 3.13, pnpm/action-setup, setup-node 24 with the pnpm cache.
  - Steps: `make install` → `make check`.
  - Gated `make test-db` step: `env.TEST_DATABASE_URL` comes from the secret, with `if: env.TEST_DATABASE_URL != ''`.
- `.claude/hooks/format.sh`:
  - Files under `frontend/` → `frontend/node_modules/.bin/prettier`.
  - `.py` files under `backend/` → `uv run --directory backend ruff format` and `ruff check --fix`.
  - Everything else is left alone.
- `CLAUDE.md` "Commands": fill in from the spec's Verification list.

**5. Verify end to end** (evidence shown for each item)
- Timed `make check` from a warm machine, under 60 s, with ruff, mypy, pytest (db deselected), eslint, prettier, tsc and vitest all visible in the output.
- Add a deliberate type error in `health.py` and a lint error in `HomePage.tsx`, show that `make check` fails and names the files, then revert.
- `make test-db` without the variable fails with the "not set" message.
- Move `node_modules` aside temporarily and show the "Run 'make install' first." message.
- Edit a `.py` and a `.tsx` file and show the format hook reformats them.
- `make dev` in the background:
  - Without `backend/.env`, the API fails with the clear message.
  - With your `backend/.env`, if it exists, curl `/api/v1/health` and screenshot the page via Chrome.
  - Stop the API and show the red state, then Retry.
- **Needs you:** I can't read or create `.env` files (they're denied by settings and the hook). Checks that need real Supabase credentials need a filled `backend/.env` and `TEST_DATABASE_URL`, either from you or run by you with `! make migrate` / `! make test-db`. Those checks are migrate, test-db passing, the wrong-password 503 and the green page. Without credentials, I'll mark them as not verified.
- CI green on a PR can't be checked: there's no remote and no `gh`.

**6. Review and ship**
- Run the `reviewer` subagent against `docs/specs/001-scaffold.md` and fix any correctness or requirement gaps.
- Then `/ship`. **Note:** the ship skill has `disable-model-invocation: true`, so I can't start it. You'll need to type `/ship docs/specs/001-scaffold.md`. With no remote and no `gh`, it will commit only and report that push and PR are left to do.

## Critical files
`Makefile`, `backend/app/core/config.py`, `backend/app/db/session.py`, `backend/app/api/v1/health.py`, `backend/app/main.py`,
`backend/alembic/env.py`, `backend/tests/conftest.py`, `frontend/src/lib/api.ts`, `frontend/src/features/health/HealthStatus.tsx`,
`.github/workflows/ci.yml`, `.claude/hooks/format.sh`, `CLAUDE.md`.
