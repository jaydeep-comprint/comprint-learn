"""Scheduled reviews (spec 007): one `practice_session` of kind `review` on one concept.

3-5 quick-check questions drawn round-robin across the concept's active KPs and judged on the
trend (`kp_flow.review_outcome`), served exactly like 005's brush-ups. Only a review in Today's
reviews (`srs.queue`) can start. Its end rates the card, gives implicit credit when passed, earns
XP (reason `review`) and, on a 2nd consecutive failed explicit review, sends the concept back to
be relearned: all in the answer's transaction.
"""

import logging
import uuid
from datetime import UTC, datetime

from fsrs import Rating
from sqlalchemy import ColumnElement, text
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.core.errors import not_found
from app.models import (
    AttemptContext,
    ConceptState,
    ConceptStatus,
    PracticeSession,
    ReviewLog,
    ReviewSource,
    SessionKind,
    SessionStatus,
)
from app.schemas.kp import AnswerIn, AnswerResult, QuestionPublic
from app.schemas.reviews import ReviewOutcomeOut, ReviewQueue
from app.services import kp_flow, learn, quiz, srs, xp

log = logging.getLogger(__name__)

RELEARN_AFTER_FAILS = 2


async def _concept(scope: OrgScope, course: str, concept: str) -> uuid.UUID:
    learn._require_student(scope)
    graph = await learn._graph(scope)
    cid = graph.by_ref.get(f"{course}/{concept}")
    if cid is None:
        raise not_found()
    return cid


def _owner(cid: uuid.UUID) -> ColumnElement[bool]:
    return (PracticeSession.kind == SessionKind.review) & (PracticeSession.concept_id == cid)


async def _locked_session(scope: OrgScope, cid: uuid.UUID) -> PracticeSession | None:
    """The student's latest review session on this concept, row-locked."""
    return await scope.session.scalar(
        scope.select(PracticeSession)
        .where(PracticeSession.student_id == scope.user.id, _owner(cid))
        .order_by(PracticeSession.started_at.desc())
        .limit(1)
        .with_for_update()
    )


async def _lock_concept(scope: OrgScope, cid: uuid.UUID) -> None:
    """Serialise review writes on a concept (the same first lock as brush-ups take)."""
    await scope.session.execute(
        scope.select(ConceptState)
        .where(ConceptState.student_id == scope.user.id, ConceptState.concept_id == cid)
        .with_for_update()
    )


def _not_due() -> Exception:
    return kp_flow._conflict("review_not_due", "This review isn't due today.")


async def _end_empty(scope: OrgScope, session: PracticeSession, cid: uuid.UUID) -> None:
    """The concept's questions were retired: the review passes (as a brush-up does), no XP."""
    log.warning("review of %s has no questions left; passing it", cid)
    _, results = await kp_flow._session_state(scope, session.id)
    session.status = SessionStatus.passed
    session.ended_at = datetime.now(UTC)
    await srs.apply_review(
        scope,
        cid,
        passed=True,
        all_correct=all(results),
        source=ReviewSource.review,
        session_id=session.id,
    )


async def review_question(scope: OrgScope, course: str, concept: str) -> QuestionPublic:
    cid = await _concept(scope, course, concept)
    await _lock_concept(scope, cid)
    session = await _locked_session(scope, cid)
    kps = await kp_flow.review_kps(scope, cid)
    try:
        if session is None or session.status != SessionStatus.active:
            status = await srs.offer_status(scope, cid)
            if status == "cap":
                await scope.session.commit()  # keep lazily created cards
                raise kp_flow._conflict("review_cap", "That's today's reviews done. More tomorrow.")
            if status != "offered" or not kps:
                await scope.session.commit()
                raise _not_due()
            session_id = await scope.session.scalar(
                insert(PracticeSession)
                .values(
                    id=uuid.uuid4(),
                    org_id=scope.org_id,
                    student_id=scope.user.id,
                    kind=SessionKind.review,
                    concept_id=cid,
                    status=SessionStatus.active,
                    current_position=1,
                )
                .on_conflict_do_nothing(
                    index_elements=[PracticeSession.student_id, PracticeSession.concept_id],
                    index_where=text("status = 'active' AND kind = 'review'"),
                )
                .returning(PracticeSession.id)
            )
            if session_id is None:  # another tab opened it first
                session = await _locked_session(scope, cid)
                assert session is not None
            else:
                session = await scope.session.get(PracticeSession, session_id)
                assert session is not None
                pool, key = await kp_flow.review_pool(scope, kps, 1)
                await kp_flow._serve(scope, session, pool, 1, key)
        else:
            pool, key = await kp_flow.review_pool(scope, kps, session.current_position)
            if session.current_item_id not in {i.id for i in pool}:  # retired mid-review
                await kp_flow._serve(scope, session, pool, session.current_position, key)
    except kp_flow.EmptyPoolError:
        if session is not None and session.status == SessionStatus.active:
            await _end_empty(scope, session, cid)
        await scope.session.commit()
        raise _not_due() from None
    out = await kp_flow.session_question(scope, session)
    await scope.session.commit()
    return out


