# Plan: Spec 007 — Reviews + quizzes

## Context
Spec `docs/specs/007-reviews-quizzes.md` (PRD item 6; built after 008). This spec adds:
- an FSRS card per student × learned concept;
- a daily "Today's reviews" queue: 3–5 question reviews of one concept, capped at 5 a day and interleaved;
- one-level implicit credit to prerequisites;
- a timed 10-question mixed quiz every 150 lifetime XP that blocks new KP and practice sessions; its misses become reviews;
- XP for reviews and quizzes through 008's ledger;
- two new roster columns.

Branch: `feat/007-reviews-quizzes`. The uncommitted spec and PRD edit go into the first commit.

## Key findings that shape the design
- **Brush-ups are the template for reviews.** In `services/kp_flow.py`:
  - Question side: `remediation_question` (L1281), `_review_question` (L1306), `_review_pool` (L1242), `_serve` (L394).
  - Answer side: `remediation_answer` (L1347) calls `answer_in_session(..., review_outcome, owner=...)` (L755), then `_serve(pos+1)`. An empty pool counts as passed, and XP comes from `xp.award_for_session` (L1399/L1402).
  - `_review_kps(scope, rem)` (L1237) only needs the concept id, so generalise it to `_review_kps(scope, concept_id)`.
- **Quizzes grade through the same helpers.**
  - `_grade_answer` (L498) for grading, and `_result` / `_explanation` (L614 / L577) for the end-of-quiz reveal.
  - `kp_flow._conflict(code, detail, **extra)` (L209) gives `quiz_pending {quiz_id}`.
- **XP.**
  - `award_for_session` (`services/xp.py:441`) maps `XpReason(session.kind.value)` 1:1, so the `review` and `quiz` values go into both `SessionKind` and `XpReason`.
  - Its `ON CONFLICT (session_id) WHERE session_id IS NOT NULL` changes to `(session_id, subject)`, to match the new unique index.
  - There is no lifetime-XP helper (`summary()` sums inline at L567), so add `lifetime_xp(scope, student_id)` (net, no floor).
- **Hook points.**
  - KP session passes by an answer: `kp_flow.answer` L1040–1047. This is the implicit-credit hook. The empty-pool path in `current_question` (L918) is not an answer and gives no credit.
  - New KP session: `_start_kp_session` L971 (after the `kp_passed` / `check_first` / `kp_order` / `kp_waiting` gates).
  - New practice session: `practice.practice_question` L191–195 (after `_gate`).
  - `frontier.mark_learned` (`frontier.py:438`) is the single learned point. It is reached from `learned_and_unlocked` and from `load(promote=True)`.
- **Migrations.**
  - Enum values are added in `autocommit_block` (0005 L96).
  - Check constraints are replaced with module constants (0006 L29).
  - RLS loop over `TABLES`; `_shrink_enum` for downgrade.
  - The only data step so far is in 0005; its test pattern is `test_migrations_db.py:35`.
- **Routes.** Routes use plain `Scope`. Student-only is enforced in the service (`_require_student` → 403). `test_route_scoping.py` picks up new `Scope` routes automatically, and none are global.
- **Frontend.**
  - `PracticeRunner` (`features/learn/PracticeRunner.tsx`) already does fetch → submit → `ResultPanel` → XP toast. It takes `renderConflict(code, err)`, so `ReviewPage` is a thin copy of `RemediationPage`.
  - `AnswerForm` with `marked={null}`, keyed per position, is a feedback-free input for the quiz (numeric, expression and MCQ only, which matches the quiz item types).
  - There is no timer or ring component yet. The no-nav route goes under `RequireAuth` beside `/change-password` (`routes.tsx:23`).
- **Content.** `speed-and-velocity` → `distance-and-displacement` has weight 0.7 (used in the implicit-credit DB test). `fsrs` isn't a dependency yet: run `uv add fsrs`, which writes the lockfile.

## Backend

