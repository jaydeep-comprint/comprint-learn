# Roadmap: MVP build order

Each line becomes one spec (`/spec ...`) and is built as one vertical slice: spec → fresh session → plan → build → `/ship`.
Each slice should work end to end before starting the next.

## Phase 0: Foundations
| # | Spec | Done when |
|---|---|---|
| 001 | **Scaffold**: monorepo (backend/ frontend/ content/), hosted Supabase Postgres, `make dev`, real `make check`, CI on GitHub Actions | `make check` passes on an empty app; CI runs on PRs |
| 002 | **Auth & tenancy**: managed auth, orgs, roles, classes, enrolment, teacher-created student accounts, admin-invited teachers, org-scoped query dependency | Teacher in school A cannot see anything in school B (tested) |
| 003 | **Content model & importer**: course → chapter → concept → KP → item; prerequisite edges with encompassing weights; key prerequisites per KP; answer specs (numeric/expression/mcq/multistep/code), `params`, misconception tags, `expected_minutes`, Bloom tags; validator + import CLI; a sample of ~3 concepts per subject (CBSE 9–10 maths, physics, Python) | `make content-check` validates (incl. cycle check); import is idempotent |

## Phase 1: Student core loop
| # | Spec | Done when |
|---|---|---|
| 004 | **Learn layer**: concept intro + worked example per KP (Markdown, KaTeX, Mermaid, images) + misconception check; responsive (phone + desktop) | Student reads a concept and answers its check; attempts stored |
| 005 | **KP flow + knowledge graph**: KP questions (2–5, extended on error), fail → retry later, remediation via key prerequisites after 2 fails, knowledge frontier; React Flow graph with 4 states + progress fill + click-to-highlight prerequisites | A student learns a concept end to end; the frontier updates; a failed KP comes back later with new questions |
| 006 | **Practice formats**: numeric + units (exact / sig figs / tolerance), randomised numbers, SymPy expressions, misconception-tagged MCQ, multi-step problems, Python tasks in a Pyodide worker | Every format grades correctly against a test bank; two students see different numbers |
| 007 | **Reviews + quizzes**: FSRS per concept, 3–5 question mixed reviews, one-level implicit credit, daily cap, interleaving; mixed timed quiz every ~150 XP with misses turned into reviews | Due reviews appear on the right days; implicit credit postpones prerequisite reviews; quiz unlocks at 150 XP |
| 008 | **XP & gamification**: XP = expected minutes × performance, penalties for rushing, hint reduction, daily goal, streaks, progress = concepts learned; opt-in class leaderboard (teacher switch) | Implementation tasks earn the most XP; rushing earns ≤ 0; leaderboard hidden unless the teacher enables it |

## Phase 2: AI + teacher
| # | Spec | Done when |
|---|---|---|
| 009 | **AI tutor**: text chat scoped to the current KP/item; points to the worked example, prerequisite or experiment; capped hints that reduce XP; rate limits; logging | Never reveals answers or steps (eval set of ~30 prompts, including jailbreak attempts) |
| 010 | **Teacher dashboard + assignments**: class overview, concept heatmap, misconception spread, per-student graph (with memory view), at-risk rules, hint usage; assign targets with due dates (priority, never a cap); leaderboard switch | Teacher finds the 3 weakest concepts in < 1 min and assigns one; assigned students see it first |
| 011 | **Teacher AI assist**: per-class/student summaries built from misconception tags and key-prerequisite causes; suggested re-teaching notes | Summaries are cited to real attempt data |
| 012 | **Placement**: teacher marks chapters covered; short adaptive diagnostic within that range; conditional learning | Diagnostic of ≤ 25 questions places a student; wrong placements drop back quickly |

## Phase 3: Pilot readiness
| # | Spec | Done when |
|---|---|---|
| 013 | **Content**: complete the pilot slices: 6–8 concepts each for CBSE 9–10 Maths (algebra), Physics (motion and force) and Python basics | Reviewed by a subject teacher |
| 014 | **Hardening**: privacy/consent flow for minors, data export/delete, error tracking, backups, load test | Security review passes; consent flow is live |

## Later (v2 candidates)
Server-side code grading sandbox · authoring UI · parent view · full multi-level FIRe (learning speed, repetition compression) · interactive physics simulations (sliders, free-body diagrams) · goal lenses (board vs JEE depth) · AI-graded free response · analytics per KP and per question · Hindi and regional languages · offline/PWA
