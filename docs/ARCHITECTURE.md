# Architecture

> Stack and key decisions. Record the *why*.

## Stack
| Layer | Choice | Why |
|---|---|---|
| Frontend | React + TypeScript + Vite, TanStack Query, React Router, Tailwind | Team choice (React); fast dev loop |
| Maths rendering | KaTeX (via remark-math / rehype-katex) | Fast and well supported |
| Diagrams | Mermaid + static SVG/PNG in content | Can be written as text in content files |
| Knowledge graph UI | React Flow (`@xyflow/react`) | Interactive DAG with custom nodes for mastery colours |
| Code editor | CodeMirror 6 | Lighter than Monaco, works on mobile |
| Python execution | **Pyodide in a Web Worker** (in-browser), pinned (`frontend/src/features/code/protocol.ts`) and loaded from jsDelivr; CodeMirror 6 editor (lazy-loaded) | No server sandbox needed; safe and free to run |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic | Team choice (Python); typed |
| Database | PostgreSQL (hosted Supabase, Session pooler, port 5432) | Relational data (orgs/classes) + JSONB for content. Test DB = a separate Supabase project (`TEST_DATABASE_URL`), used only by `make test-db` and CI |
| Auth | **Supabase Auth** (same project as the DB). FastAPI verifies its JWTs against the project JWKS (`app/core/auth.py`); our `app_user.id` = the auth user id. Teachers are invited by email; students get teacher-created accounts with a synthetic, never-emailed auth email | Don't build password, reset and invite flows ourselves; one free-tier project for DB + auth |
| Maths answer checking | SymPy (server side, `app/grading/`): student expressions go through the safe AST walker, never `parse_expr`; `simplify` runs in a time-limited process pool (1 s, numeric fallback) | Checks equivalent expressions and numbers with tolerance and units |
| Spaced repetition | `fsrs` (py-fsrs 6.3), one module-level `Scheduler` in `app/services/srs.py` (retention 0.9, no learning steps, no fuzzing) | Modern scheduler with fewer reviews than SM-2 |
| AI | Tutor (spec 009): **DeepSeek** (`deepseek-flash`) over its OpenAI-compatible API with `httpx`, JSON mode, automatic prefix caching, a server-side answer guard (`app/ai/guard.py`) on every reply (decided Nov 2026; first specified as Claude Haiku). Teacher summaries (spec 011): DeepSeek `deepseek-v4-pro` on the same client and key, JSON mode, a server-side citation guard (decided Nov 2026; first planned as Claude Sonnet). All model calls only in `backend/app/ai/` | Low cost per student; better reasoning where needed |
| Python tooling | uv, ruff, mypy, pytest | Fast and standard |
| JS tooling | pnpm, eslint, prettier, vitest, Playwright (e2e) | Standard |
| Hosting | Free tiers: Supabase (DB + Auth), Cloudflare Pages or Vercel (SPA), Render free or Fly.io/Railway (~$5/mo) for the API, GitHub Actions, Sentry free | POC budget ~$50 total (see Cost budget) |

## Cost budget (POC, ~$50 total)
| Item | Plan | Est. cost |
|---|---|---|
| Database + auth | Supabase free (2 projects: dev + test). Pauses after ~1 week idle; restore in the dashboard | $0 |
| Frontend | Cloudflare Pages / Vercel free | $0 |
| API | Render free (sleeps; ~30–60 s cold start) for demos, or Fly.io/Railway when it must stay awake | $0–5 / month |
| AI tutor | DeepSeek `deepseek-flash` (check current per-token prices). ~3k in + 300 out per message, most of the input a cached prefix; the eval and `tutor_message` log tokens per request | low; measure in the pilot |
| Teacher summaries | DeepSeek `deepseek-v4-pro` (check current prices). ~6k in + 1–3k out each, logged per row in `teacher_summary`; capped at 10/teacher and 50/school a day | well under $1 / month |
| Domain (optional) | | ~$10 / year |
Guards: a spend limit / prepaid balance in the provider console (e.g. $20), a per-student daily tutor cap (e.g. 20 messages), prompt caching on the
tutor's system prompt + item content, and logging token usage per request (`tutor_message`).

