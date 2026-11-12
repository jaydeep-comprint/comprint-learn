# Load test results (spec 015 §3), November 2026

**Verdict: functionally PASS, latency partly MISSED (recorded as findings).** A full school lab, 80
students + 2 teachers for 10 minutes, ran with **0 errors in 20,507 requests**. The overall p95 was
**640 ms** and p99 **1.1 s**. Four endpoints still miss their p95 targets. In every case the time
is spent on database round trips from this laptop to the Supabase project in Mumbai, under load on
the free-tier database. `check.py` was not loosened, so `make loadtest` still reports FAIL until
these are fixed (see Findings).

## Setup
- **Machine:** MacBook Pro (Apple silicon), macOS 26.6, Python 3.13.16; Locust, the API and its
  SymPy pool all ran on the same machine.
- **Network:** home/office connection to Supabase `ap-south-1` (Mumbai) via the Session pooler.
  The round trip measured by the orchestrator was **9 ms** (median of 10 `select 1`), and about
  10–12 ms per statement under load.
- **Database:** the test Supabase project (free tier), with certificates verified against
  Supabase's CA (`DATABASE_SSL_ROOT_CERT`).
- **Commits:** `0d9147f` for the baseline; the final run was on the PR 3 branch with the content
  cache (`33c019e`).
- **Scenario:** `backend/loadtest/locustfile.py` (seeded by `app loadtest seed`), with spawn 4/s,
  think time 3–12 s, ~75% correct answers worked out from the DB, and the rate limiter **on**.
  The tutor and teacher AI were off.
- **Command:** `make loadtest` (final settings: `ARGS="--workers 2"`, `DB_POOL_SIZE=6`,
  `DB_MAX_OVERFLOW=0`).

## Runs

| Run | Settings | Requests | Failures | p50 | p95 | p99 | Peak DB conns |
|---|---|---:|---:|---:|---:|---:|---:|
| 1. Baseline | 1 worker, pool 5+5 | 19,068 | 0 | 340 ms | 1.2 s | 2.2 s | 10 / 10 |
| 2. Bigger pool | 1 worker, pool 10+5 | 20,208 | **1,915 (9.5%)** | 260 ms | 870 ms | 1.4 s | 15 / 15 |
| 3. Two workers | 2 workers × pool 6+0 | 19,544 | 0 | 310 ms | 930 ms | 1.4 s | 12 / 12 |
| 4. **+ content cache** | 2 workers × pool 6+0 | **20,507** | **0** | **200 ms** | **640 ms** | **1.1 s** | 12 / 12 |

- **Run 2** hit Supabase's free Session pooler limit of **15 clients per project**
  (`EMAXCONNSESSION ... max clients are limited to pool_size: 15`). The load test's own
  connections took the last slots, and API requests failed with 500s. The API must stay at about
  12 connections in total, which leaves room for the nightly jobs.
