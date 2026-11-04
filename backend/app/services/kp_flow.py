"""KP question flow (spec 005): sessions, pass/fail, reopening and remediation.

The top of this module is pure (no DB) so the rules are unit-testable; the DB services below
take an `OrgScope` and write only for students (staff previews write nothing).
"""

import asyncio
import logging
import random
import secrets
import uuid
from collections.abc import Callable, Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.content import params
from app.core.errors import ApiProblem, forbidden, not_found
from app.grading import (
    GRADABLE_TYPES,
    MAX_RESPONSE,
    GradeResult,
    InvalidOptionError,
    ShownOptions,
    grade,
)
from app.models import (
    Attempt,
    AttemptContext,
    Concept,
    ConceptState,
    ConceptStatus,
    Item,
    KnowledgePoint,
    KpKeyPrereq,
    KpProgress,
    KpStatus,
    Misconception,
    PracticeSession,
    Remediation,
    RemediationOutcome,
    RemediationState,
    SessionKind,
    SessionStatus,
)
from app.models.content import ItemKind
from app.schemas.content import ItemPublic
from app.schemas.kp import AnswerIn, AnswerResult, QuestionPublic, RemediationOut
from app.schemas.learn import ConceptRef, MisconceptionOut, RemediationRef
from app.services import frontier, learn

log = logging.getLogger(__name__)

Outcome = Literal["active", "passed", "failed"]

IST = ZoneInfo("Asia/Kolkata")  # fixed for the CBSE pilot; per-school timezones are out of scope
MAX_KP_QUESTIONS = 5
MAX_REVIEW_QUESTIONS = 5

# --- pure rules -----------------------------------------------------------------------------------


def kp_outcome(results: Sequence[bool]) -> Outcome:
    """Pass: the last 2 answers correct. Fail: the last 3 wrong, or 5 answers without passing."""
    if len(results) >= 2 and results[-1] and results[-2]:
        return "passed"
    if len(results) >= 3 and not any(results[-3:]):
        return "failed"
    if len(results) >= MAX_KP_QUESTIONS:
        return "failed"
    return "active"


def review_outcome(results: Sequence[bool]) -> Outcome:
    """Pass: >= 3 answers, at least 2 of the last 3 correct and the last one correct.
    Fail: the last 3 wrong, or 5 answers without passing."""
    if len(results) >= 3 and results[-1] and sum(results[-3:]) >= 2:
        return "passed"
    if len(results) >= 3 and not any(results[-3:]):
        return "failed"
    if len(results) >= MAX_REVIEW_QUESTIONS:
        return "failed"
    return "active"


def choose_next_item[K: Hashable](
    pool: Sequence[K],
    last_answered: Mapping[K, datetime],
    served: Collection[K],
    param_items: Collection[K],
) -> K | None:
    """The next item for a session; deterministic given the student's history.

    `pool` is in this student's shuffled order (the tie-break). Items not yet served in this
    session come first, preferring ones never answered for this KP, then the least recently
    answered. Once every item has been served, only param items (new numbers) may come again.
    """
    index = {k: i for i, k in enumerate(pool)}
    floor = datetime.min.replace(tzinfo=UTC)

    def key(k: K) -> tuple[bool, datetime, int]:
        when = last_answered.get(k)
        return (when is not None, when or floor, index[k])

    fresh = [k for k in pool if k not in served]
    if fresh:
        return min(fresh, key=key)
    repeatable = [k for k in pool if k in param_items]
    return min(repeatable, key=key) if repeatable else None


def is_open(
    *,
    failed: bool,
    reopen_at: datetime | None,
    unresolved_remediations: int,
    passed_other_concept_since_fail: bool,
    passed_review_since_fail: bool,
    now: datetime,
) -> bool:
    """May the student start this KP's questions now? (Only failed KPs ever wait.)

    A failed KP is open when every remediation it triggered is resolved and one of: the cooldown
    is over, a KP in a different concept was passed since, or a remediation review was passed since.
    """
    if not failed:
        return True
    if unresolved_remediations:
        return False
    return (
        (reopen_at is not None and now >= reopen_at)
        or passed_other_concept_since_fail
        or passed_review_since_fail
    )


def next_midnight_ist(now: datetime) -> datetime:
    """The next 00:00 in Asia/Kolkata after `now` (aware), in UTC."""
    local = now.astimezone(IST)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=IST)
    return midnight.astimezone(UTC)


# --- DB services ----------------------------------------------------------------------------------

