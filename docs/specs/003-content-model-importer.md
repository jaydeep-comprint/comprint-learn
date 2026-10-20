# Spec 003: Content model & importer

Status: implemented (feat/003-content-model)
PRD link: docs/PRD.md#mvp-scope-v1 (item 2; Phase 0 of docs/ROADMAP.md)

## Summary
Courses are authored as files in `content/` (YAML + Markdown, reviewed in git): course → chapter → concept → 3–4
knowledge points (KPs) → items, with prerequisite edges carrying encompassing weights, key prerequisites per KP,
misconception-tagged MCQs, randomised `params`, typed answer specs, Bloom tags and `expected_minutes`.
`make content-check` validates the whole tree offline (schema, graph cycles across courses, answer self-consistency,
code reference solutions), and `uv run app content import` loads it into Postgres idempotently (upsert by authored
slug, version bump on change, retire on removal). Ships a real sample: 3 connected concepts per subject, plus two
read-only endpoints (`/courses`, `/courses/{slug}/graph`) that prove answers never leave the server.

## User stories
- As a content author (our team, often with Claude), I want each concept in its own folder with short YAML and
  Markdown files, so that edits are reviewable diffs.
- As a content author, I want `make content-check` to tell me exactly which file and field is wrong (a cycle, a missing
  misconception, a sig-fig spec that can't work, a code test the reference solution fails) before anything is imported.
- As an operator, I want `app content import --dry-run` to show what would change, and `app content import` to be safe
  to run any number of times.
- As a later spec (004–012), I want stable ids, versioned items and a clean public/answer split, so attempts and
  analytics can point at content that never silently changes identity.
- As any signed-in user, I want to list courses and see a course's concept graph (no questions, no answers).

## Behaviour

### Courses, tenancy and ids
- Content is **global** (platform-owned, the same for every school, read-only to users). Content tables have **no
  `org_id`** and don't inherit `TenantMixin`; RLS deny-all is still enabled on each. Per-school state (attempts,
  assignments, …) will reference content rows from later specs.
- **One course per subject**, spanning Classes 9–10: `maths-9-10`, `physics-9-10`, `python-basics`. Each chapter has
  `grade: 9 | 10` (omitted for Python). A class's course is the course whose `subject` matches the class's subject
  (`Subject` enum from spec 002; at most one active course per subject, validator-enforced).
- Every course, chapter, concept, KP, item and misconception has an **authored slug id**: `^[a-z0-9]+(-[a-z0-9]+)*$`,
  ≤ 60 chars, stable forever. Uniqueness: course slug global; chapter, concept and misconception slugs unique within the
  course; KP and item slugs unique within the concept.
- Qualified references: inside a course, a bare concept slug (`speed-and-velocity`); across courses,
  `<course>/<concept>` (`maths-9-10/linear-equations-two-variables`). **Prerequisite edges may cross courses.**
- DB rows get UUID primary keys; slugs are the import identity.

### File layout
```
content/
  README.md                         # format guide for authors (rewritten by this spec)
  maths-9-10/
    course.yaml                     # id, title, subject, chapters: [ordered chapter ids]
    misconceptions.yaml             # [{id, title, description}]
    01-linear-equations/            # folder = NN-<chapter id>; NN only for humans, order comes from course.yaml
      chapter.yaml                  # id, title, grade, concepts: [ordered concept ids]
      linear-equations-two-variables/   # folder = concept id
        concept.yaml                # metadata, prereqs, KPs + item pools, practice, misconception check
        intro.md                    # Learn-layer intro
        kp-1-worked.md              # one worked example per KP (file names are free; referenced from concept.yaml)
        kp-2-worked.md
        img/line-graph.svg          # assets referenced from Markdown with relative paths
```
- Every folder/file must be referenced: a chapter folder not listed in `course.yaml`, a concept folder not listed in
  `chapter.yaml`, or an unreferenced `.md` in a concept folder is a **warning**; a listed id with no folder is an **error**.
- Folder names must equal the id (chapters: `NN-<id>`).

