"""Direct-row seeding for the dashboard and assignment DB tests (spec 010): learning state written
straight to the tables, so a class of many students is quick to set up."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppUser,
    Attempt,
    AttemptContext,
    ConceptSource,
    ConceptState,
    ConceptStatus,
    Enrollment,
    Item,
    KnowledgePoint,
    KpProgress,
    KpStatus,
    PracticeSession,
    Remediation,
    RemediationState,
    SessionKind,
    SessionStatus,
    StudyActivity,
    StudyTime,
    Subject,
    TutorKind,
    TutorMessage,
    TutorMode,
    TutorRole,
    TutorSession,
    TutorStatus,
    XpEvent,
    XpGrade,
    XpReason,
)
from app.models.content import ItemKind
from tests.db_seed import student

NOW = datetime.now(UTC)


@dataclass
class Kp:
    id: uuid.UUID
    concept_id: uuid.UUID
    item_id: uuid.UUID


async def kps_of(session: AsyncSession, concept_id: uuid.UUID) -> list[Kp]:
    """Active KPs of a concept in order, each with one of its questions."""
    rows = (
        await session.execute(
            select(KnowledgePoint.id, KnowledgePoint.concept_id)
            .where(KnowledgePoint.concept_id == concept_id, KnowledgePoint.retired_at.is_(None))
            .order_by(KnowledgePoint.position)
        )
    ).all()
    out = []
    for kp_id, cid in rows:
        item = await session.scalar(
            select(Item.id)
            .where(Item.kp_id == kp_id, Item.kind == ItemKind.kp_question)
            .order_by(Item.position)
            .limit(1)
        )
        assert item is not None
        out.append(Kp(kp_id, cid, item))
    return out


async def add_students(
    session: AsyncSession, org_id: uuid.UUID, class_id: uuid.UUID, n: int, prefix: str
) -> list[uuid.UUID]:
    users = [student(org_id, f"{prefix}{i:02d}") for i in range(n)]
    session.add_all(users)
    await session.flush()
    session.add_all(
        Enrollment(
            org_id=org_id, class_id=class_id, student_id=u.id, created_at=NOW - timedelta(days=30)
        )
        for u in users
    )
    await session.flush()
    return [u.id for u in users]


def concept_state(
    org: uuid.UUID,
    sid: uuid.UUID,
    cid: uuid.UUID,
    status: ConceptStatus,
    learned_at: datetime | None = None,
) -> ConceptState:
    return ConceptState(
        org_id=org,
        student_id=sid,
        concept_id=cid,
        status=status,
        source=ConceptSource.lesson,
        learned_at=learned_at,
    )


def kp_progress(
    org: uuid.UUID, sid: uuid.UUID, kp: uuid.UUID, status: KpStatus, **kw: Any
) -> KpProgress:
    return KpProgress(org_id=org, student_id=sid, kp_id=kp, status=status, **kw)


async def kp_try(
    session: AsyncSession,
    org: uuid.UUID,
    sid: uuid.UUID,
    kp: Kp,
    *,
    passed: bool,
    ended_at: datetime = NOW,
    answers: int = 2,
    hints: int = 0,
    ms: int = 3000,
) -> uuid.UUID:
    """One ended KP session with `answers` attempts (all right when passed, all wrong when not)."""
    ps = PracticeSession(
        id=uuid.uuid4(),
        org_id=org,
        student_id=sid,
        kind=SessionKind.kp,
        kp_id=kp.id,
        status=SessionStatus.passed if passed else SessionStatus.failed,
        started_at=ended_at - timedelta(minutes=5),
        ended_at=ended_at,
    )
    session.add(ps)
    await session.flush()
    for pos in range(answers):
        session.add(
            attempt(
                org,
                sid,
                kp.item_id,
                correct=passed,
                context=AttemptContext.kp,
                session_id=ps.id,
                position=pos,
                hints=hints if pos == 0 else 0,
                ms=ms,
                at=ended_at,
            )
        )
    await session.flush()
    return ps.id


def attempt(
    org: uuid.UUID,
    sid: uuid.UUID,
    item_id: uuid.UUID,
    *,
    correct: bool,
    context: AttemptContext = AttemptContext.kp,
    session_id: uuid.UUID | None = None,
    position: int | None = None,
    hints: int = 0,
    ms: int = 3000,
    at: datetime = NOW,
    misconception_id: uuid.UUID | None = None,
    response: dict[str, Any] | None = None,
) -> Attempt:
    return Attempt(
        org_id=org,
        student_id=sid,
        item_id=item_id,
        item_version=1,
        context=context,
        seed=None,
        response=response or {"raw": "1"},
        correct=correct,
        misconception_id=misconception_id,
        time_taken_ms=ms,
        hints_used=hints,
        session_id=session_id,
        position=position,
        created_at=at,
    )


def xp_event(
    org: uuid.UUID, sid: uuid.UUID, cid: uuid.UUID, amount: int, *, subject: Subject, day: date
) -> XpEvent:
    return XpEvent(
        org_id=org,
        student_id=sid,
        session_id=None,
        reason=XpReason.kp,
        concept_id=cid,
        subject=subject,
        amount=amount,
        grade=XpGrade.rushed if amount < 0 else XpGrade.passed,
        base_minutes=Decimal("2.0"),
        answered=2,
        rushed_count=2 if amount < 0 else 0,
        hints=0,
        day=day,
    )


def study(
    org: uuid.UUID,
    sid: uuid.UUID,
    cid: uuid.UUID,
    seconds: int,
    activity: StudyActivity,
    at: datetime = NOW,
) -> StudyTime:
    return StudyTime(
        org_id=org,
        student_id=sid,
        concept_id=cid,
        activity=activity,
        step="intro" if activity == StudyActivity.learn else "kpq:x",
        active_seconds=seconds,
        created_at=at,
    )


def remediation(
    org: uuid.UUID, sid: uuid.UUID, kp: uuid.UUID, prereq: uuid.UUID, state: RemediationState
) -> Remediation:
    return Remediation(org_id=org, student_id=sid, kp_id=kp, prereq_concept_id=prereq, state=state)


async def tutor_thread(
    session: AsyncSession,
    org: uuid.UUID,
    sid: uuid.UUID,
    practice_session_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    flagged: bool = False,
    purged: bool = False,
) -> uuid.UUID:
    t = TutorSession(
        id=uuid.uuid4(),
        org_id=org,
        student_id=sid,
        practice_session_id=practice_session_id,
        position=0,
        item_id=item_id,
        item_version=1,
        seed=None,
        hints_used=1,
        chat_count=1,
    )
    session.add(t)
    await session.flush()
    day = NOW.date()
    session.add_all(
        [
            TutorMessage(
                org_id=org,
                tutor_session_id=t.id,
                student_id=sid,
                role=TutorRole.student,
                kind=TutorKind.chat,
                mode=TutorMode.before,
                status=TutorStatus.ok,
                flagged=flagged,
                text=None if purged else "why is it negative?",
                purged_at=NOW if purged else None,
                day=day,
                created_at=NOW - timedelta(seconds=2),
            ),
            TutorMessage(
                org_id=org,
                tutor_session_id=t.id,
                student_id=sid,
                role=TutorRole.tutor,
                kind=TutorKind.chat,
                mode=TutorMode.before,
                status=TutorStatus.ok,
                text=None if purged else "Look at the worked example.",
                purged_at=NOW if purged else None,
                day=day,
                created_at=NOW - timedelta(seconds=1),
            ),
            TutorMessage(
                org_id=org,
                tutor_session_id=t.id,
                student_id=sid,
                role=TutorRole.student,
                kind=TutorKind.chat,
                mode=TutorMode.before,
                status=TutorStatus.pending,
                text="still thinking",
                day=day,
            ),
        ]
    )
    await session.flush()
    return t.id


async def deactivate(session: AsyncSession, user_id: uuid.UUID) -> None:
    user = await session.get(AppUser, user_id)
    assert user is not None
    from app.models import UserStatus

    user.status = UserStatus.deactivated
    await session.flush()