MAX_ANSWER_MS = 1_800_000
# Index predicates as SQL literals, never bound parameters (see learn.LEARN_ATTEMPT_INDEX_WHERE).
_ACTIVE_KP_WHERE = text("status = 'active' AND kind = 'kp'")
_ACTIVE_REMEDIATION_WHERE = text("status = 'active'")
_OPEN_REMEDIATION_WHERE = text("state <> 'resolved'")


class EmptyPoolError(Exception):
    """A KP has no active gradable questions left (retired mid-session)."""


def _conflict(code: str, detail: str, **extra: Any) -> ApiProblem:
    return ApiProblem(409, code, detail, extra=extra or None)


@dataclass
class _KpCtx:
    access: "learn._Access"
    content: "learn._LessonContent"
    kp: KnowledgePoint

    @property
    def view(self) -> "frontier.KpView | None":
        concept = self.access.view
        if concept is None:
            return None
        return next(k for k in concept.kps if k.id == self.kp.id)


async def _kp_ctx(scope: OrgScope, course: str, concept: str, kp_slug: str) -> _KpCtx:
    access = await learn._access(scope, course, concept)
    content = await learn._content(scope, access.node.id)
    kp = next((k for k in content.kps if k.slug == kp_slug), None)
    if kp is None:
        raise not_found()
    return _KpCtx(access, content, kp)


async def _pool(scope: OrgScope, kp_id: uuid.UUID) -> list[Item]:
    """The KP's gradable questions (code/multistep items wait for 006), in authored order."""
    rows = await scope.session.scalars(
        select(Item)
        .where(
            Item.kp_id == kp_id,
            Item.kind == ItemKind.kp_question,
            Item.type.in_(GRADABLE_TYPES),
            Item.retired_at.is_(None),
        )
        .order_by(Item.position)
    )
    return list(rows.all())


def _question(
    scope: OrgScope,
    item: Item,
    seed: int | None,
    *,
    session_id: uuid.UUID | None,
    position: int,
    results: list[bool],
    preview_seed: int | None = None,
) -> QuestionPublic:
    public = ItemPublic.from_row(item)
    values = params.sample_answer(item.answer, seed)
    is_mcq = public.type == "mcq"
    return QuestionPublic(
        session_id=None if session_id is None else str(session_id),
        position=position,
        item_id=str(item.id),
        type=public.type,  # pools hold gradable types only (validated by the schema)
        prompt_md=params.render(public.prompt, values),
        unit=public.unit,
        options=learn._shown_options(scope, item).public() if is_mcq else None,
        variables=(list(item.answer["spec"]["variables"]) if public.type == "expression" else None),
        results=results,
        preview_seed=preview_seed,
    )


async def _session_attempts(scope: OrgScope, session_id: uuid.UUID) -> list[Attempt]:
    rows = await scope.session.scalars(
        scope.select(Attempt).where(Attempt.session_id == session_id).order_by(Attempt.position)
    )
    return list(rows.all())


async def _serve(
    scope: OrgScope, session: PracticeSession, pool: list[Item], position: int, order_key: uuid.UUID
) -> Item:
    """Choose the next item (`choose_next_item`) with a fresh seed, stored before it's returned.

    Raises `EmptyPoolError` when the pool has no active gradable items (retired content)."""
    if not pool:
        raise EmptyPoolError(order_key)
    served = {a.item_id for a in await _session_attempts(scope, session.id)}
    pool_ids = [i.id for i in pool]
    history = dict(
        (
            await scope.session.execute(
                scope.select(Attempt)
                .with_only_columns(Attempt.item_id, func.max(Attempt.created_at))
                .where(Attempt.student_id == scope.user.id, Attempt.item_id.in_(pool_ids))
                .group_by(Attempt.item_id)
            )
        ).all()
    )
    by_id = {str(i.id): i for i in pool}
    order = [by_id[k].id for k in learn.shuffled_order(list(by_id), scope.user.id, order_key)]
    params_ids = {i.id for i in pool if i.has_params}
    chosen = choose_next_item(order, history, served, params_ids)
    if chosen is None:
        # Only invalid content gets here (the validator requires >= 5 fixed items or a param
        # item): repeating means repeating an item whose answer was shown.
        log.error("KP pool %s exhausted within a session; repeating an item", order_key)
        chosen = choose_next_item(order, history, set(), params_ids)
    assert chosen is not None
    item = next(i for i in pool if i.id == chosen)
    session.current_item_id = item.id
    session.current_seed = secrets.randbelow(2**31) if item.has_params else None
    session.current_position = position
    session.current_served_at = datetime.now(UTC)
    await scope.session.flush()
    return item


