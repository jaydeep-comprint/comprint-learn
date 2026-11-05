# Spec 007: Reviews + quizzes

Status: implemented (Nov 2026)
PRD link: docs/PRD.md#mvp-scope-v1 (item 6)
Builds on: [spec 005](005-kp-flow-knowledge-graph.md) (`practice_session`, `review_outcome`, round-robin review
serving, remediation brush-ups, `_relearn`, IST day), [spec 006](006-practice-formats.md) (practice sessions),
[spec 008](008-xp-gamification.md) (XP ledger, `session_xp`, lifetime XP). **Built after 008** (ROADMAP note).

## Summary
Every learned concept gets a spaced-repetition card (FSRS, one per student × concept). When a card is due, the student
sees it in **Today's reviews**: a 3–5 question review of that concept, judged on the trend as in 005. Up to 5
reviews are offered a day, mixed across subjects. Passing lessons and reviews gives one-level **implicit credit** to
prerequisites, so they come up for review less often. Every 150 lifetime XP unlocks a **timed mixed quiz** of 10
questions over everything learned. Until the student takes it, they can't start new KP tries, and every missed
question becomes a review. Reviews and quizzes earn XP through 008's ledger. Teachers see "Reviews due" and "Last
quiz" in the roster.

## User stories
- As a student, I want a short daily list of reviews picked for me, so I don't forget what I learned.
- As a student, I want learning advanced topics to count as practice of the basics, so I'm not asked to review
  things I'm already using.
- As a student, I want a quiz now and then that mixes everything, so I know what has stuck, and my misses come back
  as reviews.
- As a teacher, I want to see who has reviews piling up and how each student's last quiz went.
- As our team, I want every scheduling change logged with its cause, so we can tune retention against the PRD's
  "≥ 70% of due reviews answered correctly".

## Behaviour

### Terms
- **Card**: `review_card`, FSRS state per student × concept.
- **Review**: one `practice_session` of kind `review` on one concept. It has 3–5 questions drawn round-robin across
  the concept's active KPs and is judged by 005's `review_outcome`. This follows Math Academy: a review covers one
  topic, interleaving happens **across** reviews, and the quiz is the mixed task.
- **Brush-up**: 005's remediation review, which stays as it is (see "Brush-ups").
- **Explicit review**: a review or a brush-up. **Implicit review**: credit from passing a dependent concept's work.

### FSRS setup (`app/services/srs.py`)
- Library: **`fsrs`** (py-fsrs, the version current at build time, ≥ 6), added with `uv add fsrs` (the lockfile is
  never edited by hand). One module-level `Scheduler(desired_retention=0.9, learning_steps=(), relearning_steps=(),
  enable_fuzzing=False)` with default parameters. Empty step lists keep every card in the Review state (day-scale
  intervals only), and no fuzzing keeps tests deterministic.
- **Day granularity**: a card is **due on** the IST date of `card.due`. It is due when that date ≤ today (IST). The
  next due date is always at least tomorrow (if FSRS returns a time earlier today, it is moved to the next IST day).
- **Ratings** (pure `rating_for(outcome, all_correct) -> Rating`):
  - passed and every answer correct → `Good`;
  - passed after a miss → `Hard`;
  - failed → `Again`.
  - `Easy` is never used.
- Every change to a card writes one `review_log` row (append-only; see Data model).

### When a card is created or updated
| Event | Card effect | `review_log.source` |
|---|---|---|
| Concept becomes learned (`frontier.mark_learned`, any `source`) with no card | Create a card and apply `Good` at `learned_at` | `learned` |
| Concept learned again after a relearn (card exists) | Apply `Good` at `learned_at`, `consecutive_fails = 0`, `credit = 0`, `due_reason = schedule` | `relearned` |
| Review ends (passed / failed) | Apply `rating_for(...)` at the session end | `review` |
| Brush-up ends (passed / failed) | Apply `rating_for(...)` to the prerequisite's card | `brushup` |
| Implicit credit reaches 1.0 | Apply `Good` now, `credit = 0` | `implicit` |
| Quiz finished with ≥ 1 miss on the concept | `due = now`, `due_reason = quiz_miss` (FSRS state untouched) | `quiz_miss` |
| Deploy backfill | See "Backfill" | `backfill` |

- A concept with **no gradable KP items** (no active `kp_question` items of type numeric, expression or mcq) gets no
  card. If one appears later, the card is created on the next read of the review queue (as in `learned`, at now).
