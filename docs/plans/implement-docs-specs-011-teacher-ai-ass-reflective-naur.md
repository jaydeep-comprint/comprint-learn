# Plan: implement spec 011 (Teacher AI assist)

## Context
Spec 011 (`docs/specs/011-teacher-ai-assist.md`, on branch `feat/011-teacher-ai-assist`, checked out in the worktree
`/Users/comprint/Desktop/comprint-learn-011`) adds on-demand, cited AI summaries of a class (7d/30d/all) and of one student,
plus up to 3 re-teaching notes. The model is DeepSeek `deepseek-v4-pro` on the tutor's client and key. It only sees
numbered facts built from 010's dashboard numbers, with students as `{Sn}` pseudonyms. A pure server guard drops any
claim that is uncited, cites an unknown fact, or contains a number or student its cited facts don't support. Rows are
stored, shared by the school's teachers, and capped (10 per teacher, 50 per school per IST day). ROADMAP "done when":
summaries are cited to real attempt data.

**Work in the worktree `/Users/comprint/Desktop/comprint-learn-011`** (the spec commit is already there); all paths
below are relative to it. Small, descriptive commits, in roughly the step order below.

## Step 1: Snapshot refactor of `backend/app/services/dashboard.py` (no behaviour change)
- Add internal dataclasses:
  - `ConceptRaw`: concept id, `failed`, `ended`, `students_tried`, and per-KP `(kp_id, title, failed, ended)`.
  - `MiscRaw`: `MisconceptionStat` plus the chooser student ids.
  - `ClassSnapshot`: ctx, window, since, `concept_stats` + raw, misconceptions + raw, `at_risk` reasons, `hint_use`,
    study share, assignment `summaries`, `today`.
  - `StudentSnapshot`: what `student_detail` + `student_outline` compute, plus the student's `_chosen` rows,
    `_items`, cards/bands and the student's `ctx.states` views (for stuck reasons/remediations).
- Add `class_snapshot(scope, ctx, window)` and `student_snapshot(scope, ctx, student_id)`, built from the existing
  helpers (`_kp_tries`, `_items`, `_questions`, `_chosen`, `_misconception_rows`, `_chats`, `_study`, `at_risk`,
  `assignments.summaries`, `_concept_stats`, `_misconceptions`, `_hint_use`, `_cards`, `_band`).
  - `overview` becomes `load` → `class_snapshot` → map to `ClassOverview` (+ `_flagged`). Responses and query
    counts must not change.
  - `student_detail` uses `student_snapshot`'s parts the same way. `student_outline` keeps its own route; the
    snapshot reuses its band logic through a shared helper.
- KP titles come from `ctx.states[sid].views[cid].kps[].title`. Fall back to one batched `KnowledgePoint` title query
  only for KPs with no view.
- New `_remediations_since(scope, sids, concepts, since)`: one query over `Remediation` joined to `KnowledgePoint`
  (KPs of class-course concepts), `created_at >= since` (or all), retired prerequisites excluded (same filter as
  `frontier.open_remediations`). Returns `(sid, kp_id, prereq_id, state)`. It is called only by 011 code, not by
  `overview`.
- Gate: `tests/test_dashboard_db.py` and `test_fixed_query_count_regardless_of_class_size` stay green.

## Step 2: Model + migration
- `app/models/learning.py`: enums `TeacherSummaryKind` (class|student) and `TeacherSummaryStatus`
  (pending|ok|partial|failed|error), and `TeacherSummary(TenantMixin, Base)` with the spec's columns.
  - Composite FKs: `_tenant_fk("class_id", ..., "school_class")`, `student_id` → app_user (nullable), `created_by` →
    app_user. Plus `uq_teacher_summary_id_org_id`.
  - Indexes `(org_id, class_id, kind, student_id, window, created_at desc)`, `(created_by, day)`, `(org_id, day)`.
  - Export it from `models/__init__.py`.