def _check_response(response: str) -> None:
    if len(response) > MAX_RESPONSE:
        raise ApiProblem(422, "invalid_response", "That answer is too long.")


async def _grade(
    scope: OrgScope, item: Item, seed: int | None, response: str, shown: ShownOptions | None = None
) -> tuple[GradeResult, ShownOptions | None, dict[str, Any]]:
    values = params.sample_answer(item.answer, seed)
    if item.type.value == "mcq" and shown is None:
        shown = learn._shown_options(scope, item)
    try:
        result = await asyncio.to_thread(
            grade, item.type.value, item.answer, values, response, shown=shown
        )
    except InvalidOptionError as exc:
        raise ApiProblem(422, "invalid_option", "That isn't one of the options.") from exc
    return result, shown, values


async def _misconception(scope: OrgScope, item: Item, slug: str | None) -> tuple[Any, Any]:
    """(id, title) of a tagged misconception in the item's course."""
    if slug is None:
        return None, None
    row = (
        await scope.session.execute(
            select(Misconception.id, Misconception.title)
            .join(Concept, Concept.course_id == Misconception.course_id)
            .where(Concept.id == item.concept_id, Misconception.slug == slug)
        )
    ).first()
    return (None, None) if row is None else (row[0], row[1])


def _explanation(item: Item, values: dict[str, Any]) -> str | None:
    text_ = item.answer.get("explanation")
    if not text_:
        return None
    try:
        return params.render(text_, values)
    except KeyError:
        return str(text_)


async def _result(
    scope: OrgScope,
    item: Item,
    result: GradeResult,
    values: dict[str, Any],
    *,
    correct: bool,
    session_status: str,
    results: list[bool],
    already_answered: bool,
) -> AnswerResult:
    _, title = await _misconception(scope, item, result.misconception)
    return AnswerResult(
        correct=correct,
        display_answer=result.display_answer,
        explanation_md=_explanation(item, values),
        misconception=None if title is None else MisconceptionOut(title=title),
        note=result.note,
        session_status=session_status,
        already_answered=already_answered,
        results=results,
    )


async def _stored_result(
    scope: OrgScope, session: PracticeSession, attempt: Attempt
) -> AnswerResult:
    """The result of an answer already given (double submit, two tabs)."""
    item = await scope.session.get(Item, attempt.item_id)
    assert item is not None
    shown = None
    raw = str(attempt.response.get("raw", ""))
    if item.type.value == "mcq":
        options = {o.id: o for o in ItemPublic.from_row(item).options or []}
        order = [i for i in attempt.response.get("order", []) if i in options]
        shown = ShownOptions([options[i] for i in order])
        raw = shown.to_client(attempt.response.get("option"))
    result, _, values = await _grade(scope, item, attempt.seed, raw, shown)
    results = [a.correct for a in await _session_attempts(scope, session.id)]
    return await _result(
        scope,
        item,
        result,
        values,
        correct=attempt.correct,
        session_status=session.status.value,
        results=results,
        already_answered=True,
    )


@dataclass
class _Answered:
    result: AnswerResult
    outcome: Outcome
    item: Item


