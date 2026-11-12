# Spec 015: Operations hardening — error tracking, backups, load test, security

Status: built (Nov 2026; PRs 1-3). Open: the browser check (batched) and the load-test latency findings (docs/loadtest/2026-11-results.md).
PRD link: docs/PRD.md#mvp-scope-v1 (item 13)

Second half of roadmap line 014 ("Hardening"), split out while specifying (Nov 2026). The privacy half is
[spec 014](014-privacy-consent-export-erasure.md). Build 014 first: the security review here covers its endpoints.

## Summary
Errors in the API and the browser reach Sentry with no personal data in them. The database is dumped, encrypted and
restore-tested every night once a production secret exists, and by one command before then. A scripted load test
proves a full school lab (80 students at once) works on the free tier. The API gains security headers, a body size
cap and per-user rate limits; CI scans dependencies and secrets; and a written security review of the whole app
passes with no high finding open.

**Deployment is out of scope** (decided Nov 2026): everything here is code, config, workflows and runbooks, checked
locally and against the dev/test Supabase projects. Workflows that need production do nothing until their secrets
exist.

## User stories
- As the developer on call, I want to see every unhandled error with a stack trace and a request id, without ever
  seeing a child's name, answer or chat text in the error tool.
- As a student or teacher, when something breaks I want a short message with a code I can tell my teacher.
- As the platform owner, I want last night's database back within an hour if Supabase loses it or we break it.
- As the platform owner, I want to know a whole computer lab can use the app at once before a school tries it.
- As the platform owner, I want a runaway script or a curious student not to exhaust the free database.
- As the platform owner, I want a recorded security review before real students' data goes in.

## Behaviour

### 1. Error tracking (Sentry, scrubbed)
- Sentry SaaS free plan, **EU region**. On only when a DSN is set: `SENTRY_DSN` (backend), `VITE_SENTRY_DSN`
  (frontend build). Unset (the default, and always in tests) = the SDK is never initialised and no network call
  is made.
- **Backend** (`sentry-sdk[fastapi]`, initialised in `app/core/observability.py`, called from `create_app`):
  - `send_default_pii=False`, `include_local_variables=False` (locals can hold names, answers, tutor text),
    `max_request_body_size="never"`, `traces_sample_rate=0` (errors only), `environment=ENVIRONMENT`,
    `release=GIT_SHA` (env, optional).
  - `before_send` removes: request body, cookies, all headers except `user-agent`, the query string, and
    breadcrumb data of `httpx` calls (URL path kept, query and body dropped). It drops the event entirely for
    `ApiProblem` with status < 500.
  - Tags only: `user.id` (our `app_user.id`), `org_id`, `role`, `request_id`. Never display name, username, email.
  - The AI modules (`app/ai/`) never attach prompts or replies to exceptions: provider errors are re-raised as
    the existing `TutorUnavailable`-style errors with status code and provider error type only.
- **Request id**: a middleware gives every request an id (incoming `X-Request-ID` if it matches
  `^[A-Za-z0-9-]{8,64}$`, else a new uuid4 hex), returns it as `X-Request-ID`, and puts it in the log record.
- **Unhandled errors**: a catch-all handler returns `500 {"code": "internal", "message": "Something went wrong.
  Please try again.", "request_id": "..."}` (never a stack trace, in any environment) and logs the exception with
  the request id. `ApiProblem` responses are unchanged.
- **Logging**: in `production` the API logs one JSON line per record (`ts`, `level`, `logger`, `msg`,
  `request_id`, and for the access line `method`, `path` template, `status`, `ms`, `user_id`, `org_id`); in
  development the current plain format stays. Paths are logged as route templates (`/students/{student_id}`), not
  raw URLs; no query strings, bodies or names.
- **Frontend** (`@sentry/react`, initialised in `src/lib/observability.ts` before render):
  - No session replay, no tracing, no feedback widget; `sendDefaultPii: false`.
  - Breadcrumbs: `console`, `dom` (click text) and `xhr`/`fetch` bodies are disabled; fetch breadcrumbs keep
    method, path and status only.
  - `beforeSend` drops `request.cookies`, `request.headers`, and anything under `extra`; user = `{id}` plus tags
    `org_id`, `role`.
  - `ignoreErrors`: aborted fetches, `ResizeObserver loop` noise, and API errors with status < 500.
  - Errors inside the Pyodide worker that come from the **student's own code** are not reported (they are results,
    not faults); a worker that fails to load Pyodide is reported without the student's code.
