# Roadmap: MVP build order

Each line becomes one spec (`/spec ...`) and is built as one vertical slice: spec → fresh session → plan → build → `/ship`.
Each slice should work end to end before starting the next.

## Phase 0: Foundations
| # | Spec | Done when |
|---|---|---|
| 001 | **Scaffold**: monorepo (backend/ frontend/ content/), hosted Supabase Postgres, `make dev`, real `make check`, CI on GitHub Actions | `make check` passes on an empty app; CI runs on PRs |
| 002 | **Auth & tenancy**: managed auth, orgs, roles, classes, enrolment, invite-by-code, org-scoped query dependency | Teacher in school A cannot see anything in school B (tested) |
| 003 | **Content model & importer**: schema for course/concept/prereq/lesson/item, validator + import CLI, one sample course (e.g. "Python basics" with 6–8 concepts) | `make content-check` validates; import is idempotent |

## Phase 1: Student core loop
| # | Spec | Done when |
|---|---|---|
| 004 | **Learn layer**: lesson viewer (Markdown, KaTeX, Mermaid, images) + quiz (MCQ, short answer) | Student completes a lesson + quiz; attempts stored |
| 005 | **Mastery engine + student knowledge graph**: per-concept Bloom mastery, unlock rules, React Flow graph coloured by mastery | Graph updates after attempts; locked concepts show what is missing |
| 006 | **Practice layer**: SymPy-checked maths/physics answers (numbers, expressions, units) + Python tasks in a Pyodide worker with test cases | A student solves a maths problem and a code task; mastery moves |
| 007 | **Spaced repetition + interleaving**: FSRS cards, daily review queue that mixes concepts | Due reviews appear on the right days; no concept appears twice in a row |
| 008 | **XP & gamification**: XP ledger, Bloom-weighted rules, levels, streaks, daily caps | Practice earns clearly more XP than theory; farming the same item is capped |

## Phase 2: AI + teacher
| # | Spec | Done when |
|---|---|---|
| 009 | **AI tutor**: chat panel in lesson and practice, grounded in the current content, Socratic hints, rate limits, logging | Tutor helps without revealing answers (eval set of ~20 prompts) |
| 010 | **Teacher dashboard**: class overview, concept heatmap, per-student knowledge graph, at-risk list | Teacher can find the class's 3 weakest concepts in under 1 minute |
| 011 | **Teacher AI assist**: per-class/student summaries, suggested re-teaching notes for weak concepts | Summaries are cited to real attempt data |

## Phase 3: Pilot readiness
| # | Spec | Done when |
|---|---|---|
| 012 | **Content**: complete first real course(s) for the pilot grade (maths + physics + Python) | Reviewed by a subject teacher |
| 013 | **Hardening**: privacy/consent flow for minors, data export/delete, error tracking, backups, load test | Security review passes; consent flow is live |

## Later (v2 candidates)
Server-side code grading sandbox · authoring UI · leaderboards · parent view · BKT/IRT mastery model · Hindi and regional languages · offline/PWA