- A card whose concept is **not learned** (relearn in progress) or **retired** is never offered and gets no credit.
  It is kept and resumes after a relearn (row above).

### Failing a review (lapse, then relearn)
- **First failed review**: `Again`. The concept stays learned, `consecutive_fails = 1`, and the card is due tomorrow
  at the earliest (FSRS decides; the min-tomorrow rule applies).
- **Second consecutive failed explicit review** (review or brush-up) → **relearn** using 005's `_relearn` (concept
  back to in progress, KPs reset, history kept, open brush-ups on it become relearns).
- Any passed explicit review sets `consecutive_fails = 0`.
- **Brush-up fails keep 005's rule** (one failed brush-up = relearn). The card still gets `Again` first.

### Brush-ups (005 remediation reviews)
- They stay triggered by KP fails, are shown first, and are **outside the daily cap**. Their routes and rules are
  unchanged.
- A brush-up's result **also counts as an explicit FSRS review** of the prerequisite (table above), so the prereq
  isn't reviewed twice.
- While a concept has a `review_due` brush-up, its card is **not offered** in Today's reviews.

### Implicit credit (one level)
- **Triggers**, for a concept C. Each trigger gives each **direct** prerequisite P of C (`concept_prereq`, any
  course) a share of P's `encompassing_weight` w:
  - a passed KP session in C: `w / n`, where n is the number of active KPs in C, so learning all of C gives about w
    (decided while specifying);
  - a passed review **or brush-up** of C: `w` (decided while specifying).
  - Practice sessions give no credit, so learning all of C gives exactly w (decided while specifying).
