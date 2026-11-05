"""The AI tutor service (spec 009): threads, hints, chat, caps and the hint count for attempts.

A thread is one question shown: (practice session, position, item, seed). Every POST is
**reserve, call, store**: Tx 1 takes a per-student advisory lock, checks mode and caps and
inserts the pending student row; the model call runs with no transaction open (the request
session's connection goes back to the pool on commit); Tx 2 stores the reply and charges it. Only
charged hint rows count in `hints_for_attempt`, so the answer path needs no tutor lock.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.ai import limits, safety
from app.ai.client import TutorClient, TutorUnavailable
from app.ai.context import StepDone, TutorContext, build_context, load_content, response_text
from app.ai.tutor_turn import TranscriptLine, TurnRequest, TurnResult, run_turn
from app.api.deps import OrgScope
from app.core.config import get_settings
from app.core.errors import ApiProblem, not_found
from app.grading import multistep
from app.models import (
    Attempt,
    Concept,
    Course,
    Item,
    Organization,
    PracticeSession,
    SessionKind,
    SessionStatus,
    TutorKind,
    TutorMessage,
    TutorMode,
    TutorRole,
    TutorSession,
    TutorStatus,
)
from app.schemas.learn import ConceptRef
from app.schemas.tutor import TutorMessageOut, TutorReply, TutorThread
from app.services import kp_flow

TUTOR_KINDS = (SessionKind.kp, SessionKind.remediation, SessionKind.practice)
CHARGED = (TutorStatus.ok, TutorStatus.guarded, TutorStatus.fallback)  # tutor hint rows
HIDDEN = (TutorStatus.pending, TutorStatus.error, TutorStatus.late)


def _conflict(code: str, message: str, **extra: object) -> ApiProblem:
    return ApiProblem(409, code, message, extra=extra or None)


def _unavailable() -> ApiProblem:
    return ApiProblem(503, "tutor_unavailable", "The tutor isn't available right now.")


def ist_day(now: datetime) -> date:
    return now.astimezone(kp_flow.IST).date()


def tutor_enabled(client: TutorClient | None) -> bool:
    return client is not None and get_settings().tutor_enabled


# --- the question a thread is about --------------------------------------------------------------


@dataclass
class _Question:
    session: PracticeSession
    position: int
    item: Item
    seed: int | None
    attempts: list[Attempt]  # rows at this position, by step
    mode: Literal["before", "after"]

    @property
    def solution_rule(self) -> "kp_flow.SolutionRule":
        return "on_pass" if self.session.kind == SessionKind.practice else "always"


async def _question(scope: OrgScope, session_id: uuid.UUID, position: int) -> _Question:
    ps = await scope.get(PracticeSession, session_id)
    if ps.student_id != scope.user.id:
        raise not_found()
    if ps.kind not in TUTOR_KINDS:
        raise _conflict("tutor_not_here", "The tutor isn't available here.")
    if position < 0 or position > ps.current_position:
        raise not_found()
    attempts = list(
        (
            await scope.session.scalars(
                scope.select(Attempt)
                .where(Attempt.session_id == ps.id, Attempt.position == position)
                .order_by(Attempt.step)
            )
        ).all()
    )
    if position == ps.current_position and ps.current_item_id is not None:
        item_id, seed = ps.current_item_id, ps.current_seed
    elif attempts:
        item_id, seed = attempts[0].item_id, attempts[0].seed
    else:
        raise not_found()
    item = await scope.session.get(Item, item_id)
    if item is None:
        raise not_found()
    if item.type.value == "multistep":
        done = len(attempts) >= multistep.step_count(item.answer)
    else:
        done = bool(attempts)
    return _Question(ps, position, item, seed, attempts, "after" if done else "before")


def _closed(q: _Question, now: datetime) -> bool:
    """POSTs are refused: before mode needs an active session; after mode allows 60 minutes."""
    if q.session.status == SessionStatus.active:
        return False
    if q.mode == "before":
        return True
    ended = q.session.ended_at or now
    return now - ended > limits.AFTER_WINDOW


async def _context(scope: OrgScope, q: _Question) -> TutorContext:
    content = await load_content(scope.session, q.item)
    if q.mode == "before":
        steps = []
        for a in q.attempts:
            graded = await kp_flow._regrade(scope, q.item, q.seed, a)
            steps.append(
                StepDone(
                    a.step,
                    response_text(
                        q.item, a.response, a.step if q.item.type.value == "multistep" else None
                    ),
                    a.correct,
                    graded.result.display_answer,
                )
            )
        return build_context(content, q.item, q.seed, mode="before", steps_done=steps)
    last = q.attempts[-1]
    result = await kp_flow._stored_result(scope, q.session, last, q.solution_rule)
    step = last.step if q.item.type.value == "multistep" else None
    return build_context(
        content,
        q.item,
        q.seed,
        mode="after",
        result=result,
        response=response_text(q.item, last.response, step),
    )


# --- threads -------------------------------------------------------------------------------------


def _thread_where(q: _Question) -> list[ColumnElement[bool]]:
    return [
        TutorSession.practice_session_id == q.session.id,
        TutorSession.position == q.position,
        TutorSession.item_id == q.item.id,
        TutorSession.seed.is_not_distinct_from(q.seed),
    ]


async def _find_thread(scope: OrgScope, q: _Question, *, lock: bool = False) -> TutorSession | None:
    stmt = scope.select(TutorSession).where(*_thread_where(q))
    if lock:
        stmt = stmt.with_for_update()
    return (await scope.session.execute(stmt)).scalar_one_or_none()


async def _ensure_thread(scope: OrgScope, q: _Question) -> TutorSession:
    await scope.session.execute(
        insert(TutorSession)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            practice_session_id=q.session.id,
            position=q.position,
            item_id=q.item.id,
            item_version=q.item.version,
            seed=q.seed,
        )
        .on_conflict_do_nothing()
    )
    thread = await _find_thread(scope, q, lock=True)
    assert thread is not None
    return thread


def _live_pending(m: TutorMessage, now: datetime) -> bool:
    """A request still in flight. An older pending row was lost (worker crash, redeploy): it
    neither blocks the thread nor counts toward the caps."""
    return m.status == TutorStatus.pending and m.created_at > now - limits.STALE_PENDING


async def _daily_used(scope: OrgScope, now: datetime) -> int:
    counted = or_(
        TutorMessage.status == TutorStatus.ok,
        and_(
            TutorMessage.status == TutorStatus.pending,
            TutorMessage.created_at > now - limits.STALE_PENDING,
        ),
    )
    return int(
        await scope.session.scalar(
            select(func.count())
            .select_from(TutorMessage)
            .where(
                TutorMessage.org_id == scope.org_id,
                TutorMessage.student_id == scope.user.id,
                TutorMessage.day == ist_day(now),
                TutorMessage.role == TutorRole.student,
                counted,
            )
        )
        or 0
    )


async def _messages(scope: OrgScope, thread: TutorSession | None) -> list[TutorMessage]:
    if thread is None:
        return []
    rows = await scope.session.scalars(
        scope.select(TutorMessage)
        .where(TutorMessage.tutor_session_id == thread.id)
        .order_by(TutorMessage.created_at, TutorMessage.role)
    )
    return list(rows.all())


async def _refs(scope: OrgScope, ids: set[uuid.UUID]) -> dict[uuid.UUID, ConceptRef]:
    if not ids:
        return {}
    rows = await scope.session.execute(
        select(Concept.id, Concept.slug, Concept.title, Course.slug)
        .join(Course, Course.id == Concept.course_id)
        .where(Concept.id.in_(ids))
    )
    return {r[0]: ConceptRef(id=f"{r[3]}/{r[1]}", title=r[2]) for r in rows.all()}


def _out(m: TutorMessage, refs: dict[uuid.UUID, ConceptRef]) -> TutorMessageOut:
    return TutorMessageOut(
        id=str(m.id),
        role=m.role.value,
        kind=m.kind.value,
        rung=m.rung,
        text=m.text,
        link=refs.get(m.link_concept_id) if m.link_concept_id else None,
        created_at=m.created_at,
    )


async def _thread_out(
    scope: OrgScope,
    q: _Question,
    thread: TutorSession | None,
    enabled: bool,
    now: datetime,
) -> TutorThread:
    messages = [m for m in await _messages(scope, thread) if m.status not in HIDDEN]
    refs = await _refs(scope, {m.link_concept_id for m in messages if m.link_concept_id})
    hints = thread.hints_used if thread else 0
    chats = thread.chat_count if thread else 0
    after = q.mode == "after"
    hints_left = 0 if after else max(0, limits.HINTS_PER_THREAD - hints)
    return TutorThread(
        enabled=enabled,
        mode=q.mode,
        closed=_closed(q, now),
        hints_used=hints,
        hints_left=hints_left,
        next_rung=None if hints_left == 0 else hints + 1,
        chat_left=max(0, limits.CHAT_PER_THREAD - chats),
        daily_left=max(0, limits.DAILY_CAP - await _daily_used(scope, now)),
        resets_at=kp_flow.next_midnight_ist(now),
        messages=[_out(m, refs) for m in messages],
    )


async def get_thread(
    scope: OrgScope, session_id: uuid.UUID, position: int, client: TutorClient | None
) -> TutorThread:
    q = await _question(scope, session_id, position)
    thread = await _find_thread(scope, q)
    return await _thread_out(scope, q, thread, tutor_enabled(client), datetime.now(UTC))


# --- hints and chat ------------------------------------------------------------------------------


@dataclass
class _Reserved:
    question: _Question
    thread_id: uuid.UUID
    student_row_id: uuid.UUID
    context: TutorContext
    transcript: list[TranscriptLine]
    mode: Literal["before", "after"]
    day: date


async def _reserve(
    scope: OrgScope,
    session_id: uuid.UUID,
    position: int,
    kind: TutorKind,
    student_text: str | None,
) -> tuple[_Reserved, TurnRequest | None]:
    """Tx 1: lock, check, insert the pending student row, commit."""
    now = datetime.now(UTC)
    await scope.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"tutor:{scope.user.id}"},
    )
    q = await _question(scope, session_id, position)
    if _closed(q, now):
        raise _conflict("session_closed", "This question has finished.")
    if kind == TutorKind.hint and q.mode == "after":
        raise _conflict("question_answered", "Hints are for before you answer.")
    thread = await _ensure_thread(scope, q)
    rows = await _messages(scope, thread)
    if any(m.role == TutorRole.student and _live_pending(m, now) for m in rows):
        raise _conflict("tutor_busy", "The tutor is still answering.")
    for m in rows:  # lost requests: close them so they're hidden and never counted
        if m.status == TutorStatus.pending:
            m.status = TutorStatus.error
    if kind == TutorKind.hint and thread.hints_used >= limits.HINTS_PER_THREAD:
        raise _conflict("tutor_hint_cap", "No hints left for this question.")
    if kind == TutorKind.chat and thread.chat_count >= limits.CHAT_PER_THREAD:
        raise _conflict("tutor_chat_cap", "No tutor messages left for this question.")
    day = ist_day(now)
    if await _daily_used(scope, now) >= limits.DAILY_CAP:
        raise ApiProblem(
            429,
            "tutor_daily_cap",
            "You've used today's tutor messages.",
            extra={"resets_at": kp_flow.next_midnight_ist(now).isoformat()},
        )
    context = await _context(scope, q)
    transcript = [
        TranscriptLine(m.role.value, m.kind.value, m.rung, m.text)
        for m in rows
        if m.status not in HIDDEN
    ]
    rung = thread.hints_used + 1 if kind == TutorKind.hint else None
    row = scope.new(
        TutorMessage,
        id=uuid.uuid4(),
        tutor_session_id=thread.id,
        student_id=scope.user.id,
        role=TutorRole.student,
        kind=kind,
        mode=TutorMode(q.mode),
        rung=rung,
        status=TutorStatus.pending,
        flagged=False,
        text=student_text,
        day=day,
    )
    await scope.session.flush()
    reserved = _Reserved(q, thread.id, row.id, context, transcript, q.mode, day)
    await scope.session.commit()
    return reserved, None if rung is None else TurnRequest("hint", rung=rung)


async def _close_pending(scope: OrgScope, row_id: uuid.UUID) -> None:
    """Mark a reserved row `error` (not charged, not counted), best effort."""
    try:
        await scope.session.rollback()
        await scope.session.execute(
            update(TutorMessage)
            .where(
                TutorMessage.org_id == scope.org_id,
                TutorMessage.id == row_id,
                TutorMessage.status == TutorStatus.pending,
            )
            .values(status=TutorStatus.error)
        )
        await scope.session.commit()
    except Exception:
        pass


async def _store(
    scope: OrgScope, r: _Reserved, req: TurnRequest, turn: TurnResult, client: TutorClient | None
) -> TutorReply:
    """Tx 2: lock the thread; a before-mode request whose question got answered meanwhile is
    stored as `late` (409 `question_answered`); otherwise store and charge the reply."""
    now = datetime.now(UTC)
    thread = await scope.get(TutorSession, r.thread_id, for_update=True)
    # Serialise with the answer path (which locks the session row): either the answer commits
    # first and this reply is `late`, or the charged hint is committed before the answer reads it.
    await scope.get(PracticeSession, r.question.session.id, for_update=True)
    student_row = await scope.get(TutorMessage, r.student_row_id)
    late = False
    if r.mode == "before":
        q = r.question
        answered = await scope.session.scalar(
            select(func.count())
            .select_from(Attempt)
            .where(
                Attempt.org_id == scope.org_id,
                Attempt.session_id == q.session.id,
                Attempt.position == q.position,
                Attempt.item_id == q.item.id,
            )
        )
        needed = multistep.step_count(q.item.answer) if q.item.type.value == "multistep" else 1
        late = int(answered or 0) >= needed
    status = TutorStatus.late if late else TutorStatus(turn.status)
    # Not `scope.new`: its first parameter is called `model`, like the column.
    tutor_row = TutorMessage(
        org_id=scope.org_id,
        id=uuid.uuid4(),
        tutor_session_id=thread.id,
        student_id=scope.user.id,
        role=TutorRole.tutor,
        kind=TutorKind(req.kind),
        mode=TutorMode(r.mode),
        rung=req.rung,
        category=turn.category,
        status=status,
        flagged=turn.flagged,
        text=turn.text,
        link_concept_id=None if turn.link is None else turn.link.concept_id,
        model=turn.model,
        input_tokens=turn.input_tokens if turn.calls else None,
        output_tokens=turn.output_tokens if turn.calls else None,
        cache_read_tokens=turn.cache_read_tokens if turn.calls else None,
        cache_write_tokens=turn.cache_write_tokens if turn.calls else None,
        latency_ms=turn.latency_ms if turn.calls else None,
        day=r.day,
        created_at=now,
    )
    scope.session.add(tutor_row)
    if late:
        student_row.status = TutorStatus.late
        await scope.session.commit()
        raise _conflict(
            "question_answered", "That question was answered while the tutor was thinking."
        )
    student_row.status = TutorStatus.ok
    if turn.flagged:
        student_row.flagged = True
    if req.kind == "hint" and status in CHARGED:
        thread.hints_used += 1
    elif req.kind == "chat":
        thread.chat_count += 1
    thread.updated_at = now
    await scope.session.flush()
    await scope.session.refresh(tutor_row)
    refs = await _refs(scope, {tutor_row.link_concept_id} if tutor_row.link_concept_id else set())
    message = _out(tutor_row, refs)
    out = await _thread_out(scope, r.question, thread, tutor_enabled(client), now)
    await scope.session.commit()
    return TutorReply(message=message, thread=out)


async def _run(
    scope: OrgScope,
    session_id: uuid.UUID,
    position: int,
    kind: TutorKind,
    client: TutorClient | None,
    student_text: str | None,
    draft: str | None,
) -> TutorReply:
    if not tutor_enabled(client):
        raise _unavailable()
    assert client is not None
    reserved, hint_req = await _reserve(scope, session_id, position, kind, student_text)
    req = hint_req or TurnRequest("chat", text=student_text)
    req = TurnRequest(req.kind, req.rung, req.text, draft)
    try:
        turn = await run_turn(
            reserved.context, reserved.transcript, req, client, get_settings().tutor_model
        )
        return await _store(scope, reserved, req, turn, client)
    except TutorUnavailable:
        await _close_pending(scope, reserved.student_row_id)
        raise _unavailable() from None
    except ApiProblem:
        raise  # `question_answered`: the row is already `late`
    except BaseException:
        # Anything else (a bug, a DB error, a cancelled request): never leave the row pending.
        await _close_pending(scope, reserved.student_row_id)
        raise


def _clean_draft(draft: str | None) -> str | None:
    if draft is None or not draft.strip():
        return None
    return safety.scrub_pii(draft[: limits.MAX_DRAFT])


async def request_hint(
    scope: OrgScope,
    session_id: uuid.UUID,
    position: int,
    client: TutorClient | None,
    draft: str | None = None,
) -> TutorReply:
    return await _run(
        scope, session_id, position, TutorKind.hint, client, None, _clean_draft(draft)
    )


async def send_message(
    scope: OrgScope,
    session_id: uuid.UUID,
    position: int,
    client: TutorClient | None,
    text_: str,
    draft: str | None = None,
) -> TutorReply:
    if len(text_) > limits.MAX_MESSAGE:
        raise ApiProblem(422, "message_too_long", f"Keep it under {limits.MAX_MESSAGE} characters.")
    if not text_.strip():
        raise ApiProblem(422, "message_empty", "Type a question first.")
    clean = safety.scrub_pii(text_.strip())
    return await _run(
        scope, session_id, position, TutorKind.chat, client, clean, _clean_draft(draft)
    )


# --- the answer path -----------------------------------------------------------------------------


async def hints_for_attempt(
    scope: OrgScope, session: PracticeSession, item_id: uuid.UUID, seed: int | None
) -> int:
    """`attempt.hints_used` for the row about to be written at the session's current position:
    charged hints on this question's thread minus those already on earlier rows (multi-step)."""
    if session.kind not in TUTOR_KINDS:
        return 0
    charged = await scope.session.scalar(
        select(TutorSession.hints_used).where(
            TutorSession.org_id == scope.org_id,
            TutorSession.practice_session_id == session.id,
            TutorSession.position == session.current_position,
            TutorSession.item_id == item_id,
            TutorSession.seed.is_not_distinct_from(seed),
        )
    )
    if not charged:
        return 0
    already = await scope.session.scalar(
        select(func.coalesce(func.sum(Attempt.hints_used), 0)).where(
            Attempt.org_id == scope.org_id,
            Attempt.session_id == session.id,
            Attempt.position == session.current_position,
        )
    )
    return max(0, int(charged) - int(already or 0))


