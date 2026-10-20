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
| Python execution | **Pyodide in a Web Worker** (in-browser) | No server sandbox needed; safe and free to run |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic | Team choice (Python); typed |
| Database | PostgreSQL (hosted Supabase, Session pooler, port 5432) | Relational data (orgs/classes) + JSONB for content. Test DB = a separate Supabase project (`TEST_DATABASE_URL`), used only by `make test-db` and CI |
| Auth | **Supabase Auth** (same project as the DB). FastAPI verifies its JWTs against the project JWKS (`app/core/auth.py`); our `app_user.id` = the auth user id. Teachers are invited by email; students get teacher-created accounts with a synthetic, never-emailed auth email | Don't build password, reset and invite flows ourselves; one free-tier project for DB + auth |
| Maths answer checking | SymPy (server side) | Checks equivalent expressions and numbers with tolerance and units |
| Spaced repetition | `fsrs` (py-fsrs) | Modern scheduler with fewer reviews than SM-2 |
| AI | Anthropic API: Claude Haiku 5.5 (`claude-haiku-5-5`) for tutor chat, Claude Sonnet 5.5 (`claude-sonnet-5-5`) for teacher summaries | Low cost per student; better reasoning where needed |
| Python tooling | uv, ruff, mypy, pytest | Fast and standard |
| JS tooling | pnpm, eslint, prettier, vitest, Playwright (e2e) | Standard |
| Hosting | Free tiers: Supabase (DB + Auth), Cloudflare Pages or Vercel (SPA), Render free or Fly.io/Railway (~$5/mo) for the API, GitHub Actions, Sentry free | POC budget ~$50 total (see Cost budget) |

## Cost budget (POC, ~$50 total)
| Item | Plan | Est. cost |
|---|---|---|
| Database + auth | Supabase free (2 projects: dev + test). Pauses after ~1 week idle; restore in the dashboard | $0 |
| Frontend | Cloudflare Pages / Vercel free | $0 |
| API | Render free (sleeps; ~30–60 s cold start) for demos, or Fly.io/Railway when it must stay awake | $0–5 / month |
| AI tutor | Claude Haiku 5.5 ($0.10 in / $0.50 out per 1M tokens). ~3k in + 300 out per message ≈ $0.00045. 50 students × 20 msgs/day × 30 days ≈ **$14/month**; less with prompt caching | ~$5–15 / month |
| Teacher summaries | Claude Sonnet 5.5 ($2 / $10 per 1M). ~10k in + 1k out ≈ $0.03 each; 10 teachers × weekly ≈ $1.20/month | ~$1–2 / month |
| Domain (optional) | | ~$10 / year |
Guards: a monthly spend limit in the Anthropic console (e.g. $20), a per-student daily tutor cap (e.g. 20 messages), prompt caching on the
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
- **Content**:
  - `course` → `chapter` → `concept` (node) → `knowledge_point` (3–4 per concept, ordered; worked example + question pool) → `item`.
  - `concept_prereq` (edge) has `encompassing_weight` (0–1: how much of the prerequisite is practised inside the concept).
  - `knowledge_point.key_prereq_ids` names the concept(s) that step really depends on, used for remediation.
  - `item` has a `bloom_level` tag, `type` (numeric | expression | mcq | multistep | code), `expected_minutes`, optional
    `params` (randomised numbers), and a type-specific answer spec (see decision 10). MCQ options carry a `misconception_id`.
- **Learning state**:
  - `attempt`: one row per answer submitted, with the result, time taken, hints used and the parameter seed.
  - `kp_progress`: per student × KP, holding status (not started | in progress | passed | failed) and the fail count.
  - `concept_state`: per student × concept, holding status (locked | ready | in progress | learned) and the source (lesson | diagnostic | teacher).
  - `review_card`: FSRS state per student × **concept**.
  - `xp_event`: an append-only ledger of XP awarded, with the reason.
  - `quiz`: mixed timed quizzes and their items; `assignment`: a teacher target (concept or chapter, class, due date).
  - `diagnostic_session`: per-topic evidence for placement.
- **AI**: `tutor_session` and `tutor_message`, kept for safety review and cost tracking.