- **Error screens**: a root React error boundary and the router `errorElement` show "Something went wrong" with
  **Reload** and the Sentry event id or API `request_id` as "Error code". The API client surfaces `request_id` in
  the existing error toast for 5xx.
- `docs/runbooks/errors.md`: creating the Sentry project (EU), the two DSNs, the "Data scrubbing" and "Prevent
  storing of IP addresses" project settings to switch on, alert rule (email on first seen issue), and the free
  quota (5k errors/month): what to do when it is hit.

### 2. Backups
- `make backup` → `scripts/backup.sh`: needs `BACKUP_DATABASE_URL` (Session pooler URL) and `BACKUP_PASSPHRASE`.
  Produces in `backups/` (gitignored):
  - `public-{UTC timestamp}.dump.gpg`: `pg_dump --format=custom --no-owner --no-privileges --schema=public`.
  - `auth-{timestamp}.dump.gpg`: data only of `auth.users` and `auth.identities` (so accounts and password hashes
    can be restored into a new Supabase project).
  - Both encrypted with `gpg --batch --symmetric --cipher-algo AES256`; the passphrase is read from the
    environment through a file descriptor, never from argv. A `SHA256SUMS` file. Plain dumps never touch disk
    (piped).
  - Fails loudly if `pg_dump`'s major version is older than the server's.
- `make restore-check FILE=backups/public-....dump.gpg` → `scripts/restore_check.sh`: needs
  `RESTORE_DATABASE_URL`, an **empty scratch Postgres** (never a Supabase project that holds data: the script
  refuses if the target has any table in `public`). Decrypts, `pg_restore`s, then prints and checks: the alembic
  revision equals the repo head or an ancestor, row counts per table, `organization` count ≥ 1, every table has RLS
  enabled. Exit non-zero on any failure.
- `.github/workflows/backup.yml`: nightly 19:30 UTC (01:00 IST) + `workflow_dispatch`. Steps: install the matching
  `postgresql-client`, `make backup`, `make restore-check` against a `postgres` service container of the same major
  version, upload the two `.gpg` files + `SHA256SUMS` as an artifact with **14-day retention**. Secrets:
  `BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE`; without them the job ends green with "skipped" (same gate pattern as
  `ci.yml`). A failed backup or restore check fails the workflow (GitHub emails the repo owner).
- `docs/runbooks/backup-restore.md`: where the passphrase lives (a password manager, **not only** in GitHub
  secrets), how to download an artifact, a full restore into a new Supabase project (create project → `alembic`
  not needed → `pg_restore` public → load auth data → re-enable RLS check → point `DATABASE_URL` at it), expected
  time, and a line to record each restore drill (date, duration, result).
- Recovery point: 24 h. Recovery time target: 1 h. Retention: 14 nightly copies. (GitHub artifacts are visible to
  repo collaborators; the encryption is what protects them.)

### 3. Load test
- **Tool**: Locust, in its own `loadtest` dependency group, so `make install` and CI stay light. Code in `backend/loadtest/`.
- **Target environment**: the API started locally by the make target on port 8001, pointed at the **test Supabase
  project** (`TEST_DATABASE_URL`): the same pooler and limits as production will have, and data that the next
  `make test-db` wipes anyway. Never the dev database. It must not run at the same time as `make test-db` (one
  shared test project).
