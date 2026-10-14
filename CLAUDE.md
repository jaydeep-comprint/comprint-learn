# Project: <PRODUCT NAME>
<One line: what it is and who it's for.>
Context: @docs/PRD.md · @docs/ARCHITECTURE.md · Playbook: CLAUDE-CODE-PLAYBOOK.md

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
- Never edit `.env*` files or lockfiles by hand (a hook blocks this).
- Prefer existing patterns and libraries in the codebase over adding new dependencies.

## Gotchas
<!-- Add one line every time Claude gets something wrong. Keep this file under ~200 lines. -->

## Compaction
- When compacting, preserve: the current spec path, modified files, test commands, open TODOs.
