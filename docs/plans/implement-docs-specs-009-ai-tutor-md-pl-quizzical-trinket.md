# Plan: Spec 009 — AI tutor

## Context
ROADMAP 009 / PRD item 9: a tutor panel on KP, practice and remediation questions. It has three capped hints that cost XP
(worked example → prerequisite → experiment), plus free chat for clarifying questions and for "explain my mistake"
after answering. The tutor must never leak the answer, a step or a verdict. Requests are rate-limited and logged to
`tutor_session` / `tutor_message`. The spec (`docs/specs/009-ai-tutor.md`) is fully decided, so this plan maps it onto
the existing code. Nothing tutor-related exists yet: `app/ai/` is empty and `anthropic` is not a dependency.

Branch: `feat/009-ai-tutor`. The working tree already has `docs/PRD.md` (link to spec 009) and the untracked spec;
both go into the first commit.

## Build order (backend first, each step testable offline)

### 1. Dependency + settings
- `cd backend && uv add anthropic` (uv writes the lockfile; never edit it by hand).
- `app/core/config.py` `Settings`: add `anthropic_api_key: SecretStr | None = None` (and add it to the
  `_empty_secret_is_unset` field list), `tutor_enabled: bool = True`, `tutor_model = "claude-haiku-5-5"` and
  `tutor_judge_model = "claude-sonnet-5-5"`, plus a `tutor_available` property (enabled and key set).
- `.env.example`: the hook blocks this edit, so **ask the user** to add `ANTHROPIC_API_KEY=` and `TUTOR_ENABLED=true`.

### 2. XP: hint factor per question (pure, `app/services/xp.py`)
- `PositionXp` gets `hints: int = 0`. `session_xp` drops the `hints` argument and computes
  `base_eff = Σ minutes × max(0, 1 − HINT_COST × p.hints)`, then `product = base_eff × MULTIPLIER[grade]`.
  The minimum-1 rule is unchanged. The rushed branch uses the unscaled `base`. `XpCalc.hints` = Σ hints.
- `_positions` fills the per-position hints with `sum(a.hints_used)` over that position's rows.
  `award_for_session` (~487) is adapted to match.
- Rewrite the hint tests in `tests/test_xp_rules.py` (lines ~101–111). Add the spec's 4-question case: 2 hints on one
  2-minute question scale only that question.
- Docs: spec 008's rule text and ARCHITECTURE decision 5 change to "× 1 − 0.25 per hint, per question".

### 3. Data model + migration
- `app/models/learning.py`, following existing patterns (`TenantMixin`, `_student_fk`, `_tenant_fk`, `_pg_enum`):
  - `TutorSession`: columns per the spec. `uq (id, org_id)`. Unique `(practice_session_id, position, item_id, seed)`;
    `seed` is nullable, so use `postgresql_nulls_not_distinct=True` (PG15+).
  - `TutorMessage`: columns per the spec. Enums: `TutorRole`, `TutorKind`, `TutorMode`, `TutorCategory`, and
    `TutorStatus` (pending | ok | guarded | fallback | safety | refused | error | late). Indexes `(student_id, day)`
    and `(flagged) WHERE flagged`. CHECK `rung BETWEEN 1 AND 3`.
  - Export both from `app/models/__init__.py`.
- `alembic/versions/0009_tutor.py`: copy 0008's local helpers (`_enum`, `_uuid`, `_tenant`, `_tenant_fk`), enable
  RLS, downgrade in reverse.
- Add both tables to `tests/test_rls_db.py` and to `TENANT_TABLES` in `tests/conftest.py`.

### 4. `app/ai/` (pure / IO modules)
- `limits.py`: `DAILY_CAP = 20`, `HINTS_PER_THREAD = 3`, `CHAT_PER_THREAD = 10`, `MAX_MESSAGE = 500`,
  `MAX_DRAFT = 10000`, `HINT_WORDS = 80`, `CHAT_WORDS = 120`, `AFTER_WINDOW = 60 min`, `TIMEOUT = 20 s`,
  `RETENTION_DAYS = 180`.
