"""Read-only queries over global content. Not tenant data, so no `OrgScope`; only active rows."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import not_found
from app.models import Chapter, Concept, ConceptPrereq, Course, KnowledgePoint
from app.schemas.content import (
    ChapterOut,
    ConceptNode,
    CourseGraph,
    CourseRef,
    CourseSummary,
    Edge,
    ExternalConcept,
)


async def list_courses(session: AsyncSession) -> list[CourseSummary]:
    chapters = (
        select(func.count())
        .where(Chapter.course_id == Course.id, Chapter.retired_at.is_(None))
        .scalar_subquery()
    )
    concepts = (
        select(func.count())
        .where(Concept.course_id == Course.id, Concept.retired_at.is_(None))
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Course.slug, Course.title, Course.subject, chapters, concepts)
        .where(Course.retired_at.is_(None))
        .order_by(Course.subject, Course.slug)
    )
    return [
        CourseSummary(slug=s, title=t, subject=sub, chapter_count=ch, concept_count=co)
        for s, t, sub, ch, co in rows.all()
    ]


async def course_graph(session: AsyncSession, slug: str) -> CourseGraph:
    course = await session.scalar(
        select(Course).where(Course.slug == slug, Course.retired_at.is_(None))
    )
    if course is None:
        raise not_found()

    chapters = (
        await session.scalars(
            select(Chapter)
            .where(Chapter.course_id == course.id, Chapter.retired_at.is_(None))
            .order_by(Chapter.position)
        )
    ).all()
    chapter_slug = {ch.id: ch.slug for ch in chapters}

    kp_count = (
        select(func.count())
        .where(KnowledgePoint.concept_id == Concept.id, KnowledgePoint.retired_at.is_(None))
        .scalar_subquery()
    )
    concept_rows = (
        await session.execute(
            select(Concept, kp_count)
            .join(Chapter, Chapter.id == Concept.chapter_id)
            .where(Concept.course_id == course.id, Concept.retired_at.is_(None))
            .order_by(Chapter.position, Concept.position)
        )
    ).all()
    concept_ids = {c.id for c, _ in concept_rows}

    # Edges into this course's concepts; prerequisites may live in other courses.
    prereq = aliased(Concept)
    prereq_course = aliased(Course)
    edge_rows = (
        await session.execute(
            select(ConceptPrereq, prereq, prereq_course.slug)
            .join(prereq, prereq.id == ConceptPrereq.prereq_id)
            .join(prereq_course, prereq_course.id == prereq.course_id)
            .where(
                ConceptPrereq.concept_id.in_(concept_ids),
                prereq.retired_at.is_(None),
                prereq_course.retired_at.is_(None),
            )
        )
    ).all()
    qid = {c.id: f"{slug}/{c.slug}" for c, _ in concept_rows}
    external: dict[str, ExternalConcept] = {}
    edges = []
    for edge, p, p_course in edge_rows:
        from_id = f"{p_course}/{p.slug}"
        if p.id not in concept_ids:
            external[from_id] = ExternalConcept(id=from_id, title=p.title, course=p_course)
        edges.append(
            Edge(from_=from_id, to=qid[edge.concept_id], weight=float(edge.encompassing_weight))
        )

    return CourseGraph(
        course=CourseRef(slug=course.slug, title=course.title, subject=course.subject),
        chapters=[
            ChapterOut(slug=ch.slug, title=ch.title, grade=ch.grade, position=ch.position)
            for ch in chapters
        ],
        concepts=[
            ConceptNode(
                id=qid[c.id],
                title=c.title,
                summary=c.summary,
                chapter=chapter_slug[c.chapter_id],
                position=c.position,
                kp_count=n,
            )
            for c, n in concept_rows
        ],
        edges=sorted(edges, key=lambda e: (e.to, e.from_)),
        external=sorted(external.values(), key=lambda e: e.id),
    )