async def _answer_in_session(
    scope: OrgScope,
    session: PracticeSession | None,
    body: AnswerIn,
    context: AttemptContext,
    judge: Callable[[Sequence[bool]], Outcome],
) -> _Answered | AnswerResult:
    """Grade and store one answer at the session's current position (the session row is locked).

    Returns the stored result for a repeat of an answered position; 409 `stale_question` for any
    other position mismatch."""
    if session is None:
        raise _conflict("stale_question", "That question is no longer current.")
    if session.status != SessionStatus.active or body.position != session.current_position:
        stored = await scope.session.scalar(
            scope.select(Attempt).where(
                Attempt.session_id == session.id, Attempt.position == body.position
            )
        )
        if stored is None:
            raise _conflict("stale_question", "That question is no longer current.")
        return await _stored_result(scope, session, stored)
    assert session.current_item_id is not None
    item = await scope.session.get(Item, session.current_item_id)
    assert item is not None
    result, shown, values = await _grade(scope, item, session.current_seed, body.response)
    misconception_id, _ = await _misconception(scope, item, result.misconception)
    now = datetime.now(UTC)
    served_at = session.current_served_at or now
    elapsed = int((now - served_at).total_seconds() * 1000)
    response: dict[str, Any] = {"raw": body.response}
    if shown is not None:
        response = {"option": result.chosen, "order": [o.id for o in shown.authored]}
    inserted = await scope.session.scalar(
        insert(Attempt)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            item_id=item.id,
            item_version=item.version,
            context=context,
            seed=session.current_seed,
            response=response,
            correct=result.correct,
            misconception_id=misconception_id,
            time_taken_ms=max(0, min(body.time_taken_ms, elapsed, MAX_ANSWER_MS)),
            hints_used=0,
            session_id=session.id,
            position=session.current_position,
        )
        .on_conflict_do_nothing(index_elements=[Attempt.session_id, Attempt.position])
        .returning(Attempt.id)
    )
    if inserted is None:  # can't happen while we hold the session lock; be safe anyway
        stored = await scope.session.scalar(
            scope.select(Attempt).where(
                Attempt.session_id == session.id, Attempt.position == body.position
            )
        )
        assert stored is not None
        return await _stored_result(scope, session, stored)
    results = [a.correct for a in await _session_attempts(scope, session.id)]
    outcome = judge(results)
    if outcome != "active":
        session.status = SessionStatus(outcome)
        session.ended_at = now
    out = await _result(
        scope,
        item,
        result,
        values,
        correct=result.correct,
        session_status=outcome,
        results=results,
        already_answered=False,
    )
    return _Answered(out, outcome, item)


async def _preview_answer(scope: OrgScope, pool: list[Item], body: AnswerIn) -> AnswerResult:
    """Staff: grade the previewed item with its seed; nothing is written."""
    item = next((i for i in pool if str(i.id) == body.item_id), None)
    if item is None:
        raise ApiProblem(422, "invalid_item", "Send the previewed item_id and seed back.")
    seed = body.seed if item.has_params else None
    result, _, values = await _grade(scope, item, seed, body.response)
    return await _result(
        scope,
        item,
        result,
        values,
        correct=result.correct,
        session_status="active",
        results=[],
        already_answered=False,
    )


# --- KP questions ---------------------------------------------------------------------------------


async def _locked_kp_session(scope: OrgScope, kp_id: uuid.UUID) -> PracticeSession | None:
    """The student's latest session for this KP, row-locked."""
    return await scope.session.scalar(
        scope.select(PracticeSession)
        .where(PracticeSession.student_id == scope.user.id, PracticeSession.kp_id == kp_id)
        .order_by(PracticeSession.started_at.desc())
        .limit(1)
        .with_for_update()
    )


async def _waiting(scope: OrgScope, ctx: _KpCtx, kp: "frontier.KpView") -> ApiProblem:
    refs = await learn.remediation_refs(scope, ctx.access.graph, kp.remediations)
    return _conflict(
        "kp_waiting",
        "This part reopens later with new questions.",
        reopen_at=None if kp.reopen_at is None else kp.reopen_at.isoformat(),
        remediations=[r.model_dump() for _, r in refs],
    )


async def current_question(
    scope: OrgScope, course: str, concept: str, kp_slug: str
) -> QuestionPublic:
    """The active session's current question, or a new session when the KP is open."""
    ctx = await _kp_ctx(scope, course, concept, kp_slug)
    pool = await _pool(scope, ctx.kp.id)
    if scope.user.is_staff:
        if not pool:
            raise not_found()
        item = random.choice(pool)
        seed = secrets.randbelow(2**31) if item.has_params else None
        return _question(
            scope, item, seed, session_id=None, position=1, results=[], preview_seed=seed
        )

    session = await _locked_kp_session(scope, ctx.kp.id)
    try:
        if session is None or session.status != SessionStatus.active:
            session = await _start_kp_session(scope, ctx, pool)
        elif session.current_item_id not in {i.id for i in pool}:  # retired mid-session
            await _serve(scope, session, pool, session.current_position, ctx.kp.id)
    except EmptyPoolError:
        await _end_active_kp_sessions(scope, ctx.kp.id)
        await _on_kp_passed(scope, ctx)
        await scope.session.commit()
        raise _conflict("kp_passed", "This part has no questions left.") from None
    current = await scope.session.get(Item, session.current_item_id)
    assert current is not None
    results = [a.correct for a in await _session_attempts(scope, session.id)]
    out = _question(
        scope,
        current,
        session.current_seed,
        session_id=session.id,
        position=session.current_position,
        results=results,
    )
    await scope.session.commit()
    return out