async def _stored_review(scope: OrgScope, session_id: str | None) -> ReviewOutcomeOut | None:
    """The review outcome of a resent final answer (from its `review_log` row)."""
    try:
        sid = None if session_id is None else uuid.UUID(session_id)
    except ValueError:
        return None
    if sid is None:
        return None
    row = await scope.session.scalar(
        scope.select(ReviewLog).where(
            ReviewLog.session_id == sid, ReviewLog.source == ReviewSource.review
        )
    )
    if row is None or row.rating is None or row.due_after is None:
        return None
    rating = Rating(row.rating)
    learned = await scope.session.scalar(
        scope.select(ConceptState)
        .with_only_columns(ConceptState.status)
        .where(ConceptState.student_id == scope.user.id, ConceptState.concept_id == row.concept_id)
    )
    relearn = rating == Rating.Again and learned != ConceptStatus.learned
    return ReviewOutcomeOut(
        rating=srs.RATING_NAMES[rating],
        next_due=None if relearn else srs.ist_day(row.due_after),
        relearn=relearn,
    )


async def review_answer(scope: OrgScope, course: str, concept: str, body: AnswerIn) -> AnswerResult:
    cid = await _concept(scope, course, concept)
    await _lock_concept(scope, cid)
    session = await _locked_session(scope, cid)
    answered = await kp_flow.answer_in_session(
        scope, session, body, AttemptContext.review, kp_flow.review_outcome, owner=_owner(cid)
    )
    if isinstance(answered, AnswerResult):
        await scope.session.rollback()
        if answered.xp is not None:  # the answer that ended the review
            answered.review = await _stored_review(scope, body.session_id)
        return answered
    assert session is not None
    out = answered.result
    outcome = answered.outcome
    if outcome == "active":
        try:
            kps = await kp_flow.review_kps(scope, cid)
            pool, key = await kp_flow.review_pool(scope, kps, session.current_position + 1)
            await kp_flow._serve(scope, session, pool, session.current_position + 1, key)
        except kp_flow.EmptyPoolError:
            log.warning("review of %s ran out of questions; passing it", cid)
            outcome = out.session_status = "passed"
            session.status = SessionStatus.passed
            session.ended_at = datetime.now(UTC)
    if outcome in ("passed", "failed"):
        passed = outcome == "passed"
        out.xp = await xp.award_for_session(scope, session, "passed" if passed else "failed", cid)
        info = await srs.apply_review(
            scope,
            cid,
            passed=passed,
            all_correct=all(out.results),
            source=ReviewSource.review,
            session_id=session.id,
        )
        relearn = False
        if passed:
            await srs.give_implicit_credit(scope, cid, "review")
        elif info is not None and info.consecutive_fails >= RELEARN_AFTER_FAILS:
            await kp_flow._relearn(scope, cid)
            relearn = True
        if info is not None:
            out.review = ReviewOutcomeOut(
                rating=srs.RATING_NAMES[info.rating],
                next_due=None if relearn else info.next_due,
                relearn=relearn,
            )
    await scope.session.commit()
    return out


async def queue(scope: OrgScope) -> ReviewQueue:
    """Today's reviews (the student's own read: may finish an expired quiz, create cards)."""
    learn._require_student(scope)
    open_quiz = await quiz._open_quiz(scope, for_update=True)
    if open_quiz is not None:
        await quiz._finish_if_over(scope, open_quiz, datetime.now(UTC))
    out = await srs.queue(scope)
    await scope.session.commit()
    return out