- **Run 3** split the CPU work (the event loop, SymPy, the dashboard's per-student state) across
  two processes and removed most of the time spent outside the database.
- **Run 4** added the per-process content cache (below). Queries per request went from 21–38 to
  14–26.

## Per-endpoint results (run 4)

| Endpoint | Requests | p50 | p95 | p99 | Target p95 | |
|---|---:|---:|---:|---:|---:|---|
| GET /classes/[id]/students/[sid] | 19 | 520 | 2,900 | 2,900 | 1,500 | **miss** |
| GET /classes/[id]/students | 19 | 550 | 2,000 | 2,000 | 1,500 | **miss** |
| GET /classes/[id]/overview | 19 | 850 | 1,700 | 1,700 | 1,500 | **miss** |
| POST /learn/concepts/[c]/[k]/kps/[kp]/answer | 1,606 | 400 | 970 | 1,400 | 800 | **miss** |
| GET /classes/[id]/heatmap | 19 | 280 | 950 | 950 | 1,500 | |
| GET /courses | 19 | 84 | 940 | 940 | 1,500 | |
| POST /learn/concepts/[c]/[k]/practice/answer | 881 | 280 | 790 | 1,300 | 800 | |
| POST /reviews/[c]/[k]/answer | 131 | 300 | 770 | 940 | 800 | |
| GET /learn/concepts/[c]/[k]/kps/[kp]/question | 1,606 | 290 | 720 | 1,100 | 1,500 | |
| GET /classes/[id]/summary | 19 | 220 | 670 | 670 | 1,500 | |
| GET /classes/[id]/leaderboard | 279 | 92 | 640 | 1,200 | 1,500 | |
| GET /classes/[id]/students/[sid]/outline | 19 | 180 | 630 | 630 | 1,500 | |
| GET /learn/concepts/[c]/[k] | 2,024 | 220 | 630 | 1,100 | 1,500 | |
| GET /learn/concepts/[c]/[k]/practice/question | 883 | 220 | 610 | 1,100 | 1,500 | |
| POST /learn/concepts/[c]/[k]/check | 198 | 230 | 600 | 930 | 1,500 | |
| POST /learn/concepts/[c]/[k]/progress | 2,831 | 220 | 580 | 970 | 1,500 | |
| GET /courses/[c]/graph | 255 | 130 | 570 | 1,000 | 1,500 | |
| GET /learn/courses/[c]/outline | 2,850 | 150 | 520 | 860 | 1,500 | |
| GET /reviews/[c]/[k]/question | 131 | 210 | 520 | 1,200 | 1,500 | |
| GET /me/xp | 823 | 140 | 500 | 780 | 1,500 | |
| GET /reviews | 1,357 | 140 | 470 | 990 | 1,500 | |
| GET /me | 825 | 82 | 440 | 790 | 1,500 | |
| GET /quizzes/current | 2,852 | 68 | 410 | 830 | 1,500 | |
| GET /me/assignments | 823 | 78 | 340 | 660 | 1,500 | |
| GET /classes/[id] | 19 | 130 | 320 | 320 | 1,500 | |
| **Overall** | **20,507** | **200** | **640** | **1,100** | p99 < 3,000 | p99 ✓ |

All times are in ms. The teacher rows have only 19 samples each (one dashboard pass per teacher
per ~60 s), so their p95 is effectively the slowest single request.

**Slowest five (p95):** the student page 2.9 s, the Students tab 2.0 s, the overview 1.7 s, the
KP answer 970 ms, and the heatmap 950 ms.

**Server-side time** (the API's access log, `queries` and `db_ms` per request): for the KP answer,
median 22 queries, DB p95 746 ms and total p95 963 ms. For the student page, 26 queries, DB p95
2.3 s. DB time is 75–95% of every slow request.

## What was changed in spec 015 (within §3's limits, plus the cache the user approved)
1. **Two uvicorn workers × 6 DB connections** (`DB_POOL_SIZE=6`, `DB_MAX_OVERFLOW=0`) is the
   recommended production setting (deploy checklist). Never more than ~12 in total on the free
   Session pooler.
2. **A per-process content cache** (`app/content/cache.py`, approved by the user on 2026-11-12):
   - What it holds: the course graph, the knowledge points with their question types, and which
     concepts have practice items.
   - How it stays correct: one stamp query per transaction, made of row counts and the latest
     `updated_at` of every content table, so an import or a test's truncate is seen at once.
   - What it isn't: no tenant-owned or student data is cached.
3. **Per-request diagnostics:** the access log now records `queries` and `db_ms`.
4. **Indexes:** none were added. The hot tables already have `(org_id, student_id, …)` indexes,
   and no slow query showed up unloaded. The heaviest dashboard aggregate took 90 ms.

## Findings (for the user to decide)
- **F1. Round trips dominate.** At ~10 ms per statement, 20–26 statements cost 200–300 ms before
  any work is done, and more under load. **Recommendation: host the API in the same region as
  the database** (Mumbai: Fly.io `bom`, or any `ap-south-1` host), where a round trip is ~1 ms.
  Render's nearest region (Singapore) would be *slower* than this laptop. Expected effect: every
  endpoint well inside its target.
- **F2. KP answer p95 970 ms (target 800).** It reads `item` up to 4 times and the session's
  `attempt`s 3 times, and a session-ending answer adds ~10 XP/quiz queries. Next step if needed:
  reuse the loaded pool for the current item, load attempts once per request, and fold the XP
  day/goal reads into one query (~8 fewer statements).
- **F3. Teacher pages p95 1.7–2.9 s (target 1.5).** These are 24–26 aggregates per page, mostly
  against data the students are writing at the same time. Next step: batch the per-student
  aggregates in `class_view.load` and `dashboard.class_snapshot` into fewer statements. Or
  accept it: teachers open these pages a few times a lesson, and a 2–3 s worst case is
  noticeable but usable.
- **F4. Free-tier ceilings.** The Session pooler allows 15 clients, and the free database compute
  is shared. One lab (80) is the tested limit; two concurrent labs should be tested before a
  larger pilot, or the project moved to a paid compute size.
- **F5. Functional result.** No 5xx, no timeouts, no pool errors, and no scenario mistakes. Every
  answer worked out as correct was graded correct. The rate limiter stayed on and never tripped
  for a real lab.

## How to rerun
`make loadtest` (needs `backend/certs/supabase-ca.crt`; never during `make test-db`; ~15 min
including seeding). A smoke run is `make loadtest ARGS="--users 30 --run-time 2m"`. Tuning knobs:
`ARGS="--workers 2"`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`. Results land in `backend/loadtest/out/`
(`report.md`, `summary.json`, `api.log`).
