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
| Database | PostgreSQL | Relational data (orgs/classes) + JSONB for content |
| Auth | Managed auth (Supabase Auth or Clerk) issuing JWTs; FastAPI verifies them | Don't build password, reset and invite flows ourselves |
| Maths answer checking | SymPy (server side) | Checks equivalent expressions and numbers with tolerance and units |
| Spaced repetition | `fsrs` (py-fsrs) | Modern scheduler with fewer reviews than SM-2 |
| AI | Anthropic API: Haiku for tutor chat, Sonnet for teacher summaries | Low cost per student; better reasoning where needed |
| Python tooling | uv, ruff, mypy, pytest | Fast and standard |
| JS tooling | pnpm, eslint, prettier, vitest, Playwright (e2e) | Standard |
| Hosting | <decide: e.g. Render/Fly/Railway for API + Vercel/Netlify for SPA + managed Postgres> | |

## Repo layout
```
backend/      FastAPI app (app/api, app/models, app/services, app/ai), alembic/, tests/
frontend/     React SPA (src/features/<feature>, src/components, src/lib)
content/      Pre-authored courses (content-as-code), validated + imported by a CLI
docs/         PRD, architecture, roadmap, specs, plans
```

## Domain model (core tables)
- **Tenancy**: `organization` (school) → `user` (role: admin | teacher | student, org_id) → `class` → `enrollment`.
- **Content**: `course` → `concept` (node) → `concept_prereq` (edge) → `lesson` → `item`.
  An `item` is a quiz question, a maths problem or a code task. Each item has a `bloom_level`, a `layer` (learn | practice), a `type` and a JSON payload.
- **Learning state**:
  - `attempt`: one row per answer submitted, with the result and time taken.
  - `mastery`: per student × concept × bloom_level, holding a score (0–1) and a status.
  - `review_card`: FSRS state per student × item.
  - `xp_event`: an append-only ledger of XP awarded.
- **AI**: `tutor_session` and `tutor_message`, kept for safety review and cost tracking.

## Key decisions
| # | Decision | Reason | Alternatives rejected |
|---|---|---|---|
| 1 | Content is files in `content/` (Markdown + YAML), validated against a schema and imported by `uv run app content import` | Pre-authored fixed courses: reviewable in git, easy for Claude to help write | Authoring UI (out of MVP scope) |
| 2 | Every tenant-owned table has `org_id`; a single FastAPI dependency scopes every query | One choke point for isolation; tested | Separate DB per school (overkill) |
| 3 | Mastery score: an exponentially weighted average of recent correct answers per (concept, Bloom level). Level is mastered at ≥ 0.8 with ≥ N attempts. A concept unlocks when its prerequisites are mastered at **Apply** | Simple and explainable to teachers; can be swapped for BKT/IRT later | Full BKT/IRT now (needs data we don't have yet) |
| 4 | Learn layer covers Remember/Understand. Practice covers Apply/Analyze. Implementations and multi-step problems cover Evaluate/Create | Matches the two-layer product idea | |
| 5 | XP = base(bloom_level) × difficulty × first-try bonus. Repeats earn less, and each item has a daily XP cap | Rewards real practice and stops XP farming | Flat XP per item |
| 6 | Python runs client-side in Pyodide. MVP grading also runs client-side | No sandbox infrastructure needed | Judge0 / server sandbox (**v2**, when XP needs to be cheat-proof) |
| 7 | Maths and physics answers are checked **server side** with SymPy | Answers are never sent to the client | Client-side checking (leaks answers) |
| 8 | The AI tutor gets only the current lesson/item content and the student's attempts. Its system prompt is Socratic and never reveals solutions. Requests are rate-limited per student per day | Cost, safety and learning value | General chatbot |
| 9 | Review sessions are built from FSRS due cards and interleaved across concepts, so the same concept never appears twice in a row | Interleaving + spacing | Reviewing one concept at a time |

## Boundaries
- The frontend talks to the backend only through `/api/v1`. It never connects to the database directly.
- Answer keys and test cases marked hidden never reach the client. Practice-code test cases are an exception: they are visible in the MVP (decision 6).
- All AI calls go through `backend/app/ai/` (one place for prompts, models, rate limits and logging).
