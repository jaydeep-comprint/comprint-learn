# Plan: Spec 013, PR 1 (`feat/013-pilot-content-maths`)

## Context
Spec 013 (`docs/specs/013-pilot-content.md`) grows each pilot course from 3 to 8 concepts and adds a
review pack so subject teachers can check content without the repo. It ships as three PRs. **This session
does PR 1 only** (user decision): the tooling (review pack, strict `content-check`, pilot quality test,
review tracking doc, doc updates) plus the maths course. Physics and Python each get a fresh session.
New concepts are authored **one subagent per concept** (user decision); I check each with the strict
validator and read it before committing.

Uncommitted doc edits already on `main` (`docs/PRD.md`, `docs/ROADMAP.md`, the spec file) go onto the
branch as the first commit. `docs/drafts/` is unrelated and stays untracked.

## Steps

### 0. Branch
`git switch -c feat/013-pilot-content-maths`; commit the spec + PRD/ROADMAP edits ("Spec 013: pilot content").

### 1. Review pack (TDD)
- `backend/app/grading/numeric.py`: rename `_display` → `display_value` (one call site, line 194). No behaviour change.
- `backend/app/content/review_pack.py` (new), pure: `build_review_pack(bundle, course_id, *, seeds) -> str`.
  - Builds a JSON document per course: header (title, counts, generated-at, sha passed in, seed note per
    decision 9), misconceptions, chapters → concepts (title, summary, prereqs+weights, intro, misconception
    check, KPs with key prereqs, worked example, items; then practice).
  - Per item: reuse `hashing.split_item(item)` to get the stored `answer` dict (same as the importer), then
    for param items seeds 1…N via `params.sample` + `params.render` for prompt, step prompts and explanation;
    numeric answer via `display_value` (+ unit); expression via `expression.answer_expr` + `sympy.latex`;
    MCQ options with correct flag and misconception titles; multistep per step; code: starter, solution,
    every test with expected, time limit. Fixed items rendered once. Params/constraints/derived as written.
  - Images: every `image_refs` in Markdown replaced by `data:` URIs (resolved under the concept dir), done in
    the JSON text, not HTML.
  - Template: string constant (or `review_pack.html` beside it) with the JSON in
    `<script type="application/json">` escaped `<`→`<`, `>`→`>`, `&`→`&`. Client JS: pinned
    jsDelivr `katex@0.19.1` (+CSS, auto-render not needed: extract `$…$`/`$$…$$` first, render with
    `katex.renderToString`, restore after `marked@16.4.2` parse), marked `html` renderer overridden to
    escape; `mermaid@12.2.0` ESM loaded only if a mermaid block exists. DOM built with `textContent`/
    `createElement` except the marked+KaTeX output. Print CSS: `break-before: page` per concept and a
    "Reviewer notes" box.
  - Deterministic: sorted, no dict-order surprises; only header date/sha vary.
- `backend/app/cli.py`: `@content_app.command("review-pack")` with `--root`, `--course` (repeatable),
  `--out` (default `DEFAULT_CONTENT_ROOT.parent / "review-packs"`), `--seeds 3`. Uses `check_content(root,
  strict=False)`, prints issues, exit 1 on errors with nothing written; sha via `git -C <root> rev-parse
  --short HEAD` (omitted on failure); unknown `--course` → error.
- `backend/tests/test_content_review_pack.py` (from `tests/content_fixtures.py`): answers + hidden tests
  present; 3 seeds for a param item, once for a fixed one; MCQ correct + misconception titles; image inlined;
  `<script>` in a prompt stays inside the JSON block (exactly one `<script type="application/json">`, no extra
  script tag); CLI refuses a broken tree and writes nothing; same output twice ignoring header. CLI test via
  typer `CliRunner` like `tests/test_cli.py`.
- `Makefile`: `review-pack` target; `content-check` adds `--strict`. `.gitignore`: `/review-packs/`.

