"""Right of access (spec 014): everything stored about one student, as one JSON document.

Built in one transaction with a fixed number of queries (one per section; content refs resolved in
three lookups at the end), whatever the number of rows or classes. Never included: `item.answer`
(answer keys, hidden tests, explanations), other students' data, internal token/latency counts and
`teacher_summary.facts`/`pseudonyms`. Content is named by slug (retired content still resolves).
"""

import enum
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import aliased

from app.api.deps import OrgScope
from app.models import (
    AppUser,
    Attempt,
    AuditAction,
    AuditEvent,
    Concept,
    ConceptState,
    Course,
    DiagnosticSession,
    Enrollment,
    Item,
    KnowledgePoint,
    KpProgress,
    LessonProgress,
    Organization,
    PracticeSession,
    Quiz,
    QuizItem,
    Remediation,
    ReviewCard,
    ReviewLog,
    Role,
    SchoolClass,
    StudentGoal,
    StudyTime,
    TeacherSummary,
    TeacherSummaryKind,
    TutorMessage,
    TutorSession,
    UserStatus,
    XpDay,
    XpEvent,
)
from app.services import assignments, class_view, frontier, learn, tenancy

EXPORT_VERSION = 1
TOKEN = re.compile(r"\{S(\d+)\}")
CONSENT_ACTIONS = (AuditAction.consent_recorded, AuditAction.consent_withdrawn)

# Content id columns → the exported key and the ref kind.
_REFS = {
    "item_id": ("item", "item"),
    "current_item_id": None,  # never exported (the question being shown)
    "concept_id": ("concept", "concept"),
    "prereq_concept_id": ("prereq_concept", "concept"),
    "link_concept_id": ("link_concept", "concept"),
    "kp_id": ("kp", "kp"),
}


def _value(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _value(x) for k, x in v.items()}
    return v