### 1. Dependency + migration `0008_reviews_quizzes.py` (down_revision `0007_xp`)
- Run `cd backend && uv add fsrs` (≥ 6). Check whether it ships `py.typed`. If it doesn't, add a mypy override `ignore_missing_imports` for `fsrs` in pyproject.
- Enum values (autocommit block):
  - `session_kind`, `attempt_context` and `xp_reason` each get `review` and `quiz`.
  - New enums: `review_due_reason` (schedule, quiz_miss), `review_source` (learned, relearned, review, brushup, implicit, quiz_miss, backfill) and `quiz_status` (pending, active, finished, cancelled).
- New tables, following the 0007 helpers (`_tenant`, `_tenant_fk`, `ix_<t>_org_id`). Each gets RLS on.
  - `review_card`: PK `(student_id, concept_id)` and the columns from the spec, with `CHECK credit >= 0` and index `(org_id, student_id, due)`.
  - `review_log`: an identity bigint id, with composite FKs to `practice_session` and `quiz` and index `(org_id, student_id, concept_id, created_at)`.
  - `quiz`: has `uq_quiz_id_org_id` for the composite FKs, unique `(student_id, xp_mark)` and partial unique `(student_id) WHERE status IN ('pending','active')`.
    - The spec says `<> 'finished'`, but cancelled quizzes must also stop blocking the next one, so the plan uses `IN ('pending','active')`. This is noted in the spec.
  - `quiz_item`: PK `(quiz_id, position)`, with content FKs to item and concept.
- `practice_session`:
  - Add `quiz_id`, with a composite FK to `quiz`.
  - Rewrite `ck_practice_session_kind_links` to the spec's expression.
  - Add partial uniques: `uq_practice_session_active_review` on `(student_id, concept_id) WHERE status='active' AND kind='review'`, and `uq_practice_session_quiz` on `(quiz_id) WHERE kind='quiz'`.
  - The existing `uq_practice_session_active_practice` predicate already includes `kind='practice'`, so it's fine.
- `attempt`: rewrite `ck_attempt_session_iff_practice` to the 5-context list.
- `xp_event`: drop `uq_xp_event_session` and create unique `(session_id, subject) WHERE session_id IS NOT NULL`.
- **Backfill data step**:
  - Select learned `concept_state` rows whose concept is not retired and has an active `kp_question` item of a quick type.
  - In Python, apply `Scheduler(...).review_card(Card(), Rating.Good, learned_at)` with the same config as `srs.py`. The config is duplicated inline, so the migration doesn't import app code.
  - Insert cards plus `review_log(source='backfill')`, with `ON CONFLICT DO NOTHING`.
- Downgrade reverses everything. It deletes review/quiz sessions, attempts and xp rows first, then shrinks the enums (`_shrink_enum`, dropping and recreating the dependent partial indexes as 0005 does).

### 2. Models (`models/learning.py`)
- Add enum members, the `ReviewDueReason`, `ReviewSource` and `QuizStatus` enums, and the models `ReviewCard`, `ReviewLog`, `Quiz` and `QuizItem`.
- Add `PracticeSession.quiz_id` and update the constraint and index definitions, so `test_models_match_migrations` stays green.
- Add the new tables to `TENANT_TABLES` in `tests/conftest.py` and to the sets in `test_rls_db.py`.

### 3. `app/services/srs.py` (new)
**Pure functions:**
- `SCHEDULER`, configured exactly as in the spec.
- `to_fsrs(card_row)` and `from_fsrs(...)`. The state is always Review and the step is None.
- `due_on(due) -> date` (IST), and `min_tomorrow(due, now)`, which pushes `due` to the next 00:00 IST if `due_on <= today`.
- `rating_for(outcome, all_correct)`.
- `earliness(last_review, due, now)` (span ≤ 0 → 1).
- `implicit_share(w, n_kps, kind: Literal["kp","review","brushup","practice"])`.
- `credit_step(credit, share, earliness) -> (new_credit, fire: bool)`, using the 1e-6 tolerance.
- `struggling(consecutive_fails, last_relearn_at, now)`.
- `retrievability(card_row, at)`, using `SCHEDULER.get_card_retrievability`.
- `order_queue(cards: list[QueueCard]) -> list[QueueCard]`:
  - sort by retrievability ascending, ties broken by `concept_id`;
  - round-robin by subject;
  - greedy pick that avoids the same chapter next to itself when it can;
  - deterministic.
