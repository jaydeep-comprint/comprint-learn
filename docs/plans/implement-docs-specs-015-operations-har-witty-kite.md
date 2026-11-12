# Plan: Spec 015 — Operations hardening

## Context
Spec 014 (privacy) is merged to `main` (93cb04c), so 015 can start. 015 is the last MVP spec. It covers:
- scrubbed error tracking
- encrypted, restore-tested backups
- a lab-sized load test
- security headers, a body cap and rate limits
- CI scanning
- a written security review

Deployment is out of scope. The spec is fully decided, so this plan maps it onto the code that exists today. The work ships as three PRs on `feat/015-operations-1`, `-2` and `-3`, merged one after the other. Each PR goes through: reviewer subagent → `/ship`.

What exists today:
- No logging config, no `request.state`, no catch-all 500, no rate limiting, no Sentry.
- CORS is the only middleware (`backend/app/main.py:41-50`).
- `ApiProblem` is in `app/core/errors.py:6` and its handler is at `main.py:31`.
- The frontend already has toasts (sonner, used locally in about 25 files). There is no error boundary or `errorElement`.
- The QueryClient has no default `retry`.
- `retryUnlessClientError` is at `features/learn/api.ts:31` and is used per query in about 10 feature `api.ts` files.

---

## PR 1: Error tracking, request id, error screens (`feat/015-operations-1`)

### Backend
1. **Dependency:** `cd backend && uv add "sentry-sdk[fastapi]"`.
2. **`app/core/config.py`:** add `sentry_dsn: SecretStr | None`, `git_sha: str | None` and `log_json` (derived: environment == production). Rate-limit and proxy settings come in PR 2. An empty string counts as unset, as in the existing validator at 98-103.
3. **`app/core/observability.py` (new):**
   - `init_sentry(settings)`: does nothing without a DSN. Otherwise it uses the exact options from spec §1 and registers `before_send`.
   - `before_send(event, hint)`:
     - Strips the request body, cookies, query string and all headers except user-agent.
     - Strips frame `vars` (defence in depth on top of `include_local_variables=False`).
     - Removes `data` from httpx breadcrumbs except the URL path.
     - Drops `ApiProblem` with status < 500.
     - For `RequestValidationError`/`ValidationError`, replaces the message and exception value with error types and field paths only.
   - `set_user_context(user)`: sets tags `user.id`, `org_id`, `role`, `is_admin`.
   - `JsonFormatter` and `configure_logging(settings)`:
     - Production: JSON on root, `uvicorn.error` and `app.access`; `uvicorn.access` disabled.
     - Development: unchanged.
   - A `request_id` contextvar plus a logging `Filter` that adds it to every record.
4. **`app/core/middleware.py` (new, pure ASGI):**
   - `RequestIdMiddleware`: validates against `^[A-Za-z0-9-]{8,64}$`, otherwise uses a uuid4 hex. Sets the contextvar and `scope["state"]`, echoes the `X-Request-ID` header, and writes the access log in production (method, route template from `scope["route"].path` or `"(unmatched)"`, status, ms, and user_id/org_id from state).
   - `CatchAllMiddleware`: on an exception before the response has started, returns the 500 `internal` JSON with `request_id` and calls `sentry_sdk.capture_exception` + `log.exception`. It skips `CancelledError` and client disconnects. If the response has already started, it re-raises nothing and just logs.
   - PR 2 adds security headers and the body cap to this file.
5. **`app/main.py`:**
   - Call `configure_logging` and `init_sentry`.
   - Middleware order, outer → inner: request id → CORS (now `expose_headers` adds `X-Request-ID`, `Retry-After`) → catch-all → app.
   - The `ApiProblem` handler calls `capture_exception` with fingerprint `[code]` when status ≥ 500.
   - `ApiProblem` gains `headers: dict[str, str] | None`, and the handler passes them through.
   - Docs URLs are `None` in production. That is spec §4 but trivial, so it goes here with `test_config`.