class _Refs:
    """Collects content ids while sections are built; resolves them to slugs in three queries."""

    def __init__(self) -> None:
        self.ids: dict[str, set[uuid.UUID]] = {"item": set(), "concept": set(), "kp": set()}
        self.rows: list[dict[str, Any]] = []

    def row(
        self,
        values: Mapping[str, Any],
        *,
        drop: Iterable[str] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One exported row (registered, so its content ids are resolved later). `extra` keys
        are added as they are (nested lists the caller fills in)."""
        skip = {"org_id", "student_id", *drop}
        out: dict[str, Any] = {}
        for k, v in values.items():
            if k in skip:
                continue
            if k in _REFS:
                ref = _REFS[k]
                if ref is None:
                    continue
                key, kind = ref
                if v is not None:
                    self.ids[kind].add(v)
                out[key] = v  # resolved later
                continue
            out[k] = _value(v)
        out.update(extra or {})
        self.rows.append(out)
        return out

    async def resolve(self, scope: OrgScope) -> None:
        names: dict[uuid.UUID, str] = {}
        s = scope.session
        # Always three queries (an empty IN is fine), so the export's query count is fixed.
        titles: dict[uuid.UUID, str] = {}
        for cid, course, slug, title in (
            await s.execute(
                select(Concept.id, Course.slug, Concept.slug, Concept.title)
                .join(Course, Course.id == Concept.course_id)
                .where(Concept.id.in_(self.ids["concept"]))
            )
        ).all():
            names[cid] = f"{course}/{slug}"
            titles[cid] = title
        for kid, course, concept, slug in (
            await s.execute(
                select(KnowledgePoint.id, Course.slug, Concept.slug, KnowledgePoint.slug)
                .join(Concept, Concept.id == KnowledgePoint.concept_id)
                .join(Course, Course.id == Concept.course_id)
                .where(KnowledgePoint.id.in_(self.ids["kp"]))
            )
        ).all():
            names[kid] = f"{course}/{concept}/{slug}"
        for iid, course, concept, slug in (
            await s.execute(
                select(Item.id, Course.slug, Concept.slug, Item.slug)
                .join(Concept, Concept.id == Item.concept_id)
                .join(Course, Course.id == Concept.course_id)
                .where(Item.id.in_(self.ids["item"]))
            )
        ).all():
            names[iid] = f"{course}/{concept}/{slug}"
        keys = {key for ref in _REFS.values() if ref for key in [ref[0]]}
        for row in self.rows:
            if "title" in row and row["title"] is None and row.get("concept") is not None:
                row["title"] = titles.get(row["concept"])
            for key in keys & row.keys():
                v = row[key]
                row[key] = None if v is None else names.get(v, str(v))
            if "concepts" in row:  # assignment targets
                row["concepts"] = [names.get(c, str(c)) for c in row["concepts"]]


async def _all(scope: OrgScope, stmt: Select[Any]) -> list[Mapping[str, Any]]:
    return list((await scope.session.execute(stmt)).mappings().all())


def _table(model: Any, student_id: uuid.UUID, org_id: uuid.UUID, *order: Any) -> Select[Any]:
    t = model.__table__
    return select(t).where(t.c.org_id == org_id, t.c.student_id == student_id).order_by(*order)


def _fill_own_token(content: Any, token: str | None, name: str) -> Any:
    """The student's own `{Sn}` token becomes their name; other tokens stay tokens."""
    if token is None:
        return content
    if isinstance(content, str):
        return TOKEN.sub(lambda m: name if f"S{m.group(1)}" == token else m.group(0), content)
    if isinstance(content, list):
        return [_fill_own_token(x, token, name) for x in content]
    if isinstance(content, dict):
        return {k: _fill_own_token(v, token, name) for k, v in content.items()}
    return content


async def _assignment_rows(
    scope: OrgScope, student: AppUser, classes: Sequence[SchoolClass], refs: _Refs
) -> list[dict[str, Any]]:
    """Assignments that target the student in any of their classes (archived ones too), with the
    status computed as on the dashboard: one graph load and one `class_states` call."""
    loaded = await assignments._load(scope, [c.id for c in classes])
    by_class = {c.id: c for c in classes}
    mine = [a for a in loaded if a.row.all_students or student.id in a.student_ids]
    if not mine:
        return []
    graph = await learn._graph(scope)
    items = []
    for a in mine:
        course = class_view.class_course(graph, by_class[a.row.class_id])
        own = set(class_view.course_concepts(graph, course))
        items.append((a, [c for c in a.concepts if c in own]))
    ids = class_view.with_ancestors(graph, [c for _, ts in items for c in ts])
    fronts = await frontier.class_states(scope, [student.id], ids, graph.prereqs)
    today = assignments.today_ist(datetime.now(UTC))
    out = []
    for a, targets in items:
        status = (
            assignments.evaluate(graph, fronts.get(student.id), targets, a.row, today).status
            if targets
            else None
        )
        refs.ids["concept"].update(a.concepts)
        out.append(
            refs.row(
                {},
                extra={
                    "class": by_class[a.row.class_id].name,
                    "concepts": list(a.concepts),
                    "due_date": a.row.due_date.isoformat(),
                    "note": a.row.note,
                    "status": status,
                    "created_at": _value(a.row.created_at),
                },
            )
        )
    return out


async def student_export(scope: OrgScope, student_id: uuid.UUID) -> dict[str, Any]:
    """Everything stored about one student of the caller's school (erased → 404)."""
    student = await tenancy.get_student(scope, student_id)
    sid, org = student.id, scope.org_id
    school = await scope.session.get(Organization, org)
    assert school is not None
    refs = _Refs()

    actor = aliased(AppUser)
    consent_events = (
        await scope.session.execute(
            select(AuditEvent.action, AuditEvent.created_at, AuditEvent.meta, actor.display_name)
            .outerjoin(actor, (actor.id == AuditEvent.actor_id) & (actor.org_id == org))
            .where(
                AuditEvent.org_id == org,
                AuditEvent.target_id == sid,
                AuditEvent.action.in_(CONSENT_ACTIONS),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    ).all()

    class_rows = (
        await scope.session.execute(
            select(SchoolClass, Enrollment.created_at)
            .join(
                Enrollment,
                (Enrollment.class_id == SchoolClass.id) & (Enrollment.org_id == SchoolClass.org_id),
            )
            .where(Enrollment.org_id == org, Enrollment.student_id == sid)
            .order_by(SchoolClass.name)
        )
    ).all()
    classes = [c for c, _ in class_rows]

    states = await _all(scope, _table(ConceptState, sid, org, ConceptState.concept_id))
    kps = await _all(scope, _table(KpProgress, sid, org, KpProgress.kp_id))
    lessons = await _all(scope, _table(LessonProgress, sid, org, LessonProgress.concept_id))
    by_concept: dict[uuid.UUID, dict[str, Any]] = {}

    def concept_entry(cid: uuid.UUID) -> dict[str, Any]:
        if cid not in by_concept:
            by_concept[cid] = refs.row(
                {"concept_id": cid},
                extra={"title": None, "state": None, "kps": [], "lesson": None},
            )
        return by_concept[cid]

    for r in states:
        concept_entry(r["concept_id"])["state"] = refs.row(r, drop=("concept_id",))
    kp_concepts = dict(
        (
            await scope.session.execute(
                select(KnowledgePoint.id, KnowledgePoint.concept_id).where(
                    KnowledgePoint.id.in_([r["kp_id"] for r in kps])
                )
            )
        ).all()
    )
    for r in kps:
        concept_entry(kp_concepts[r["kp_id"]])["kps"].append(refs.row(r))
    for r in lessons:
        concept_entry(r["concept_id"])["lesson"] = refs.row(r, drop=("concept_id",))

    attempts = [
        refs.row(r, drop=("id", "misconception_id"))
        for r in await _all(scope, _table(Attempt, sid, org, Attempt.created_at, Attempt.id))
    ]
    study = [
        refs.row(r, drop=("id",))
        for r in await _all(scope, _table(StudyTime, sid, org, StudyTime.created_at, StudyTime.id))
    ]
    sessions = [
        refs.row(r, drop=("current_seed", "current_position", "current_served_at"))
        for r in await _all(
            scope, _table(PracticeSession, sid, org, PracticeSession.started_at, PracticeSession.id)
        )
    ]
    remediations = [
        refs.row(r)
        for r in await _all(
            scope, _table(Remediation, sid, org, Remediation.created_at, Remediation.id)
        )
    ]
    xp_events = [
        refs.row(r, drop=("id",))
        for r in await _all(scope, _table(XpEvent, sid, org, XpEvent.created_at, XpEvent.id))
    ]
    xp_days = [refs.row(r) for r in await _all(scope, _table(XpDay, sid, org, XpDay.day))]
    goals = [refs.row(r) for r in await _all(scope, _table(StudentGoal, sid, org))]
    cards = [
        refs.row(r) for r in await _all(scope, _table(ReviewCard, sid, org, ReviewCard.concept_id))
    ]
    review_log = [
        refs.row(r, drop=("id",))
        for r in await _all(scope, _table(ReviewLog, sid, org, ReviewLog.created_at, ReviewLog.id))
    ]
    quizzes = {
        r["id"]: refs.row(r, extra={"items": []})
        for r in await _all(scope, _table(Quiz, sid, org, Quiz.created_at, Quiz.id))
    }
    qi = QuizItem.__table__
    for r in await _all(
        scope,
        select(qi)
        .where(qi.c.org_id == org, qi.c.quiz_id.in_(list(quizzes)))
        .order_by(qi.c.quiz_id, qi.c.position),
    ):
        quizzes[r["quiz_id"]]["items"].append(refs.row(r, drop=("quiz_id",)))

    diagnostics = [
        refs.row(
            {
                "id": d.id,
                "class": name,
                "status": d.status,
                "sent_at": d.sent_at,
                "started_at": d.started_at,
                "finished_at": d.finished_at,
                "cancelled_at": d.cancelled_at,
                "answered": d.answered,
                "results": d.results,
            }
        )
        for d, name in (
            await scope.session.execute(
                select(DiagnosticSession, SchoolClass.name)
                .join(
                    SchoolClass,
                    (SchoolClass.id == DiagnosticSession.class_id)
                    & (SchoolClass.org_id == DiagnosticSession.org_id),
                )
                .where(DiagnosticSession.org_id == org, DiagnosticSession.student_id == sid)
                .order_by(DiagnosticSession.sent_at, DiagnosticSession.id)
            )
        ).all()
    ]

    assignment_rows = await _assignment_rows(scope, student, classes, refs)

    threads = {
        r["id"]: refs.row(r, extra={"messages": []})
        for r in await _all(
            scope, _table(TutorSession, sid, org, TutorSession.created_at, TutorSession.id)
        )
    }
    for r in await _all(
        scope, _table(TutorMessage, sid, org, TutorMessage.created_at, TutorMessage.id)
    ):
        threads[r["tutor_session_id"]]["messages"].append(
            refs.row(
                r,
                drop=(
                    "tutor_session_id",
                    "model",
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "latency_ms",
                ),
            )
        )

    summaries = []
    for ts in (
        await scope.session.scalars(
            select(TeacherSummary)
            .where(
                TeacherSummary.org_id == org,
                TeacherSummary.student_id == sid,
                TeacherSummary.kind == TeacherSummaryKind.student,
            )
            .order_by(TeacherSummary.created_at, TeacherSummary.id)
        )
    ).all():
        token = next((k for k, v in ts.pseudonyms.items() if str(v) == str(sid)), None)
        summaries.append(
            {
                "created_at": _value(ts.created_at),
                "window": ts.window,
                "status": ts.status.value,
                "content": _fill_own_token(ts.content, token, student.display_name),
            }
        )

    await refs.resolve(scope)
    return {
        "export_version": EXPORT_VERSION,
        "generated_at": _value(datetime.now(UTC)),
        "student": {
            "id": str(sid),
            "display_name": student.display_name,
            "username": student.username,
            "status": student.status.value,
            "created_at": _value(student.created_at),
        },
        "school": {"name": school.name, "code": school.code},
        "consent": {
            "tutor_consent_at": _value(student.tutor_consent_at),
            "tutor_consent_form": student.tutor_consent_form,
            "events": [
                {
                    "action": a.value,
                    "at": _value(at),
                    "form": meta.get("form"),
                    "by": by,
                }
                for a, at, meta, by in consent_events
            ],
        },
        "classes": [
            {
                "name": c.name,
                "subject": c.subject.value,
                "grade": c.grade,
                "enrolled_at": _value(at),
            }
            for c, at in class_rows
        ],
        "concepts": list(by_concept.values()),
        "attempts": attempts,
        "study_time": study,
        "practice_sessions": sessions,
        "remediations": remediations,
        "xp_events": xp_events,
        "xp_days": xp_days,
        "goals": goals,
        "review_cards": cards,
        "review_log": review_log,
        "quizzes": list(quizzes.values()),
        "diagnostics": diagnostics,
        "assignments": assignment_rows,
        "tutor": list(threads.values()),
        "ai_summaries": summaries,
    }


async def school_export(scope: OrgScope) -> tuple[dict[str, Any], list[AppUser]]:
    """The school file for the CLI (school, classes, teachers) and the students to export one by
    one (every non-erased student)."""
    school = await scope.session.get(Organization, scope.org_id)
    assert school is not None
    classes = (
        await scope.session.scalars(scope.select(SchoolClass).order_by(SchoolClass.name))
    ).all()
    users = (await scope.session.scalars(scope.select(AppUser).order_by(AppUser.id))).all()
    teachers = [u for u in users if u.role == Role.teacher]
    students = [u for u in users if u.role == Role.student and u.status != UserStatus.erased]
    data = {
        "export_version": EXPORT_VERSION,
        "generated_at": _value(datetime.now(UTC)),
        "school": {"name": school.name, "code": school.code},
        "classes": [
            {
                "name": c.name,
                "subject": c.subject.value,
                "grade": c.grade,
                "archived": c.archived_at is not None,
            }
            for c in classes
        ],
        "teachers": [
            {
                "display_name": t.display_name,
                "email": t.email,
                "role": "admin" if t.is_admin else "teacher",
                "status": t.status.value,
            }
            for t in teachers
        ],
    }
    return data, students