- **Earliness**: `clamp((now − last_review) / (due − last_review), 0, 1)`. Credit right after a review is worth
  nothing, and credit when the card is due or overdue is worth everything (Math Academy's "discounted when early").
- `P.credit += share × earliness` (`credit` is float8). When `credit ≥ 1 − 1e-6`, apply `Good` at now, reset
  `credit = 0` (any overflow is dropped) and log `implicit`. No credit is added while P's `due_reason = quiz_miss`
  (decided while specifying).
- **Only one level**: an implicit review never passes credit on to P's own prerequisites. Failures pass no penalty up
  (full FIRe is v2).
- **Switched off for struggling** (per prerequisite P), when either:
  - P's last explicit review (review or brush-up) failed (`consecutive_fails > 0`), or
  - P was relearned in the last 30 days (a `review_log` row with source `relearned` within 30 days).
- Skipped when P has no card, isn't learned, or is retired. Credit is computed in the same transaction as the
  triggering answer. Pure function `implicit_share(w, n_kps, kind)` and `earliness(card, now)`.

### Today's reviews (the queue, computed on read)
- **Daily cap: 5 scheduled reviews per IST day**, across all subjects. A review counts against the cap when its
  session ends (passed or failed) with `due_reason = schedule`. Quiz-miss reviews and brush-ups never count.
- **Offered list** = quiz-miss cards (uncapped, shown first) + up to `5 − done_today` scheduled cards that are due,
  learned, not retired and have no `review_due` brush-up.
- **Order** of scheduled cards: lowest FSRS retrievability now first. Then **interleave**: round-robin by subject
  (subject of the concept's course), and within the round-robin never put two concepts from the same chapter next to
  each other when another choice exists. The list is stable within a day (same inputs → same order).
- Due cards beyond the cap roll over to the next day; nothing is lost.
- A started review (active session) stays in the list until it ends, even if the cap would now hide it.
- Starting a review that isn't in the offered list → 409 `review_not_due` ("This review isn't due today."). When the
  cap is reached → 409 `review_cap` ("That's today's reviews done. More tomorrow.").

### Review sessions
- `GET /reviews/{course}/{concept}/question` opens (or resumes) the session. One active review per student × concept
  (partial unique index). Serving, seeds, reload behaviour, `stale_question` / `already_answered` and time capping all
  work as in 005's brush-up (round-robin across the concept's active KPs, each KP's pool by 005's serving rules,
  fresh seeds, `review_outcome`).
- A review isn't blocked by a pending quiz.
- On end: card update (rating), implicit credit if passed, XP (reason `review`, same rule as `remediation`: partial
  allowed, rush penalty applies), and relearn on a 2nd consecutive fail. All in the same transaction.
- The result carries `review: {rating, next_due: date | null, relearn: bool}`. `next_due` is null when a relearn
  started.
- A review whose question pool runs out (retired content) passes, as 005's brush-up does.

### Quizzes
- **Trigger**: after every XP award (008's `award_for_session` and `award_for_quiz`, same transaction), if the
  student has no `pending` or `active` quiz and `lifetime net XP ≥ next_mark`, create a quiz with `xp_mark =
  next_mark`, status `pending`. Lifetime XP is all subjects, net (negatives count, as stored).
  - `next_mark` = 150 with no quiz yet. After a quiz **finishes**, `next_mark` = the student's lifetime net XP at that
    moment (including the quiz's own XP) + 150, stored on the finished quiz as `next_mark`. Quizzes are therefore
    **never back-to-back**: a student who jumped from 150 to 470 XP gets one quiz, and the next one comes at 470 +
    quiz XP + 150 (user decision in the builder check).
  - **Not created** while the student has **< 3 learned concepts with gradable items**. The check runs again on the
    next award.
- **Blocking**: while a quiz is `pending` or `active`, the server refuses to **open a new** KP or practice session
  (409 `quiz_pending`, "Take your quiz to keep learning.", `{quiz_id}`). Already-open sessions can be finished.
  Reading lessons, reviews, brush-ups, "Practise again" (no XP) and staff previews stay allowed.
- **Contents** (chosen when the quiz **starts**, stored on `quiz_item`): 10 questions from active `kp_question` items
  of type numeric, expression or mcq (no code or multistep, which take too long under a timer) in the student's
  learned, non-retired concepts across all subjects:
  - concepts ordered by lowest retrievability first. One question per concept until 10, then cycle again (a different
    KP of the concept where possible). With 3–9 concepts some concepts get 2+ questions;
  - item per KP chosen by 005's serving rules (least recently answered), with a fresh seed for param items;
  - question order interleaved by subject, as in the review queue.
  - The "~80% average" target isn't tuned in the MVP: we log quiz scores and measure it (decided while specifying).
- **Timer**: 1.5 min per question (15 min for 10), one shared countdown from `started_at`. The server enforces it:
  answers received after `deadline + 30 s` grace → 409 `quiz_over`. The quiz is finished when every question is
  answered, or on the first read or write after the deadline (computed lazily, nothing scheduled). Unanswered
  questions count as wrong.
- **Flow**: questions in order, one at a time, no going back, **no feedback until the end** (each answer gets only
  "Saved"). There's no "skip" or "I don't know" button. The student must answer to move on, or let time run out. No
  notes: the quiz page hides the app navigation. That isn't enforced beyond the UI.
- **Leaving**: the timer keeps running. Reopening `/quiz/:id` resumes at the next unanswered question.
- **Result**: score (correct / 10), and per question the prompt, the student's answer, correct or not, the correct
  answer for their numbers and the explanation (only now). Missed concepts are listed as "Added to your reviews".
- **Misses become reviews**: for each concept with ≥ 1 missed or unanswered question, the card becomes due now with
  `due_reason = quiz_miss`, outside the cap. A correct quiz answer doesn't change the card (one question isn't a
  review) (decided while specifying).
- **XP** (reason `quiz`): **one event per subject in the quiz** (user decision in the builder check), so quiz XP
  counts towards that subject's daily goal, weekly leaderboard and roster like any other work. Each event carries
  the quiz's `session_id` and the `concept_id` of that subject's first quiz item. The unique index on
  `xp_event.session_id` becomes unique on `(session_id, subject)` where `session_id` is not null.
  - **Per-subject grade** (pure `xp.quiz_xp`, over that subject's items; `base` = Σ `expected_minutes` of the
    correctly answered items):
    - `perfect`: all of the subject's items correct, × 1.2;
    - `passed`: ≥ 1 correct, × 1.0;
    - `poor`: 0 correct, 0;
    - `rushed` replaces `poor`/`passed` only when **fewer than half** of the subject's items are correct **and** ≥
      min(2, answered wrong) *answered* wrong items were faster than 008's `is_rushed` threshold. Unanswered items
      never count as rushed. Penalty: −0.25 × Σ `expected_minutes` of the subject's items, at least −1 (decided
      while specifying).
  - No hints in quizzes. Rounding follows 008.
  - A quiz finished by **time-out** earns XP like one finished by its last answer. This is an explicit exception to
    008's "side-effect closes earn nothing" (decided while specifying).
  - Written by `xp.award_for_quiz`, which updates `xp_day` for each subject as `award_for_session` does. The toast
    shows the total, and the result shows the per-subject split.
- Staff can't take quizzes (student-only routes). Students never see another student's quiz (`OrgScope` +
  `student_id`, 404).

### Backfill (migration)
- For every `concept_state` with `status = learned` (any concept with gradable items) the migration creates a card as
  if `learned_at` were a first `Good` review (computed with py-fsrs inside the data migration, so cards learned long
  ago may already be due). The daily cap spreads them out. Logged with source `backfill`.
- No quizzes are created by the migration. The first one is created on the student's next award once lifetime XP ≥
  150.

### Errors (summary)
- 409 `review_not_due`, 409 `review_cap`, 409 `quiz_pending` `{quiz_id}`, 409 `quiz_over`, 409 `quiz_not_started`
  (answer before start), 409 `stale_question` / `already_answered` (as in 005), 404 for another student's or
  school's quiz or card, 403 for staff on student-only routes (existing error).

## UI / UX
### Student
- **Home** (`/`): above the course cards:
  - **Quiz banner** (when a quiz is pending or active): "Quiz time! 10 questions · 15 minutes · no notes", with a
    **Start quiz** button (or **Resume quiz · 9:12 left**). Under it: "New lessons are paused until you take it."
  - **Today's reviews** card: a list of the offered reviews ("Acceleration · Physics", a "From your quiz" badge on
    quiz-miss ones), each linking to `/review/:course/:concept`. Header "3 of 5 done today". Empty states: "No reviews
    due. Next one on 12 Nov." / "That's today's reviews done 🎉". The card is hidden when the student has no cards at
    all. It has loading and error states like the other home cards.
  - The course cards' existing **Brush up** lists are unchanged.