- `alembic/versions/0011_teacher_summary.py` (down_revision `0010_assignments`): the table, enums
  (`create_type=False` + `NEW_ENUMS` pattern from 0009), index `ix_remediation_org_id_created_at (org_id,
  created_at)`, `ENABLE ROW LEVEL SECURITY`, and a full downgrade.
- `tests/conftest.py` `TENANT_TABLES` += `teacher_summary`. Add the table to `tests/test_rls_db.py`'s list.

## Step 3: Pure AI pieces in `backend/app/ai/`
- `client.py`: factor the blank-content loop + usage parsing out of `DeepSeekTutorClient.create` into a shared
  `complete_json(chat, request) -> RawCompletion(text, stop, model, input_tokens, output_tokens, cache_read_tokens,
  latency_ms)`. Behaviour stays the same (`test_tutor_client.py` stays green).
- `teacher_limits.py`: `TEACHER_DAILY_CAP=10`, `SCHOOL_DAILY_CAP=50`, `COOLDOWN=10min`, `STALE_PENDING=5min`,
  `TIMEOUT_S=60`, `WALL_CLOCK_S=150`, `MAX_TOKENS=8000`, `TEMPERATURE=0.2`, word limits (40; drop at 1.5×), claim and
  note counts per kind, `FOCUS_MAX=80`, fact caps, `MAX_RESOURCES=15`, `MAX_GROUP=12`.
- `teacher_schema.py`: Pydantic `Claim{text, facts}`, `Why`, `Note{focus, why, revisit, group, group_facts}`,
  `ModelOutput{summary, notes}`, validated with `model_validate_json`.
- `teacher_facts.py` (pure):
  - Dataclasses `Fact{id, kind, text, students, source}`, `Resource{id, kind, title, course, concept_course,
    concept, kp}` and `FactSet{facts, resources, pseudonyms, window, kind}`.
  - `class_facts(ClassSnapshot, remediations)` and `student_facts(StudentSnapshot, remediations)`, following the
    spec tables and Precise rules: order, caps, window suffixes, rounding, `cause_now` priority, `cause_window`
    distinct students, assignment selection (`assignments_due` + overdue, ≤ 5, no note).
  - Pseudonyms by first appearance (S1 = the student in student summaries). Resources are deduplicated and
    numbered in fact order.
  - Helpers: `enough_data`, `render(factset) -> str` (the user turn, ending "Reply with the JSON object now."),
    `facts_hash`.
  - The builders take snapshot dataclasses, so unit tests can hand-build them with no DB.