async def _start_kp_session(scope: OrgScope, ctx: _KpCtx, pool: list[Item]) -> PracticeSession:
    kp = ctx.view
    concept = ctx.access.view
    assert kp is not None and concept is not None
    if kp.passed:
        raise _conflict("kp_passed", "You've already passed this part.")
    check = ctx.content.check
    if check is not None and await learn._stored_attempt(scope, check.id) is None:
        raise _conflict("check_first", "Answer the quick check first.")
    for earlier in concept.kps:
        if earlier.id == kp.id:
            break
        if not earlier.passed:
            raise _conflict("kp_order", "Pass the earlier parts first.", kp=earlier.slug)
    if not kp.open:
        raise await _waiting(scope, ctx, kp)

    session_id = await scope.session.scalar(
        insert(PracticeSession)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            kind=SessionKind.kp,
            kp_id=kp.id,
            status=SessionStatus.active,
            current_position=1,
        )
        .on_conflict_do_nothing(
            index_elements=[PracticeSession.student_id, PracticeSession.kp_id],
            index_where=_ACTIVE_KP_WHERE,
        )
        .returning(PracticeSession.id)
    )
    if session_id is None:  # another tab opened it first: use that one
        winner = await _locked_kp_session(scope, kp.id)
        assert winner is not None
        return winner
    await scope.session.execute(
        insert(KpProgress)
        .values(
            org_id=scope.org_id,
            student_id=scope.user.id,
            kp_id=kp.id,
            status=KpStatus.in_progress,
        )
        .on_conflict_do_update(
            index_elements=[KpProgress.student_id, KpProgress.kp_id],
            set_={"status": KpStatus.in_progress, "updated_at": func.now()},
            where=(KpProgress.org_id == scope.org_id) & (KpProgress.status != KpStatus.passed),
        )
    )
    await frontier.ensure_started(scope, ctx.access.node.id)
    session = await scope.session.get(PracticeSession, session_id)
    assert session is not None
    await _serve(scope, session, pool, 1, kp.id)
    return session


async def answer(
    scope: OrgScope, course: str, concept: str, kp_slug: str, body: AnswerIn
) -> AnswerResult:
    _check_response(body.response)
    ctx = await _kp_ctx(scope, course, concept, kp_slug)
    pool = await _pool(scope, ctx.kp.id)
    if scope.user.is_staff:
        return await _preview_answer(scope, pool, body)

    session = await _locked_kp_session(scope, ctx.kp.id)
    answered = await _answer_in_session(scope, session, body, AttemptContext.kp, kp_outcome)
    if isinstance(answered, AnswerResult):
        await scope.session.rollback()
        return answered
    assert session is not None
    out = answered.result
    if answered.outcome == "active":
        try:
            await _serve(scope, session, pool, session.current_position + 1, ctx.kp.id)
        except EmptyPoolError:  # every question retired mid-session: the KP doesn't block
            out.session_status = "passed"
            answered = _Answered(out, "passed", answered.item)
            await _end_active_kp_sessions(scope, ctx.kp.id)
    if answered.outcome == "passed":
        out.concept_learned, out.unlocked = await _on_kp_passed(scope, ctx)
    elif answered.outcome == "failed":
        out.remediations = await _on_kp_failed(scope, ctx)
    await scope.session.commit()
    return out


async def _end_active_kp_sessions(scope: OrgScope, kp_id: uuid.UUID) -> None:
    """A KP whose gradable questions were all retired counts as passed (spec edge case)."""
    log.warning("KP %s has no gradable questions left; marking it passed", kp_id)
    await scope.session.execute(
        update(PracticeSession)
        .where(
            PracticeSession.org_id == scope.org_id,
            PracticeSession.student_id == scope.user.id,
            PracticeSession.kp_id == kp_id,
            PracticeSession.status == SessionStatus.active,
        )
        .values(status=SessionStatus.passed, ended_at=func.now())
        .execution_options(synchronize_session="fetch")
    )


async def _reachable(scope: OrgScope, graph: "learn._Graph") -> set[uuid.UUID]:
    slugs = await learn._student_course_slugs(scope, graph)
    return {c for slug in slugs for c, _ in graph.outline(slug)}