## Repo layout
```
backend/      FastAPI app (app/api, app/models, app/services, app/ai), alembic/, tests/
frontend/     React SPA (src/features/<feature>, src/components, src/lib)
content/      Pre-authored courses (content-as-code), validated + imported by a CLI
docs/         PRD, architecture, roadmap, specs, plans
```

## Domain model (core tables)
- **Tenancy**: `organization` (school, unique `code`) → `app_user` (role: teacher | student, `is_admin` for teachers only, status
  invited | active | deactivated, org_id) → `school_class` → `enrollment`; `class_teacher` links co-teachers (no extra access).
  Link tables carry `org_id` with composite FKs to `(id, org_id)`, so the DB rejects cross-school links. Students store a
  display name and username only (no email).
- **Content** (global: platform-owned, the same for every school; **no `org_id`**, not `TenantMixin`, read without
  `OrgScope`; RLS still on). Imported from `content/` by `app content import`: each row has its authored `slug`
  (the identity), `content_hash` + `version` (+1 when the authored content changes), `position`, and `retired_at`
  (removed content is retired, never deleted).
  - `course` (one active per subject) → `chapter` (`grade` 9/10) → `concept` (node, `intro_md`) → `knowledge_point`
    (3–4 per concept, ordered; `worked_example_md`) → `item`; `misconception` per course. `concept.asset_path`
    (`<course>/<chapter-folder>/<concept>`, derived on import) is where its images are served:
    `/content-assets/<asset_path>/img/...`.
  - `concept_prereq` (edge; may cross courses) has `encompassing_weight` (0–1: how much of the prerequisite is practised
    inside the concept). `kp_key_prereq` links a KP to the concept(s) that step really depends on, used for remediation.
  - `item` has `kind` (kp_question | practice | misconception_check), a `bloom_level` tag, `type` (numeric | expression |
    mcq | multistep | code), `expected_minutes`, `has_params`, and two JSON documents: **`public`** (all a client may
    ever see: prompt template, MCQ option texts, step prompts, unit, code starter + visible tests) and **`answer`**
    (answer spec per decision 10, `params`/`constraints`/`derived`, MCQ correct id + misconception map, explanation,
    code solution + hidden tests). API item shapes are built only from `public` (`ItemPublic.from_row`).
  - Randomised numbers: `app.content.params.sample(item, seed)` is the one implementation that derives an item's
    numbers (and so its answer) from an attempt's seed.