# --- operator tasks (CLI; every school) ----------------------------------------------------------


async def purge_text(session: AsyncSession, now: datetime) -> int:
    """Null the text of messages older than `RETENTION_DAYS` (counts, tokens, status and flags
    stay). Idempotent. Operator CLI only: this spans every school."""
    cutoff = now - timedelta(days=limits.RETENTION_DAYS)
    result = await session.execute(
        update(TutorMessage)
        .where(TutorMessage.created_at < cutoff, TutorMessage.purged_at.is_(None))
        .values(text=None, purged_at=now)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class FlaggedRow:
    org_code: str
    student_id: uuid.UUID
    tutor_session_id: uuid.UUID
    message_id: uuid.UUID
    created_at: datetime
    text: str | None


async def flagged(session: AsyncSession, org_code: str | None = None) -> list[FlaggedRow]:
    """Flagged student messages (safety), newest first: ids only, never a name or username.
    Operator CLI only: this spans every school unless `org_code` is given."""
    stmt = (
        select(
            Organization.code,
            TutorMessage.student_id,
            TutorMessage.tutor_session_id,
            TutorMessage.id,
            TutorMessage.created_at,
            TutorMessage.text,
        )
        .join(Organization, Organization.id == TutorMessage.org_id)
        .where(TutorMessage.flagged, TutorMessage.role == TutorRole.student)
        .order_by(TutorMessage.created_at.desc())
    )
    if org_code:
        stmt = stmt.where(Organization.code == org_code.strip().upper())
    return [FlaggedRow(*row) for row in (await session.execute(stmt)).all()]