- `cap_left(done_today, cap=5)`.

**DB functions** (take `OrgScope`, never commit):
- `gradable(scope, concept_ids) -> set[UUID]`: concepts with an active quick `kp_question` (reuse `frontier.active_kps(...).quick`).
- `on_learned(scope, concept_id, at)`:
  - Insert the card with `ON CONFLICT DO NOTHING`, applying `Good` at `at` and logging `learned`.
  - If the card already exists, run the relearned path instead: apply `Good`, `consecutive_fails=0`, `credit=0`, `due_reason=schedule`, and log `relearned`.
- `apply_review(scope, concept_id, outcome, all_correct, source, session_id) -> ReviewInfo`:
  - Lock the card, rate it, and apply `min_tomorrow`.
  - Update `consecutive_fails` and reset `due_reason` to schedule.
  - Log a row with the old `due_reason` and the before/after values.
  - Return `{rating, next_due, consecutive_fails}`.
- `give_implicit_credit(scope, concept_id, kind)`:
  - Loop over the direct prerequisites of `concept_id` (`ConceptPrereq`) and their `encompassing_weight`.
  - Skip a prerequisite when it has no card, isn't learned, is retired, has `due_reason=quiz_miss`, or is struggling.
  - Otherwise add credit and log `implicit` with `credit_added`. When credit fires, apply `Good` at now.
- `mark_quiz_miss(scope, concept_ids, quiz_id)`.
- `queue(scope) -> ReviewQueue`:
  1. Lazily create missing cards for learned gradable concepts (the "appears later" rule).
  2. Load the student's cards, joined to concept, chapter and course, filtered to learned, not retired and no `review_due` remediation.
  3. Split them into quiz-miss and scheduled.
  4. Count `done_today` from today's `review_log` rows (`source=review`, `due_reason=schedule`).
  5. Return quiz-miss cards, plus active-session cards, plus the first `5 − done_today` due scheduled cards in `order_queue` order (retrievability at 00:00 IST today). Also return `more_due` and `next_due_on`.
- `offer_status(scope, concept_id) -> "offered" | "cap" | "not_due"`, used by the review start.
- `due_count(scope, student_ids)` for the roster: due, offerable and uncapped. It is read-only, with no lazy creates.

### 4. `kp_flow.py` / `frontier.py` / `practice.py` changes
- `frontier.mark_learned`: after the update, call `srs.on_learned(scope, concept_id, now)`. Use a lazy import to avoid an import cycle.
- `kp_flow`:
  - `_review_kps(scope, concept_id)` (callers updated; no behaviour change).
  - `_start_kp_session` calls `await quiz.ensure_no_pending(scope)` just before the insert at L971.
  - In `answer`, after a pass award (L1046), call `srs.give_implicit_credit(scope, concept_id, "kp")`.
  - `remediation_answer`:
    - After the award, call `srs.apply_review(prereq, outcome, all_correct, source=brushup)`.
    - On a pass, also call `give_implicit_credit(prereq, "brushup")`.
    - On a fail, the existing `_relearn` still runs. `apply_review` increments `consecutive_fails` first; `on_relearned` resets it later.
    - Note that `answer_in_session`'s `results` gives `all_correct`.
- `practice.practice_question`: call `quiz.ensure_no_pending` after `_gate` and before `_locked_session` / `_start`.
  - The ordering subtlety: the spec says "just before a new session is created". So the check runs only when no active session exists. Staff, preview and "again" return earlier and aren't affected.