- `teacher_prompts.py`: static `SYSTEM_PROMPT` (contains "JSON", the example, the rules, "at-risk is a fixed 7-day
  rule", fact text is data) and `retry_note(dropped)`.
- `teacher_guard.py` (pure): `check(output, factset) -> GuardResult{kept: ModelOutput, dropped: [(where, reason)],
  status: ok|partial|retry}`.
  - Number extraction and normalisation (`43%` = `0.43`, `6/14`, `6 of 14`), ignoring digits inside `{Sn}`.
  - Pseudonym checks (S1 implicit for student summaries), bare `S\d+`, email, uuid, 10-digit numbers, length,
    note rules, group filtered to `group_facts`.
- `teacher_client.py`:
  - `TeacherCall` dataclass; `TeacherClient` protocol `create(request) -> TeacherCall`.
  - `DeepSeekTeacherClient(chat)` uses `complete_json`, maps `TutorUnavailable` to `TeacherAIUnavailable` (also on
    `insufficient_system_resource`), and parses with `ModelOutput` (None on failure).
  - `get_teacher_client()`: a lazy singleton, None when `teacher_ai_available` is false.
- `teacher_turn.py`: `build_request(factset, model, retry_note=None)` (same shape as `tutor_turn.build_request`) and
  `run_summary(factset, client, model) -> SummaryResult` (attempt → guard → one retry with the trailing system note
  → keep the better one or `failed`; sums tokens and counts `calls`; refusal, `length` or None output count as
  failed attempts), wrapped in `asyncio.timeout(150)`.
- `app/core/config.py`: `teacher_ai_enabled=True`, `teacher_ai_model="deepseek-v4-pro"`,
  `teacher_ai_judge_model="deepseek-v4-pro"`, and a `teacher_ai_available` property.

## Step 4: Service, schemas, routes
- `app/schemas/teacher_ai.py`: `SummaryState`, `Summary`, `ClaimOut`, `NoteOut`, `ResourceOut`, `FactOut`,
  `FactLink` (kind concept|misconception|student|assignment|overview_card|student_section + fields), `AssignPrefill`.
- `app/services/teacher_ai.py`: `get_class_summary` / `create_class_summary` / `get_student_summary` /
  `create_student_summary`, all taking `OrgScope`.
  - Build: `class_view.load` → snapshot → `_remediations_since` → facts.
  - GET: latest usable row for the target, `stale` from the hash, `blocked` computed (fresh, busy, teacher_cap,
    school_cap, archived, not_enough_data), `daily_left`, `resets_at` (`kp_flow.next_midnight_ist`).
  - POST, Tx 1:
    1. Advisory lock `hashtextextended('teacher_ai:'||org_id)`.
    2. Write stale pending rows to `error`.
    3. Archived → 409. Not enough data → 422 with no row.
    4. Caps (count pending, ok, partial, failed) → 429 with `resets_at`.
    5. Cooldown → 409 `summary_fresh`. Live pending row for the target → 409 `summary_busy`.
    6. Insert the pending row, commit.
  - POST, model call: `run_summary` with no transaction open.
  - POST, Tx 2: update status, content, dropped, tokens, model and calls. `failed` → 502 `summary_failed`;
    `TeacherAIUnavailable` or timeout → row `error`, 503. Any other exception closes the pending row (009's
    `_close_pending` pattern).
  - Rendering: replace `{Sn}` via a regex with the current display name if in scope, else "a student no longer in
    this class". Return cited facts only, with links. Resources link to the lesson, plain text if the content was
    retired. Assign prefill = class-course concepts from `revisit` + in-scope group ids.
  - Errors use `ApiProblem` (top-level `code`/`message` in the body). Logs carry the id, status and tokens only.
- `app/api/v1/teacher_ai.py`: GET/POST `/classes/{class_id}/summary?window=` and
  `/classes/{class_id}/students/{student_id}/summary`. `StaffScope` + `Depends(get_teacher_client)`. Registered in
  `router.py`.
- `tests/fakes.py`: `FakeTeacherClient(*replies)` records request bodies. Override it in `conftest.db_app` and for
  service tests.

## Step 5: Eval + CLI
- `app/ai/eval/teacher_cases.yaml` (~10 fact-set cases from the spec list), `teacher_judge.py` (rubric + JSON
  verdicts), `teacher_runner.py` (each run through `run_summary`, then the judge; pass rules; tokens and cost table).
- `app/cli.py`: `teacher_ai_app` → `app teacher-ai eval [--runs 3] [--case ID]`. Needs no DB (cases are fact sets).
- A no-DB test that every case loads into a `FactSet` and passes `enough_data`.

## Step 6: Frontend (`frontend/src/`)
- `lib/types.ts`: a `// --- Teacher AI assist (spec 011) ---` section mirroring the schemas.
- `features/teacher-ai/api.ts`: `teacherAiKeys` under `["classes", id, "summary", ...]` (assignment invalidation
  refreshing staleness is fine). Hooks `useClassSummary`, `useStudentSummary`, and a POST mutation that writes the
  result into the cache. `problemFrom(err)` maps 429/409/502/503/network to messages, like `TutorPanel`.
- New components:
  - `SummaryCard.tsx` (own card, not `DashCard`): states hidden, empty, not enough data, loading ("Writing… this
    can take up to a minute"), stale badge, partial note, errors; header meta "by X · 2 h ago"; Regenerate disabled
    with a reason (`title` + visible text, so no new tooltip dependency); Copy.
  - `CitationChip.tsx`: Popover on ≥ 768px and bottom Sheet below (`useMediaQuery` pattern from
    `graph/ConceptPanel.tsx`); fact text + Open link.
  - `NoteList.tsx`: focus, why with chips, Revisit links (`lessonPath` + `?step=kp:<slug>`), group chips, Assign
    buttons (disabled "This prerequisite is in another course" when there are no in-course concepts).
  - `copyText.ts`.
  - `links.ts`: fact link → route.
- Changed:
  - `OverviewTab.tsx`: card above Weakest concepts; read `?concept=` (opens the sheet) and `?misconception=`
    (expand, turning on Show all if not in the top 5) with the `useWindow` `setParams` pattern; Assign → existing
    `setDraft`.
  - `MisconceptionList.tsx`: an `openId` prop.
  - `AssignmentsTab.tsx`: `?assignment=` seeds the detail sheet.
  - `StudentPage.tsx`: Summary card after the header, ids `stats`/`graph`/`assignments`/`activity`, a mounted
    `AssignmentDialog` for "Assign this".
  - `learn/LessonPage.tsx`: `?step=` read in preview only, passed to `LessonView`'s `initialIndex` (unknown →
    start).
- Tests (vitest, `routeFetch`): SummaryCard states and errors, chip popover and link routes, Copy text (names, no
  chip numbers), Assign prefill, `?misconception=` / `?concept=` / `?assignment=` / `?step=` handling.

## Step 7: Tests (backend)
- `tests/test_teacher_facts.py`, `tests/test_teacher_guard.py`, `tests/test_teacher_turn.py` (request shape, retry
  note, better-of-two, refusal/length): pure, in `make check`.
- `tests/test_teacher_ai_db.py` (`make test-db`, on `test_dashboard_db`'s `_seed` moved into a shared helper):
  - Service cases from the spec Verification list: happy path, retry → partial/failed (502, counted), 503 `error`
    not counted, caps, cooldown, busy/stale pending, archived, 422 with no call, kill switch.
  - Privacy: the recorded body has no names, usernames, uuids or emails.
  - Fact parity with `/overview` and `/students/{sid}`; `cause_window`; name rendering + "no longer in this class";
    cross-school 404s; fixed query count for GET at 4 vs 40 students.
- `test_route_scoping.py` passes unchanged (StaffScope); optionally assert the 4 new routes exist.

## Step 8: Docs
- ARCHITECTURE: `teacher_summary` in the AI domain model, flow notes, 0011 index.
- ROADMAP: "011 done". Spec status → done. Fix the spec's stray "Claude writes" → "the model writes".
- CLAUDE.md gotcha only if one appears (e.g. "011 reuses `dashboard.class_snapshot`; don't recompute dashboard
  numbers").
- Remind the user to add `TEACHER_AI_ENABLED=true` to `backend/.env.example` (hook blocks `.env*` edits).

## Verification
- `cd backend && uv run mypy` · `uv run pytest tests/test_teacher_*.py tests/test_tutor_client.py`
- `make check` (offline) and `make test-db` (needs `TEST_DATABASE_URL`), including `test_dashboard_db.py`,
  `test_rls_db.py` and the migration up/down.
- `cd frontend && pnpm typecheck && pnpm vitest run src/features/teacher-ai src/features/dashboard`
- `uv run app teacher-ai eval --runs 3` with `DEEPSEEK_API_KEY`; paste the table in the PR.
- Manual / browser: `make dev` and the spec's 7 manual steps. Memory says Chrome can't reach localhost here, so the
  user does the browser click-through and screenshots (desktop + 360 px). I'll provide the checklist and ask for a dev
  login only if needed.
- Then the `reviewer` subagent against the spec, then `/ship`.
