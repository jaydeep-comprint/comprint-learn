# Plan: implement spec 012 (Placement)

## Context
Spec 012 (`docs/specs/012-placement.md`, untracked on main) adds placement. On a new **Placement** tab, a teacher ticks
the chapters a class has covered and sends an adaptive diagnostic to the class or to chosen students. Each diagnostic
has at most 25 untimed quick questions, no feedback, an "I don't know" button and can be paused. At the end, evidence-rich concepts become
learned (`source = diagnostic`), borderline ones become *conditionally* learned (first card `Hard`, due tomorrow), and
lesson-learned concepts the student clearly fails go back to relearn. ARCHITECTURE decision 12 is built here.

Branch `feat/012-placement` from main in this checkout. The uncommitted PRD link, the spec and the untracked 011
plan go into the first commit (spec "Implementation notes" and the memory note). Small commits, roughly in the step order below.
The shared test DB means **no parallel `make test-db` runs**.

### Where the code differs from what the spec assumes (handled below)
1. `frontier.mark_learned` (`frontier.py:588`) is UPDATE-only and hard-codes `source=lesson`. Most range concepts have
   no `concept_state` row → it must become an upsert.
2. It resolves `relearn` remediations where the concept is the **prerequisite**. The spec also wants the concept's
   **own** KPs' open remediations resolved (`relearned`) and its active KP and practice sessions failed. No helper does that yet.
3. `srs.first_review` (`srs.py:101`) hard-codes `Rating.Good`, and `on_learned` logs `learned`/`relearned`.
4. `frontier.fetch` selects only status and `learned_at`. Views have no `source`/`conditional`. A placed concept's
   `parts_passed` counts only practice.
5. The quiz never replaces a retired item on GET. Copy `kp_flow.current_question` (916–917) instead.
6. No helper loads weighted edges transitively. `learn._graph` keeps unweighted `prereqs` only.

## Step 1: Model + migration 0012
- `app/models/learning.py`:
  - `AttemptContext.diagnostic`, `SessionKind.diagnostic`, `ReviewSource.placed`.
  - New `DiagnosticStatus` (`sent|active|finished|cancelled`).
  - `ConceptState.conditional: bool` (server_default false).
  - `PracticeSession.diagnostic_id` + `_tenant_fk("diagnostic_id", "practice_session", "diagnostic_session")`, the
    extended `kind_links` CHECK (`(kind = 'diagnostic') = (diagnostic_id IS NOT NULL)`) and a partial unique index on
    `diagnostic_id` where `kind = 'diagnostic'`.
  - `session_iff_practice` CHECK += `'diagnostic'`.
  - `ClassCoveredChapter(TenantMixin)`: PK `(class_id, chapter_id)`, `_tenant_fk` class, content FK chapter,
    `created_by` composite FK, `created_at`.
  - `DiagnosticSession(TenantMixin)`: the spec's columns (`chapter_ids`/`range_ids`/`served_item_ids` as
    `ARRAY(UUID)`, `evidence`/`results` JSONB, `answered` smallint), `_student_fk`, class and `sent_by` composite FKs,
    `UniqueConstraint(id, org_id)`, partial unique `uq_diagnostic_session_open (student_id, class_id) WHERE status IN
    ('sent','active')`, and an index `(org_id, class_id, student_id, sent_at desc)`.
  - Export from `models/__init__.py`.
- `alembic/versions/0012_placement.py` (down_revision `0011_teacher_summary`), copying 0008's patterns:
  - `ALTER TYPE ... ADD VALUE` inside `autocommit_block` for `attempt_context`, `session_kind` and `review_source`.
  - The new enum uses `create_type=False` + `NEW_ENUMS`.
  - Old/new CHECK-text constants, then drop and recreate the CHECKs.
  - Tables, the add-column with its FK and partial index, and RLS on both tables.
  - Full downgrade: delete rows using the new values, then `_shrink_enum` (with the dependent CHECKs and partial
    indexes dropped and recreated), then drop the column and the tables.
- Tests: `conftest.TENANT_TABLES` += both tables; `test_rls_db.py` set += both; `test_migrations_db.py` (up/down) passes.

## Step 2: Pure engine `app/services/placement_engine.py` (+ `tests/test_placement_engine.py`, TDD)
- Dataclasses:
  - `RangeGraph(concepts, parents, children, weight[(c,p)], order: dict[cid,int])`, in-range edges only.
  - `Ev(e, asked, wrong)`.