### 5. `app/services/reviews.py` (new)
- `review_question(scope, course, concept)`:
  1. Require a student and resolve the concept within the course (404 otherwise).
  2. Lock the active review session.
  3. If there is none, use `srs.offer_status` to raise `review_cap` or `review_not_due`. Otherwise insert `PracticeSession(kind=review, concept_id)` with `on_conflict_do_nothing` and serve position 1 through `_review_pool` / `_serve`.
  4. An empty pool counts as a pass: run `_finish(passed)` with no XP, matching the brush-up empty-question path, then raise 409 `review_not_due`.
  5. Call `quiz.finish_if_over` first, since this is a student read. Commit.
- `review_answer(scope, course, concept, body)`:
  1. Run `answer_in_session(..., AttemptContext.review, review_outcome, owner=kind==review & concept_id==...)`.
  2. While the session is active, serve the next question; an empty pool counts as a pass.
  3. When it ends:
     - `xp.award_for_session(session, outcome, concept_id)`;
     - `srs.apply_review(source=review)`;
     - on a pass, `give_implicit_credit("review")`;
     - on a fail with `consecutive_fails >= 2`, `kp_flow._relearn` (`next_due=None`, `relearn=True`).
  4. Set `out.review = ReviewOutcomeOut`. Resends go through `_stored_result`, which also re-attaches `review` from the session's `review_log` row. Commit.

### 6. `app/services/quiz.py` (new)
**Pure functions:**
- `choose_items(concepts_by_retrievability, kp_pools, history, rng) -> list[Pick]`:
  - one per concept, then cycle (next KP);
  - fixed items never repeat, param items may;
  - stop at 10 or when nothing is left;
  - interleave by subject with `srs.order_queue`'s interleaver.
- `deadline_for(started_at, total)`: 90 s × total; `is_late(now, deadline)` adds 30 s grace.
- `next_mark(lifetime_after)` = lifetime + 150; `should_create(lifetime, mark, learned_gradable)`.

**DB functions:**
- `current_mark(scope)`: the latest finished or cancelled quiz's `next_mark`, else 150.
- `maybe_create(scope)`: if there is no pending/active quiz, lifetime ≥ mark and there are ≥ 3 learned gradable concepts, insert a pending quiz `ON CONFLICT DO NOTHING`.
- `ensure_no_pending(scope)` raises 409 `quiz_pending {quiz_id}`.
- `current(scope)`: runs `finish_if_over`, then returns `QuizState`. The state includes `seconds_left`, computed server-side so the client timer is immune to clock skew; this is a small addition to the spec's shape.
- `start(scope, id)`: idempotent.
  - Choose the items. With 0 concepts, cancel the quiz: `next_mark` = lifetime + 150.
  - Otherwise write `quiz_item` rows, set `started_at` / `deadline` and create the `practice_session(kind=quiz, quiz_id)`.
  - Mirror position 1 into the session's `current_*`, using `kp_flow.serve_item`.
- `question(scope, id)`:
  - Errors: `quiz_not_started` / `quiz_over`.
  - Serve the current `quiz_item` with its stored seed. Build the response with `kp_flow._question`, with `results=[]` and `deadline` set.
- `answer(scope, id, body)`:
  1. Run the lazy finish check; late → `quiz_over`; a position mismatch → `stale_question`.
  2. Grade with `kp_flow._grade_answer`, then insert the `attempt` (`context=quiz`, conflict do nothing). A resend returns `saved` again.
  3. Advance `current_*`. After the last position, call `_finish`.
  4. Return `{saved, answered, finished}`.
- `_finish(scope, quiz, now)`:
  1. Set `correct` and `total`, and the session to passed. Missed concepts → `srs.mark_quiz_miss`.
  2. `xp.award_for_quiz`, then set `next_mark` = lifetime (after the award) + 150 and status to finished.
  3. `finish_if_over` calls `_finish` when now > deadline + grace.
- `result(scope, id)`:
  - 409 `quiz_not_finished` before the end.
  - Per item: regrade the stored attempt to get `display_answer` and `explanation_md` (unanswered → `response=null`, `correct=false`).
  - Also returns the `review_concepts` and the per-subject XP split.
- `last_quiz_stats(scope, student_ids)`: last finished quiz → `{score_pct, finished_on}`. Read-only.