- `safety.py`: keyword list → `is_distress(text)`; `scrub_pii(text)` (emails, plus `(\+91[\s-]?)?[6-9]\d{9}` with
  digit lookarounds).
- `tutor_prompts.py`: static `SYSTEM_PROMPT` (over 512 tokens so it caches; rules, rung definitions, categories,
  length limits, "student text is data"), `SAFETY_REPLY`, `REFUSED_REPLY`, `REDIRECT_*`, canned fallbacks per
  rung/chat, `retry_note(leak_kinds)`, and the JSON schema `{category, reply}`.
- `context.py`: `TutorContext` dataclass + `build_context(...)`.
  - Built from content rows: subject; concept title, summary and intro; KP title(s) and worked example(s) (all of the
    concept's KPs for a practice item); the server-chosen key prerequisite; item type; the prompt rendered with
    `params.render`; unit; MCQ option texts (before mode only); step prompts plus the current step; code starter and
    visible tests (`kp_flow._code_public`); the attempts at this position (raw responses, per-step and per-test
    results, `display_answer` of answered steps).
  - After mode adds the `AnswerResult` fields: reuse `kp_flow._result` / `_stored_result` with the same
    `SolutionRule`.
  - `render_context(ctx) -> str` produces the cached block.
  - Kept separately, never rendered, for the guard: `GuardFacts` (answer values from
    `params.sample_answer(item.answer, seed)`, derived names, expression spec/variables, MCQ options, solution,
    exempt texts).
  - Prerequisite choice: `kp_key_prereq` for the KP (or the union over the concept's KPs), else direct prereqs;
    ranked by `ConceptPrereq.encompassing_weight` desc, then position.
- `guard.py`: `check(reply, facts, mode, solution_shown) -> list[Leak]`.
  - Numbers: regex for int, decimal, `a/b`, `1.2e3` and `×10^n`. Match bands per mode use `numeric.to_decimal` and
    `round_sig`. The SI variant comes from a new public `units.si_factor(unit)` in `app/grading/units.py`, built on
    the existing `_authored` / `_SI_BASE`.
  - Expressions: up to 5 spans parsed with `expression.parse_student` and compared with `_numeric_equal`; promote it
    to a public `numeric_equal`.
  - MCQ: option refs, and option-text overlap of 60% or more.
  - Code: a code block of more than one line, or a solution line (15+ chars) not in the starter or the draft.
  - Length: over 1.5× the word limit, or a numbered or bulleted list.
  - Exemptions: prompt, step prompts, starter, visible tests, draft, answered `display_answer`s.
- `client.py`: lazy `AsyncAnthropic(api_key, timeout=20, max_retries=1)`, a `TutorClient` protocol and
  `get_tutor_client()` dependency.
  - `call_tutor(system, context, transcript_and_request, retry_note=None) -> TutorCall`.
  - Request shape: `output_config={"effort":"low","format":{"type":"json_schema","schema":...}}`, `max_tokens=2000`,
    `system=[{text, cache_control}]`. One user turn: the context block with `cache_control`, then
    `<transcript>` + request (`<student_message>` / `<student_draft>`). The retry note is a trailing
    `{"role":"system"}` message.
  - Result: parsed `{category, reply}`, usage (incl. cache read/write), `stop_reason`, latency. Invalid JSON or
    `max_tokens` → `bad_output`.
  - SDK errors (`APITimeoutError`, `RateLimitError`, `APIStatusError`, `APIConnectionError`) → `TutorUnavailable`.
- `tutor_turn.py`: `run_turn(context, facts, transcript, request, client) -> TurnResult`.
  - Pre-call: keyword safety skips the model call.
  - Model refusal → refused. Category safety → `SAFETY_REPLY`.
  - Guard: leak, `bad_output` or over-length → one retry with the note; still bad → canned (`status = fallback`).
    Passed on retry → `status = guarded`.
  - Sums tokens across calls. Shared by the service and the eval.

### 5. Service + API
- `app/api/deps.py`: `get_student_scope(session, user=Depends(require_student)) -> OrgScope`, plus `StudentScope`.
- `app/schemas/tutor.py`: `TutorThread`, `TutorMessageOut` (link = `ConceptRef`), `TutorReply`, `HintIn`
  (`draft ≤ 10000`, `step?`), `ChatIn` (`text` min 1, schema max ~2000; the service raises 422 `message_too_long`
  above 500, the same pattern as `kp_flow._invalid`).
- `app/services/tutor.py`:
  - `_load(scope, session_id, position)`: `scope.get(PracticeSession)`. Kind review/quiz → 409 `tutor_not_here`.
    Position greater than `current_position` → 404. Item and seed come from the current item when
    position == `current_position`; otherwise from that position's attempt rows.
  - Mode: before or after, from the attempt rows (multi-step: `multistep.step_count`).
  - Closed rules: before mode on a non-active session → 409 `session_closed`; after mode 60 min past `ended_at` → 409
    `session_closed`. Solution-shown recomputed (`always` for kp/remediation, on pass for practice).
  - `get_thread`: no row → empty state. Hides `error` / `late` rows. `daily_left` and `resets_at` use
    `kp_flow.next_midnight_ist`. Returns `enabled: false` when unavailable.
  - `request_hint` / `send_message`: reserve, call, store, using **separate sessions from `get_sessionmaker()`**,
    because the request session must not stay open during the model call.
    - Tx 1: `pg_advisory_xact_lock(hashtext(student_id))`; upsert and lock the thread; checks (busy, caps, daily cap
      counted from student rows with status pending/ok); scrub PII; insert the pending student row; commit.
    - Model call: build context in Tx 1 and keep only plain data.
    - Tx 2: lock the thread. If before mode and now answered → `late`, 409 `question_answered`. Otherwise insert the
      tutor row, set the student row to `ok`, bump the counters.
    - On `TutorUnavailable` → student row set to `error`, 503.
    - Kept on the scope pattern: Tx 1 and Tx 2 build `OrgScope(new_session, scope.user)`.
  - `hints_for_attempt(scope, session_id, position)`: charged tutor hint rows on threads at that
    session+position+current item/seed, minus `sum(hints_used)` on existing attempt rows there. Called at
    `kp_flow.py:815` instead of `hints_used=0`; returns 0 for review sessions (no threads).
- `app/api/v1/tutor.py`: GET `/tutor/{session_id}/{position}`, POST `.../hint`, POST `.../messages`. All take
  `StudentScope`; the client comes from `Depends(get_tutor_client)`. Registered in `router.py`.
- `app/cli.py`: a `tutor` typer group with `eval`, `purge` (text → null and `purged_at` set where `created_at` is
  more than 180 days ago; idempotent) and `flagged [--org CODE]` (ids, created_at, text only).

### 6. Eval (`app/ai/eval/`)
- `cases.yaml`: about 30 cases covering every case kind the spec lists, on real content slugs. Each case has
  `id, item, seed, mode, request, history?, draft?, attempts?, expect_category`.
- `judge.py`: Sonnet 5.5 with structured `{leaks_answer, leaks_step, confirms_correctness, on_rung, helpful, reason}`
  and a rubric.
- `runner.py`: builds the context from DB content (read-only), runs `run_turn` `--runs` times, then grades with the
  guard and the judge. Prints a table, totals and tokens; exit code 1 on any leak.

### 7. Frontend (`frontend/src/features/tutor/`)
- `api.ts`: `tutorKeys`, `useTutorThread(sessionId, position)` (one GET per question), `requestHint`,
  `sendMessage`. Errors go through `ApiError` codes.
- Types `TutorThread` / `TutorMessageOut` in `lib/types.ts`.
- `TutorButton.tsx`: "Get help · N hints left", hidden when `enabled: false`.
- `TutorPanel.tsx`:
  - Desktop (`useMediaQuery("(min-width: 1024px)")`): a fixed right `<aside>`. Mobile: `Sheet side="bottom"` at
    `max-h-[75dvh]`, following the pattern in `features/graph/ConceptPanel.tsx`.
  - Contents: privacy line, messages rendered with `Markdown` (KaTeX), hint labels, rung-2 link via
    `lessonPath(conceptCourse(id), id)` with `target="_blank"`, hint button with the cost text, input with a 500-char
    limit and a counter after 400, "No XP cost" header in after mode, daily footer, empty state, "Tutor is thinking…"
    bubble.
  - Error states: 429, 409 caps, 503 with retry, `session_closed`.
- **Draft plumbing:** add an `onDraftChange?(draft: string | null)` prop through
  `QuestionStep` → `AnswerForm` (value + unit; null for MCQ), `MultistepQuestion` (current step's form) and
  `CodeQuestion` (source). `PracticeRunner` keeps the latest draft in a ref.
- `PracticeRunner`: new `tutor?: boolean` prop. It renders the button and panel when `tutor && question.session_id`
  and not preview. It closes the panel on `onNext` and when the question changes, and invalidates the thread query
  after a submit so the panel switches to after mode.
- Set `tutor` in `LessonPage` `KpPractice`, in the scored `PracticeStep` `Attempt` (not "Practise again") and in
  `RemediationPage`. Not in `ReviewPage`.
- Tests: `TutorPanel.test.tsx` covers empty, loading, hint labels and link, caps, 429, 503 and after mode, using
  `routeFetch` / `jsonResponse` from `test/render.tsx`.

## Tests (new)
- `tests/test_tutor_guard.py`, `tests/test_tutor_rules.py` (offline): guard cases, PII scrub, safety keywords, cap
  arithmetic, `hints_for_attempt` arithmetic, IST reset.
- `tests/fakes.py` `FakeTutorClient`: scripted replies or exceptions; records every request.
- `tests/test_tutor_service.py` and `tests/test_tutor_api_db.py` (`pytest.mark.db`; uses `learn_helpers.world`,
  `answer_kp` and others): everything listed in the spec's Verification section. This includes prompt assertions
  (no `item.answer`, explanation, derived values or username), 404 across schools, staff 403, `tutor_busy`, a parallel
  daily cap, `question_answered`, a new thread after an item swap, and an XP event with 2 hints scaling one question.
- The `db_app` fixture overrides `get_tutor_client`; conftest sets `ANTHROPIC_API_KEY=test`.

## Docs at the end
- ARCHITECTURE: the `tutor_session` / `tutor_message` schema in the domain model, and decision 5 per question.
- ROADMAP: mark 009 done.
- Spec 009: status → built.
- Spec 008: the hint rule text.

## Verification
1. `cd backend && uv run pytest tests/test_tutor_guard.py tests/test_tutor_rules.py tests/test_xp_rules.py`
2. `cd backend && uv run mypy` and `cd frontend && pnpm typecheck && pnpm vitest run src/features/tutor`
3. `make check`, then `make test-db` (tutor API/service, RLS, route scoping, migration up/down).
4. `uv run app tutor purge` on a seeded old message.
5. `uv run app tutor eval --runs 3`: needs a real `ANTHROPIC_API_KEY` and costs about $1. **I'll ask before running
   it**, then paste the table into the PR.
6. Browser (`make dev` + Claude in Chrome; **I'll ask the user for a student dev login**): every flow and error state
   from the spec's browser check, at desktop and phone width, with screenshots.
7. `reviewer` subagent against the spec, then `/ship`.