6. **`app/api/deps.py`:** after `CurrentUser` is built, set `request.state.user_id`/`org_id` and call `set_user_context`. This needs `request: Request` added to `get_current_user_allow_password_change`.
7. **AI modules:** `client.py`/`teacher_client.py` already raise fixed reason strings. Change the `from exc` raises to `from None` so the httpx exception (URL, request) isn't chained into Sentry. `TutorUnavailable` keeps the status code and type in its message.
8. **Debug route:** `GET /api/v1/debug/boom` (`app/api/v1/debug.py`). It is included only when `ENVIRONMENT=development`, depends on `CurrentUser` via `Scope`, and raises `RuntimeError`. The route-walking test runs under `test`, so add a test that builds the app with `development` and checks the route is authenticated and scoped.
9. **`.env.example`:** add commented `SENTRY_DSN` and `GIT_SHA`.

### Frontend
1. Run `pnpm add @sentry/react`.
2. **`src/lib/observability.ts`:**
   - `initObservability()`: does nothing without `VITE_SENTRY_DSN`. No integrations for replay, tracing or feedback; `sendDefaultPii: false`.
   - `beforeBreadcrumb`: drops console, `ui.click` and xhr; reduces fetch breadcrumbs to method, path (URL with no query) and status.
   - `beforeSend`: drops `request.cookies`, `request.headers` and `extra`.
   - `ignoreErrors`: AbortError, ResizeObserver loop, and `ApiError` with status < 500 (via `beforeSend`).
   - `setObservedUser({id, org_id, role})`, called from AuthProvider when `me` loads and cleared on sign-out.
   - `reportOnce(key, message)` for Pyodide load failures.
3. **`src/main.tsx`:**
   - Call `initObservability()` before render and wrap the tree in a root `Sentry.ErrorBoundary`, falling back to `<ErrorScreen>`.
   - The QueryClient gets `retry: retryUnlessClientError`, which moves to `src/lib/api.ts` and is re-exported from learn for its existing imports. Remove the per-query `retry:` lines where they duplicate it.
   - Add `QueryCache`/`MutationCache` `onError` that calls `toast.error` only for 429 (PR 2 adds the 429 text; wire it now).
4. **`src/components/ErrorScreen.tsx`:** title, one sentence, a **Reload** button, and "Error code: xxxxxxxx" (the Sentry event id or `ApiError.requestId`). Works at phone width.
5. **`src/routes.tsx`:** `errorElement: <RouteError/>` on the root route. It uses `useRouteError()` → `ErrorScreen` and captures non-`ApiError` errors with Sentry.
6. **`src/lib/api.ts`:** `ApiError.requestId` comes from `body.request_id`, otherwise the `X-Request-ID` header. In `src/lib/errors.ts`, `errorMessage()` appends "(code xxxxxxxx)" for 5xx and returns the 429/413 texts.
7. **`features/code/usePython.ts`:** on `load_error`, call `reportOnce("pyodide-load", ...)` with a fixed fingerprint and no code. Errors from student code are never reported; they already arrive as `progress` outputs.

### Tests (PR 1)
- `backend/tests/test_observability.py`:
  - no DSN means `sentry_sdk` has no client
  - `before_send` scrubbing on a synthetic event
  - a validation error carrying a name and a fake `sk-…` secret produces neither in the event
  - ApiProblem 4xx dropped, 5xx kept with a fingerprint
  - JSON formatter fields
- `backend/tests/test_middleware.py` (first half):
  - request id generated, accepted, and rejected when malformed
  - the catch-all 500 shape keeps CORS and `X-Request-ID` and has no trace
- `test_config.py`: docs routes 404 in production.
- vitest:
  - ErrorScreen and RouteError render a code
  - `api.test.ts`: `requestId` from body or header, and `errorMessage` 5xx suffix
  - `observability.test.ts`: `beforeSend`/`beforeBreadcrumb` scrubbing
  - `usePython`: load_error is reported once
- `docs/runbooks/errors.md`.

---

