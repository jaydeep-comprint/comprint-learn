# Load test (spec 015 §3)

One school lab, **80 students + 2 teachers for 10 minutes**, against the API started locally on
:8001 and pointed at the **test** Supabase project (same pooler and limits as production; the next
`make test-db` wipes the data anyway). Never the dev database.

```
make loadtest                                  # the full run (~15 min incl. seeding)
make loadtest ARGS="--users 30 --run-time 2m"  # a smoke run
make loadtest ARGS="--workers 2"               # tuning: uvicorn workers
```

Needs `TEST_DATABASE_URL` and `SUPABASE_URL` (env or `backend/.env`). It holds the shared test-DB
lock for the whole run, so it refuses to start during `make test-db`, and `make test-db` refuses
during it. Ctrl-C stops the API too.

What happens (`run.py`):
1. `app loadtest seed` (test environment only): schema rebuilt (downgrade base → upgrade head),
   `content/` imported, school `LOADTEST` with 1 teacher and classes "Maths 9" / "Physics 9"
   (40 students each). Students start with 0–3 concepts learned and, for half, reviews due.
   Ids go to `.seed.json` (gitignored).
2. The API on :8001 with a random per-run `SUPABASE_JWT_SECRET` (the HS256 path): Locust mints
   tokens for the seeded users (`tokens.py`), so no Supabase auth users and no sign-in calls.
   Tutor and teacher AI are off (no DeepSeek spend). The rate limiter stays **on**.
3. Locust headless (`locustfile.py`), think time 3–12 s. Students: home → a lesson (progress and
   study-time posts, the check) → a KP session or the practice item, answered right ~75% of the
   time → a due review → the knowledge graph → sometimes the leaderboard; a pending quiz is taken
   first. Answers are worked out from the test DB (`answers.py`: the session's seed + the item's
   key through the app's own grader code), so no answer key crosses the API. An answer meant to be
   right that grades wrong counts as a failure. Teachers: overview, Students tab, heatmap and one
   student every ~60 s.
4. `check.py` on Locust's CSV: error rate < 1%; p95 < 800 ms for `POST .../answer`, < 1500 ms for
   the rest; p99 < 3 s; no pool errors in the API log; peak DB connections ≤ workers ×
   (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`).

Output in `out/` (gitignored): `run_stats.csv` etc., `api.log` (JSON lines, one access line per
request), `summary.json` and `report.md` (the tables for `docs/loadtest/`).

Notes:
- DB connections are counted with `lsof` on the API processes: Supabase's pooler overwrites
  `application_name`, so `pg_stat_activity` can't tell the API's connections apart.
- Locust reads the DB over one shared connection: the Session pooler pins a server connection per
  client, and the API needs them.
- If a threshold is missed only because of laptop-to-Supabase round trips, `check.py` is not
  loosened: the results file reports it as a finding (the round trip and the server-side time per
  endpoint are recorded for that).
