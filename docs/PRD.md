# PRD: Learning App (MVP)

> One page. Product-level "why" and "what". Feature details live in docs/specs/ (order in docs/ROADMAP.md).

## Problem
Students in schools and institutes read and memorise theory but rarely get enough *applied* practice, and they forget
material because nothing brings it back at the right time. Teachers can't see, per concept, what each student actually
understands, so help arrives late and is generic.

## Users
| Persona | Need | Current alternative |
|---|---|---|
| **Student** (CBSE Classes 9–10: maths, physics, Python) | Short theory, lots of practice, help when stuck, clear progress | Textbooks, YouTube, worksheets |
| **Teacher** | See who is stuck on which concept and act on it quickly | Test marks, gut feel |
| **School admin** | Onboard teachers, classes and students | Spreadsheets |

## Core ideas
- **Knowledge graph**: each course is a graph of concepts with prerequisite edges. Each concept is broken into
  **3–4 knowledge points (KPs)**, each a worked example followed by 2–5 questions. A concept counts as **learned** when all of its KPs pass.
  Every question is tagged with a **Bloom level** (Remember → Create) so teachers can see the *depth* of understanding.
- **Two layers per concept**:
  1. **Learn (theory, kept short)**: an intro, a worked example per KP, and one misconception check.
  2. **Practice (the main focus)**: KP questions, multi-step problems and Python implementations.
- **Retention**: spaced repetition per concept, where practising an advanced concept also counts as review of its prerequisites.
  Reviews **interleave** concepts, and a timed mixed quiz runs every ~150 XP.
- **Gamification**: **1 XP ≈ 1 minute of focused work**, scaled by performance. Implementations earn the most because they take
  longest, and rushing or guessing earns nothing or a small penalty. Progress = concepts learned.
- Research behind these choices: [docs/research/COMPETITOR-INSIGHTS.md](research/COMPETITOR-INSIGHTS.md) (Math Academy, PhysicsGraph, Vizuara).

## Goals & success metrics (pilot)
- Students spend **≥ 60% of their time in practice**, not theory → measured from activity logs.
- **Review retention**: ≥ 70% of due reviews answered correctly.
- **Teacher usage**: each pilot teacher opens the dashboard weekly and can name their class's 3 weakest concepts.
- **Engagement**: ≥ 50% of pilot students active on 3 or more days a week.

## MVP scope (v1)
Build order and spec numbers: docs/ROADMAP.md.
0. Foundations: monorepo scaffold, `make dev` / `make check`, CI ([spec 001](specs/001-scaffold.md)).
1. Multi-school accounts: schools → teachers → classes → students, with roles.
2. Pre-authored courses (content-as-code): concepts, KPs, prerequisite graph, items. First content is a **6–8 concept slice
   of each of** CBSE Class 9–10 Maths (algebra), Physics (motion and force) and Python basics.
3. Student **Learn** layer: intro + worked examples (text, images, diagrams, maths) + misconception check.
4. Student **Practice** layer, with these formats: numeric + units (exact / significant figures / tolerance, randomised numbers),
   SymPy expressions, limited multiple choice (misconception-tagged), multi-step problems, and Python code with tests.
5. Mastery: the KP flow (fail → retry later → remediate key prerequisites), the knowledge frontier, and a visual knowledge graph.
6. Spaced repetition per concept with implicit credit, a daily review cap, and a mixed timed quiz every ~150 XP.
7. XP (minutes × performance), daily goal, streaks. **Class leaderboards are opt-in, switched on by the teacher**, and ranked by XP, never time spent.
8. Placement: the teacher marks the chapters already covered, then a **short adaptive diagnostic within that range**.
9. AI tutor, scoped to the current lesson or question: it points to the worked example, the prerequisite, or an experiment to try.
   It never gives answers or steps; hints are capped and reduce XP.
10. Teacher dashboard: class overview, per-student knowledge graph, weakest concepts, misconception spread, at-risk students,
    and **assigned targets** (concept/chapter + due date). Assignments set priority but **never cap**: students can still learn
    anything whose prerequisites are learned.
11. Teacher AI assist: class/student summaries and suggested notes for re-teaching.

## Non-goals (NOT in v1)
- A content authoring UI (our team authors content in the repo).
- Languages other than Python for code; arbitrary file/project uploads.
- Native mobile apps (responsive web only).
- Parent accounts, payments, public signup, cross-school leaderboards.
- Languages other than English (the content format should allow translations later).
- Voice or screen-watching AI; uploading your own material.
- Live classes or video hosting (embedding YouTube links is fine).

## Constraints
- **Minors' data**: most students are under 18. If the pilot is in India, the DPDP Act 2023 requires verifiable parental
  consent and bans tracking or targeted ads for children. Collect as little personal data as possible, and get legal
  review before the pilot.
- Every school's data is isolated from every other school (multi-tenant).
- AI cost must stay low per student per month: use a small model by default, rate-limit, and cache.
- **Budget: ~$50 total for the POC/MVP** (hosting + AI API). Use free tiers everywhere, set a hard spend limit in the
  Anthropic console, and cap tutor messages per student per day. See the cost table in docs/ARCHITECTURE.md.

## Decided (Oct 2026)
- Board/grades: **CBSE Classes 9–10**. Language: **English only**.
- Devices: **both school labs and phones**. Responsive UI; code tasks are designed for desktop but usable on tablets.
- Leaderboards: personal stats by default; teachers see everyone; class leaderboards are opt-in per class.
- Teacher control: assign targets with due dates; never cap students who are ahead.

- Content review: light self-review for the POC (no formal subject-teacher review yet).

## Open questions
- Pilot timeline; how many pilot schools and classes?