### `concept.yaml`
```yaml
id: acceleration
title: Acceleration
summary: How quickly velocity changes, and in which direction.   # one line, ≤ 160 chars
prereqs:
  - {concept: speed-and-velocity, weight: 0.7}                     # encompassing_weight, 0 < w ≤ 1
  - {concept: maths-9-10/linear-equations-two-variables, weight: 0.2}
intro: intro.md
misconception_check:            # exactly one item; bloom remember|understand; Learn layer
  id: check
  type: mcq
  ...
kps:                            # 3–4, ordered
  - id: kp1
    title: Acceleration as rate of change of velocity
    worked_example: kp-1-worked.md
    key_prereqs: [speed-and-velocity]   # ⊆ this concept's direct prereqs; may be empty
    items: [...]                        # the KP question pool
practice:                       # ≥ 1 item; type multistep or code only
  - ...
```

### Items (common fields)
```yaml
- id: kp2-q3
  type: numeric                 # numeric | expression | mcq | multistep | code
  bloom: apply                  # remember | understand | apply | analyze | evaluate | create
  expected_minutes: 2           # 0.5–30, multiples of 0.5
  prompt: |                     # Markdown + KaTeX; {{name}} placeholders for params/derived
    A car speeds up from {{u}} m/s to {{v}} m/s in {{t}} s. Find its acceleration.
  params:                       # optional: randomised numbers
    u: {min: 0, max: 10, step: 2}
    v: {min: 12, max: 30, step: 2}
    t: {choices: [2, 4, 5]}
  constraints: ["v > u"]        # optional SymPy boolean expressions over params
  derived: {a: "(v - u) / t"}   # optional SymPy expressions over params (and earlier derived)
  answer:
    numeric: {value: "a", unit: "m/s^2", mode: sigfig, sigfigs: 2}
  explanation: |                # optional Markdown, shown only after an attempt (server-side until then)
    a = (v − u) / t = ({{v}} − {{u}}) / {{t}} = {{a}} m/s².
```
- `{{name}}` must resolve to a param or derived value; an unknown name is an error, an unused param a warning.
  Rendering rule (shared code, used by 004/006): integers print plainly; other rationals/floats print with up to 4
  significant figures, no trailing zeros.
- Params: `{min, max, step}` (inclusive, integers or decimals) or `{choices: [...]}`. Expressions are parsed with
  `sympy.parse_expr` with a whitelisted namespace (no `eval`, no attribute access, no imports).
- **Sampling is deterministic**: `sample(item, seed: int) -> dict[str, Rational|float]` uses `random.Random(seed)`, draws
  params in declaration order, retries up to 100 times until all `constraints` hold, then evaluates `derived` in order.
  It lives in `app/content/params.py` and is the single implementation later specs use to derive answers from a seed.

### Answer specs (ARCHITECTURE decision 10)
| Type | Spec | Rules |
|---|---|---|
| `numeric` | `{value, unit?, mode: exact\|sigfig\|tolerance, sigfigs?, rel_tol?, abs_tol?, sci_notation?: bool}` | `value` = number or expression over params/derived. `unit` parsed with `sympy.physics.units` (e.g. `m/s^2`, `km/h`, `N`); omit for dimensionless. `sigfig` needs `sigfigs` 1–6; `tolerance` needs exactly one of `rel_tol` (0–0.2) / `abs_tol` (> 0); `exact` must evaluate to a value with a finite decimal or an integer |
| `expression` | `{value, variables: [x, …], sympy_mode: exact\|equivalent\|simplified}` | `value` parses as SymPy over `variables` (+ params); free symbols ⊆ `variables` |
| `mcq` | `{options: [{id, text, correct?: bool, misconception?}], shuffle?: true}` | 2–5 options, exactly one `correct`, option ids unique (`a`–`e`), every `misconception` exists in the course's `misconceptions.yaml`, at least one distractor tagged. Used sparingly (warning if > 30% of a KP pool is MCQ) |
| `multistep` | `{steps: [{prompt, answer: <numeric\|expression\|mcq spec>}]}` | 2–10 steps; no nested multistep or code; steps share the item's params/derived |
| `code` | `{entry, starter, solution, tests: [{args, expected, visible}], time_limit_ms?: 2000}` | `entry` = function name defined by `starter` and `solution`; `args` a JSON list, `expected` JSON; ≥ 3 tests, ≥ 1 visible (hidden tests optional; spec 006 decides how they are graded). Stdout tasks: a test may use `{stdin?, expected_stdout, visible}` instead of `args/expected`. Standard library only; no file/network access |

### Public vs answer split (never-to-client rule)
Each item is stored as two JSON documents:
- `public`: what a client may ever see — prompt template, MCQ option ids + text (no `correct`, no `misconception`),
  multistep step prompts, code `entry`, `starter` and **visible** tests, unit string for numeric answers (so the UI can show
  "m/s²"), and `has_params`.
