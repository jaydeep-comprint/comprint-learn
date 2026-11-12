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
1. Multi-school accounts: schools → teachers → classes → students, with roles ([spec 002](specs/002-auth-tenancy.md)).
2. Pre-authored courses (content-as-code): concepts, KPs, prerequisite graph, items. First content is a **6–8 concept slice
   of each of** CBSE Class 9–10 Maths (algebra), Physics (motion and force) and Python basics ([spec 003](specs/003-content-model-importer.md));
   completed to 8 concepts per subject in [spec 013](specs/013-pilot-content.md).
3. Student **Learn** layer: intro + worked examples (text, images, diagrams, maths) + misconception check ([spec 004](specs/004-learn-layer.md)).
4. Student **Practice** layer, with these formats: numeric + units (exact / significant figures / tolerance, randomised numbers),
   SymPy expressions, limited multiple choice (misconception-tagged), multi-step problems, and Python code with tests
   ([spec 006](specs/006-practice-formats.md)). Each lesson ends with a required Practice step.
5. Mastery: the KP flow (fail → retry later → remediate key prerequisites), the knowledge frontier, and a visual knowledge graph ([spec 005](specs/005-kp-flow-knowledge-graph.md)).
6. Spaced repetition per concept with implicit credit, a daily review cap, and a mixed timed quiz every ~150 XP ([spec 007](specs/007-reviews-quizzes.md)).
7. XP (minutes × performance), daily goal, streaks. **Class leaderboards are opt-in, switched on by the teacher**, and ranked by XP, never time spent ([spec 008](specs/008-xp-gamification.md); built before 007).
8. Placement: the teacher marks the chapters already covered, then a **short adaptive diagnostic within that range** ([spec 012](specs/012-placement.md)).
9. AI tutor, scoped to the current lesson or question: it points to the worked example, the prerequisite, or an experiment to try.
   It never gives answers or steps; hints are capped and reduce XP ([spec 009](specs/009-ai-tutor.md)).
10. Teacher dashboard: class overview, per-student knowledge graph, weakest concepts, misconception spread, at-risk students,
    and **assigned targets** (one or more concepts, a chapter selects all of its concepts, + due date, for the class or chosen students). Assignments set priority but **never cap**: students can still learn
    anything whose prerequisites are learned ([spec 010](specs/010-teacher-dashboard-assignments.md)).
11. Teacher AI assist: class/student summaries and suggested notes for re-teaching, every sentence cited to dashboard
    facts; students sent as pseudonyms only ([spec 011](specs/011-teacher-ai-assist.md)).
12. Privacy: school-attested parental consent for the AI tutor (the tutor is locked until a teacher records it), per-student
    data export, erasure (anonymise after a 7-day grace) and an audit log ([spec 014](specs/014-privacy-consent-export-erasure.md)).
13. Operations hardening: scrubbed error tracking, encrypted backups, a one-lab load test, rate limits, security headers and
    a security review ([spec 015](specs/015-operations-hardening.md)).

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
  review before the pilot. The AI tutor runs on DeepSeek (servers in China): the review must cover sending students'
  tutor chat text there (the tutor sends no names or ids and scrubs emails and phone numbers). Teacher summaries
  (spec 011) also run on DeepSeek and send class learning statistics there under pseudonyms (no names, ids, answers
  or chat text); the review must cover that too. Spec 014 built consent, export and erasure on four assumptions the
  review must confirm ([docs/pilot-readiness.md](pilot-readiness.md)): (1) learning without parental consent is lawful
  because the school is the data fiduciary for classroom activity; (2) a teacher's tick is acceptable evidence of
  verifiable parental consent when the school keeps the signed form; (3) pseudonymised class statistics for teacher
  summaries need no parental consent; (4) anonymised learning rows (including submitted answers and code) are no longer
  personal data.
  Error tracking (spec 015) is a third data flow: Sentry (EU region) receives stack traces, request ids and the ids
  `user.id`, `org_id` and role only (no names, answers, code, chat text, bodies, cookies or IP addresses); the review
  must cover it too.
- Every school's data is isolated from every other school (multi-tenant).
- AI cost must stay low per student per month: use a small model by default, rate-limit, and cache.
- **Budget: ~$50 total for the POC/MVP** (hosting + AI API). Use free tiers everywhere, set a hard spend limit in the
  AI provider consoles, and cap tutor messages per student per day. See the cost table in docs/ARCHITECTURE.md.

## Decided (Oct 2026)
- Board/grades: **CBSE Classes 9–10**. Language: **English only**.
- Devices: **both school labs and phones**. Responsive UI; code tasks are designed for desktop but usable on tablets.
- Leaderboards: personal stats by default; teachers see everyone; class leaderboards are opt-in per class.
- Teacher control: assign targets with due dates; never cap students who are ahead.

- Content review: self-review (strict validator + an independent AI subject review) ships the content (spec 013);
  a subject-teacher review of every concept, tracked in docs/content-review.md, is a pilot gate
  ([docs/pilot-readiness.md](pilot-readiness.md)).

- Consent (Nov 2026, spec 014): **school-attested and for the AI tutor only**. The school collects signed forms and a
  teacher records them; app use without the tutor is treated as the school's own educational activity. Erasure anonymises
  and keeps learning rows. These are assumptions for the legal review ([docs/pilot-readiness.md](pilot-readiness.md)).

## Open questions
- Pilot timeline; how many pilot schools and classes?