- Functions:
  - `initial(range, learned_ids) -> dict[cid, Ev]`: a +1 prior for learned concepts.
  - `ancestor_weights(g, c)`: max-product over paths, by DFS/DP in topological order.
  - `descendants(g, c)`.
  - `apply_answer(g, ev, c, correct) -> ev`: correct gives `+1` to c and `+w(a)` to each ancestor a. Wrong/IDK gives
    `−1` to c (with `asked+1`, `wrong+1`) and `−1` to each descendant. A correct answer also increments `asked`.
  - `decided(ev_c)`: `e ≥ 2 or e ≤ −1 or asked ≥ 2`.
  - `next_concept(g, ev, askable) -> cid | None`: `0.5·gain(correct) + 0.5·gain(wrong)` over the whole range,
    including c and c reaching `asked = 2`. Ties go to |order − mid|, then the lowest id.
  - `pick_item(items_by_kp, kp_order, asked, served, rng)`: the last KP for the 1st question, a different KP for the
    2nd, falling back to any unserved item.
  - `finished(answered, g, ev, askable)`: `answered ≥ 25` or no askable concept undecided.
  - `classify(g, ev, learned_ids) -> Results(learned, conditional, demoted)`: the spec's table, plus implied ancestors
    of placed concepts as conditional, and "demote needs `wrong ≥ 1`".
  - `topo(g, ids)`.
- Constants `MAX_QUESTIONS=25`, `MAX_PER_CONCEPT=2`, `LEARNED_E=2`, `COND_E=1`, `FAIL_E=-1`.
- `random.Random` is injected so tests are deterministic.
- Tests: the spec's engine list (chain, diamond, mid-graph first pick, weights, cap, stop rules, classification).

## Step 3: Learning-core changes (behaviour-preserving for lessons)
- `srs.py`:
  - `first_review(at, rating=Good)`.
  - `on_learned(scope, cid, at=None, *, rating=Good, source: learned|placed = learned)`: a new card logs `source`;
    re-rating an existing card logs `placed` when the source is placed (never `relearned`).
  - `apply_review` and `mark_quiz_miss` clear `ConceptState.conditional` (one UPDATE).
  - `give_implicit_credit` skips prerequisites whose state is conditional, next to the `quiz_miss` skip at ~L417.
  - `_state` (L549) backfills with `Hard` for conditional rows.
- `frontier.py`:
  - `mark_learned(scope, cid, *, source=lesson, rating=Good, conditional=False)` becomes a `pg insert ...
    on_conflict_do_update` on `(student_id, concept_id)`. Lessons set `conditional=false`, which is harmless.
  - The existing remediation resolve and `on_learned(rating, source=placed if diagnostic)` stay.
  - `fetch` also selects `source` and `conditional` into `StudentRows`/`Frontier` (`stored_source`, `conditional`),
    with no extra query.
- `kp_flow._relearn` clears `conditional`.
- New `kp_flow.end_concept_work(scope, cid)`: fails the active KP sessions (KPs of the concept) and practice sessions
  (`concept_id`) without XP, and resolves open remediations whose KP belongs to the concept (`relearned`). Placement
  calls it before `mark_learned` for in-progress concepts.
- Outline schemas: `OutlineConcept` (`schemas/learn.py`) += `placed: bool`, `conditional: bool`. They are filled in
  `learn.outline`/`_home_concept` and `dashboard.student_outline`. When `status == learned`, `parts_passed =
  parts_total` (a learned concept shows as complete).
- Gate: the existing `test_srs_rules`, `test_kp_flow`, `test_reviews_db`, `test_kp_api_db` and `test_learn_*` stay green.

## Step 4: Service `app/services/placement.py` (all through `OrgScope`)
- **Graph and range**:
  - `_weighted_graph(scope_session, node_ids)`: one `select(ConceptPrereq...)` over active nodes, reusing
    `learn._graph(scope)` for nodes, chapters and outline.
  - `range_for(graph, chapter_ids)`: the chapters' active concepts plus `learn._ancestors`.
  - `askable(range)`: one query of active `kp_question` items with `Item.type.in_(QUICK_TYPES)`, active KPs, grouped
    by concept then KP position.
  - Outline order for the tie-break: the class course first, then other courses by slug, then (chapter position,
    concept position), via `_Node.sort_key`.