async def _on_kp_passed(scope: OrgScope, ctx: _KpCtx) -> tuple[bool, list[ConceptRef]]:
    """KP passed; the concept is learned once every active KP is. Returns (learned, unlocked)."""
    await scope.session.execute(
        insert(KpProgress)
        .values(
            org_id=scope.org_id,
            student_id=scope.user.id,
            kp_id=ctx.kp.id,
            status=KpStatus.passed,
            passed_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=[KpProgress.student_id, KpProgress.kp_id],
            set_={"status": KpStatus.passed, "passed_at": func.now(), "updated_at": func.now()},
            where=KpProgress.org_id == scope.org_id,
        )
    )
    graph = ctx.access.graph
    cid = ctx.access.node.id
    front = await frontier.load(scope, [cid], graph.prereqs, promote=False)
    view = front.views[cid]
    if view.status == "learned" or view.next_kp is not None:
        return False, []
    await frontier.mark_learned(scope, cid)
    reachable = await _reachable(scope, graph)
    dependants = [c for c, ps in graph.prereqs.items() if cid in ps and c in reachable]
    after = await frontier.load(scope, dependants, graph.prereqs, promote=False)
    unlocked = sorted(
        (c for c in dependants if after.status(c) == "ready"),
        key=lambda c: graph.nodes[c].sort_key(),
    )
    return True, [learn._concept_ref(graph, c) for c in unlocked]


async def _on_kp_failed(scope: OrgScope, ctx: _KpCtx) -> list[RemediationRef]:
    """KP failed: cooldown until the next IST midnight; from the 2nd fail on, one remediation per
    active key prerequisite that has none open (a review if it's learned, else a relearn)."""
    now = datetime.now(UTC)
    fail_count = await scope.session.scalar(
        insert(KpProgress)
        .values(
            org_id=scope.org_id,
            student_id=scope.user.id,
            kp_id=ctx.kp.id,
            status=KpStatus.failed,
            fail_count=1,
            failed_at=now,
            reopen_at=next_midnight_ist(now),
        )
        .on_conflict_do_update(
            index_elements=[KpProgress.student_id, KpProgress.kp_id],
            set_={
                "status": KpStatus.failed,
                "fail_count": KpProgress.fail_count + 1,
                "failed_at": now,
                "reopen_at": next_midnight_ist(now),
                "updated_at": func.now(),
            },
            where=KpProgress.org_id == scope.org_id,
        )
        .returning(KpProgress.fail_count)
    )
    if fail_count is None or fail_count < 2:
        return []
    graph = ctx.access.graph
    prereqs = [
        p
        for p in (
            await scope.session.scalars(
                select(KpKeyPrereq.concept_id).where(KpKeyPrereq.kp_id == ctx.kp.id)
            )
        ).all()
        if p in graph.nodes
    ]
    if not prereqs:
        return []
    learned = set(
        (
            await scope.session.scalars(
                scope.select(ConceptState)
                .with_only_columns(ConceptState.concept_id)
                .where(
                    ConceptState.student_id == scope.user.id,
                    ConceptState.concept_id.in_(prereqs),
                    ConceptState.status == ConceptStatus.learned,
                )
            )
        ).all()
    )
    created = []
    for prereq in sorted(prereqs, key=lambda p: graph.nodes[p].sort_key()):
        state = RemediationState.review_due if prereq in learned else RemediationState.relearn
        rid = await scope.session.scalar(
            insert(Remediation)
            .values(
                id=uuid.uuid4(),
                org_id=scope.org_id,
                student_id=scope.user.id,
                kp_id=ctx.kp.id,
                prereq_concept_id=prereq,
                state=state,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    Remediation.student_id,
                    Remediation.kp_id,
                    Remediation.prereq_concept_id,
                ],
                index_where=_OPEN_REMEDIATION_WHERE,
            )
            .returning(Remediation.id)
        )
        if rid is not None:
            created.append(frontier.RemediationView(rid, ctx.kp.id, prereq, state))
    refs = await learn.remediation_refs(scope, graph, created)
    return [r for _, r in refs]


# --- remediation reviews --------------------------------------------------------------------------


async def _remediation(
    scope: OrgScope, remediation_id: str, *, for_update: bool = False
) -> Remediation:
    """The caller's own remediation (404 for anyone else's; staff 403)."""
    if scope.user.is_staff:
        raise forbidden()
    try:
        rid = uuid.UUID(remediation_id)
    except ValueError as exc:
        raise not_found() from exc
    rem = await scope.get(Remediation, rid, for_update=for_update)
    if rem.student_id != scope.user.id:
        raise not_found()
    return rem