## PR 2: Headers, body cap, rate limits, CI scanning, backups (`feat/015-operations-2`)

### Backend
1. **`middleware.py`:**
   - `SecurityHeadersMiddleware`: the spec §4 set. `Cache-Control: no-store` on `/api/*` (except where a route already set one). CSP on `application/json` responses. HSTS only in production.
   - `BodyCapMiddleware`: 256 KB. Rejects when `Content-Length` is over the cap, and counts bytes while wrapping `receive` for chunked bodies. Returns 413 `payload_too_large` + message.
   - Final order: request id → CORS → security headers → body cap → catch-all → app.
2. **`app/core/ratelimit.py`:**
   - A `TokenBucket` with a monotonic clock that can be injected.
   - `RateLimiter` holds a dict of `key → bucket` plus a last-seen time, and sweeps buckets idle for 10 minutes or more on access (amortised).
   - Buckets: `write` (capacity 40, refill 120/60 per s), `read` (120, 10/s), `ip_unauth` (300/min), plus named expensive buckets: `export` 5/h, `bulk_students` 10/h, `consent_bulk` 30/min.
   - `client_ip(scope, trusted_proxy_count)`: takes the Nth address from the right of XFF.
   - `RateLimited` → `ApiProblem(429, "rate_limited", message, headers={"Retry-After": n})`.
   - `limit(bucket_name)`: a dependency factory for the expensive routes. It consumes the named bucket after auth.
3. **Settings:** `rate_limit_enabled` (default True; the conftest env sets it to false), `rate_limit_write_per_min/burst`, `rate_limit_read_per_min/burst` and `trusted_proxy_count`. The production guard goes in `create_app()`: it raises if `"*" in cors_origins` or if `app_url` is not https.
4. **`deps.py`:**
   - In `get_current_user_allow_password_change`: right after `verify()` succeeds, consume `write`/`read` by request method, keyed by `token.user_id`, **before** `session.get(AppUser…)`.
   - A missing token or `Unauthenticated` consumes the per-IP bucket first. If that is empty the response is 429, otherwise 401.
   - `AuthUnavailable` and deactivated users don't count against the per-IP bucket.
   - The limiter is a module singleton, reset by a test fixture.
5. **Expensive routes:** add `Depends(limit("export"))` to `students.py:57`, `limit("bulk_students")` to `classes.py:70` and `limit("consent_bulk")` to `students.py:30`.
6. `/health`, unmatched paths and 422s are naturally unlimited: the limit lives in the auth dependency, which runs before validation only when a route matched. Check the 422 ordering in a test. FastAPI resolves dependencies and body validation together, so if body errors are reported before deps run, record that as is.

