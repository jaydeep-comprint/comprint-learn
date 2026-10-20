# Plan: build spec 003 (Content model & importer)

Spec: `docs/specs/003-content-model-importer.md` · Branch: `feat/003-content-model` (from `main` at c213bdc)

## Context
Specs 001–002 left a tenant-scoped app (auth, schools, classes). 003 adds the platform-owned, global content layer that
every later spec (004–012) points at: the file format in `content/`, an offline validator wired into `make check`, an
idempotent importer into Postgres, two read-only graph endpoints, and a real 9-concept sample.

## Ground rules
- `make check` after every step, output shown. Deps only via `uv add` (lockfile is hook-protected).
- Content tables are global: no `TenantMixin`, no `OrgScope`, but RLS on; routes get a `GLOBAL_CONTENT` allowlist in
  the route-scoping test.
- Expressions are never `eval`ed: an `ast` walker with a whitelist builds SymPy objects directly (stricter than
  `parse_expr`, which evals internally).

## Steps
1. **Deps + file schema + params/units** — `uv add sympy pyyaml`, `uv add --dev types-PyYAML`.
   `app/content/schema.py` (Pydantic, `extra="forbid"`; item `answer` is `{<type>: spec}`), `params.py` (safe AST →
   SymPy, `sample(item, seed)`, `render`, `format_number`), `units.py` (curated `sympy.physics.units` table).
   Tests: `test_content_schema.py`, `test_content_params.py` (golden seed values, 1,000-seed constraints, malicious input).
2. **Loader + validator + code runner + `app content check`** — `loader.py` (duplicate-key-safe YAML, folder walk,
   Markdown/image reads, pydantic errors → `Issue` with field path + nearest id), `validate.py` (rules 1–7),
   `code_runner.py` (one `python -I` subprocess per item, SIGALRM per test, 10 s cap, results via a file),
   `hashing.py` (`canonical_json`, `split_item`). CLI group + `make content-check` (in `check`) + `make content-import`.
   Tests: `test_content_validate.py` (one broken fixture per rule, exact message lines), `test_content_code_runner.py`,
   `test_content_split.py`.
3. **Sample content** (3 subject forks in parallel, each iterating on `make content-check` until clean with `--strict`).
4. **Models + migration 0003 + importer + `app content import`** — tables per spec, RLS; importer diffs desired vs
   existing rows per level (retire → flush → upsert, flush per level), link rows diffed (not replaced), advisory lock,
   one transaction, dry-run = rollback. Tests: `test_content_import_db.py`, `test_rls_db.py`, migration drift test.
5. **Read API** — `schemas/content.py` (`CourseSummary`, `CourseGraph`, `ItemPublic.from_row` with `extra="forbid"`),
   `services/content.py`, `api/v1/courses.py`; `GLOBAL_CONTENT` allowlist. Tests: `test_courses_api_db.py`.
6. **Frontend asset plugin** — `frontend/vite/content-assets.ts` (dev middleware + build `emitFile`, svg/png/webp/jpg
   only, path-traversal safe) + vitest; `pnpm build` check.
7. **Docs** — `content/README.md` author guide, ARCHITECTURE domain model + boundaries, CLAUDE.md commands/gotchas.
8. **Verify** — `make check`, `make test-db`, then reviewer + security-reviewer subagents; stop for `/ship`.

## Interpretation notes (record as deviations if they stick)
- Stdout code tests: the harness feeds `stdin`, calls `entry(*args)` (args default `[]`) and compares stdout.
- `content_hash` covers authored content only (not position/parent); derived columns (`public`/`answer`, position,
  parent ids) are refreshed without a version bump when they differ.
- "Retired slug reappears in another course" is a DB fact, so it is reported by the importer, not the offline check.
- SVGs with `<script>`, `on*=` handlers or `javascript:` are rejected (they are served same-origin).
