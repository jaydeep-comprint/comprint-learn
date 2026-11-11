# Content: author's guide

Courses are authored here as YAML + Markdown, reviewed in git, validated offline and imported into
Postgres. Content is global: every school sees the same courses.

```sh
make content-check                    # validate everything, strict: warnings fail too (part of make check)
cd backend && uv run app content check --root ../content   # the same, warnings only reported
make content-import ARGS=--dry-run    # show what would change in DATABASE_URL
make content-import                   # import (one transaction, safe to repeat)
make review-pack                      # review-packs/<course>.html: every item with answers, for reviewers
```

## Pilot quality bar (spec 013)

`backend/tests/test_pilot_content.py` checks the pilot courses on top of the validator. Concepts added since
spec 013 need **exactly 4 KPs**; the 9 original concepts keep 3 (a 4th KP would re-open learned concepts).
Every KP: pool weight **≥ 10**, **≥ 2 quick checks** (numeric / expression / mcq: brush-ups, quizzes and
placement draw only these), MCQ ≤ 30% of the pool. Practice: 2–3 items (the original concepts exactly 2);
maths and physics use param `multistep`, Python `code`. New items' `expected_minutes`: quick checks 0.5–2,
multi-step 4–10, code 2–5 inside a KP and 5–15 as practice. Every MCQ has a distractor tagged with a
misconception. New concepts with prerequisites have at least one KP with `key_prereqs`. Never add a
prerequisite to an existing concept (it would change frontiers of students who started it).

Python has no free-text answer type: "what does this print" questions with a number use `numeric`; text
output uses `mcq` (within the 30% cap) or a small `code` task.

**Review**: `make review-pack` renders each course to one self-contained HTML file (answers, sample seeds,
hidden tests) that can be printed or emailed to a subject teacher. It is gitignored and must never reach
students. Review status per concept is tracked in [docs/content-review.md](../docs/content-review.md).

## Layout

```
content/
  maths-9-10/                       # folder = course id
    course.yaml                     # id, title, subject, chapters: [ordered chapter ids]
    misconceptions.yaml             # [{id, title, description}]
    01-linear-equations/            # NN-<chapter id>; NN is only for humans, order comes from course.yaml
      chapter.yaml                  # id, title, grade (9 | 10; omit for Python), concepts: [ordered ids]
      linear-equations-two-variables/   # folder = concept id
        concept.yaml                # metadata, prereqs, KPs + item pools, practice, misconception check
        intro.md                    # Learn-layer intro
        kp-1-worked.md              # one worked example per KP (any name; referenced from concept.yaml)
        img/line-graph.svg          # images, referenced from Markdown as img/line-graph.svg
```

- One course per subject (`maths`, `physics`, `python`), spanning Classes 9–10.
- Every folder and `.md` file must be referenced. A listed id with no folder is an error; an unlisted
  folder or unreferenced `.md` is a warning.

## Ids

Every course, chapter, concept, KP, item and misconception has a slug id: lowercase letters, digits and
single hyphens (`speed-and-velocity`), at most 60 characters, **stable forever**. Students' attempts point
at these ids.