async def remediation_info(scope: OrgScope, remediation_id: str) -> RemediationOut:
    rem = await _remediation(scope, remediation_id)
    graph = await learn._graph(scope)
    kp = await scope.session.get(KnowledgePoint, rem.kp_id)
    if kp is None or kp.concept_id not in graph.nodes or rem.prereq_concept_id not in graph.nodes:
        raise not_found()
    return RemediationOut(
        id=str(rem.id),
        state=rem.state.value,
        kind="review" if rem.state == RemediationState.review_due else "relearn",
        prereq=learn._concept_ref(graph, rem.prereq_concept_id),
        concept=learn._concept_ref(graph, kp.concept_id),
        kp_title=kp.title,
    )


async def _review_kps(scope: OrgScope, rem: Remediation) -> list["frontier.KpView"]:
    kps = await frontier.active_kps(scope, [rem.prereq_concept_id])
    return [k for k in kps if k.gradable]


async def _review_pool(
    scope: OrgScope, kps: list["frontier.KpView"], position: int
) -> tuple[list[Item], uuid.UUID]:
    """Round-robin across the prereq's KPs: position p draws from KP (p - 1) mod n."""
    if not kps:
        raise EmptyPoolError(None)
    kp = kps[(position - 1) % len(kps)]
    return await _pool(scope, kp.id), kp.id


def _resolve_review(rem: Remediation, session: PracticeSession | None) -> None:
    rem.state = RemediationState.resolved
    rem.outcome = RemediationOutcome.review_passed
    rem.resolved_at = datetime.now(UTC)
    if session is not None and session.status == SessionStatus.active:
        session.status = SessionStatus.passed
        session.ended_at = rem.resolved_at


async def _kp_unblocked(scope: OrgScope, rem: Remediation) -> bool:
    """No other open remediation still blocks the KP this one was created for (the same rule as
    the frontier: remediations on retired prerequisites don't block)."""
    blocking = frontier.open_remediations(scope).where(
        Remediation.kp_id == rem.kp_id, Remediation.id != rem.id
    )
    others = await scope.session.scalar(blocking.with_only_columns(func.count()))
    return not others


async def _locked_review_session(scope: OrgScope, rem: Remediation) -> PracticeSession | None:
    return await scope.session.scalar(
        scope.select(PracticeSession)
        .where(PracticeSession.remediation_id == rem.id)
        .order_by(PracticeSession.started_at.desc())
        .limit(1)
        .with_for_update()
    )


async def remediation_question(scope: OrgScope, remediation_id: str) -> QuestionPublic:
    rem = await _remediation(scope, remediation_id, for_update=True)
    if rem.state != RemediationState.review_due:
        raise _conflict("not_due", "This brush-up isn't due.", state=rem.state.value)
    session = await _locked_review_session(scope, rem)
    try:
        return await _review_question(scope, rem, session)
    except EmptyPoolError:  # the prereq's questions were retired: don't block the KP forever
        log.warning("remediation %s has no questions left; resolving it", rem.id)
        _resolve_review(rem, session)
        # A session opened just before the pool turned out empty mustn't stay active.
        await scope.session.execute(
            update(PracticeSession)
            .where(
                PracticeSession.org_id == scope.org_id,
                PracticeSession.remediation_id == rem.id,
                PracticeSession.status == SessionStatus.active,
            )
            .values(status=SessionStatus.passed, ended_at=func.now())
            .execution_options(synchronize_session="fetch")
        )
        await scope.session.commit()
        raise _conflict("not_due", "This brush-up has no questions.", state="resolved") from None


async def _review_question(
    scope: OrgScope, rem: Remediation, session: PracticeSession | None
) -> QuestionPublic:
    kps = await _review_kps(scope, rem)
    if not kps:
        raise EmptyPoolError(rem.id)
    if session is None or session.status != SessionStatus.active:
        session_id = await scope.session.scalar(
            insert(PracticeSession)
            .values(
                id=uuid.uuid4(),
                org_id=scope.org_id,
                student_id=scope.user.id,
                kind=SessionKind.remediation,
                remediation_id=rem.id,
                status=SessionStatus.active,
                current_position=1,
            )
            .on_conflict_do_nothing(
                index_elements=[PracticeSession.remediation_id],
                index_where=_ACTIVE_REMEDIATION_WHERE,
            )
            .returning(PracticeSession.id)
        )
        if session_id is None:
            session = await _locked_review_session(scope, rem)
            assert session is not None
        else:
            session = await scope.session.get(PracticeSession, session_id)
            assert session is not None
            pool, key = await _review_pool(scope, kps, 1)
            await _serve(scope, session, pool, 1, key)
    else:
        pool, key = await _review_pool(scope, kps, session.current_position)
        if session.current_item_id not in {i.id for i in pool}:
            await _serve(scope, session, pool, session.current_position, key)
    item = await scope.session.get(Item, session.current_item_id)
    assert item is not None
    results = [a.correct for a in await _session_attempts(scope, session.id)]
    out = _question(
        scope,
        item,
        session.current_seed,
        session_id=session.id,
        position=session.current_position,
        results=results,
    )
    await scope.session.commit()
    return out