- **Teacher**:
  - `overview(scope, class_id)`: uses `class_view.load(states=False)`. Chapters come from `class_course` (with
    `covered` flags, current-course rows only), plus the range preview counts. Student rows come from the latest
    diagnostic per enrolled student (DISTINCT ON) and the counts of the latest *finished* one.
  - `set_chapters`: writable check (copy `assignments._writable` → 409 `class_archived`). Validates that the chapters
    belong to the class course (else 422), then deletes and inserts only the current course's rows.
  - `send(all_students | student_ids)`: student validation reuses `assignments._check_students`. Errors: 422 when no
    chapter is ticked or the range has no askable concept. It skips students with an open or finished diagnostic and
    returns `{sent, skipped}`.
  - `resend` (409 `diagnostic_open` if one is open) and `cancel` (`FOR UPDATE`; 409 `diagnostic_closed` if finished
    or cancelled; sets its practice_session to `failed`).
  - `student_outcomes(sid)`.
- **Student** (`learn._require_student`):
  - `_own(id, for_update)`: 404 when it's not the caller's, or when the caller isn't actively enrolled in its class.
  - `current()`: open diagnostics in enrolled classes, with course, subject, class name and answered.
  - `start`: idempotent when active; 409 `diagnostic_closed` when closed. It freezes `chapter_ids`/`range_ids` from
    the current covered rows (the class-course chapters) and sets `evidence = initial(...)`. An empty range or no
    askable concept finishes at once with empty results. Otherwise it creates the `practice_session(kind=diagnostic)`,
    picks the first concept and item, and serves it with `kp_flow.serve_item`-style fields.
  - `question`: 409 `diagnostic_not_started` before start; the cancelled state gives `diagnostic_closed`. If the
    current item is retired, it re-picks at the same position, dropping concepts with no askable item left. It returns
    `kp_flow._question(...)` (built from `item.public` only).
  - `answer(DiagnosticAnswerIn)`:
    - Lock the diagnostic and the session.
    - Stale and idempotent handling as in `quiz.answer`: a resent answered position returns `{finished, answered}`.
    - Grade with `kp_flow._grade_answer`, or `idk → correct=False, response={idk:true}`.
    - Insert an `Attempt(context=diagnostic, …, on_conflict_do_nothing)`, then `apply_answer`, `answered += 1`.
    - Then either `_finish` or pick and serve the next question.
    - The response never includes correctness.
  - `_finish`:
    - Take `pg_advisory_xact_lock(hashtextextended('placement:'||student))` and lock the range `concept_state`
      rows `FOR UPDATE`.
    - `classify` against the current stored states.
    - Promotions in topological order: `end_concept_work` if the concept is in progress, then `mark_learned(source=diagnostic,
      rating=Hard|Good, conditional)`. A later `e ≥ 2` on a conditional concept clears the flag.
    - Then demotions via `kp_flow._relearn`.
    - Store `results`, set the session to `passed` and the status to `finished`. No XP, `xp_day` or quiz-mark writes.
    - `mark_learned` uses `scope.user.id`, so it runs as the student, which is correct here.
  - `result`: finished only. Lists are learned, conditional and to_learn (range concepts not learned now), as `ConceptRef`.
- **Dashboard tweaks** (`dashboard.py`):
  - `_questions` (L327) and `_chosen` (L496) get `Attempt.context != diagnostic`.
  - The activity feed gets an explicit `PracticeSession.kind != diagnostic`.
  - The `inactive` rule already counts every attempt, so it needs no change.