- **Lesson pages**: with a quiz pending, a KP question step that would open a new session shows the quiz panel ("Take
  your quiz to keep learning" + button) in place of the question. The same applies to the Practice step. An open
  session continues normally.
- **Review page** `/review/:course/:concept`:
  - Title "Review: {concept}", "Question n of 3–5".
  - It reuses `QuestionStep` / `AnswerForm` / `ResultPanel` (feedback after each answer, as in brush-ups).
  - End screen:
    - passed: "Nice, see you again on {next_due}";
    - first fail: "We'll review this again tomorrow";
    - relearn: "Let's relearn {concept}", with a link to the lesson.
  - 008's XP toast as usual. A 409 `review_cap` / `review_not_due` shows a friendly panel with a link home.
- **Quiz page** `/quiz/:id`:
  - The app navigation is hidden. A sticky countdown appears (`mm:ss`; warning colour under 1 min). "Question n of 10".
  - The answer inputs are reused, with **Submit** → "Saved" → next question.
  - Before start: an intro screen with the rules and a **Start** button (starting sets the timer).
  - On time-out mid-question: the current input is **not** auto-submitted (decided while specifying). Go to the result.
  - **Result screen**: the score ring "8 / 10", the XP toast, and a list of questions (✓ / ✗, your answer, the
    correct answer, the explanation, collapsed by default on phones). Then "Added to your reviews: …" and "Back to
    learning".
  - Works at 360 px.

### Teacher
- **Class roster** (ClassDetailPage) gains two columns:
  - **Reviews due**: the number of due, offerable cards today, uncapped; quiz-miss cards included.
  - **Last quiz**: "80% · 3 Nov", or "—".
- No other teacher views (010 owns the memory view and at-risk rules).

## Technical design
- Files / modules touched:
  - Backend (new):
    - `app/services/srs.py` (scheduler, `rating_for`, `earliness`, `implicit_share`, `order_queue` pure;
      `on_learned`, `on_relearned`, `apply_review`, `give_implicit_credit`, `queue`, `due_count`);
    - `app/services/reviews.py` (review question/answer, reusing `kp_flow.answer_in_session`, `_review_pool`,
      `_serve`);
    - `app/services/quiz.py` (`maybe_create`, `start`, `question`, `answer`, `finish_if_over`, `result`,
      `last_quiz_stats`, `choose_items` pure part);
    - `app/schemas/reviews.py`, `app/schemas/quiz.py`;
    - `app/api/v1/reviews.py`, `app/api/v1/quiz.py` (registered in `router.py`).
  - Backend (changed):
    - `models/learning.py` (enums + new models below);
    - `services/frontier.py` (`mark_learned` → `srs.on_learned` / `on_relearned`);
    - `services/kp_flow.py`:
      - `_start_kp_session` refuses on a pending quiz;
      - a passed KP → `srs.give_implicit_credit`;
      - `remediation_answer` → `srs.apply_review(source=brushup)`, with relearn on a 2nd consecutive fail using the
        same `_relearn`;
      - `review_outcome` / `_review_pool` / `_serve` made reusable (move or re-export, no behaviour change);
    - `services/practice.py` (start refused on a pending quiz);
    - `services/xp.py`:
      - `XpReason` + `review`, `quiz`;
      - `award_for_session` handles `review` sessions;
      - new `quiz_xp` / `award_for_quiz`;
      - after every award → `quiz.maybe_create`;
    - `services/tenancy.py` + `schemas/tenancy.py` (roster `reviews_due`, `last_quiz: {score_pct, finished_on} | null`);
    - `schemas/kp.py` (`AnswerResult.review`);
    - `tests/test_route_scoping.py` (new routes scoped; none global).
  - Migration `alembic/versions/0008_reviews_quizzes.py`:
    - enum values;
    - new tables with RLS enabled;
    - `practice_session` / `attempt` constraint updates;
    - the backfill data step.
  - Frontend (new):
    - `src/features/reviews/{api.ts, TodaysReviews.tsx, ReviewPage.tsx}`;
    - `src/features/quiz/{api.ts, QuizBanner.tsx, QuizPage.tsx, QuizTimer.tsx, QuizResult.tsx, QuizPendingPanel.tsx}`.
  - Frontend (changed):
    - `features/learn/StudentHome.tsx` (banner + reviews card);
    - `QuestionStep.tsx` / `PracticeStep.tsx` (409 `quiz_pending` → `QuizPendingPanel`);
    - `features/xp/awardToast.ts` (review/quiz copy);
    - `features/classes/ClassDetailPage.tsx` (roster columns);
    - `lib/types.ts`;
    - `routes.tsx` (`/review/:course/:concept`, `/quiz/:id`, student guard; the quiz route renders without AppShell
      nav).
  - Docs:
    - ARCHITECTURE decision 9 (lapse-then-relearn; credit accumulation and earliness; struggling = recent fail /
      relearn; cap 5 across subjects) and decision 11 (10 questions / 15 min, blocking new KP tries, lifetime XP
      across subjects);
    - the domain model (`review_card`, `review_log`, `quiz`, `quiz_item`);
    - Stack row: `fsrs` version;
    - ROADMAP: 007 done note.
- Data model changes (tenant-owned: `TenantMixin`, composite FKs `(x_id, org_id)`, RLS on):
  - Enum values:
    - `session_kind` + `review`, `quiz`;
    - `attempt_context` + `review`, `quiz`;
    - `xp_reason` + `review`, `quiz`.
  - `practice_session`:
    - `concept_id` is now set for kinds `practice` **and** `review`;
    - new `quiz_id uuid null` (composite FK → `quiz`) for kind `quiz`;
    - the check is `(kind IN ('practice','review')) = (concept_id IS NOT NULL) AND (kind = 'quiz') = (quiz_id IS NOT
      NULL)` (plus the existing kp/remediation clauses);
    - partial unique `(student_id, concept_id) WHERE status = 'active' AND kind = 'review'`, and `(quiz_id) WHERE
      kind = 'quiz'` (one session per quiz).
    - A quiz is one `practice_session` (positions 1–N, 1-based like everywhere else; `concept_id` null), created at
      `start`. `current_*` mirrors the current `quiz_item`, so `attempt` uniqueness, `stale_question` and the XP
      `session_id` all work unchanged. Its `status` mirrors the quiz's (`active` → `passed` when finished, decided
      while specifying).
  - `attempt`: the session check becomes `context IN ('kp','remediation','practice','review','quiz')`.
  - `review_card`:
    - PK `(student_id, concept_id)`, `org_id`;
    - `stability float8`, `difficulty float8`, `due timestamptz`, `last_review timestamptz`;
    - `reps`, `lapses`, `consecutive_fails smallint default 0`;
    - `credit float8 default 0` (CHECK `credit >= 0`);
    - `due_reason review_due_reason (schedule|quiz_miss) default schedule`;
    - `created_at`, `updated_at`.
    - Index `(org_id, student_id, due)`.
    - The FSRS `Card` is rebuilt from these columns (state is always Review).
  - `review_log` (append-only):
    - `id bigint identity`, `student_id`, `concept_id`;
    - `source review_source (learned|relearned|review|brushup|implicit|quiz_miss|backfill)`;
    - `rating smallint null`, `session_id null`, `quiz_id null`;
    - `due_reason review_due_reason null`: the card's reason when an explicit review ran. The daily cap counts today's
      (IST) rows with `source = review` and `due_reason = schedule`;
    - `due_before`, `due_after`, `stability_before`, `stability_after` (null where not applicable), `credit_added
      numeric null`;
    - `created_at`.
    - Index `(org_id, student_id, concept_id, created_at)`.
  - `quiz`:
    - `id uuid`, `student_id`, `xp_mark int`;
    - `status quiz_status (pending|active|finished|cancelled)`, `next_mark int null` (set on finish or cancel);
    - `created_at`, `started_at null`, `deadline null`, `finished_at null`;
    - `correct smallint null`, `total smallint null`.
    - Unique `(student_id, xp_mark)`; partial unique `(student_id) WHERE status <> 'finished'`.
  - `quiz_item`: PK `(quiz_id, position)`, `org_id`, `item_id`, `concept_id`, `seed int null`.
  - Ids, numbers and dates only, with no personal data.