### 2. Quality bar test + tracking doc
- `backend/tests/test_pilot_content.py`: loads `DEFAULT_CONTENT_ROOT`; `PILOT_COURSES = {"maths-9-10": 8}`
  (physics/Python added in their PRs); `LEGACY` = the 9 existing concept ids. Asserts per spec table: KP count
  (new 4 / legacy 3), pool weight ≥ 10, ≥ 2 quick checks per KP, MCQ share ≤ 30% by count, practice count
  (new 2–3, legacy exactly 2; maths/physics practice = param multistep), new-item `expected_minutes` ranges
  (by type), every MCQ has a tagged distractor, new concepts with prereqs have a KP with non-empty
  `key_prereqs`, existing concepts' prereqs unchanged (snapshot of current edges). "New item" = id not in a
  hard-coded legacy item-id snapshot taken now (so minutes rules skip existing items).
- `docs/content-review.md`: checklist + 24 rows, all `draft`.
- `content/README.md`: review pack, strict `make content-check`, pilot bar. `content/CLAUDE.md` unchanged.

### 3. Maths content
- **Syllabus check first** (decision 5): confirm x³+y³+z³−3xyz in Class 9 Polynomials and the quadratic formula
  in rationalised Class 10 NCERT (WebSearch); note any swap in the PR.
- `course.yaml` chapters → `[polynomials, linear-equations, pair-of-linear-equations, quadratic-equations]`;
  new folders `00-polynomials/`, `03-quadratic-equations/` with `chapter.yaml` (grade 9 / 10).
- `misconceptions.yaml`: add `square-of-sum`, `degree-counts-terms`, `factor-sign`, `divides-by-variable`,
  `discriminant-sign` (+ others as authored).
- I write `polynomials-basics` myself as the model concept, run `content check --strict` + the pilot test.
- Then 4 subagents in parallel (`general-purpose`), one per concept (`algebraic-identities`,
  `factorisation-of-polynomials`, `quadratic-equations-solving`, `nature-of-roots`). Brief: spec table row,
  quality bar, `content/README.md`, the model concept path, misconception ids available (they may propose
  new ones in a separate note; I add them to `misconceptions.yaml` to avoid edit conflicts), "write only
  inside your concept folder", run `uv run app content check --root ../content --strict` and
  `uv run pytest tests/test_pilot_content.py` until clean.
- Top-ups for the 3 existing maths concepts (I do these): +2 weight per KP (one new param quick check each,
  new ids), and one new param multistep practice item each. No edits to existing items.
- I read every concept file before committing; one commit per concept.

### 4. DB tests the maths content breaks (decision 11)
- `test_courses_api_db.py`: maths counts → derive from `load(DEFAULT_CONTENT_ROOT)` (physics/python stay
  until their PRs, but derive them too so later PRs don't touch it again).
- `test_placement_db.py`: covered-chapter flags (line ~165) → look up by chapter id; "every maths outline concept
  placed" (~245) → only concepts in the covered range; counts (~257) by id.
- `test_learn_api_db.py`: physics outline untouched in this PR; check for maths order assumptions.
- Measure `make test-db` time before/after; if notably slower, cache the `world()` import once per session
  (decision 12).

### 5. Self-review gate
- `cd backend && uv run app content check --root ../content --strict` clean; `make check`; `make test-db`
  (run alone, shared DB); `alembic current` on the dev DB, then `make content-import ARGS=--dry-run`,
  `make content-import` twice (second: no changes).
- `make review-pack`; open `review-packs/maths-9-10.html` (file://, so Chrome may work; otherwise the user
  checks) — KaTeX, SVGs, answers, print preview; screenshot one concept.
- Independent AI review: fresh `general-purpose` subagent gets only the pack path, the maths concept folders and
  the checklist from `docs/content-review.md`; solves every item at seed 1. Fix findings; the 8 maths rows →
  `ai-reviewed` with today's date.
- `reviewer` subagent on the diff vs spec, then `/ship`.

## Verification
- `cd backend && uv run pytest tests/test_content_review_pack.py tests/test_pilot_content.py tests/test_content_validate.py tests/test_cli.py`
- `cd backend && uv run mypy`, `make check`, `make test-db`
- `content check --strict` → `content OK: 3 courses, 14 concepts, … items` with no warnings
- `make review-pack` writes three HTML files; maths one inspected
- Browser check by the user (Chrome can't reach localhost): one new maths concept Learn → KP → practice;
  knowledge graph with 8 maths nodes at desktop + phone width; placement chapter list and assignment dialog
  show the new chapters.