### 7. `services/xp.py`
- `XpReason` gets `review` and `quiz`. `award_for_session` accepts review sessions (no change beyond the enum) and uses the new conflict target.
- Add `lifetime_xp(scope, student_id=None)`.
- Pure `quiz_xp(items: list[QuizPos]) -> XpCalc`, applying the spec's per-subject rules and reusing `is_rushed` and `_round`.
- `award_for_quiz(scope, quiz, session, picks) -> QuizXpOut`:
  - one `xp_event` per subject, carrying `session_id` and that subject's first `concept_id`;
  - `_bump_days` per event;
  - returns the total plus `subjects: [{subject, amount, grade}]` and `goal_met_today`.
  - `QuizResult.xp` uses this shape (total for the toast, split for the result). The spec's `XpAwardOut` can't carry a split.
- `maybe_create` runs after `award_for_session` and `award_for_quiz`. It is a lazy `from app.services import quiz` inside the function, which avoids the import cycle.

### 8. Schemas + routes
- `schemas/reviews.py`: `ReviewQueue`, `ReviewOffer` and `ReviewOutcomeOut`.
- `schemas/quiz.py`: `QuizState`, `QuizSaved`, `QuizResult`, `QuizResultItem` and `QuizXpOut`.
- `schemas/kp.py`: `QuestionPublic.deadline: datetime | None`, `AnswerResult.review: ReviewOutcomeOut | None`.
- `api/v1/reviews.py`: `GET /reviews`, `GET /reviews/{course}/{concept}/question` and `POST .../answer`.
- `api/v1/quiz.py`: `GET /quizzes/current`, `POST /quizzes/{id}/start`, `GET /quizzes/{id}/question`, `POST /quizzes/{id}/answer` and `GET /quizzes/{id}/result`.
- Both are registered in `router.py`, and all use `Scope`.
- Roster:
  - `ClassStudentOut` gains `reviews_due: int = 0` and `last_quiz: LastQuizOut | None`.
  - It is filled in `tenancy.list_class_students` (`services/tenancy.py:561`) beside `xp.roster_stats`.

## Frontend
- `lib/types.ts`:
  - New: `ReviewQueue`, `ReviewOffer`, `ReviewOutcome`, `QuizState`, `QuizSaved` and `QuizResult`.
  - Extended: `AnswerResult.review`, `Question.deadline`, `ClassStudent.reviews_due` / `last_quiz`.
- `features/reviews/`:
  - `api.ts`: `reviewKeys`, `useReviewQueue`, `useReviewQuestion` and `submitReviewAnswer`.
  - `TodaysReviews.tsx`:
    - header "n of 5 done today"; rows linking to `/review/:course/:concept`, with a "From your quiz" badge;
    - both empty states; skeleton and error with retry;
    - hidden when the student has no cards (the API also returns `has_cards`).
  - `ReviewPage.tsx`:
    - modelled on `RemediationPage`: `PracticeRunner` with header "Review: {title}";
    - `renderConflict` handles `review_cap` / `review_not_due` (friendly panel + home link);
    - end screens for pass / first fail / relearn, using `result.review`.
- `features/quiz/`:
  - `api.ts`.
  - `QuizBanner.tsx`: Start / "Resume quiz · m:ss left", built on the warning banner style from `SlipsView`.
  - `QuizTimer.tsx`:
    - counts down from `seconds_left` with a performance.now() anchor;
    - sticky, `tabular-nums`, warning colour under 60 s;
    - fires `onExpire`.
  - `QuizPage.tsx`:
    1. Intro screen with the rules and **Start**.
    2. Then per question: `AnswerForm` with `marked={null}` and `key={position}`, submit → "Saved" → refetch the next question.
    3. A `quiz_over` 409 or the timer expiring goes to the result.
  - `QuizResult.tsx`:
    - an SVG score ring "8 / 10";
    - the XP toast via `showAwardToast` (using the total; the dedupe key is the quiz id);
    - a per-subject split;
    - a list of `<details>` items, collapsed on phones (open by default at `sm+`);
    - "Added to your reviews" and "Back to learning".
  - `QuizPendingPanel.tsx`.