- `answer`: everything else — the answer spec, `params`/`constraints`/`derived`, MCQ correct id + misconception map,
  `explanation`, code `solution` and **hidden** tests.
API schemas are built only from `public` (`ItemPublic.from_row`); a unit test asserts no answer key can leak through.
(Note for spec 006: under decision 6 code grading runs client-side in Pyodide; 006 decides when hidden tests are sent
for grading. `solution` is never sent.)

### Validation (`app content check`, `make content-check`)
Errors fail the check (exit 1); warnings print but pass (`--strict` turns them into errors). Every message is
`<path>: <field path> (<id>): <message>`, e.g.
`content/physics-9-10/01-motion/acceleration/concept.yaml: kps[1].items[2] (kp2-q3): sigfigs is required when mode is sigfig`.

1. **Schema**: Pydantic models for every file (unknown keys are errors, so typos don't vanish).
2. **References**: ids unique per scope; every prereq/key-prereq/misconception/Markdown file/image resolves; images are
   relative, stay inside the concept folder, are `.svg|.png|.webp|.jpg`, ≤ 500 KB.
3. **Graph**: no self-edges, no duplicate edges, `0 < weight ≤ 1`, and **no cycles across all courses** (error names the
   cycle: `a → b → c → a`). `key_prereqs` ⊆ the concept's direct prereqs. At most one course per subject.
4. **Structure**: 3–4 KPs per concept; exactly one misconception check (bloom remember/understand); ≥ 1 practice item
   (multistep or code); every item has `bloom` and `expected_minutes`. **KP pool size**: a fixed item counts 1, a
   param item 2; each pool needs ≥ 6 (error) and should have ≥ 8 (warning).
5. **Answer self-consistency** (per item, 50 seeds for param items, seed 0 for fixed ones): constraints satisfiable on
   ≥ 95% of seeds; every derived/answer value finite and real (no division by zero); numeric units parse and `value`
   is non-zero when `mode: sigfig`; param items produce ≥ 5 distinct rendered prompts; expressions parse; MCQ rules above.
6. **Code reference solutions**: for every code item, run `solution` against **all** tests in a subprocess
   (`python -I`, temp dir, JSON harness, `time_limit_ms` per test, 10 s per item); any failure, exception or timeout is
   an error naming the test index. Also run `starter` to check it defines `entry` (it should fail tests; no check on that).
   Content is trusted repo code, so this is a correctness check, not a sandbox.
7. **Retire safety**: falls out of rule 2 — an active concept referencing a removed concept is a missing reference.

### Import (`app content import [--dry-run]`)
- Runs the full validator first; **any error → nothing is written**, exit 1. Then the whole import runs in **one
  transaction** against `DATABASE_URL` (all-or-nothing).
- Upsert by slug at each level. Each course, chapter, concept, KP, item and misconception row stores `content_hash`
  (sha256 of its canonical JSON, including the text of referenced Markdown and the sha256 of referenced images) and
  `version` (starts at 1, +1 when the hash changes). Unchanged rows are not touched (`updated_at` stays).
- Rows in the DB but absent from the files are **retired** (`retired_at = now()`), never deleted. A retired row that
  reappears is un-retired (and versioned if its hash changed). Retiring a course/chapter/concept retires its children.
- Link rows (`concept_prereq`, `kp_key_prereq`) are replaced to match the files (no history); edges touching a retired
  concept are removed.
- Position (order) changes update `position` without a version bump (order isn't content).
- Output: per course, counts of created / updated / retired / unretired / unchanged per level, e.g.
  `physics-9-10: concepts 3 unchanged · items 41 unchanged, 1 updated (v2), 1 retired`. `--dry-run` prints the same
  diff and writes nothing (transaction rolled back).
- Running import twice in a row: the second run reports everything unchanged and changes no row (`updated_at`
  identical) — the idempotency check.

### Read API
Both need `get_current_user` (any role, any school; content is global). Only active (non-retired) rows.
- `GET /api/v1/courses` → `[{slug, title, subject, chapter_count, concept_count}]`, ordered by subject.
- `GET /api/v1/courses/{slug}/graph` → `{course: {slug, title, subject}, chapters: [{slug, title, grade, position}],
  concepts: [{id: "<course>/<slug>", title, summary, chapter, position, kp_count}], edges: [{from, to, weight}],
  external: [{id, title, course}]}` — `external` lists concepts from other courses that are prerequisites of this
  course's concepts, so the graph can draw them. No items, no KP content. Unknown or retired slug → 404
  `{"code": "not_found"}`.

### Sample content (Claude drafts, light self-review per PRD)
Real CBSE content, connected, exercising every format:
- **Maths (`maths-9-10`)**, chapters *Linear equations in two variables* (9) and *Pair of linear equations* (10):
  `linear-equations-two-variables` → `pair-of-linear-equations-graphical` → `pair-of-linear-equations-algebraic`
  (substitution/elimination). Numeric exact, expression (equivalent), MCQ with misconceptions, multistep practice.
- **Physics (`physics-9-10`)**, chapter *Motion* (9): `distance-and-displacement` → `speed-and-velocity` →
  `acceleration`; `speed-and-velocity` also requires `maths-9-10/linear-equations-two-variables` (weight 0.2, rearranging
  a formula). Numeric with units, sig figs and tolerance, params with constraints, multistep practice.
- **Python (`python-basics`)**, chapter *Basics*: `variables-and-types` → `conditionals` → `loops`. Short code items
  and MCQs in KP pools; code implementations as practice; at least one stdout task.
- Each concept: intro, 3–4 KPs with worked examples, pools that pass the size rule, ≥ 1 param item per maths/physics
  KP, one misconception check, ≥ 1 practice item, ≥ 3 misconceptions per course. At least one SVG diagram (physics).

## UI / UX
No student/teacher screens in this spec (Learn layer is 004, graph view is 005). Author UX is the CLI:
- `make content-check` / `uv run app content check [--strict]`: prints `N errors, M warnings` with one line per issue,
  grouped by file; success prints `content OK: 3 courses, 9 concepts, K items`.
- `uv run app content import [--dry-run]`: prints the diff summary above; ends with `Imported.` or `Dry run, nothing
  written.`
- `content/README.md`: an author's guide (layout, every field, answer-spec cheat sheet, param syntax, the rules the
  validator enforces, how to retire vs edit, "change the meaning of a question → give it a new id").
- Assets in the web app: a small Vite plugin (`frontend/vite/content-assets.ts`, no new dependency) serves image files
  from `../content/**/img/**` at `/content-assets/<course>/<chapter-folder>/<concept>/img/<file>` in dev and copies them
  into the build output, so they ship on the Pages/Vercel CDN. Extension allowlist (svg/png/webp/jpg) — never `.yaml`
  or `.md`. Rewriting Markdown image paths to these URLs is spec 004.

## Technical design
- Files / modules touched:
  - Backend (new)
    - `app/content/schema.py` — Pydantic file models (`CourseFile`, `ChapterFile`, `ConceptFile`, `KpFile`, `ItemFile`
      and per-type answer specs, discriminated on `type`), `extra="forbid"`.
    - `app/content/loader.py` — walks `content/`, parses YAML (`yaml.safe_load`), reads Markdown/images →
      `ContentBundle` (in-memory, with source paths for messages).
    - `app/content/params.py` — `sample(item, seed)`, `render(template, values)`, safe SymPy parsing.
    - `app/content/units.py` — unit-string parsing with `sympy.physics.units`.
    - `app/content/validate.py` — `validate(bundle) -> list[Issue]` (`Issue(level, path, field, id, message)`), rules 1–7.
    - `app/content/code_runner.py` — subprocess harness for reference solutions.
    - `app/content/hashing.py` — canonical JSON + sha256 per row; public/answer split (`split_item`).
    - `app/content/importer.py` — `import_bundle(session, bundle, *, dry_run) -> ImportReport`.
    - `app/models/content.py`, `app/schemas/content.py` (`CourseSummary`, `CourseGraph`, `ItemPublic.from_row`),
      `app/services/content.py`, `app/api/v1/courses.py`.
    - `alembic/versions/0003_content.py` — tables below + `ENABLE ROW LEVEL SECURITY` on each.
  - Backend (edit): `app/cli.py` (`content_app` Typer group: `check`, `import`), `app/models/__init__.py`,
    `app/api/v1/router.py`, `tests/test_route_scoping.py` (new `GLOBAL_CONTENT` allowlist: routes that authenticate but
    read only global content and so skip `OrgScope`), `tests/test_rls_db.py` (assert new tables).
  - Dependencies: `sympy`, `pyyaml` (+ `types-PyYAML` dev) via `uv add` only (never hand-edit the lockfile).
  - Make: `content-check` (`cd backend && uv run --frozen app content check --root ../content`), added to `check`;
    `content-import` (`uv run app content import --root ../content`).
  - Frontend: `vite/content-assets.ts` + `vite.config.ts` (edit).
  - Content: `content/README.md` (rewrite) and the sample tree.
  - Docs (edit): `docs/ARCHITECTURE.md` domain model (content tables are global, no `org_id`; `kp_key_prereq` link table
    instead of an id array; `misconception` table; item `public`/`answer` split; `version`/`retired_at`) and Boundaries
    (the global-content exemption to org scoping); `CLAUDE.md` Commands (`make content-check`, `make content-import`) and
    Gotchas (content tables are global and exempt from `TenantMixin`/`OrgScope`, still need RLS).
- Data model changes (all with `id uuid pk`, `slug`, `content_hash text`, `version int default 1`, `created_at`,
  `updated_at`, `retired_at timestamptz null` unless noted):
  - `course` (`slug` unique, `title`, `subject` — reuse the `Subject` enum type from 0002, `position`). Partial unique
    index on `subject` where `retired_at IS NULL`.
  - `chapter` (`course_id` FK, `title`, `grade smallint null` check 9/10, `position`; unique `(course_id, slug)`).
  - `concept` (`course_id`, `chapter_id` FKs, `title`, `summary`, `intro_md`, `position`; unique `(course_id, slug)`).
  - `concept_prereq` (`concept_id`, `prereq_id` FKs → concept; PK pair; `encompassing_weight numeric(3,2)` check
    `> 0 AND <= 1`; check `concept_id <> prereq_id`). No hash/version.
  - `knowledge_point` (`concept_id` FK, `title`, `worked_example_md`, `position`; unique `(concept_id, slug)`).
  - `kp_key_prereq` (`kp_id` FK, `concept_id` FK; PK pair). No hash/version.
  - `misconception` (`course_id` FK, `title`, `description`; unique `(course_id, slug)`).
  - `item` (`concept_id` FK, `kp_id` FK null, `kind` enum `kp_question | practice | misconception_check` with check
    `kp_id IS NOT NULL` iff `kp_question`, `type` enum, `bloom_level` enum, `expected_minutes numeric(3,1)`,
    `has_params bool`, `position`, `public jsonb`, `answer jsonb`; unique `(concept_id, slug)`).
  - Assets are not stored in the DB (files + hash only).
- API / interfaces:
  - CLI: `app content check [--root PATH] [--strict]`, `app content import [--root PATH] [--dry-run]`.
  - HTTP: `GET /api/v1/courses`, `GET /api/v1/courses/{slug}/graph` (shapes above).
  - Python: `app.content.params.sample/render`, `app.content.hashing.split_item` — reused by 004–007.

## Edge cases
- Cycle that only exists across courses (physics → maths → physics): caught; message shows qualified ids.
- Cross-course prereq to a course not in the tree (or retired): missing-reference error.
- Concept moved to another chapter of the same course: same slug → updated `chapter_id`, no new row. Moved to another
  course: treated as retire + create (identity is per course); validator warns when a retired slug reappears elsewhere.
- KP renumbered/reordered: positions change, ids stay; no version bump.
- Item edited (prompt typo) → version 2; author wants a genuinely different question → new id, old one retired.
- Two items with the same slug in different KPs of one concept → error (item slugs are per concept).
- Params whose constraints are rarely satisfiable (< 95% of 50 seeds) → error; constraints never satisfiable → error.
- `sigfig` mode with a value that is 0 for some seed → error naming the seed.
- `exact` numeric answer that is an infinite decimal (1/3) → error suggesting `sigfig` or `tolerance`.
- Code solution with an infinite loop → timeout error, check continues with other items.
- Unicode/LaTeX in YAML: prompts are block scalars (`|`); README tells authors to quote strings containing `:` or `#`.
- Image referenced as `../other-concept/img/x.svg` or an absolute/URL path → error (must stay in the concept folder;
  external URLs except YouTube links are disallowed).
- Import against an empty DB, then deleting the whole `content/python-basics/` folder → course and all children
  retired, nothing deleted.
- Import interrupted (network drop to Supabase) → transaction rolls back; re-run is safe.

## Out of scope
- Any Learn/Practice UI, Markdown/KaTeX/Mermaid rendering, image path rewriting (spec 004); graph UI (005).
- Grading answers (unit conversion, sig-fig checking of student input, SymPy equivalence, Pyodide) — spec 006. This
  spec only validates that the *authored* specs are coherent.
- KaTeX/Mermaid syntax linting in the validator.
- Content authoring UI, translations (format leaves room: all text fields are plain strings today), per-school content.
- Full pilot content (6–8 concepts per subject) — spec 013. Subject-teacher review.
- Item-level analytics, attempt references (005+).
- Importing a single course (`--course`); import always processes the whole tree.

## Deviations (recorded during the build)
- Expressions are parsed by a whitelisted Python `ast` walk that builds SymPy objects directly, not `sympy.parse_expr`
  (which `eval`s internally). Same syntax for authors (`^` is a power); stricter and never evaluates code.
- Stdout code tests: the harness feeds `stdin`, calls `entry(*args)` (`args` default `[]`) and compares printed lines
  (trailing whitespace ignored). `entry` is therefore required for stdout tasks too.
- `content_hash` covers authored content only (not position or parent). Derived columns (`public`/`answer`, position,
  `chapter_id`, `kp_id`, `kind`) are refreshed without a version bump when they differ; such rows count as "updated"
  without a `(vN)` label.
- Link rows are diffed (delete stale, insert new, update weights) rather than deleted and re-inserted, so an unchanged
  import writes nothing at all.
- "A retired slug reappears in another course" needs the database, so the importer reports it as a warning line;
  the offline validator can't.
- Extra validator checks beyond the spec: duplicate YAML keys, the correct MCQ option can't carry a misconception,
  SVGs with scripts/event handlers are rejected (they are served same-origin), code may import only standard-library
  modules outside an I/O denylist, and `exact` / `sigfig` / `tolerance` fields that don't apply to the mode are errors.
- Every content table has `position` (spec listed it for most); misconceptions keep their file order.
- Imports take a transaction-scoped advisory lock so two concurrent imports can't interleave.

## Verification (end-to-end)
- [x] `make content-check` passes on the sample (3 courses, 9 concepts) and is part of `make check`; output pasted.
- [x] `tests/test_content_schema.py`: valid fixture parses; unknown key, bad slug, wrong enum each fail with the path.
- [x] `tests/test_content_validate.py`: one minimal broken fixture per rule (cycle incl. cross-course, missing
      misconception, key prereq not a direct prereq, 2 KPs, pool weight 5, MCQ with two correct, sigfig without
      sigfigs, unsatisfiable constraints, division by zero for some seed, oversize/escaping image, unparsable unit) —
      each asserts the exact message line; plus warnings (unused param, pool < 8, unreferenced .md).
- [x] `tests/test_content_params.py`: `sample(item, 42)` is identical across runs (golden values); constraints honoured
      over 1,000 seeds; `render` formatting rules; malicious expressions (`__import__('os')`, attribute access) rejected.
- [x] `tests/test_content_code_runner.py`: passing solution, failing test (index reported), exception, timeout, stdout task.
- [x] `tests/test_content_split.py`: for every sample item, `public` contains no `correct`, `misconception`,
      `solution`, `derived`, `constraints`, `explanation` or hidden test, and `ItemPublic.from_row` output equals
      `public` only.
- [x] `tests/test_content_import_db.py` (`-m db`): import sample → counts match; import again → all unchanged and every
      `updated_at` identical; edit one prompt → that item `version == 2`, nothing else changes; remove an item → it is
      retired; restore it → un-retired; a validation error → zero rows written; `--dry-run` → zero rows written;
      forced failure mid-import → rollback.
- [x] `tests/test_courses_api_db.py` (`-m db`): student and teacher from different schools both get the same 3 courses;
      graph for `physics-9-10` has 3 concepts, the edges, and `maths-9-10/linear-equations-two-variables` in `external`;
      no response contains the keys listed above; unknown slug → 404; unauthenticated → 401.
- [x] `tests/test_route_scoping.py` passes with the two routes in `GLOBAL_CONTENT` only; `test_rls_db.py` covers all
      new tables.
- [x] Frontend: `pnpm build` output contains `content-assets/physics-9-10/…/img/*.svg` and no `.yaml`/`.md`; vitest for
      the plugin's allowlist.
- [ ] Manual: `make migrate && make content-import` against the dev DB (paste output), run again (all unchanged),
      `curl` both endpoints with a teacher token and paste trimmed responses.
- [x] `cd backend && uv run mypy` and `cd frontend && pnpm typecheck` clean; `make check` green.