- **Learning state** (tenant-owned: `TenantMixin`, composite FK `(student_id, org_id)` → `app_user`):
  - `attempt`: one row per answer submitted, with the result, time taken, hints used and the parameter seed.
    `context` says where (`learn` in spec 004; `kp` and `remediation` in 005; `practice` in 006; later specs
    add more) and `item_version` which version was answered. The Learn check is one try: a partial unique index
    allows one `learn` attempt per student × item. KP, remediation and practice answers belong to a
    `practice_session` at a `position`; a multi-step item stores one row per answered `step` (0 otherwise), and
    `(session_id, position, step)` is unique (a CHECK ties `session_id` to those contexts). `response` is
    `{raw}` plus `unit` for numeric answers with a unit (MCQ: `{option, order}` with authored ids; code:
    `{code, outputs, verdicts}`, one output per test in authored order: `{value}` | `{stdout}` | `{error}` |
    `{timeout}`).
  - `lesson_progress` (spec 004): per student × concept, the Learn lesson's `seen_steps`, `last_step` (resume) and
    `finished_at` (set once, when the check is answered and every current `kp:` step is seen). Since spec 005 it
    is for analytics only ("Learn layer read") and gates nothing.
  - `study_time` (spec 004): append-only active seconds per student × concept × step (1–600 per row, ids only),
    for the "time in practice vs theory" metric. `activity` is `learn` (intro/check/worked examples) or
    `practice` (spec 005: `kpq:` question steps, and `remediation` reviews logged against the prerequisite;
    spec 006: the `practice` step).
  - `concept_state` (spec 005): per student × concept, stores only `in_progress` (created on the lesson's first
    progress post) and `learned` (every active KP passed **and**, since spec 006, a passed practice session for the
    concept when it has active practice items; concepts learned before stay learned, and a relearn after a failed
    review needs only the KPs again because the earlier practice pass still counts), plus `source`
    (lesson | diagnostic | teacher),
    `learned_at` and `relearn_count`. `ready` (every direct prerequisite learned) and `locked` are computed
    (`app/services/frontier.py`). **"Learned" is the gate** that opens dependants (the knowledge frontier); a
    started concept never re-locks.
  - `kp_progress` (spec 005): per student × KP, status (not started | in progress | passed | failed), `fail_count`,
    `passed_at`, `failed_at` and `reopen_at` (next 00:00 Asia/Kolkata). A failed KP reopens on read: its
    remediations are resolved and the cooldown is over, or the student passed a KP in another concept or a
    remediation review since.
  - `practice_session` (spec 005; 007 may reuse it): one try at a KP's questions (`kind = kp`), one remediation
    review (`kind = remediation`) or, since spec 006, one practice item for a concept (`kind = practice`,
    `concept_id`; it passes or fails with that item), with status (active | passed | failed) and the question being shown
    (`current_item_id`, `current_seed`, `current_position`, `current_served_at`), stored before it's returned so
    reloads get the same question. Partial unique indexes allow one active session per student × KP, per
    remediation and per student × concept (practice). Spec 008 awards XP when an answer ends a session.
  - `remediation` (spec 005): created by the 2nd (and later) fail of a KP, one per active key prerequisite
    (`kp_key_prereq`): `review_due` (a 3–5 question review) if the prerequisite is learned, else `relearn`; a failed
    review sends the prerequisite back to in progress (KPs reset, history kept). Resolved when the review passes or
    the prerequisite is learned again.
  - `review_card` (spec 007): FSRS state per student × **concept** (stability, difficulty, `due`, `last_review`,
    reps/lapses), always in FSRS's Review state; `consecutive_fails`, implicit `credit` (0–1) and `due_reason`
    (schedule | quiz_miss). Created when a concept with gradable KP items is learned (`frontier.mark_learned` →
    `srs.on_learned`); a relearn reviews it Good again. Migration 0008 backfilled cards from `learned_at`.
  - `review_log` (spec 007): append-only, one row per card change with its `source` (learned, relearned, review,
    brushup, implicit, quiz_miss, backfill), the rating and before/after values. The daily cap counts today's
    (IST) `review` rows with `due_reason = schedule`.
  - Reviews are `practice_session` kind `review` (`concept_id`; one active per student × concept); a quiz is one
    session of kind `quiz` (`quiz_id`). `xp_event` is unique on `(session_id, subject)`: a quiz writes one event
    per subject.
  - `xp_event` (spec 008): an append-only ledger, one row per session ended by an answer (unique `session_id`;
    amount may be 0 or negative) with the reason, concept, subject, IST `day`, grade and the rule's inputs
    (`base_minutes`, `answered`, `rushed_count`, `hints`). Sessions closed as a side effect, previews and "Practise
    again" earn nothing. Spec 007 adds review and quiz reasons.
  - `xp_day` (spec 008): per student × IST date × subject: net `xp`, the `goal` frozen at the day's first XP (raised
    the same day, never lowered; null = no class for that subject) and `met_at` (once met, stays met). A day is met
    when it has a goal row and every goal row is met; the streak is computed on read.
  - `student_goal` (spec 008): a student's own daily goal per subject (≥ the class goal). `school_class` has
    `daily_goal` (5–60, default 15) and `leaderboard_enabled` (off by default).
  - `quiz` (spec 007): per student, created `pending` at an XP mark (`xp_mark`; `next_mark` set on finish or
    cancel), then active (`started_at`, `deadline`) and finished (`correct` / `total`); at most one pending or
    active. `quiz_item`: its questions (position, item, concept, seed), chosen at start.
  - `assignment` (spec 010): a teacher target for one class: `due_date`, optional `note` (≤ 200), `all_students`,
    `created_by`, soft `deleted_at`. `assignment_concept` holds its 1–10 target concepts (`position`, content FK) and
    `assignment_student` the chosen students (rows only when `all_students` is false); both cascade from
    `assignment`. Per-student statuses (done early / on time / late, overdue, in progress, not started) and the
    Focus path are computed on read (`app/services/assignments.py`), never stored. Targets outside the current class
    course (retired, or after a subject change) are ignored.
  - `diagnostic_session`: per-topic evidence for placement.
