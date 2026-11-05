"""Shared helpers for the review and quiz DB tests (spec 007)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.models import (
    Concept,
    ConceptSource,
    ConceptState,
    ConceptStatus,
    Course,
    Enrollment,
    KnowledgePoint,
    KpProgress,
    KpStatus,
    PracticeSession,
    ReviewCard,
    ReviewLog,
    SessionStatus,
)
from app.services import srs
from tests.conftest import DbApp
from tests.learn_helpers import World, answer_question, get

REVIEWS = "/api/v1/reviews"


def review_path(ref: str) -> str:
    return f"{REVIEWS}/{ref}"


async def concept_id(db: DbApp, ref: str) -> uuid.UUID:
    course, slug = ref.split("/")
    async with db.sessions() as session:
        cid = await session.scalar(
            select(Concept.id)
            .join(Course, Course.id == Concept.course_id)
            .where(Course.slug == course, Concept.slug == slug)
        )
        assert cid is not None
        return cid


async def both_subjects(db: DbApp, w: World) -> uuid.UUID:
    """The physics student, also enrolled in the maths class."""
    s = w.physics_student
    async with db.sessions() as session:
        session.add(Enrollment(org_id=w.a.org_id, class_id=w.a.class_ids[0], student_id=s))
        await session.commit()
    return s


async def seed_learned(
    db: DbApp, org_id: uuid.UUID, user: uuid.UUID, refs: list[str], *, days_ago: int = 10
) -> None:
    """Mark concepts learned (every KP passed) with a card from a first `Good` `days_ago`."""
    at = datetime.now(UTC) - timedelta(days=days_ago)
    for ref in refs:
        cid = await concept_id(db, ref)
        first = srs.first_review(at)
        async with db.sessions() as session:
            session.add(
                ConceptState(
                    org_id=org_id,
                    student_id=user,
                    concept_id=cid,
                    status=ConceptStatus.learned,
                    source=ConceptSource.lesson,
                    learned_at=at,
                )
            )
            kps = (
                await session.scalars(
                    select(KnowledgePoint.id).where(KnowledgePoint.concept_id == cid)
                )
            ).all()
            for kp in kps:
                session.add(
                    KpProgress(
                        org_id=org_id,
                        student_id=user,
                        kp_id=kp,
                        status=KpStatus.passed,
                        passed_at=at,
                    )
                )
            session.add(
                ReviewCard(
                    org_id=org_id,
                    student_id=user,
                    concept_id=cid,
                    stability=first.stability,
                    difficulty=first.difficulty,
                    due=first.due,
                    last_review=at,
                    reps=1,
                )
            )
            await session.commit()


async def set_card(db: DbApp, user: uuid.UUID, ref: str, **values: Any) -> None:
    cid = await concept_id(db, ref)
    async with db.sessions() as session:
        await session.execute(
            update(ReviewCard)
            .where(ReviewCard.student_id == user, ReviewCard.concept_id == cid)
            .values(**values)
        )
        await session.commit()


async def make_due(db: DbApp, user: uuid.UUID, ref: str) -> None:
    await set_card(db, user, ref, due=datetime.now(UTC) - timedelta(days=1))


async def card(db: DbApp, user: uuid.UUID, ref: str) -> ReviewCard | None:
    cid = await concept_id(db, ref)
    async with db.sessions() as session:
        return await session.scalar(
            select(ReviewCard).where(ReviewCard.student_id == user, ReviewCard.concept_id == cid)
        )


async def logs(db: DbApp, user: uuid.UUID, ref: str | None = None) -> list[ReviewLog]:
    async with db.sessions() as session:
        stmt = select(ReviewLog).where(ReviewLog.student_id == user).order_by(ReviewLog.id)
        if ref is not None:
            stmt = stmt.where(ReviewLog.concept_id == await concept_id(db, ref))
        return list((await session.scalars(stmt)).all())


async def concept_status(db: DbApp, user: uuid.UUID, ref: str) -> ConceptStatus | None:
    cid = await concept_id(db, ref)
    async with db.sessions() as session:
        return await session.scalar(
            select(ConceptState.status).where(
                ConceptState.student_id == user, ConceptState.concept_id == cid
            )
        )


async def slow_down(db: DbApp, user: uuid.UUID) -> None:
    """Pretend the current question was served 10 minutes ago (answers aren't rushed)."""
    async with db.sessions() as session:
        await session.execute(
            update(PracticeSession)
            .where(
                PracticeSession.student_id == user,
                PracticeSession.status == SessionStatus.active,
            )
            .values(current_served_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await session.commit()


async def do_review(db: DbApp, user: uuid.UUID, ref: str, pattern: str) -> dict[str, Any]:
    """Answer a review with `pattern` (C/W) until it ends; returns the last result."""
    path = review_path(ref)
    result: dict[str, Any] = {}
    for c in pattern:
        q = await get(db, user, f"{path}/question")
        await slow_down(db, user)
        result = await answer_question(db, user, path, q, correct=c == "C")
        if result["session_status"] != "active":
            return result
    return result


async def queue(db: DbApp, user: uuid.UUID) -> dict[str, Any]:
    out: dict[str, Any] = await get(db, user, REVIEWS)
    return out


def offered_refs(q: dict[str, Any]) -> list[str]:
    return [o["concept"]["id"] for o in q["offered"]]
