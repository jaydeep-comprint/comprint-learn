# PRD: Learning App (MVP)

> One page. Product-level "why" and "what". Feature details live in docs/specs/ (order in docs/ROADMAP.md).

## Problem
Students in schools and institutes read and memorise theory but rarely get enough *applied* practice, and they forget
material because nothing brings it back at the right time. Teachers can't see, per concept, what each student actually
understands, so help arrives late and is generic.

## Users
| Persona | Need | Current alternative |
|---|---|---|
| **Student** (school syllabus: maths, physics, Python) | Short theory, lots of practice, help when stuck, clear progress | Textbooks, YouTube, worksheets |
| **Teacher** | See who is stuck on which concept and act on it quickly | Test marks, gut feel |
| **School admin** | Onboard teachers, classes and students | Spreadsheets |

## Core ideas
- **Knowledge graph**: each course is a graph of concepts with prerequisite edges. Mastery is tracked per student, per
  concept, per **Bloom level** (Remember → Understand → Apply → Analyze → Evaluate → Create).
- **Two layers per concept**:
  1. **Learn (theory, kept short)**: visual + text lesson, an AI tutor to chat with, a quick quiz (Remember/Understand).
  2. **Practice (the main focus)**: maths/physics problems and Python implementations (Apply → Create).
- **Retention**: spaced repetition schedules reviews, and review sessions **interleave** concepts.
- **Gamification**: XP weighted by Bloom level. Theory earns little; practice and implementations earn the most.

## Goals & success metrics (pilot)
- Students spend **≥ 60% of their time in practice**, not theory → measured from activity logs.
- **Review retention**: ≥ 70% of due reviews answered correctly.
- **Teacher usage**: each pilot teacher opens the dashboard weekly and can name their class's 3 weakest concepts.
- **Engagement**: ≥ 50% of pilot students active on 3 or more days a week.

## MVP scope (v1)
Build order and spec numbers: docs/ROADMAP.md.
0. Foundations: monorepo scaffold, `make dev` / `make check`, CI ([spec 001](specs/001-scaffold.md)).
1. Multi-school accounts: schools → teachers → classes → students, with roles.
2. Pre-authored courses (content-as-code): concepts, prerequisite graph, lessons, quizzes, practice items.
3. Student **Learn** layer: lesson viewer (text, images, diagrams, maths), quiz.
4. Student **Practice** layer: numeric/expression answers for maths/physics; in-browser Python editor with test cases.
5. Mastery engine (Bloom levels per concept) and a visual knowledge graph for the student.
6. Spaced repetition and interleaved review sessions.
7. XP, levels, streaks.
8. AI tutor in lessons and practice (hints, never hands over the answer).
9. Teacher dashboard: class overview, per-student knowledge graph, weakest concepts, students at risk.
10. Teacher AI assist: class/student summaries and suggested notes for re-teaching.

## Non-goals (NOT in v1)
- A content authoring UI (our team authors content in the repo).
- Languages other than Python for code; arbitrary file/project uploads.
- Native mobile apps (responsive web only).
- Parent accounts, payments, public signup, cross-school leaderboards.
- Live classes or video hosting (embedding YouTube links is fine).

## Constraints
- **Minors' data**: most students are under 18. If the pilot is in India, the DPDP Act 2023 requires verifiable parental
  consent and bans tracking or targeted ads for children. Collect as little personal data as possible, and get legal
  review before the pilot.
- Every school's data is isolated from every other school (multi-tenant).
- AI cost must stay low per student per month: use a small model by default, rate-limit, and cache.
- Budget / timeline: <fill in>

## Open questions
- Which boards and grades come first (CBSE / ICSE / state; classes 8–12)? → decides the first course.
- Medium of instruction: English only, or also Hindi or regional languages?
- Main devices: school computer labs, or students' phones? (Code practice on phones is limited.)
- Are leaderboards wanted, or only personal XP? (Competition can demotivate weaker students.)
- Can teachers assign specific concepts or reviews, or does everyone follow the graph freely?