## Step 5: API + schemas
- `app/schemas/placement.py`: `PlacementOverview`, `ChaptersIn`, `SendIn` (`student_ids: list | None`, where None means
  the whole class, as in assignments; the spec's `all_students` bool is accepted too), `SendOut`, `PlacementStudentRow`,
  `StudentOutcomes`, `DiagnosticCurrent`, `DiagnosticState`, `DiagnosticQuestion` (= `QuestionPublic`),
  `DiagnosticAnswerIn` (`session_id`, `position`, `time_taken_ms` required; `response`/`unit` optional; `idk: bool`;
  a validator requires a response or idk), `DiagnosticSaved {finished, answered}`, `DiagnosticResult`.
- `app/api/v1/placement.py`: teacher routes `/classes/{class_id}/placement[...]` with `StaffScope`; student routes
  `/diagnostics/...` with `Scope`. Register them in `router.py`. `test_route_scoping.py` passes with no exemptions.

## Step 6: DB tests `tests/test_placement_db.py`
Build a multi-chapter fixture with `content_fixtures` (2 chapters + a cross-course prerequisite), or use the real content
via `learn_helpers.world` where it suffices. Reuse `answer_fields`, `seed_learned` and `dashboard_seed`. Cover the
spec's DB list:
- send skips; re-send and cancel; the frozen range across courses;
- no correctness or answer in responses;
- promotion (source, conditional, due tomorrow vs ~2 days, `review_log.source = placed`);
- demotion via relearn; no `xp_event`;
- conditional clears on the first review;
- tutor 409 on a diagnostic session;
- cross-school and unenrolled → 404;
- idempotent resend of the final answer;
- an in-progress concept's sessions and remediations are closed on promotion;
- diagnostic attempts are excluded from dashboard accuracy.

## Step 7: Frontend
- `features/placement/api.ts`: query keys `["classes", id, "placement"]` and `["placement", ...]`, the
  `retryUnlessClientError` hooks, plain POSTs for start and answer (as in `quiz/api.ts`), and invalidation of
  `["classes", id]`, `learnKeys.all` and `["placement","current"]`.
- Extract `components/StudentPicker.tsx` from `AssignmentDialog.tsx` L243–281, keeping the labels so
  `assignments.test.tsx` stays green.
- `PlacementTab.tsx`:
  - A chapter checklist (grade shown) with Save, and the range preview line.
  - An unsaved-changes guard: `useBlocker` + `beforeunload` + `AlertDialog` (the `SlipsView.tsx` pattern).
  - A Send button (disabled with a hint when nothing is ticked) that opens `SendPlacementDialog.tsx` (with the
    `StudentPicker`), then a sonner toast "Sent to N students (M already had one)".
  - A status table with DropdownMenu Cancel/Re-send through `ConfirmDialog`, disabled when archived.
  - A finished row opens `PlacementResultSheet.tsx` (`useParam("placement")`).
  - Empty states: no course, and no students (`EmptyState` + roster link).
- `ClassLayout.tsx`: a tab after Assignments; `routes.tsx` gets the `placement` child.
- `PlacementCard.tsx` in `StudentHome` between `QuizBanner` and `AssignedCard`: one card per open diagnostic, showing
  the class name when two share a subject, with Start/Continue.
- `PlacementPage.tsx` at `/placement/:id`, in the full-screen student block beside `/quiz/:id`:
  - `AnswerForm` with `marked={null}`, the counter "Question N · at most 25", Submit, "I don't know" and Pause (home).
  - 409 `stale_question` refetches; `diagnostic_closed` shows the cancelled message with a home link.
  - An empty range shows "Nothing to check right now".
- `PlacementResult.tsx` at `/placement/:id/result`: "You placed out of N concepts", three lists, and a graph button.
- Chips:
  - `lib/types.ts` `OutlineConcept` += `placed`, `conditional`.
  - The chip is "Placed" or "Placed · check soon". It goes in `ConceptNode.tsx` (the status line and `aria-label`),
    `ConceptPanel.tsx` (the status line), `CoursePage.tsx` `ConceptRow` (badges) and `StudentPage.tsx` `Details`.
- Tests: `features/placement/*.test.tsx` using `routeFetch` + `renderAt`. The tab test wraps the tab in a parent route
  that supplies `<Outlet context={{cls, courseSlug}}>`. Add a `ConceptNode.test.tsx` case for the chip.

## Step 8: Docs at ship
- ARCHITECTURE: decision 12 gets "Built in spec 012" (thresholds, 25 cap, conditional = Hard first card). The domain
  model gains `class_covered_chapter`, `diagnostic_session`, `concept_state.conditional`, the `diagnostic`
  context/kind and `review_source.placed`. Update the `diagnostic_session` placeholder line.
- CLAUDE.md gotcha (if useful): `frontier.mark_learned` is now an upsert with `source`/`conditional`.
- Set the spec status to built.

## Verification
- `cd backend && uv run pytest tests/test_placement_engine.py` (TDD, first), then `uv run mypy`.
- `make test-db` (one run at a time): `test_placement_db.py`, `test_rls_db.py`, `test_migrations_db.py`, plus the
  existing kp/review/srs/dashboard/quiz DB suites for regressions.
- `cd frontend && pnpm vitest run src/features/placement src/features/assignments src/features/graph` and
  `pnpm typecheck`.
- `make check`.
- Browser: `make dev`, then the spec's browser script (teacher ticks 2 maths chapters and sends → the student answers
  with some IDK, pauses and resumes on the same question, finishes → the result and chips → the teacher's finished row,
  sheet and graph chip; cancel and re-send). Take screenshots of the tab, question page, result, the "no chapters"
  state and the cancelled message. Chrome can't reach localhost here (memory note), so ask the user for a dev login and
  have them run the browser check if the extension still fails.
- Then the `reviewer` subagent against the spec, then `/ship`.