- Unique: course ids globally; chapter, concept and misconception ids within the course; KP and item ids
  within the concept (an item id can't be reused in another KP of the same concept).
- References: a bare concept id inside a course (`speed-and-velocity`), `<course>/<concept>` across
  courses (`maths-9-10/linear-equations-two-variables`). Prerequisites may cross courses.

## `concept.yaml`

```yaml
id: acceleration
title: Acceleration
summary: How quickly velocity changes, and in which direction.   # one line, <= 160 chars
prereqs:
  - {concept: speed-and-velocity, weight: 0.7}       # weight: how much of the prereq is practised here, 0 < w <= 1
  - {concept: maths-9-10/linear-equations-two-variables, weight: 0.2}
intro: intro.md
misconception_check:            # exactly one item: type mcq, no params, bloom remember | understand (Learn layer)
  id: check
  type: mcq
  ...
kps:                            # 3-4 knowledge points, in order
  - id: kp1
    title: Acceleration as rate of change of velocity
    worked_example: kp-1-worked.md
    key_prereqs: [speed-and-velocity]   # must be direct prereqs of this concept; may be empty
    items: [...]                        # the KP's question pool
practice:                       # >= 1 item, type multistep or code
  - ...
```

**Practice step (spec 006)**: every lesson ends with Practice: one item drawn from `practice:` per attempt.
A concept is learned only when every KP is passed *and* a practice attempt is passed. A failed code task is
served again (the editor keeps the student's code); a failed multi-step problem draws the next item (or the same
one with new numbers). Give each concept 1–3 practice items; param multi-step items are best.

**Pool size**: a fixed item counts 1, an item with `params` counts 2. Each KP pool needs at least 6 (error)
and should have at least 8 (warning). Keep MCQs to at most 30% of a pool (warning).

**KP practice** serves every type one at a time (spec 006: `multistep` and `code` too; a multi-step item
counts as one question). Each KP needs at least 2 questions (error), at least 5 fixed ones if none has params
(error), and a weight of at least 5 (warning), so a 5-question session never runs out of new questions.
**Brush-up reviews** of a prerequisite serve only `numeric`, `expression` and `mcq` questions (quick checks),
so every KP needs at least one of those (error). Write explanations with `{{name}}` placeholders freely: they're
rendered with the student's numbers after each answer.

**Misconception check**: one MCQ with fixed numbers (`type: mcq`, no `params`; both errors). Students get one try
in the lesson; afterwards they see the correct option, the `explanation`, and, for a tagged wrong option, the
misconception's `title` as "Common mix-up: …" (write titles for students; `description` is for teachers only).

## Items

```yaml
- id: kp2-q3
  type: numeric                 # numeric | expression | mcq | multistep | code
  bloom: apply                  # remember | understand | apply | analyze | evaluate | create
  expected_minutes: 2           # 0.5-30 in steps of 0.5 (XP is based on it)
  prompt: |                     # Markdown + KaTeX ($...$); {{name}} for params / derived values
    A car speeds up from {{u}} m/s to {{v}} m/s in {{t}} s. Find its acceleration.
  params:                       # optional random numbers
    u: {min: 0, max: 10, step: 2}       # inclusive range (decimals are fine: {min: 0.5, max: 2, step: 0.5})
    t: {choices: [2, 4, 5]}
    v: {min: 12, max: 30, step: 2}
  constraints: ["v > u"]        # optional conditions; must hold on >= 95% of seeds
  derived: {a: "(v - u) / t"}   # optional, evaluated in order (may use earlier derived values)
  answer:
    numeric: {value: "a", unit: "m/s^2", mode: sigfig, sigfigs: 2}
  explanation: |                # optional; shown only after an attempt
    a = (v − u) / t = ({{v}} − {{u}}) / {{t}} = {{a}} m/s².
```

- `{{name}}` must be a param or derived value. In prompts, integers print plainly and other values with up
  to 4 significant figures, no trailing zeros.
- Expressions (`constraints`, `derived`, answer `value`s) use `+ - * / ^ ** %`, comparisons
  (`< <= > >= == !=`), `and` / `or` / `not`, numbers, your names, `pi`, `E` and these functions only:
  `sqrt sin cos tan asin acos atan exp log ln abs floor ceiling Min Max`. Write `2*x`, not `2x`.
- Param items must give at least 5 different prompts over 50 seeds, and every derived/answer value must be
  a finite real number for every seed (no division by zero).
- Code items can't have params.

### Answer specs

| `type` | `answer:` | Rules |
|---|---|---|
| `numeric` | `numeric: {value, unit?, mode, sigfigs?, rel_tol?, abs_tol?, sci_notation?}` | `value`: number or expression. `unit` e.g. `m`, `km/h`, `m/s^2`, `N`, `kJ` (omit if dimensionless). Students type their own unit beside the number: any unit of the same quantity is converted and accepted (`0.5 km` for `500 m`), with aliases `kmph`/`kph`/`km/hr` → `km/h`, `mps` → `m/s`, `sec(s)` → `s`, `hr(s)` → `h`, `kgs` → `kg`, `Ω` → `ohm`, `²`/`³`, and a space or `·` between units. Units are case-sensitive (`ms` is milliseconds). Sig figs and tolerance apply in the student's unit; in `exact` mode, the value must be a finite decimal in that unit (else "Give it in {unit}"). `mode: exact` → value must be an integer or finite decimal for every seed (1/3 isn't; use `sigfig`/`tolerance`). `mode: sigfig` → `sigfigs` 1–6, value never 0. `mode: tolerance` → exactly one of `rel_tol` (0–0.2) or `abs_tol` (> 0) |
| `expression` | `expression: {value, variables: [x, ...], sympy_mode: exact \| equivalent \| simplified}` | `value` may use only `variables` (and params/derived, substituted as numbers) |
| `mcq` | `mcq: {options: [{id, text, correct?, misconception?}], shuffle?: true}` | 2–5 options with ids `a`–`e`, exactly one `correct: true`, at least one distractor tagged with a `misconception` id from the course's `misconceptions.yaml`; the correct option has none. Use sparingly |
| `multistep` | `multistep: {steps: [{prompt, answer: {numeric \| expression \| mcq: ...}}]}` | 2–10 steps; steps share the item's params/derived. Students answer one step at a time (one try each, then the correct value is shown); the item is correct when ≥ 75% of steps are correct, the last one included |
| `code` | `code: {entry, starter, solution, tests: [...], time_limit_ms?: 2000}` | `entry`: the function both `starter` and `solution` define. ≥ 3 tests, ≥ 1 `visible: true`. A test is `{args: [...], expected: <JSON>}` (return value) or `{stdin?: "...", expected_stdout: "..."}` (printed output; `entry(*args)` is called with stdin fed in, lines compared ignoring trailing spaces). Standard library only, no file/network/OS modules. `time_limit_ms` ≤ 5000 (code runs in the student's browser, in Pyodide). The checker runs `solution` against every test, using the same comparison the server uses for students (floats close, lists/dicts deep, `True` ≠ `1`) |

**Never to the client**: the answer spec, params/constraints/derived, MCQ correctness and misconception tags,
explanations, the code `solution` and hidden tests' expected values stay on the server. Visible code tests are
shown to students. Hidden tests' *inputs* (`args` / `stdin`) are sent, because the browser runs the code; their
`expected` / `expected_stdout` never are. The `solution` is shown after a KP code question is answered, and after
a practice task is passed.

## Markdown and images

- Images live in the concept's `img/` folder: `![alt](img/file.svg)`; `.svg .png .webp .jpg`, at most
  500 KB, file names `A-Z a-z 0-9 . _ -`, no symlinks. Every file in `img/` ships to the CDN, referenced or not.
- SVGs are served from the app's own origin, so they may not contain scripts, event handlers (`onload=`),
  links (`<a>`, or any `href` other than `#fragment`), `<animate>`/`<set>`, embedded HTML, `data:` images or
  character entities (`&#176;`: type the character `°` instead). Inkscape and matplotlib exports often need a
  quick clean-up.
- External links: https YouTube links only.

## YAML tips

- Use block scalars (`|`) for prompts, Markdown and code.
- Quote strings that contain `:` or `#`, or start with `{`, `[`, `*`, `&`, `!`, `%` or `@`.
- `yes`, `no`, `on`, `off` unquoted become true/false; quote them in text.
- Duplicate keys are errors.

## Editing vs retiring

- Import matches rows by id. Editing content (a prompt typo, a better worked example) bumps that row's
  `version`; reordering or moving a concept between chapters of a course does not.
- **Changing what a question asks → give it a new id** and delete the old one. Removed content is
  retired, never deleted, so old attempts keep pointing at what the student actually saw. Bringing an id
  back un-retires it.
- Moving a concept to another course is a retire + create (new identity; progress doesn't follow).
