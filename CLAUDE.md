# Project: Learning App (MVP)
Multi-school learning platform (maths, physics, Python): knowledge graph with Bloom mastery, short theory + heavy practice, spaced repetition, XP, AI tutor, teacher dashboard.
Context: @docs/PRD.md · @docs/ARCHITECTURE.md · Build order: docs/ROADMAP.md · Playbook: CLAUDE-CODE-PLAYBOOK.md
Stack: FastAPI + SQLAlchemy + Postgres (backend/), React + TS + Vite (frontend/), content-as-code (content/).

## Commands
<!-- Fill these in once the stack is chosen. .claude/hooks/verify.sh runs `make check` if present. -->
- Dev: `<cmd>`
- Test (single file): `<cmd> path/to/test`
- Test (all): `<cmd>`
- Typecheck: `<cmd>`
- Lint/format: `<cmd>`
- Full check (what the Stop hook runs): `make check`

## Workflow
- New features start from a spec in docs/specs/ (use `/spec`). Implement in a fresh session, plan first.
- After code changes: run typecheck + related tests and show the output. Don't claim done without evidence.
- Before shipping: use the `reviewer` subagent to check the diff against the spec, then `/ship`.
- Branches: `feat/<spec-number>-<slug>`, `fix/<slug>`. Small, descriptive commits.

## Rules
- Every tenant-owned query must go through the org-scoping dependency. Never query by id alone.
- Answer keys and hidden tests never go to the client. Maths answers are checked server side (SymPy).
- All Anthropic API calls go through backend/app/ai/. Tutor model: Haiku; teacher summaries: Sonnet.
- Students are minors: store as little personal data as possible, and never log personal details in AI prompts or analytics.
- Never edit `.env*` files or lockfiles by hand (a hook blocks this).
- Prefer existing patterns and libraries in the codebase over adding new dependencies.

## Gotchas
<!-- Add one line every time Claude gets something wrong. Keep this file under ~200 lines. -->

## Compaction
- When compacting, preserve: the current spec path, modified files, test commands, open TODOs.
