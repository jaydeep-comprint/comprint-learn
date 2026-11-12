"""The shared read context of a class view (spec 010): the class, its course, the students in
scope and their read-only frontiers. Used by the dashboard and the assignment services.

Students in scope = an enrollment row in the class and account status active. Statuses come from
`frontier.class_states` (one fixed set of queries for any number of students; never writes).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.api.deps import OrgScope
from app.core.errors import not_found
from app.models import AppUser, Course, Enrollment, SchoolClass, UserStatus
from app.services import frontier, learn


@dataclass
class Student:
    id: uuid.UUID
    display_name: str
    status: UserStatus
    enrolled_at: datetime
    # Spec 014, for the student page's Privacy card only (never in AI facts).
    username: str = ""
    tutor_consent_at: datetime | None = None
    tutor_consent_form: str | None = None
    erase_due_at: datetime | None = None


@dataclass
class ClassCtx:
    cls: SchoolClass
    graph: learn._Graph
    course: Course | None
    concepts: list[uuid.UUID]  # the class course's own concepts, in course order
    students: list[Student]  # in scope (or the one student asked for), by name
    states: dict[uuid.UUID, frontier.Frontier] = field(default_factory=dict)

    @property
    def concept_set(self) -> set[uuid.UUID]:
        return set(self.concepts)

    @property
    def student_ids(self) -> list[uuid.UUID]:
        return [s.id for s in self.students]

    def ref(self, cid: uuid.UUID) -> str:
        return self.graph.nodes[cid].ref

    def title(self, cid: uuid.UUID) -> str:
        return self.graph.nodes[cid].title

    def order(self, cid: uuid.UUID) -> int:
        """Course order (unknown concepts last)."""
        try:
            return self.concepts.index(cid)
        except ValueError:
            return len(self.concepts)


def class_course(graph: learn._Graph, school_class: SchoolClass) -> Course | None:
    return next((c for c in graph.courses.values() if c.subject == school_class.subject), None)


def course_concepts(graph: learn._Graph, course: Course | None) -> list[uuid.UUID]:
    if course is None:
        return []
    own = [n for n in graph.nodes.values() if n.course_id == course.id]
    own.sort(key=lambda n: (n.chapter_position, n.position, n.slug))
    return [n.id for n in own]


def with_ancestors(graph: learn._Graph, concept_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    out = dict.fromkeys(concept_ids)
    for cid in concept_ids:
        for a in learn._ancestors(cid, graph.prereqs):
            out.setdefault(a)
    return list(out)


async def enrolled_students(
    scope: OrgScope,
    class_id: uuid.UUID,
    *,
    only: uuid.UUID | None = None,
    active_only: bool = True,
) -> list[Student]:
    stmt = (
        scope.select(AppUser)
        .with_only_columns(
            AppUser.id,
            AppUser.display_name,
            AppUser.status,
            Enrollment.created_at,
            AppUser.username,
            AppUser.tutor_consent_at,
            AppUser.tutor_consent_form,
            AppUser.erase_due_at,
        )
        .join(
            Enrollment,
            (Enrollment.student_id == AppUser.id) & (Enrollment.org_id == AppUser.org_id),
        )
        .where(Enrollment.class_id == class_id)
        .order_by(AppUser.display_name, AppUser.id)
    )
    if active_only:
        stmt = stmt.where(AppUser.status == UserStatus.active)
    if only is not None:
        stmt = stmt.where(AppUser.id == only)
    rows = (await scope.session.execute(stmt)).all()
    out = [Student(r[0], r[1], r[2], r[3], r[4] or "", r[5], r[6], r[7]) for r in rows]
    out.sort(key=lambda s: (s.display_name.lower(), str(s.id)))
    return out


async def load(
    scope: OrgScope,
    class_id: uuid.UUID,
    *,
    student_id: uuid.UUID | None = None,
    states: bool = True,
) -> ClassCtx:
    """The class view. With `student_id`, only that student (404 without an enrollment row in the
    class; a deactivated but enrolled student is allowed)."""
    school_class = await scope.get(SchoolClass, class_id)
    graph = await learn._graph(scope)
    course = class_course(graph, school_class)
    concepts = course_concepts(graph, course)
    if student_id is not None:
        students = await enrolled_students(scope, class_id, only=student_id, active_only=False)
        if not students:
            raise not_found()
    else:
        students = await enrolled_students(scope, class_id)
    ctx = ClassCtx(school_class, graph, course, concepts, students)
    if states and students and concepts:
        ctx.states = await frontier.class_states(
            scope, ctx.student_ids, with_ancestors(graph, concepts), graph.prereqs
        )
    return ctx
