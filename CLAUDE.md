# Project: Learning App (MVP)
Multi-school learning platform (maths, physics, Python): knowledge graph with Bloom mastery, short theory + heavy practice, spaced repetition, XP, AI tutor, teacher dashboard.
Context: @docs/PRD.md · @docs/ARCHITECTURE.md · Build order: docs/ROADMAP.md · Playbook: CLAUDE-CODE-PLAYBOOK.md
Stack: FastAPI + SQLAlchemy + Postgres (backend/), React + TS + Vite (frontend/), content-as-code (content/).

## Commands
- Setup: `make install` (uv sync + pnpm install). Backend config: copy `backend/.env.example` to `backend/.env`.
- Dev: `make dev` (API :8000 + web :5173; Vite proxies `/api`)
- Test (single file): `cd backend && uv run pytest path/to/test` · `cd frontend && pnpm vitest run path/to/test`
- Test (all): `make check` (offline) + `make test-db` (needs `TEST_DATABASE_URL`, a separate Supabase project)
- Typecheck: `cd backend && uv run mypy` · `cd frontend && pnpm typecheck`
- Lint/format: `make fmt`
- Migrate: `make migrate` (alembic upgrade head against `DATABASE_URL`)
- Content: `make content-check` (offline validator, part of `make check`; `--strict` via `uv run app content check`) · `make content-import` (`ARGS=--dry-run` to preview). Format: content/README.md
- Onboard a school: `cd backend && uv run app org create --name "..." --code ABC --admin-email ... --admin-name "..."` (`app org list`)
- Full check (what the Stop hook and CI run): `make check`

## Workflow
- New features start from a spec in docs/specs/ (use `/spec`). Implement in a fresh session, plan first.
- After code changes: run typecheck + related tests and show the output. Don't claim done without evidence.
- After frontend changes: tests aren't enough. Run `make dev`, open the changed flow in the browser (Claude in Chrome / the `run` skill),
  click through it, including the empty/error states, and show screenshots. If you need a dev login, ask the user; never store one in the repo.
- Before shipping: use the `reviewer` subagent to check the diff against the spec, then `/ship`.
- Branches: `feat/<spec-number>-<slug>`, `fix/<slug>`. Small, descriptive commits.

## Rules
- Every tenant-owned query must go through the org-scoping dependency. Never query by id alone.
- Answer keys and hidden tests never go to the client. Maths answers are checked server side (SymPy).
- All AI model calls go through backend/app/ai/. Tutor: DeepSeek (`deepseek-flash`, decided Nov 2026); teacher summaries: DeepSeek too (`deepseek-v4-pro`, spec 011).
- Students are minors: store as little personal data as possible, and never log personal details in AI prompts or analytics.
- Nothing personal in logs or Sentry (spec 015): ids, route templates and stack traces only; never names, answers, code, chat text, bodies or query strings.
- Never edit `.env*` files or lockfiles by hand (a hook blocks this).
- Prefer existing patterns and libraries in the codebase over adding new dependencies.

## Gotchas
<!-- Add one line every time Claude gets something wrong. Keep this file under ~200 lines. -->
- Services take an `OrgScope` (`app/api/deps.py`), never a raw session + id; new routes must depend on it (route-walking test).
- Students have no email: their Supabase auth email is synthetic, `{username}@{school-code}.students.invalid`, never shown or sent.
- New tables: inherit `TenantMixin`, add composite FKs for links, and enable RLS in the migration (`test_rls_db.py`).
- Content tables (`course`…`item`) are global: no `TenantMixin`/`OrgScope`, but still RLS. Item answers live in `item.answer`; API shapes come only from `item.public`.
- Teacher reads of learning state use `frontier.class_states` (batched, read-only); never call `frontier.load` for staff (it promotes on read). Class views share `services/class_view.load`.
- Teacher AI summaries (spec 011) build their facts from `dashboard.class_snapshot` / `student_snapshot`: change dashboard numbers there, not in `overview`, so cards and summary facts stay the same numbers.
- Spec 014: student queries must exclude `status = erased` (anonymised rows stay). Use the existing helpers
  (`tenancy.get_student`, `list_students`, `class_view.load`); erasure deletes enrolments, so rosters drop them.
- FastAPI 0.143 nests included routers: walk routes with `fastapi.routing.iter_route_contexts(app.routes)`, not `app.routes`.

## Compaction
- When compacting, preserve: the current spec path, modified files, test commands, open TODOs.