- Changed:
  - `StudentHome.tsx`: banner and reviews card between the h1 and the courses.
  - `LessonPage.tsx` KP `renderConflict` (L94), `PracticeStep.tsx` (L56) and `RemediationPage` are untouched: brush-ups aren't blocked. `quiz_pending` → `QuizPendingPanel`.
  - `awardToast.ts`: optional `reason` for review/quiz copy.
  - `ClassDetailPage.tsx`: "Reviews due" and "Last quiz" columns after Streak.
  - `routes.tsx`:
    - `/review/:course/:concept` as a lazy route inside AppShell;
    - `/quiz/:id` as a sibling of AppShell under `RequireAuth` → `RequireRole access="student"`, so it renders with no nav.
- Invalidation: after a review or quiz ends, invalidate `learnKeys.all`, `reviewKeys.all`, `quizKeys.current` and `xpKeys.me`.

## Docs
- ARCHITECTURE:
  - decisions 9 and 11 (lapse-then-relearn, credit + earliness, struggling, cap 5; 10 questions / 15 min, blocking, lifetime XP);
  - domain-model entries for `review_card`, `review_log`, `quiz` and `quiz_item`;
  - Stack row for the `fsrs` version.
- ROADMAP: 007 done note.
- Spec: status → implemented. Note two small refinements: `seconds_left` on `QuizState`, and `QuizResult.xp` as a total-plus-split; the partial unique index excludes cancelled quizzes too.

## Tests
- `tests/test_srs_rules.py` and `tests/test_quiz_rules.py` (pure, offline): every bullet in the spec's Verification lists.
- `tests/test_reviews_db.py` and `tests/test_quiz_db.py` use the `learn_helpers.world`, `learn_concept` / `answer_kp` helpers and `_slow_down` from `test_xp_db`. They seed `review_card.due` / `xp_event` directly where waiting is needed. They cover every DB bullet in the spec, including 404 across schools and 403 for staff.
- `test_migrations_db.py`: add `test_0008_backfills_cards` (downgrade to 0007, insert a learned `concept_state`, upgrade, assert the card plus a `backfill` log row).
- Existing tests to keep green: `test_xp_db.py`, which exercises the conflict-target change; `test_kp_api_db.py` and `test_practice_api_db.py`; `test_route_scoping.py`.
- Vitest:
  - `TodaysReviews`, `QuizBanner`, `QuizTimer` (fake timers), `QuizPage`, `QuizResult` and `ReviewPage` end screens;
  - `LessonPage` / `QuestionStep` `quiz_pending` → panel;
  - all using `routeFetch` / `jsonResponse` from `test/render.tsx`.

## Build order + commits
1. Branch. Commit the spec and PRD edit.
2. `uv add fsrs`, the migration and models. Check: `uv run mypy`, `test_migrations_db`, `test_rls_db`.
3. `srs.py` and its rule tests, then the hooks in frontier, kp_flow and practice. Commit: backend reviews core.
4. `reviews.py`, its routes and its DB tests. Then `quiz.py`, the xp changes, the quiz routes and their DB tests. Then the roster. Commit: backend.
5. Frontend pieces and vitest. Commit: frontend.
6. Docs. Commit.

## Verification
- `cd backend && uv run mypy` and `cd frontend && pnpm typecheck` clean. `make check` green (offline, includes the new rule tests). `make test-db` green (needs `TEST_DATABASE_URL`).
- Run the manual script (spec Verification, steps 1–7) under `make dev`, seeding `review_card.due` / `quiz.deadline` / `xp_event` via SQL where waiting is needed.
- Browser check (Claude in Chrome):
  - home (reviews card, quiz banner, empty states);
  - a review (pass / fail / relearn);
  - the quiz (intro, timer warning, time-out → result);
  - the result at desktop and 360 px;
  - the teacher roster.
  - Screenshots of each. **I'll ask you for a dev student and teacher login at that point.**
- Then the `reviewer` subagent against the spec, then `/ship`.