## Key decisions
| # | Decision | Reason | Alternatives rejected |
|---|---|---|---|
| 1 | Content is files in `content/` (Markdown + YAML), validated against a schema and imported by `uv run app content import` | Pre-authored fixed courses: reviewable in git, easy for Claude to help write | Authoring UI (out of MVP scope) |
| 2 | Every tenant-owned table has `org_id`; a single FastAPI dependency scopes every query | One choke point for isolation; tested | Separate DB per school (overkill) |
| 3 | **Mastery = knowledge points.** A concept is 3–4 KPs; each KP is a worked example plus 2–5 questions (more after a wrong answer). Failing a KP ends the lesson, and the student retries **later** with new questions. Two fails at the same KP schedule reviews of its key prerequisites. A concept is *learned* when every KP passes. A concept is *ready* (on the knowledge frontier) when all of its prerequisites are learned | Proven by Math Academy (95% first-try pass rate); simple to explain; Bloom stays useful as tags | A mastery score per Bloom level as the gate (rejected Oct 2026; see research doc) |
| 4 | Learn layer = intro + worked examples + one misconception check (Remember/Understand). Practice = KP questions, multi-step problems, code (Apply → Create). Bloom levels are **tags on items**, used for teacher analytics and depth views | Matches the two-layer idea without turning Bloom into a gate | |
| 5 | **XP = item.expected_minutes × performance multiplier** (perfect 1.2, pass 1.0, partial 0.3, poor 0, rushing or guessing a small negative). Hints reduce it, repeats earn less, and there's no "I don't know" button. Daily goal ~30–40 XP. Progress bars count **concepts learned**, not XP | 1 XP ≈ 1 min of focused work (Math Academy); implementations earn most because they take longest; penalties stop XP farming | Bloom-weighted XP (rejected Oct 2026) |
| 6 | Python runs client-side in Pyodide. MVP grading also runs client-side | No sandbox infrastructure needed | Judge0 / server sandbox (**v2**, when XP needs to be cheat-proof) |
| 7 | Maths and physics answers are checked **server side** with SymPy | Answers are never sent to the client | Client-side checking (leaks answers) |
| 8 | **The AI tutor never lowers the bar.** It sees only the current item/KP content and the student's attempts. It points to the worked example, the key prerequisite, or an experiment to try; it never gives the answer or the next step. Hints are capped per item and reduce XP, and teachers see hint usage. Text only. Rate-limited per student per day. Measured in the pilot | Math Academy's critique of chat tutors plus Vizuara's "try this experiment" style; cost and DPDP | General chatbot; voice or screen-watching tutor |
| 9 | **Spaced repetition per concept** (FSRS, starting when a concept is learned). A review is 3–5 mixed questions across that concept's KPs, judged on the trend of answers. Passing a review or lesson gives **one-level implicit credit** to prerequisites (`encompassing_weight` × credit, discounted when early), switched off for struggling students. Reviews are interleaved across concepts; daily cap ~5 | Far fewer reviews than per-item cards; uses the graph | Per-item flashcards; full multi-level FIRe (v2) |
| 10 | **Answer specs by type**: `numeric{value, unit, mode: exact\|sigfig\|tolerance, sigfigs?, rel_tol?, sci_notation?}`, `expression{sympy_mode: exact\|equivalent\|simplified}`, `mcq{options[{text, correct, misconception_id?}]}` (used sparingly), `multistep{steps[]}` (each step has its own spec), `code{tests[]}`. Items can declare `params` for randomised numbers; the server derives answers from the seed | PhysicsGraph's schema; randomised numbers stop answer-sharing in class | Multiple choice as the main format (encourages backward reasoning) |
| 11 | **Mixed timed quiz every ~150 XP**: no notes, covers everything learned so far, tuned for ~80% average score. Every miss becomes a review | Retention metric for teachers; retrieval practice | Teacher-scheduled quizzes only |
| 12 | **Placement**: the teacher marks the chapters already covered for the class, then each student takes a short **adaptive diagnostic** within that range. A correct answer adds evidence to the topic and its prerequisites; a wrong answer subtracts from the topic and the topics above it. Topics that only just pass are *conditionally learned* and drop back quickly if the student struggles | Combines how schools work with catching individual gaps | Placement by the teacher only; a full-course diagnostic |
| 13 | **Assignments set priority, never a cap.** A teacher target (concept/chapter + due date) puts it and its missing prerequisites first (Focus Mode). Students can still learn any concept on their frontier | Teacher control without holding back fast students | Teacher-unlocked chapters (rejected) |
| 14 | **Competition**: students see their own XP, streak and progress. Teachers see everyone. Class leaderboards are **opt-in per class (teacher switch)**, ranked by XP and never by time spent; never across schools | Motivation without demotivating weaker students (minors) | Always-on leaderboards |
| 15 | **At-risk rules** (teacher dashboard): KP fail rate > 10%, any negative XP in the week, XP per active minute < 0.5, falling memory on core concepts, overdue assignments | Math Academy's warning signs; easy to explain | |
| 16 | **Log everything from day one** (attempts with time taken, hints, seeds, KP results) for analytics per KP and per question later | Content improvement needs the data | |

## Boundaries
- The frontend talks to the backend only through `/api/v1`. It never connects to the database directly.
- Answer keys and test cases marked hidden never reach the client. Practice-code test cases are an exception: they are visible in the MVP (decision 6).
- All AI calls go through `backend/app/ai/` (one place for prompts, models, rate limits and logging).
- **Org scoping**: every tenant-owned query goes through `OrgScope` (`app/api/deps.py`); ids from another school are 404.
  `tests/test_route_scoping.py` fails if a route skips auth or the scope.
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