- API / interfaces (`/api/v1`, `OrgScope`, student-only unless noted):
  - `GET /reviews` → `ReviewQueue {cap: 5, done_today, offered: [{course, concept: ConceptRef, subject, reason:
    "schedule"|"quiz_miss", due_on, active: bool}], more_due: int, next_due_on: date|null}`.
  - `GET /reviews/{course}/{concept}/question` → `QuestionPublic`. `POST /reviews/{course}/{concept}/answer`
    `AnswerIn` → `AnswerResult` (+ `review`, `xp`).
  - `GET /quizzes/current` → `QuizState | null` `{id, status, total, minutes, deadline|null, answered}`.
  - `POST /quizzes/{id}/start` → `QuizState` (idempotent once started).
  - `GET /quizzes/{id}/question` → `QuestionPublic` (`position`, `deadline`) or 409 `quiz_over`.
  - `POST /quizzes/{id}/answer` `AnswerIn` → `{saved: true, answered, finished: bool}`. There is no correctness
    field until the quiz is finished.
  - `GET /quizzes/{id}/result` → `QuizResult {correct, total, xp: XpAwardOut|null, items: [{position, concept,
    prompt_md, response, correct, display_answer, explanation_md}], review_concepts: [ConceptRef]}`. Returns 409
    `quiz_not_finished` before the end (after the lazy finish check).
  - Answer keys only ever appear in `AnswerResult` (reviews) and `QuizResult` (after the end), never in a question.
  - Roster: `ClassStudentOut` + `reviews_due: int`, `last_quiz: {score_pct, finished_on} | null` (staff).