- **Auth without Supabase**: the load-test API process runs with `SUPABASE_JWT_SECRET` set to a random per-run
  secret (the verifier's existing HS256 path), and Locust mints HS256 tokens for the seeded users. No Supabase auth
  users are created and no sign-in endpoint is hit. `ENVIRONMENT=test`; the run aborts if `ENVIRONMENT` is
  `production`.
- **Seed**: `uv run app loadtest seed` (available only when `ENVIRONMENT=test`): migrates to head, imports
  `content/`, creates school `LOADTEST` with 1 teacher, 2 classes (maths-9, physics-9) × 40 students, and gives
  each student a spread of state (some concepts learned, some review cards due) so reviews and dashboards have
  work. Writes the ids to `backend/loadtest/.seed.json` (gitignored).
- **Scenario** (`locustfile.py`), 80 student users + 2 teacher users, spawn 4/s, 10 minutes, think time 3–12 s:
  - Student loop, weighted: home (`/me`, XP summary, course outline, assignments card) → open a lesson (progress
    posts, study-time posts) → start a KP session and answer its questions (a correct answer ~75% of the time,
    worked out by Locust itself: it reads the session's `current_seed` and the item's `answer` straight from the
    test database and calls `app.content.params.sample`, so no API change and no answer key crosses the API) → a due review → the
    knowledge graph → occasionally the leaderboard. Numeric, expression (SymPy) and MCQ items; code items submit a
    canned output set.
  - Teacher loop: class overview, Students tab + heatmap, one student page, every 60 s.
  - The tutor is off (`TUTOR_ENABLED=false`) and teacher AI is off: no DeepSeek calls, no spend.
- **Pass criteria** (from Locust's CSV, checked by `backend/loadtest/check.py`, exit non-zero on a miss):
  - error rate < 1% (any 5xx, timeout or connection error; 4xx from the scenario's own mistakes count too);
  - p95 < 800 ms for answer submits (`POST .../answer`), p95 < 1500 ms for every other endpoint, p99 < 3 s overall;
  - no `QueuePool limit` / pool timeout in the API log; DB connections stay ≤ `DB_POOL_SIZE + DB_MAX_OVERFLOW`.
- `make loadtest` = seed → start API → Locust headless → `check.py` → stop API. `make loadtest ARGS="--users 30
  --run-time 2m"` for a smoke run.
- **Results**: `docs/loadtest/2026-11-results.md`: machine, network, commit, settings (`DB_POOL_SIZE`, workers),
  the per-endpoint table (requests, p50/p95/p99, failures), the slowest five endpoints, and what was changed.
- **If it fails**: fixes inside this spec are limited to indexes, removing N+1 queries, pool settings, the number
  of uvicorn workers and moving SymPy work off the event loop if it blocks. Anything bigger (caching layers,
  schema redesign) is written up in the results file as a finding with a recommendation, and the user decides.
- The rate limiter (section 4) stays **on** during the test: a real lab must not trip it.

### 4. Security hardening
- **Headers** (API middleware, every response): `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy: same-site`, `Cache-Control: no-store` on `/api/*`, `Content-Security-Policy: default-src 'none';
  frame-ancestors 'none'` on JSON responses, and `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  only when `ENVIRONMENT=production`.
- **SPA headers**: `_headers` (Cloudflare Pages / Netlify format; the runbook gives the Vercel equivalent). The
  tracked `frontend/public/_headers` is replaced by a `dist/_headers` emitted at build by a Vite plugin from
  `csp.ts` (its existing `/content-assets/*` rule is kept), with a CSP that allows exactly: self; scripts from self + `cdn.jsdelivr.net` (Pyodide) with
  `'wasm-unsafe-eval'`; `worker-src 'self' blob:`; styles self + `'unsafe-inline'` (KaTeX, React Flow);
  `img-src 'self' data:`; `font-src 'self' data:` (KaTeX); `connect-src` self + the API origin + the Supabase project + Sentry
  ingest + `cdn.jsdelivr.net`; `frame-src 'none'` (YouTube is links only, no iframes);
  `frame-ancestors 'none'`; `base-uri 'self'`; `form-action 'self'`. The same policy is applied by `vite preview`
  (read from one shared file) so it can be tested locally: a built app must run a lesson, a KaTeX formula, a
  Mermaid diagram, the knowledge graph and a Python task with zero CSP violations in the console.
- **Body size cap**: requests with a body over **256 KB** → `413 {"code": "payload_too_large"}` (checked from
  `Content-Length` and enforced while reading for chunked bodies). The largest legitimate body is a code
  submission: the service accepts code up to 20 000 chars (`grading/code.py`) plus test outputs. The response
  also carries `"message": "That's too large to send."`.
- **Rate limiting** (in-process token buckets, no Redis; `app/core/ratelimit.py`):
  - **Per authenticated user only** (a school lab shares one public IP, so per-IP limits on signed-in traffic would
    lock out a class). Keyed by `app_user.id` after auth.
  - Writes (`POST/PATCH/PUT/DELETE`): 120/min, burst 40. Reads: 600/min, burst 120.
  - Expensive endpoints, own buckets: student export 5/hour per admin; bulk student creation 10/hour per teacher;
    consent bulk 30/min. The tutor and teacher-AI keep their existing caps.
  - Unauthenticated requests (bad or missing token) are limited per IP: 300/min, to slow token guessing and floods;
    `/health` is exempt. The client IP comes from `X-Forwarded-For` only when `TRUSTED_PROXY_COUNT` > 0 (default 0
    = socket address).
  - Over the limit → `429 {"code": "rate_limited", "message": "Too many requests. Wait a moment and try again."}`
    with `Retry-After` (seconds). The frontend API client shows that message as a toast and does **not** retry
    automatically; TanStack Query retries are off for 429.
  - Limits are per process: with N workers the effective limit is up to N× (documented; good enough for the MVP).
    Buckets idle for 10 minutes are dropped. `RATE_LIMIT_ENABLED=false` switches it off (the unit-test default;
    the limiter's own tests switch it on).
- **Production config guard**: with `ENVIRONMENT=production` the app refuses to start if `CORS_ORIGINS`
  contains `*` or if `APP_URL` is not `https://`. (Empty `CORS_ORIGINS` stays valid: a same-origin deployment.
  `SUPABASE_JWT_SECRET` stays allowed: legacy HS256 projects are supported and can't be told apart.) The guard
  runs in `create_app()` only, so CLI commands are unaffected.
  The interactive docs (`/docs`, `/redoc`, `/openapi.json`) are off in production.
- **CI scanning** (`.github/workflows/ci.yml`, a second job `security`, needs network, not part of `make check`;
  also `make audit` locally):
  - `uvx pip-audit` on the exported lock (`uv export --frozen --no-dev`), failing on any known vulnerability with
    a fix available;
  - `pnpm audit --prod --audit-level high`;
  - `gitleaks detect` (the binary, pinned version, full history on `main`, the PR range on pull requests) with a
    `.gitleaks.toml` allow-list for test fixtures.
  - An ignore needs a line in `docs/security-review.md` (id, reason, date to revisit).

### 5. Security review
- `docs/security-review.md`: a dated checklist with, for each line, **evidence** (test name, file:line or a
  command's output) and a result. Areas:
  1. Authentication: token verification, `sessions_valid_after`, password flows, Supabase settings (public sign-up
     off, redirect allow-list) checked in the dev project.
  2. Tenant isolation: every route through `OrgScope` (route-walking test), composite FKs, cross-school ids → 404.
  3. Authorisation: student vs teacher vs admin on every route (a generated route × role table).
  4. Answer-key leakage: every response schema built from `item.public`; grep + test evidence.
  5. Input handling: the SymPy safe AST walker, Markdown rendering (no raw HTML), SQL only through SQLAlchemy
     binds, `LIKE` escaping, upload surface (none).
  6. AI: prompt-injection eval results (spec 009), what leaves for DeepSeek (no names/ids), guard coverage.
  7. Privacy endpoints from spec 014: export contents, erasure, audit log, consent gate.
  8. Secrets: none in the repo or history (gitleaks), none in logs or Sentry (a test sends a fake secret-bearing
     error through `before_send`).
  9. Data at rest and in transit: RLS deny-all on every table, SSL to Postgres, backups encrypted.
  10. Headers, CORS, rate limits, body cap, error responses (no stack traces).
  11. Dependencies: audit results.
  12. Client: tokens in memory/Supabase storage, no secrets in the bundle (grep the built `dist/` for the service
      role key name and `DEEPSEEK`), CSP.
- Process: run the `security-reviewer` subagent **once per area on the whole codebase** (not only this spec's
  diff), give it the checklist line and the relevant paths, and record its findings with a severity (critical /
  high / medium / low). **Pass** = no critical or high open. Mediums are fixed in this spec or listed with a reason
  and an owner. Lows are listed.
- The review is repeated (and the file re-dated) before the pilot starts if more than a month has passed; that
  repeat is a line in `docs/pilot-readiness.md`, not part of this spec.

### Decided while specifying (builder check, Nov 2026)
- **Order** (decided while specifying): start 015 only after spec 014 is on `main` (it owns migration 0013, the
  export and consent routes that get their own rate buckets, and review area 7).
- **Catch-all 500** (decided while specifying): not `add_exception_handler(Exception, ...)` (that runs outside all
  middleware, so the response would lose CORS, security headers and the request id). It is caught inside our own
  ASGI middleware, ordered request id → CORS → security headers → body cap → catch-all → app, which calls
  `sentry_sdk.capture_exception` itself. `CancelledError`, client disconnects and responses already started are
  not reported. CORS gains `expose_headers=["X-Request-ID", "Retry-After"]`.
- **`ApiProblem` and Sentry** (decided while specifying): `ApiProblem` ≥ 500 (502/503 from Supabase or DeepSeek
  outages) is captured explicitly in its handler with a fingerprint of its `code`, so an outage is one issue, not
  thousands. `ApiProblem` gains an optional `headers` field (needed for `Retry-After`).
- **Rate-limit placement** (decided while specifying): the per-user bucket is checked right after the token is
  verified (the `sub` is the user id) and **before** the `app_user` lookup, so a flood costs no DB query. Only
  missing or invalid-token 401s count against the per-IP bucket (not 503 `auth_unavailable`, not deactivated
  users); it is 300/min because a whole lab's sessions can expire together. The frontend treats a 429 received
  with no valid session as signed out. Expensive endpoints consume their own bucket **and** the general one.
  `/health`, unmatched paths and validation 422s are not limited. Bucket reading: "120/min, burst 40" = capacity
  40, refill 2/s. `TRUSTED_PROXY_COUNT = N` takes the Nth address from the right of `X-Forwarded-For`.
  Limits are settings (`RATE_LIMIT_WRITE_PER_MIN`, `RATE_LIMIT_READ_PER_MIN` and bursts) so the browser check can
  lower them.
- **Content assets** (decided while specifying): they are served by the SPA host (a Vite plugin bundles them),
  not the API, so the API has no `/content-assets` exception. CSP origins come from `VITE_API_BASE_URL`,
  `VITE_SUPABASE_URL` and `VITE_SENTRY_DSN` at build. `preview.headers` can't do per-path rules, so the
  content-assets rule isn't reproduced in preview. Pyodide is a dynamic `import()` inside a module worker: the
  `/*` rule covers the worker script.
- **Logging** (decided while specifying): there is no logging config today. In production `create_app` installs
  the JSON formatter on root, `uvicorn.error` and our own access logger and disables `uvicorn.access` (it prints
  raw URLs with query strings). Development is unchanged (no own access line). Unmatched routes log
  `path="(unmatched)"`; `user_id`/`org_id` come from `request.state`, set by the auth dependency; the request id
  travels in a contextvar. Sentry tags: `role` = teacher | student plus `is_admin`.
- **Frontend errors** (decided while specifying): there is no global toast today. `ApiError` gains `requestId`
  (body, else the `X-Request-ID` header); `errorMessage()` appends "(code xxxxxxxx)" (first 8 chars) for 5xx and
  returns the 429 and 413 texts; a global `QueryCache`/`MutationCache` `onError` toasts 429 only. The learn
  feature's `retryUnlessClientError` becomes the global query `retry`, so no 4xx is retried anywhere.
- **Pyodide load failures** (decided while specifying): the worker posts `load_error`, it never throws;
  `usePython` reports it with `captureMessage` once per page session, fixed fingerprint, no code (a lab that
  blocks jsDelivr must not send 80 events per lesson).
- **Load scenario realism** (decided while specifying): classes are named "Maths 9" and "Physics 9" on the courses
  `maths-9-10` and `physics-9-10`. The scenario reads state and does only allowed actions: it takes a pending
  quiz, falls back to practice items and reads when nothing is ready, and marks expected 409s (`quiz_pending`,
  cooldowns, the review cap) as successes with `catch_response`. The seed leaves most concepts unlearned. MCQ
  answers are matched from the DB the same way as numeric ones.
- **Load-test auth** (decided while specifying): tokens need `aud="authenticated"`,
  `iss="{SUPABASE_URL}/auth/v1"`, `sub`, `iat`, `exp` (run time + 1 h); Locust and the API process share
  `SUPABASE_URL`. Seeded users are inserted directly (active, `must_change_password=false`), no `SupabaseAdmin`.
- **Sharing the test database** (decided while specifying): a session-level `pg_try_advisory_lock` on a dedicated
  connection, held by a session fixture in `tests/conftest.py` and by the load-test orchestrator; whoever comes
  second stops with a clear message (a CI `make test-db` during a local load test fails: accepted). `app loadtest
  seed` also requires `DATABASE_URL == TEST_DATABASE_URL` (the make target's small Python launcher sets it) and
  rebuilds the schema like conftest (downgrade base → upgrade head).
- **Network-bound results** (decided while specifying): the results file records the measured laptop → Supabase
  round trip and the server-side time per endpoint. If a threshold is missed only because of round trips,
  `check.py` is **not** loosened: it is reported as a finding and the user decides. DB connections are measured by
  polling `pg_stat_activity` with a distinct `application_name`; the number of uvicorn workers is a tuning knob
  (SymPy already runs off the event loop in a 2-process pool) and must respect the pooler's connection cap.
- **Backups** (decided while specifying): the script detects the server major with `SHOW server_version`; the
  workflow installs that client from PGDG and starts the scratch Postgres with `docker run` (a `services:` tag is
  static). `restore_check.sh` drops the scratch DB's empty `public` schema first, uses `pg_restore
  --exit-on-error`, and also decrypts the auth dump and asserts with `pg_restore --list` that it holds the two
  TABLE DATA entries. Loading auth data into a new Supabase project is documented in the runbook as **not yet
  drilled**. Locally, a missing or too-old `pg_dump` or `gpg` fails with an install hint.
- **CI scanning** (decided while specifying): `uv export --frozen --no-dev --no-emit-project` → `pip-audit -f
  json` → a small filter script (pip-audit has no "only when a fix exists" mode). If gitleaks finds a real secret
  in history: stop, tell the user to rotate it, then allow-list that commit with a line in
  `docs/security-review.md`. `make audit` fails with an install hint when gitleaks is missing.
- **Security review mechanics** (decided while specifying): the `security-reviewer` agent's default is the diff;
  each run's prompt overrides that with the area and whole paths. Area 1's Supabase dashboard settings are
  confirmed by the user and recorded. Area 6 cites the last recorded tutor eval (no paid re-run unless asked).
  Area 3's route × role table is generated by a script walking `iter_route_contexts`.
- **Debug route** (decided while specifying): `GET /api/v1/debug/boom` exists only when `ENVIRONMENT=development`,
  is authenticated and passes the route-walking test; it is the one exception to "no new routes".

## UI / UX
- Error boundary screen (full page) and route error element: title, one sentence, **Reload**, small "Error code:
  ab12cd34". Works signed out and at phone width.
- 5xx toast: existing toast + "(code ab12cd34)". 429 toast: the rate-limit message. 413: "That's too large to
  send."
- No other visible change.

## Technical design
- **Files / modules touched**
  - Backend, new: `app/core/observability.py` (Sentry init, `before_send`, JSON log formatter),
    `app/core/middleware.py` (request id, security headers, body cap, access log; pure ASGI middleware, not
    `BaseHTTPMiddleware`, so streaming and cancellation keep working), `app/core/ratelimit.py` (token bucket +
    dependency), `backend/loadtest/` (`locustfile.py`, `seed.py`, `tokens.py`, `check.py`, `README.md`),
    `scripts/backup.sh`, `scripts/restore_check.sh`.
  - Backend, changed: `app/main.py` (wire middleware, catch-all handler, docs off in production),
    `app/core/config.py` (`sentry_dsn`, `git_sha`, `rate_limit_enabled`, `trusted_proxy_count`, the production
    guard), `app/api/deps.py` (rate-limit check after auth; per-IP check on auth failure),
    `app/cli.py` (`loadtest seed`, test environment only), `pyproject.toml` via `uv add sentry-sdk[fastapi]` and
    `uv add --group loadtest locust` (never edit the lockfile by hand), `backend/.env.example` (new variables, commented).
  - Frontend, new: `src/lib/observability.ts`, `src/components/ErrorScreen.tsx`,
    `csp.ts` (the one policy source, used by `vite.config.ts` for `preview.headers` and by a Vite plugin that
    emits `dist/_headers`). Removed: the tracked `public/_headers`.
  - Frontend, changed: `src/main.tsx` (init + boundary), the router (`errorElement`), `src/lib/api.ts`
    (`request_id`, 429, 413), `package.json` via `pnpm add @sentry/react`.
  - Repo: `Makefile` (`backup`, `restore-check`, `loadtest`, `audit`), `.gitignore` (`backups/`,
    `backend/loadtest/.seed.json`, Locust CSVs), `.gitleaks.toml`, `.github/workflows/ci.yml` (`security` job),
    `.github/workflows/backup.yml`.
  - Docs: `docs/runbooks/errors.md`, `docs/runbooks/backup-restore.md`, `docs/runbooks/deploy-checklist.md` (the
    env vars, headers and Supabase settings a future deployment must set; no deployment is done),
    `docs/loadtest/2026-11-results.md`, `docs/security-review.md`, `docs/ARCHITECTURE.md` (stack rows for Sentry
    and Locust, Boundaries: rate limits, headers, error shape, what may be sent to Sentry), `CLAUDE.md` (commands:
    `make loadtest`, `make backup`, `make audit`; rule: nothing personal in logs or Sentry), `docs/PRD.md`
    Constraints (Sentry as a third data flow for the legal review: ids and stack traces only).
- **Data model changes**: none. (Indexes found by the load test go in `alembic/versions/0014_loadtest_indexes.py`
  if needed.)
- **API / interfaces**: no new routes. New response shapes: `500 internal` with `request_id`, `429 rate_limited`
  with `Retry-After`, `413 payload_too_large`; `X-Request-ID` on every response.
- **New dependencies**: `sentry-sdk[fastapi]`, `@sentry/react`, `locust` (dev). CI tools run without being added
  to the project (`uvx pip-audit`, the gitleaks binary).

## Edge cases
- Sentry is down or the DSN is wrong → requests are unaffected (the SDK sends in the background and drops).
- An exception message itself contains personal text (e.g. a validation error echoing input) → `before_send`
  replaces the message of `RequestValidationError`/`ValidationError` events with the error types and field paths
  only; a test proves a name in the input never reaches the event.
- A 500 inside the catch-all handler or the middleware → plain `500` with the request id header; never a loop.
- Streaming or cancelled requests (client closed) are not reported as errors.
- The body cap must not break `content-assets` (GET only) or bulk student creation (small).
- A teacher clicking quickly through the dashboard (many parallel reads on load) stays under 600/min; the
  dashboard's heaviest page load is counted in a test and must use < 25% of the read burst.
- A student whose browser retries on a flaky network → 429s tell them to wait; in-progress answers are not lost
  (the session's current question is stored server side, as today).
- Two API workers → limits are per worker; `Retry-After` may be slightly optimistic.
- Clock jumps on the host → buckets use a monotonic clock.
- Backup while students are active → `pg_dump` is a consistent snapshot; no lock that blocks writes.
- The backup passphrase is lost → backups are unrecoverable: the runbook makes storing it in a password manager a
  setup step, and the restore check proves the stored one works.
- The dump grows past the artifact limit → not at pilot scale (a full school is a few MB); the workflow prints
  the size and warns over 500 MB.
- Supabase free project paused (idle a week) → the backup fails loudly; the runbook says restore the project.
- The load test is interrupted → the API subprocess is still stopped (trap), and the `LOADTEST` school is removed
  by the next `make test-db` (the schema is rebuilt).
- `make loadtest` and `make test-db` started together → the second refuses to start (a lock row / advisory lock
  on the test database), with a clear message.
- gitleaks flags a test fixture token → allow-listed by path in `.gitleaks.toml`, never by disabling the rule.
- An audit finding has no fixed version yet → ignored with an entry in `docs/security-review.md` and a revisit date.

## Out of scope
- Deploying to any host; creating the Sentry project, production secrets or the production Supabase project (the
  runbooks say how; the user does it).
- Performance tracing, session replay, uptime monitoring, log shipping, dashboards, on-call alerts beyond Sentry's
  email.
- Redis or any shared rate-limit store; a WAF; CAPTCHA; bot detection.
- Point-in-time recovery, off-site copies beyond GitHub artifacts, backups of Supabase Storage (unused).
- Load beyond one lab (80 concurrent); soak tests; load-testing the AI tutor or teacher summaries against DeepSeek.
- A third-party penetration test.
- Consent, export, erasure, audit log (spec 014). The legal review and the teacher content review
  (`docs/pilot-readiness.md`).
- Server-side sandboxing of student code (v2, decision 6).

## Verification (end-to-end)
Delivered as three PRs (branches `feat/015-operations-1`, `-2`, `-3`, as spec 013 did): **PR 1** error tracking + request id + error screens; **PR 2**
headers, body cap, rate limits, CI scanning, backups; **PR 3** load test (+ fixes) and the security review.

- [ ] `cd backend && uv run mypy`, `cd frontend && pnpm typecheck`, `make check` green; `make test-db` green.
- [x] `tests/test_observability.py`: with no DSN the SDK is not initialised; `before_send` on a synthetic event
      strips body, cookies, headers, query, locals and httpx breadcrumb data; a validation error carrying a name
      and a fake secret yields an event with neither; `ApiProblem` 4xx is dropped, 5xx kept.
- [x] `tests/test_middleware.py`: request id generated / accepted / rejected when malformed and echoed; catch-all
      500 shape with no trace; every header present; HSTS only in production; 413 for `Content-Length` over the cap
      and for an oversized chunked body; a 20 000-char code submission with realistic
      outputs is not a 413.
- [x] `tests/test_ratelimit.py`: bucket maths with a fake clock; per-user isolation (80 users from one IP are
      independent); 429 + `Retry-After`; per-IP limit only for missing/invalid tokens; idle
      buckets dropped; the read burst constant is 120. The page-load count is a vitest: rendering the class
      Overview and the Students tab with a counting fetch mock makes fewer than 30 GETs each.
- [x] `tests/test_config.py`: the production guard refuses each bad setting; docs routes 404 in production.
- [x] Frontend vitest: error boundary renders the screen with a code; API client surfaces `request_id`, 429 and
      413 messages and does not retry a 429; observability `beforeSend` strips what it should.
- [ ] CSP: `pnpm build && pnpm preview`, then open a lesson with maths, a Mermaid diagram, the knowledge graph and
      a Python task: zero CSP violations in the console (screenshot of the clean console).
- [ ] Sentry smoke (skipped: no DSN provided; unit + end-to-end SDK tests are the gate) (manual, optional DSN from the user): one test error from the API and one from the browser
      arrive, grouped, with request id and no personal data (screenshot of the event JSON). Skipped with a note if
      no DSN is provided; the unit tests above are the gate.
- [x] Backups: `make backup` against the dev project, then `make restore-check` into a scratch Postgres (local
      Docker or the workflow's service container): output shows the alembic head, row counts and RLS on every
      table. `backup.yml` run by `workflow_dispatch`: green "skipped" without secrets; with `BACKUP_*` secrets
      pointing at the dev project, green with an encrypted artifact. `actionlint` clean. The drill is recorded in
      the runbook.
- [ ] Load test (functional pass, 0 errors in 20,507 requests; 4 endpoints miss p95, recorded as findings F1-F4 in docs/loadtest/2026-11-results.md for the user): `make loadtest` (80 students + 2 teachers, 10 min) passes `check.py`; results and any fixes are
      in `docs/loadtest/2026-11-results.md`. A 30-user smoke run also works.
- [ ] CI `security` job green on the PR (pending: runs when PR 2/3 are pushed) (pip-audit, pnpm audit, gitleaks); `make audit` works locally.
- [x] `docs/security-review.md` complete: every checklist line has evidence and a result; `security-reviewer`
      subagent run per area; no critical or high finding open; mediums fixed or listed with reason and owner.
- [ ] Browser check (done by the user: Chrome can't reach localhost from the session): `make dev`, trigger a 500
      (`GET /api/v1/debug/boom`, registered only in development) and
      see the toast with a code; break a component to see the error screen; trigger a 429 with a lowered limit.
      Screenshots of each, desktop and phone width.