### Frontend
- 429 and 413 messages in `errorMessage`.
- 429 is not retried; this is covered by the global retry.
- A 429 when `getAccessToken()` returns null → treat as signed out (redirect to `/login`).
- `csp.ts` at the frontend root:
  - `buildCsp(env)` uses origins from `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` (https plus the wss realtime origin isn't needed, so http(s) only) and the `VITE_SENTRY_DSN` ingest host.
  - `buildHeadersFile()` generates `/*` and keeps the `/content-assets/*` rule.
  - A Vite plugin emits `dist/_headers`.
  - `vite.config.ts` gets `preview.headers` from the same source.
- Delete `public/_headers`.
- Note: `style-src 'unsafe-inline'` covers Mermaid's inline `<style>`, sonner and React Flow. Workers are same-origin module workers, so `worker-src 'self' blob:` is enough.

### CI and backups
- `.gitleaks.toml`: path allow-list for test fixtures.
- `Makefile audit`:
  - `uv export --frozen --no-dev --no-emit-project` → `uvx pip-audit -r - -f json` → `scripts/pip_audit_filter.py` (fails only on vulnerabilities with a fix version, honouring an ignore list parsed from `docs/security-review.md`)
  - `pnpm audit --prod --audit-level high`
  - `gitleaks detect` (install hint if it's missing)
- `ci.yml` gets a `security` job with a pinned gitleaks binary. `fetch-depth: 0` on `main`; the PR range on pull requests.
- `scripts/backup.sh` and `scripts/restore_check.sh`, exactly as spec §2 and "Backups (decided)" describe:
  - `set -euo pipefail` and a check of the `pg_dump` major against `SHOW server_version`
  - `pg_dump | gpg --batch --symmetric --cipher-algo AES256 --passphrase-fd 3 3<<<"$BACKUP_PASSPHRASE"`
  - `SHA256SUMS`
  - the restore check drops `public`, runs `pg_restore --exit-on-error`, then checks the alembic revision is an ancestor via `uv run alembic history`, prints row counts, checks orgs ≥ 1, checks RLS on every table, and confirms the auth dump's `--list` has the 2 TABLE DATA entries
- `.github/workflows/backup.yml`:
  - cron `30 19 * * *` + dispatch, with a secret gate step (the `privacy-jobs.yml` pattern)
  - installs `postgresql-client-$MAJOR` from PGDG and starts scratch Postgres with `docker run postgres:$MAJOR`
  - uploads an artifact with `retention-days: 14` and warns over 500 MB
- `.gitignore`: `backups/`.
- `docs/runbooks/backup-restore.md`.

### Tests (PR 2)
- `test_middleware.py` second half:
  - every header, and HSTS only in production
  - 413 by Content-Length and by chunked body
  - a 20 000-char code plus realistic outputs is not 413
- `test_ratelimit.py`:
  - bucket maths with a fake clock
  - 80 users behind one IP are independent
  - 429 + `Retry-After`
  - the per-IP limit applies only to missing/invalid tokens, not 503
  - idle buckets are swept
  - `READ_BURST == 120`
  - the expensive bucket consumes both buckets
  - XFF Nth-from-right
- `test_config.py`: the production guard cases, and CLI unaffected.
- vitest:
  - 429/413 messages, 429 not retried, 429 signed-out redirect
  - `csp.test.ts` (policy string, `_headers` output keeps the content-assets rule)
  - dashboard page-load counting: Overview and Students tab render with `routeFetch` counting GETs < 30 each
- Run `actionlint` on both workflows.

---

## PR 3: Load test, fixes, security review (`feat/015-operations-3`)

### Load test
1. **Dependencies:** `uv add --group loadtest locust`. `make install` keeps `uv sync` without that group. Check the Makefile uses default groups only.
2. **Shared-DB lock:**
   - `app/testing/dblock.py` (or `loadtest/dblock.py`, importable by tests) holds a session `pg_try_advisory_lock(<const>)` on a dedicated asyncpg/psycopg connection.
   - A session fixture in `tests/conftest.py` takes it for `db` runs and fails clearly if it's held.
   - The orchestrator takes it too.
3. **`app/cli.py`:** a `loadtest` sub-app with `seed`.
   - Refuses unless `ENVIRONMENT=test` and `DATABASE_URL == TEST_DATABASE_URL`.
   - Rebuilds the schema (alembic downgrade base → upgrade head, the same subprocess calls as conftest `migrated_test_db`) and runs `import_tree(DEFAULT_CONTENT_ROOT, sessions)`.
   - Inserts ORM rows directly, reusing `tests/db_seed.py` patterns:
     - org `LOADTEST`
     - 1 teacher
     - classes "Maths 9" (maths, grade 9) and "Physics 9", 40 students each, as active with `must_change_password=False`
   - Per student, deterministically: `frontier.mark_learned` on 0–3 root concepts through a system `OrgScope`, then set some `review_card.due = now` so reviews are due.
   - Writes `backend/loadtest/.seed.json` (gitignored).
4. **`backend/loadtest/`:**
   - `tokens.py`: HS256 mint with `aud`/`iss`/`sub`/`iat`/`exp`.
   - `answers.py`: a correct or incorrect response computed from the DB. It reads `practice_session.current_item_id/current_seed` and `item.answer`, and reuses `app.grading` helpers the way `tests/learn_helpers.py::_quick/answer_fields` does. MCQ is matched by option text. Code items submit canned outputs.
   - `locustfile.py`:
     - Student and Teacher user classes per spec §3: weights, think time 3–12 s, 75% correct.
     - `catch_response` marks expected 409s as successes.
     - Requests are named by route template so the CSV groups them.
   - `run.py` (the orchestrator called by `make loadtest`):
     - Refuses production.
     - Generates the secret, sets `DATABASE_URL=TEST_DATABASE_URL`, `TUTOR_ENABLED=false`, `TEACHER_AI_ENABLED=false` and a distinct `application_name`.
     - Takes the lock, seeds, starts uvicorn on :8001 as a subprocess (`try/finally` + signal handling), waits for `/health`, and runs `locust --headless --csv`.
     - Polls `pg_stat_activity` for peak connections and greps the API log for `QueuePool`.
     - Runs `check.py`, then stops the API.
   - `check.py`: the pass criteria from the CSV plus the peak connections and log scan. Exits non-zero on a miss.
   - `README.md`.
5. **Makefile:** `loadtest` with `ARGS` pass-through. `.gitignore`: `.seed.json`, Locust CSVs and logs.
6. **Run it:** a 30-user smoke run, then the full run (80 + 2, 10 min). Write `docs/loadtest/2026-11-results.md`.
   - Fixes are limited to the spec's list: indexes go in `0014_loadtest_indexes.py`; N+1 fixes, pool and workers.
   - If a miss is caused by round trips only, it is reported, not loosened. Bigger fixes are written up and handed to the user.

### Security review
- `scripts/route_roles.py`: walks `iter_route_contexts` and prints a route × (role dependency) table for area 3.
- `docs/security-review.md`, a dated checklist with 12 areas:
  - Run the `security-reviewer` subagent once per area against whole paths. Batch related areas so the runs can be parallel; the spec says once per area, so it is still 12 prompts.
  - Record findings with severity. Fix criticals and highs; fix mediums or list them with a reason and owner.
- Area 1 Supabase settings: **ask the user to confirm** that public sign-up is off and that the redirect allow-list is set in the dev project.
- Area 6: cite the last recorded tutor eval.
- Area 12: `pnpm build` and grep `dist/` for `service_role`/`DEEPSEEK`.

### Docs (spread across the PRs where the change lands)
- `docs/runbooks/deploy-checklist.md`.
- ARCHITECTURE: stack rows for Sentry and Locust; Boundaries for rate limits, headers, the error shape and what is sent to Sentry.
- CLAUDE.md: commands `make loadtest`/`backup`/`audit`, and the rule "nothing personal in logs or Sentry".
- PRD Constraints: Sentry as a third data flow.
- `backend/.env.example`: the new vars.
- Mark the spec status as built at the end.

---

## Verification
- Every PR: `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, `make check` (shown), and `make test-db` (shared DB: never in parallel with the load test).
- PR 2: `make audit` locally (gitleaks installed, or the hint is shown); `actionlint`. Backup drill: `make backup` against the dev project, then `make restore-check` into `docker run postgres:<major>`. The output shows head, counts and RLS. Record the drill in the runbook. Dispatching `backup.yml` needs the user to add secrets, so it is reported as pending if they aren't added.
- PR 3: smoke run plus full `make loadtest` output; `check.py` green or findings written up.
- **Browser checks** (memory: batched at end, and Chrome can't reach localhost): the CSP zero-violation check on `pnpm preview`, `/debug/boom` toast, error screen and lowered-limit 429 go on the end-of-project pending list with 013 and 014. They are not claimed as done.
- The Sentry smoke test is skipped with a note unless the user supplies a DSN.

## Points needing the user during execution
- Confirm the Supabase dev-project dashboard settings (security area 1).
- Optional: a Sentry DSN for the smoke test, and adding `BACKUP_*` secrets to GitHub for the workflow drill.
- If the load test misses thresholds beyond the allowed fixes, decide on the recommendations.