async def remediation_answer(scope: OrgScope, remediation_id: str, body: AnswerIn) -> AnswerResult:
    _check_response(body.response)
    rem = await _remediation(scope, remediation_id)
    # Serialise every review on this prerequisite (prereq row, then remediation, then session):
    # two reviews on the same prereq failing at once would otherwise each hold their own
    # session and wait for the other's in `close_review_sessions` (a deadlock).
    await scope.session.execute(
        scope.select(ConceptState)
        .where(
            ConceptState.student_id == scope.user.id,
            ConceptState.concept_id == rem.prereq_concept_id,
        )
        .with_for_update()
    )
    await scope.session.refresh(rem, with_for_update=True)
    session = await _locked_review_session(scope, rem)
    if rem.state != RemediationState.review_due:
        # A repeat of an answered position still gets its stored result; nothing else may be
        # answered once the brush-up stopped being due (e.g. a relearn closed it in another tab).
        if session is not None and session.status != SessionStatus.active:
            stored = await scope.session.scalar(
                scope.select(Attempt).where(
                    Attempt.session_id == session.id, Attempt.position == body.position
                )
            )
            if stored is not None:
                return await _stored_result(scope, session, stored)
        raise _conflict("not_due", "This brush-up isn't due.", state=rem.state.value)
    answered = await _answer_in_session(
        scope, session, body, AttemptContext.remediation, review_outcome
    )
    if isinstance(answered, AnswerResult):
        await scope.session.rollback()
        return answered
    assert session is not None
    out = answered.result
    outcome = answered.outcome
    if outcome == "active":
        try:
            kps = await _review_kps(scope, rem)
            pool, key = await _review_pool(scope, kps, session.current_position + 1)
            await _serve(scope, session, pool, session.current_position + 1, key)
        except EmptyPoolError:
            log.warning("remediation %s ran out of questions; resolving it", rem.id)
            outcome = out.session_status = "passed"
    if outcome == "passed":
        _resolve_review(rem, session)
        out.kp_open = await _kp_unblocked(scope, rem)
    elif outcome == "failed":
        await _relearn(scope, rem.prereq_concept_id)
    await scope.session.commit()
    return out


async def _relearn(scope: OrgScope, concept_id: uuid.UUID) -> None:
    """A failed review: the prereq goes back to in progress with every KP reset (history kept);
    its open reviews become relearns (their active sessions end), resolved when it's learned
    again."""
    await frontier.close_review_sessions(scope, concept_id)
    await scope.session.execute(
        update(ConceptState)
        .where(
            ConceptState.org_id == scope.org_id,
            ConceptState.student_id == scope.user.id,
            ConceptState.concept_id == concept_id,
        )
        .values(
            status=ConceptStatus.in_progress,
            learned_at=None,
            relearn_count=ConceptState.relearn_count + 1,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    kp_ids = select(KnowledgePoint.id).where(KnowledgePoint.concept_id == concept_id)
    await scope.session.execute(
        update(KpProgress)
        .where(
            KpProgress.org_id == scope.org_id,
            KpProgress.student_id == scope.user.id,
            KpProgress.kp_id.in_(kp_ids),
        )
        .values(
            status=KpStatus.not_started,
            fail_count=0,
            passed_at=None,
            failed_at=None,
            reopen_at=None,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    await scope.session.execute(
        update(Remediation)
        .where(
            Remediation.org_id == scope.org_id,
            Remediation.student_id == scope.user.id,
            Remediation.prereq_concept_id == concept_id,
            Remediation.state == RemediationState.review_due,
        )
        .values(state=RemediationState.relearn)
        .execution_options(synchronize_session=False)
    )