## Implementation notes (build)
- `QuizState` also carries `seconds_left` (computed on the server, so the client timer ignores clock skew), and
  there is a `GET /quizzes/{id}` for the quiz page. `QuizResult.xp` is `{amount, base_minutes, goal_met_today,
  subjects: [{subject, amount, grade}]}` (the toast total plus the per-subject split). `ReviewQueue` has `has_cards`.
- The open-quiz partial unique index is `status IN ('pending', 'active')`, so a cancelled quiz doesn't block the next.
- Reads after the deadline finish the quiz; answers are still accepted until the deadline + 30 s grace.
- A new quiz's mark is also above every earlier quiz's mark (unique `(student_id, xp_mark)` after penalties).
- Review time is logged as practice study time with the step `review` (like a brush-up's `remediation`).
- With the sample weights (0.7 on `speed-and-velocity` → `distance-and-displacement`), learning a dependant alone
  adds 0.7 credit: the implicit `Good` fires with earlier credit or a later review (verification step 4 seeds it).

## Builder-check decisions (decided while specifying)
- **Quiz answers bypass `answer_in_session`.** `quiz.answer` has its own grade-and-store path: it reuses
  `kp_flow._grade_answer` and writes the `attempt`, then returns only `{saved, answered, finished}`. Quiz
  `QuestionPublic` leaves `results` empty. A resent position returns `saved` again, never correctness.
  `QuestionPublic` gains an optional `deadline`. `GET /quizzes/{id}/question` on a pending quiz → 409
  `quiz_not_started`.
- **Who finishes a quiz lazily**: only the student's own quiz/review/home reads and writes. Staff reads never write.
  The roster shows the last **finished** quiz.
- **Short quizzes**: fixed (non-param) items never repeat within a quiz, and param items may repeat with new seeds.
  `total` = the questions available (≥ 3, at most 10), the timer is 1.5 min × `total`, and the UI copy uses `total`
  ("N questions · M minutes").
- **Quiz at start with too few concepts**: start with whatever gradable learned concepts exist (≥ 1). With 0 (all
  relearning), the quiz is `cancelled`: it stops blocking, earns nothing, and `next_mark` = lifetime XP + 150.
- **Every explicit review end resets `due_reason` to `schedule`** after logging the old value. The relearn update
  does too.
- **Queue stability**: retrievability is computed at 00:00 IST today, and ties are broken by `concept_id`.
- **Which concepts**: cards exist for every learned concept, whatever course it belongs to. `/reviews/{course}/{concept}`
  checks that the concept belongs to `course` and that the student has a card on it that is in the offered list; it
  doesn't require a class for that course.
- **Error order**:
  - `quiz_pending` is checked **after** the existing gates (`check_first`, `kp_order`, `kp_waiting`, `kp_passed`,
    the practice gate) and just before a new session is created.
  - A due scheduled card beyond the cap → `review_cap` (not `review_not_due`).
- **`mark_learned`**: `srs.on_learned` treats "a card already exists" as a relearn. Cards may be created from GET
  paths (`frontier.load(promote=True)`), which is acceptable because the write is idempotent (insert on conflict do
  nothing).
- **Brush-up fail**: apply `Again`, increment `consecutive_fails`, then 005's relearn. `on_relearned` resets it later.
- **Backfill reproducibility**: the migration calls py-fsrs at run time. It runs once, so it isn't pinned
  separately. Concepts with no gradable active items are skipped.

## Edge cases
- **Two tabs or a double submit** on a review or quiz: as in 005, the unique `(session_id, position, step)` lets one
  insert win. Two tabs starting the quiz: `start` is idempotent and the same deadline is returned.
- **Award that crosses 150 inside a session that ends a KP**: the quiz is created in that transaction. The next
  question of an **open** session is still served, but a new KP session isn't.
- **Lifetime XP drops below the mark** (penalties) after a quiz is created: the quiz stays pending.
- **< 3 learned concepts at 150 XP**: no quiz yet. Created on the first award after the 3rd learned concept.
- **Quiz started, concept retired mid-quiz**: the stored `quiz_item` is served as is (the item row still exists).
- **Quiz-miss on a concept now being relearned**: the card is marked, but not offered until it is learned again (then
  the `relearned` update resets `due_reason`).
- **Card due and a brush-up due on the same concept**: only the brush-up shows. Its result updates the card.
- **Implicit credit** on a card with `due − last_review = 0` (shouldn't happen): earliness = 1.
- **Credit from a concept in another course** (Physics → Maths prerequisite): applies normally (subject doesn't
  matter).
- **Review started yesterday, finished today**: it counts against today's cap (session end day).
- **Student with all three subjects and 20 due cards**: 5 a day, interleaved, oldest-memory first. The rest roll over.
- **Clock at IST midnight** during a review: the cap resets for the new day. A review active across midnight is still
  answerable.
- **Staff preview** of a lesson with a quiz pending: not blocked.
- **Deactivated student**: nothing scheduled runs. Cards just age.

## Out of scope
- Full multi-level FIRe: learning speed, repetition compression, penalties flowing up the graph (v2).
- Bundled multi-concept review sessions. Reviews of practice / code / multistep items (reviews and quizzes use KP
  questions only).
- Tuning the quiz to ~80% (measure first). Quiz difficulty adaptation. Teacher-scheduled quizzes.
- Notifications or reminders for due reviews or quizzes.
- Teacher memory view, at-risk rules ("falling memory"), per-student quiz history (010).
- Per-school timezones. Changing FSRS parameters per student (optimiser).
- Placement-learned concepts' cards (012 calls `mark_learned`, which already creates them).

## Verification (end-to-end)
- [ ] Unit (`tests/test_srs_rules.py`, no DB):
  - `rating_for` on every outcome.
  - The min-tomorrow rule at 23:59 and 00:01 IST.
  - `earliness` at 0, 50%, overdue.
  - `implicit_share` for KP / review / brush-up (practice gives none).
  - Credit accumulation reaching 1.0 → one `Good`.
  - Struggling switches credit off.
  - `order_queue`: retrievability order, subject round-robin, no adjacent same-chapter when avoidable, stable.
  - Cap arithmetic with quiz-miss cards excluded.
- [ ] Unit (`tests/test_quiz_rules.py`):
  - `choose_items` with 3 / 9 / 15 learned concepts (10 items, cycling, interleaved, no code/multistep).
  - `quiz_xp`: perfect, passed, poor, rushed.
  - Deadline + grace.
  - Mark arithmetic (150 → 470 XP gives one quiz; the next mark = lifetime XP at finish + 150; cancel sets it too).
- [ ] DB (`tests/test_reviews_db.py`, `tests/test_quiz_db.py`, `make test-db`):
  - Learning a concept creates a card. Relearning updates it.
  - A due card appears. A 6th review → 409 `review_cap`. A quiz-miss review is allowed past the cap.
  - Fail once → still learned, due tomorrow. Fail again → relearn (KPs reset). A pass in between resets the count.
  - A brush-up result updates the prereq card, and a brush-up-due concept is hidden from the queue.
  - Passing all KPs of a dependent concept when the prereq is due → implicit `Good` and a later due date ("implicit
    credit postpones prerequisite reviews"). Not applied after a recent failed review.
  - The award that crosses 150 creates exactly one quiz. A new KP session → 409 `quiz_pending`; an open session
    continues; reviews are still allowed.
  - Quiz: answers save without correctness. Late answer → 409 `quiz_over`. Lazy finish after the deadline (unanswered
    = wrong). Result reveals answers. Misses → `quiz_miss` cards. One XP event per subject in the quiz, and `xp_day` is updated per subject.
  - Another school's quiz or review → 404. Staff → 403.
  - The backfill migration creates cards from `learned_at`.
  - Roster `reviews_due` and `last_quiz`.
  - `test_rls_db.py` passes for the new tables, and `test_route_scoping.py` covers the new routes.
- [ ] Frontend (vitest):
  - `TodaysReviews` (list, quiz-miss badge, both empty states, error).
  - `QuizBanner` (pending vs resume with time left).
  - `QuizTimer` (warning under 1 min, time-out → result).
  - `QuizPage` (no feedback before the end, navigation hidden).
  - `QuizResult` (score, answers, review list).
  - `QuestionStep` on 409 `quiz_pending` → `QuizPendingPanel`.
  - Review end screens (pass / first fail / relearn).
- [ ] `make check` and `make test-db` are green. `cd backend && uv run mypy` and `cd frontend && pnpm typecheck` are
  clean.
- [ ] Manual (`make dev`, sample content, one school, a maths + physics class, one student). Seed by setting card
  `due` / `xp_event` rows directly where waiting is needed:
  1. Learn a concept → no review today. Set its card due to today → it shows in Today's reviews. Pass it → "see you
     again on …", and the XP toast.
  2. Make 7 cards due → 5 offered, interleaved by subject. After 5, "That's today's reviews done 🎉".
  3. Fail a review twice (on two days, via the `due` seed) → the second fail shows "Let's relearn …", and the concept
     shows in progress.
  4. With `distance-and-displacement` due, pass `speed-and-velocity`'s KPs (weight on the edge) → its card's due
     date moves later (check `review_log` source `implicit`).
  5. Earn XP past 150 → the quiz banner appears. Opening a new KP shows "Take your quiz to keep learning". Take the
     quiz: the timer counts down, no feedback until the end. Miss two → result shows them, and Today's reviews shows
     them with "From your quiz".
  6. Start a quiz and wait out the timer (or seed `deadline`) → reopening shows the result with unanswered as wrong.
  7. As the teacher: the roster shows Reviews due and Last quiz.
- [ ] Browser check: `make dev`, click through the home (reviews card, quiz banner, empty states), a review, the quiz
  (timer, time-out) and the result at desktop and 360 px, plus the teacher roster. Screenshots of each.