- **AI** (spec 009, tenant-owned):
  - `tutor_session`: one thread per question shown, unique `(practice_session_id, position, item_id, seed)` (nulls
    not distinct), with `item_version`, the charged `hints_used` (0–3) and `chat_count`. A new session or a swapped
    item starts a new thread with fresh caps.
  - `tutor_message`: one row per student request (`role = student`; a hint request has null `text`) and one per
    tutor reply, with `kind` (hint | chat), `mode` (before | after), `rung`, `category`, `status` (pending | ok |
    guarded | fallback | safety | refused | error | late), `flagged`, tokens (incl. cache read/write), latency,
    the IST `day`, and `purged_at` (text nulled after 180 days by `app tutor purge`). Caps count student rows
    with status pending/ok. `attempt.hints_used` = charged hints on the thread minus those already on earlier rows
    at that position (`services/tutor.hints_for_attempt`).
  - Flow: Tx 1 (advisory lock per student, caps, pending student row) → model call with no transaction open
    (`app/ai/tutor_turn.run_turn`: prompt → model → answer guard → one retry → canned fallback) → Tx 2 (store and
    charge; `late` if the question was answered meanwhile).
  - `teacher_summary` (spec 011): one row per Generate, for a class × window (`7d` | `30d` | `all`) or a class ×
    student (`7d`): status (pending | ok | partial | failed | error), `facts` (the numbered facts and resources
    exactly as sent, students as `{Sn}` pseudonyms), `pseudonyms` (`{S1: student_id}`, never sent), `facts_hash`
    (staleness and the 10-minute cooldown), `content` (the guarded output, still with tokens), `dropped` (guard
    reasons), `created_by`, model, tokens, latency, `calls`, IST `day`. Shared by the school's teachers; names are
    filled in on read from the current roster ("a student no longer in this class" otherwise). Caps: 10 per teacher
    and 50 per school per IST day (pending, ok, partial and failed count; error doesn't).
  - Summary flow (`app/services/teacher_ai.py`): facts from 010's `dashboard.class_snapshot` /
    `student_snapshot` (the same numbers as the cards) plus one query for remediations created in the window
    (`app/ai/teacher_facts.py`) → Tx 1 (advisory lock per school, caps, cooldown, busy, pending row) → model call
    with no transaction open (`app/ai/teacher_turn.run_summary`: prompt → model → citation guard
    `app/ai/teacher_guard.py` → one retry; 180 s wall clock) → Tx 2 (store). Every claim cites fact ids; the guard
    drops uncited claims, numbers or students not in the cited facts, and identity leaks.

## Key decisions
| # | Decision | Reason | Alternatives rejected |
|---|---|---|---|
| 1 | Content is files in `content/` (Markdown + YAML), validated against a schema and imported by `uv run app content import` | Pre-authored fixed courses: reviewable in git, easy for Claude to help write | Authoring UI (out of MVP scope) |
| 2 | Every tenant-owned table has `org_id`; a single FastAPI dependency scopes every query | One choke point for isolation; tested | Separate DB per school (overkill) |
| 3 | **Mastery = knowledge points.** A concept is 3–4 KPs; each KP is a worked example plus 2–5 questions (more after a wrong answer). Failing a KP ends the lesson, and the student retries **later** with new questions. Two fails at the same KP schedule reviews of its key prerequisites. A concept is *learned* when every KP passes. A concept is *ready* (on the knowledge frontier) when all of its prerequisites are learned | Proven by Math Academy (95% first-try pass rate); simple to explain; Bloom stays useful as tags | A mastery score per Bloom level as the gate (rejected Oct 2026; see research doc) |
| 4 | Learn layer = intro + worked examples + one misconception check (Remember/Understand). Practice = KP questions, multi-step problems, code (Apply → Create). Bloom levels are **tags on items**, used for teacher analytics and depth views | Matches the two-layer idea without turning Bloom into a gate | |
| 5 | **XP = item.expected_minutes × performance multiplier**, once per session ended by an answer (perfect 1.2, pass 1.0, partial 0.3 for a failed KP/review with ≥ half right, poor 0). **Rushing**: a failed session with ≥ min(2, answered) wrong answers faster than max(5 s, 15% of expected) costs 0.25 × base (at least 1). Hints reduce it per question (that question's minutes × 1 − 0.25 per hint, spec 009), repeats ("Practise again") earn 0, and there's no "I don't know" button. A **daily goal per subject**: the teacher's class goal (default 15) or the student's own, higher one; one streak across subjects. Progress bars count **concepts learned**, not XP | 1 XP ≈ 1 min of focused work (Math Academy); implementations earn most because they take longest; penalties stop XP farming | Bloom-weighted XP (rejected Oct 2026) |
| 6 | Python runs client-side in Pyodide. The browser runs every test (visible tests, and hidden tests' *inputs*) and sends the outputs; the server compares them with expected values only it keeps (`app/grading/code.py`, the same comparison the content validator uses), so hidden expected values never reach the client. Return values travel as JSON text made by Python, so `1`, `1.0` and `True` stay distinct through JavaScript. The server never runs code and can't detect hand-crafted outputs (stored with the code for later review) | No sandbox infrastructure needed | Judge0 / server sandbox (**v2**, when XP needs to be cheat-proof) |
| 7 | Maths and physics answers are checked **server side** with SymPy | Answers are never sent to the client | Client-side checking (leaks answers) |
| 8 | **The AI tutor never lowers the bar.** It sees only the current item/KP content and the student's attempts. It points to the worked example, the key prerequisite, or an experiment to try; it never gives the answer or the next step. Hints are capped per item and reduce XP, and teachers see hint usage. Text only. Rate-limited per student per day. Measured in the pilot | Math Academy's critique of chat tutors plus Vizuara's "try this experiment" style; cost and DPDP | General chatbot; voice or screen-watching tutor |
| 9 | **Spaced repetition per concept** (FSRS, starting when a concept is learned). A review is 3–5 mixed questions across that concept's KPs, judged on the trend of answers. Passing a review or lesson gives **one-level implicit credit** to prerequisites (`encompassing_weight` × credit, discounted when early), switched off for struggling students. Reviews are interleaved across concepts; daily cap ~5. **Built in spec 007**: a passed KP gives each direct prerequisite w / n (n = the concept's KPs), a passed review or brush-up gives w, practice gives nothing; credit × earliness (0 just after a review, 1 when due) accumulates and fires one `Good` at 1.0. Struggling = the last explicit review failed or a relearn in the last 30 days. A first failed review is `Again` (still learned); a 2nd consecutive failed explicit review relearns (a failed brush-up still relearns at once). The cap is 5 scheduled reviews a day across subjects; quiz misses and brush-ups are outside it | Far fewer reviews than per-item cards; uses the graph | Per-item flashcards; full multi-level FIRe (v2) |
| 10 | **Answer specs by type**: `numeric{value, unit, mode: exact\|sigfig\|tolerance, sigfigs?, rel_tol?, sci_notation?}`, `expression{sympy_mode: exact\|equivalent\|simplified}`, `mcq{options[{text, correct, misconception_id?}]}` (used sparingly), `multistep{steps[]}` (each step has its own spec), `code{tests[]}`. Items can declare `params` for randomised numbers; the server derives answers from the seed | PhysicsGraph's schema; randomised numbers stop answer-sharing in class | Multiple choice as the main format (encourages backward reasoning) |
| 11 | **Mixed timed quiz every ~150 XP**: no notes, covers everything learned so far, tuned for ~80% average score. Every miss becomes a review. **Built in spec 007**: lifetime net XP across subjects; the next mark is lifetime XP at the quiz's end + 150 (never back-to-back); needs 3 learned concepts with gradable items. 10 quick-check KP questions (lowest retrievability first, interleaved by subject), 1.5 min each on one server-enforced timer (+30 s grace for answers in flight), no feedback until the end. A pending quiz blocks new KP and practice sessions (409 `quiz_pending`), not reviews. XP is one event per subject; the ~80% target is measured, not tuned, in the MVP | Retention metric for teachers; retrieval practice | Teacher-scheduled quizzes only |
| 12 | **Placement**: the teacher marks the chapters already covered for the class, then each student takes a short **adaptive diagnostic** within that range. A correct answer adds evidence to the topic and its prerequisites; a wrong answer subtracts from the topic and the topics above it. Topics that only just pass are *conditionally learned* and drop back quickly if the student struggles | Combines how schools work with catching individual gaps | Placement by the teacher only; a full-course diagnostic |
| 13 | **Assignments set priority, never a cap.** A teacher target (concept/chapter + due date) puts it and its missing prerequisites first (Focus Mode). Students can still learn any concept on their frontier. **Built in spec 010**: 1–10 concepts of the class course (a chapter selects all its concepts), due today to +180 days (IST), whole class or chosen students, evaluated live; the student's home card shows the unlearned targets and all unlearned ancestors in outline order, with Next = the first in-progress step (or its due brush-up), else the first ready one | Teacher control without holding back fast students | Teacher-unlocked chapters (rejected) |
| 14 | **Competition**: students see their own XP, streak and progress. Teachers see everyone. Class leaderboards are **opt-in per class (teacher switch)**, ranked by XP and never by time spent; never across schools | Motivation without demotivating weaker students (minors) | Always-on leaderboards |
| 15 | **At-risk rules** (teacher dashboard): KP fail rate > 10%, any negative XP in the week, XP per active minute < 0.5, falling memory on core concepts, overdue assignments. **Built in spec 010** over the last 7 IST days, class subject only, constants `AT_RISK_*` in `app/services/dashboard.py`: KP fail rate > 10% with ≥ 5 KP tries; any negative `xp_event`; net XP per active minute < 0.5 with ≥ 30 active minutes; ≥ 2 weak cards (retrievability < 0.7) on concepts that are a prerequisite of an active concept; an overdue assignment; `inactive` (no attempt or study time in 7 days, enrolled ≥ 7 days; replaces "5 school days": there's no school calendar) | Math Academy's warning signs; easy to explain | |
| 16 | **Log everything from day one** (attempts with time taken, hints, seeds, KP results) for analytics per KP and per question later | Content improvement needs the data | |

## Boundaries
- The frontend talks to the backend only through `/api/v1`. It never connects to the database directly.
- Answer keys and test cases marked hidden never reach the client. Practice-code test cases are an exception: they are visible in the MVP (decision 6).
- All AI calls go through `backend/app/ai/` (one place for prompts, models, rate limits and logging).
- **Org scoping**: every tenant-owned query goes through `OrgScope` (`app/api/deps.py`); ids from another school are 404.
  `tests/test_route_scoping.py` fails if a route skips auth or the scope. The one exemption is **global content**
  (`/courses`, `/courses/{slug}/graph`): those routes authenticate but read only platform-owned content, and are listed
  in `GLOBAL_CONTENT` in that test. Content routes never return `item.answer`.
- **Teacher reads are read-only** (spec 010): the dashboard computes statuses with `frontier.class_states` (batched for
  many students, a fixed number of queries, never promotes or writes); complete-but-not-promoted concepts count as
  learned there. Dashboard responses carry ids, display names and `item.public` text only.
- **RLS deny-all**: row-level security is enabled with no policies on every table in `public`, so Supabase's Data API
  (anon/authenticated keys) reads nothing. The backend connects as `postgres`, which bypasses RLS. Every migration that
  adds a table must enable RLS on it (`tests/test_rls_db.py` checks).
- **Supabase Auth settings** (each project): turn **off** "Allow new users to sign up" (Authentication → Sign In / Providers).
  Accounts are created only by admin invite or by teachers; with public sign-up on, anyone holding the anon key could
  pre-register predictable student auth emails and block account creation. Set the Site URL / redirect allow-list to
  `APP_URL` so invite and reset links land on `/accept-invite` and `/reset-password`.
- **Sessions**: Supabase revokes refresh tokens on a password change, but issued access tokens live until expiry, so the
  API also rejects tokens whose `iat` is before `app_user.sessions_valid_after` (set on admin reset, in-app password change and
  deactivation; a staff email-recovery reset goes straight to Supabase and doesn't set it).
