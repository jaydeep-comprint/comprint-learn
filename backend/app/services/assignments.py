"""Teacher assignments and the student's Focus Mode (spec 010).

An assignment is 1 to 10 concepts of the class course with a due date, for the whole class or chosen
students. Per-student statuses are computed on read (never stored) from the read-only frontiers in
`class_view`; assignments set priority and never cap what a student can learn.
"""

import uuid
from collections.abc import Callable, Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, update

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, conflict, not_found
from app.models import (
    AppUser,
    Assignment,
    AssignmentConcept,
    AssignmentStudent,
    Enrollment,
    KpStatus,
    RemediationState,
    SchoolClass,
    UserStatus,
)
from app.schemas.assignments import (
    AssignmentDetail,
    AssignmentIn,
    AssignmentPatch,
    AssignmentStudentRow,
    AssignmentSummary,
    FocusNext,
    MyAssignment,
    NextConcept,
    PathStatus,
    PathStep,
    StatusCounts,
    StudentAssignmentRow,
    StudentStatus,
    TargetRef,
)
from app.services import class_view, frontier, kp_flow, learn, tenancy
from app.services.class_view import ClassCtx

MAX_CONCEPTS = 10
MAX_DUE_DAYS = 180
MAX_NOTE = 200
RECENT_DONE = timedelta(days=7)

PICK_CONCEPTS = "Pick 1 to 10 concepts."
PICK_DATE = "Pick a due date from today up to 6 months ahead."
NOTE_TOO_LONG = "Notes can be up to 200 characters."
NOT_IN_COURSE = "These concepts aren't in this class's course."
NOT_IN_CLASS = "Some students aren't in this class."

DONE: tuple[StudentStatus, ...] = ("done_early", "done_on_time", "done_late")


def today_ist(now: datetime) -> date:
    return now.astimezone(kp_flow.IST).date()


# --- pure rules -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetState:
    learned: bool
    started: bool  # in progress or learned
    done_at: datetime | None  # when learned (None if not learned)


def assignment_status(
    targets: Sequence[TargetState],
    *,
    path_started: bool,
    created_at: datetime,
    due_date: date,
    today: date,
) -> tuple[StudentStatus, datetime | None]:
    """A student's status on one assignment (spec 010 "Per student status")."""
    if targets and all(t.learned for t in targets):
        times = [t.done_at for t in targets if t.done_at is not None]
        done_at = max(times) if times else None
        if done_at is None or done_at < created_at:
            return "done_early", done_at
        if today_ist(done_at) <= due_date:
            return "done_on_time", done_at
        return "done_late", done_at
    if today > due_date:
        return "overdue", None
    if any(t.started for t in targets) or path_started:
        return "in_progress", None
    return "not_started", None


def focus_path[K: Hashable](
    targets: Sequence[K],
    prereqs: Mapping[K, Collection[K]],
    learned: Callable[[K], bool],
    sort_key: Callable[[K], Any],
) -> list[K]:
    """The unlearned targets plus all their unlearned ancestors (walking through learned ones),
    prerequisites first, in `learn.build_outline` order (targets in course order)."""
    own = sorted(dict.fromkeys(targets), key=sort_key)
    return [c for c, _ in learn.build_outline(own, prereqs, sort_key) if not learned(c)]


@dataclass(frozen=True)
class Step:
    concept: uuid.UUID
    status: PathStatus
    waiting: bool
    brush_up_id: uuid.UUID | None  # set when stuck by a review_due remediation


def next_step(steps: Sequence[Step]) -> Step | None:
    """The first in-progress step (a stuck one only via its brush-up; a waiting one is
    skipped), else the first ready one, else none."""
    for s in steps:
        if s.status == "in_progress":
            return s
        if s.status == "stuck" and s.brush_up_id is not None:
            return s
    return next((s for s in steps if s.status == "ready"), None)


def path_status(view: frontier.ConceptView | None) -> tuple[PathStatus, bool, uuid.UUID | None]:
    """(status, waiting, brush-up id) of an unlearned concept."""
    if view is None:
        return "locked", False, None
    waiting = view.waiting is not None
    if view.status == "in_progress":
        rems = [r for kp in view.kps for r in kp.remediations]
        failed_waiting = any(kp.status == KpStatus.failed and not kp.open for kp in view.kps)
        if rems or failed_waiting:
            due = next((r.id for r in rems if r.state == RemediationState.review_due), None)
            return "stuck", waiting, due
        return "in_progress", waiting, None
    if view.status == "ready":
        return "ready", False, None
    return "locked", False, None


# --- shared per-student evaluation ----------------------------------------------------------------


@dataclass
class Evaluated:
    status: StudentStatus
    done_at: datetime | None
    learned: int
    total: int
    path: list[uuid.UUID]
    next: Step | None
    steps: list[Step]


def _sort_key(graph: learn._Graph) -> Callable[[uuid.UUID], Any]:
    return lambda cid: graph.nodes[cid].sort_key()


def evaluate(
    graph: learn._Graph,
    front: frontier.Frontier | None,
    targets: Sequence[uuid.UUID],
    a: Assignment,
    today: date,
) -> Evaluated:
    def status(cid: uuid.UUID) -> str:
        return "locked" if front is None else front.status(cid)

    def learned(cid: uuid.UUID) -> bool:
        return status(cid) == "learned"

    states = [
        TargetState(
            learned=learned(c),
            started=status(c) in ("learned", "in_progress"),
            done_at=frontier.done_at(front, c) if front is not None and learned(c) else None,
        )
        for c in targets
    ]
    path = focus_path(targets, graph.prereqs, learned, _sort_key(graph))
    steps = []
    for cid in path:
        st, waiting, brush = path_status(None if front is None else front.views.get(cid))
        steps.append(Step(cid, st, waiting, brush))
    path_started = any(s.status in ("in_progress", "stuck") for s in steps)
    result, done_at = assignment_status(
        states,
        path_started=path_started,
        created_at=a.created_at,
        due_date=a.due_date,
        today=today,
    )
    return Evaluated(
        result,
        done_at,
        sum(s.learned for s in states),
        len(states),
        path,
        next_step(steps),
        steps,
    )


# --- loading --------------------------------------------------------------------------------------


@dataclass
class Loaded:
    row: Assignment
    concepts: list[uuid.UUID]  # as stored, in order
    student_ids: list[uuid.UUID]  # as stored


async def _load(
    scope: OrgScope,
    class_ids: Collection[uuid.UUID],
    *,
    assignment_id: uuid.UUID | None = None,
) -> list[Loaded]:
    """Live (not deleted) assignments of these classes, oldest first: three queries."""
    if not class_ids:
        return []
    stmt = (
        scope.select(Assignment)
        .where(Assignment.class_id.in_(class_ids), Assignment.deleted_at.is_(None))
        .order_by(Assignment.created_at, Assignment.id)
    )
    if assignment_id is not None:
        stmt = stmt.where(Assignment.id == assignment_id)
    rows = list((await scope.session.scalars(stmt)).all())
    if not rows:
        return []
    ids = [r.id for r in rows]
    concepts: dict[uuid.UUID, list[uuid.UUID]] = {}
    for c in (
        await scope.session.scalars(
            scope.select(AssignmentConcept)
            .where(AssignmentConcept.assignment_id.in_(ids))
            .order_by(AssignmentConcept.assignment_id, AssignmentConcept.position)
        )
    ).all():
        concepts.setdefault(c.assignment_id, []).append(c.concept_id)
    students: dict[uuid.UUID, list[uuid.UUID]] = {}
    for s in (
        await scope.session.scalars(
            scope.select(AssignmentStudent).where(AssignmentStudent.assignment_id.in_(ids))
        )
    ).all():
        students.setdefault(s.assignment_id, []).append(s.student_id)
    return [Loaded(r, concepts.get(r.id, []), students.get(r.id, [])) for r in rows]


def targets_of(ctx: ClassCtx, a: Loaded) -> list[uuid.UUID]:
    """Non-retired targets in the current class course (others are ignored)."""
    own = ctx.concept_set
    return [c for c in a.concepts if c in own]


def audience(ctx: ClassCtx, a: Loaded) -> list[class_view.Student]:
    """Live audience: in-scope students, all or the chosen ones."""
    if a.row.all_students:
        return list(ctx.students)
    chosen = set(a.student_ids)
    return [s for s in ctx.students if s.id in chosen]


def title_of(graph: learn._Graph, targets: Sequence[uuid.UUID]) -> str:
    if not targets:
        return "Content no longer available"
    first = graph.nodes[targets[0]].title
    return first if len(targets) == 1 else f"{first} + {len(targets) - 1} more"


def _counts(evals: Sequence[Evaluated]) -> StatusCounts:
    c = StatusCounts(total=len(evals))
    for e in evals:
        if e.status in DONE:
            c.done += 1
            c.done_late += e.status == "done_late"
            c.already_learned += e.status == "done_early"
        elif e.status == "overdue":
            c.overdue += 1
        elif e.status == "in_progress":
            c.in_progress += 1
        else:
            c.not_started += 1
    return c


def _summary(ctx: ClassCtx, a: Loaded, today: date) -> tuple[AssignmentSummary, list[Evaluated]]:
    targets = targets_of(ctx, a)
    evals = (
        [evaluate(ctx.graph, ctx.states.get(s.id), targets, a.row, today) for s in audience(ctx, a)]
        if targets
        else []
    )
    summary = AssignmentSummary(
        id=a.row.id,
        title=title_of(ctx.graph, targets),
        concepts=[TargetRef(concept=ctx.ref(c), title=ctx.title(c)) for c in targets],
        content_available=bool(targets),
        due_date=a.row.due_date,
        note=a.row.note,
        all_students=a.row.all_students,
        student_ids=[] if a.row.all_students else a.student_ids,
        counts=_counts(evals),
        active=a.row.due_date >= today,
        created_at=a.row.created_at,
    )
    return summary, evals


def _next(ctx: ClassCtx, e: Evaluated) -> NextConcept | None:
    if e.next is None:
        return None
    return NextConcept(concept=ctx.ref(e.next.concept), title=ctx.title(e.next.concept))


async def class_assignments(scope: OrgScope, class_id: uuid.UUID) -> list[AssignmentSummary]:
    ctx = await class_view.load(scope, class_id)
    return await summaries(scope, ctx)


async def summaries(scope: OrgScope, ctx: ClassCtx) -> list[AssignmentSummary]:
    """Every live assignment of the class: upcoming first (due date asc), then past (newest due
    first)."""
    today = today_ist(datetime.now(UTC))
    out = [_summary(ctx, a, today)[0] for a in await _load(scope, [ctx.cls.id])]
    upcoming = sorted((s for s in out if s.active), key=lambda s: (s.due_date, s.created_at))
    past = sorted(
        (s for s in out if not s.active), key=lambda s: (s.due_date, s.created_at), reverse=True
    )
    return upcoming + past


async def overdue_by_student(
    scope: OrgScope, ctx: ClassCtx
) -> dict[uuid.UUID, list[tuple[str, date]]]:
    """student -> (title, due date) of each overdue assignment (none in an archived class)."""
    out: dict[uuid.UUID, list[tuple[str, date]]] = {}
    if ctx.cls.archived_at is not None:
        return out
    today = today_ist(datetime.now(UTC))
    for a in await _load(scope, [ctx.cls.id]):
        targets = targets_of(ctx, a)
        if not targets or a.row.due_date >= today:
            continue
        for s in audience(ctx, a):
            e = evaluate(ctx.graph, ctx.states.get(s.id), targets, a.row, today)
            if e.status == "overdue":
                out.setdefault(s.id, []).append((title_of(ctx.graph, targets), a.row.due_date))
    return out


async def student_rows(scope: OrgScope, ctx: ClassCtx) -> list[StudentAssignmentRow]:
    """The (single) student's assignments in this class, for the teacher's student page."""
    today = today_ist(datetime.now(UTC))
    if not ctx.students:
        return []
    student = ctx.students[0]
    out = []
    for a in await _load(scope, [ctx.cls.id]):
        targets = targets_of(ctx, a)
        if not targets or (not a.row.all_students and student.id not in a.student_ids):
            continue
        e = evaluate(ctx.graph, ctx.states.get(student.id), targets, a.row, today)
        out.append(
            StudentAssignmentRow(
                id=a.row.id,
                title=title_of(ctx.graph, targets),
                due_date=a.row.due_date,
                status=e.status,
                done_at=e.done_at,
                learned=e.learned,
                total=e.total,
                next=_next(ctx, e),
            )
        )
    out.sort(key=lambda r: (r.status != "overdue", r.due_date))
    return out


async def assignment_detail(
    scope: OrgScope, class_id: uuid.UUID, assignment_id: uuid.UUID
) -> AssignmentDetail:
    ctx = await class_view.load(scope, class_id)
    found = await _load(scope, [class_id], assignment_id=assignment_id)
    if not found:
        raise not_found()
    a = found[0]
    today = today_ist(datetime.now(UTC))
    summary, evals = _summary(ctx, a, today)
    students = audience(ctx, a) if summary.content_available else []
    rows = [
        AssignmentStudentRow(
            student_id=s.id,
            display_name=s.display_name,
            status=e.status,
            done_at=e.done_at,
            learned=e.learned,
            total=e.total,
            next=_next(ctx, e),
        )
        for s, e in zip(students, evals, strict=True)
    ]
    return AssignmentDetail(**summary.model_dump(), students=rows)


# --- writes ---------------------------------------------------------------------------------------


def _invalid(message: str) -> ApiProblem:
    return ApiProblem(422, "assignment_invalid", message)


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    note = note.strip()
    if len(note) > MAX_NOTE:
        raise _invalid(NOTE_TOO_LONG)
    return note or None


def _check_due(due: date) -> None:
    today = today_ist(datetime.now(UTC))
    if not today <= due <= today + timedelta(days=MAX_DUE_DAYS):
        raise _invalid(PICK_DATE)


def _resolve_concepts(ctx: ClassCtx, refs: Sequence[str]) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(r.strip() for r in refs))
    if not 1 <= len(unique) <= MAX_CONCEPTS:
        raise _invalid(PICK_CONCEPTS)
    own = ctx.concept_set
    ids = [ctx.graph.by_ref.get(r) for r in unique]
    if ctx.course is None or any(i is None or i not in own for i in ids):
        raise ApiProblem(422, "concept_not_in_course", NOT_IN_COURSE)
    return [i for i in ids if i is not None]


async def _check_students(
    scope: OrgScope, class_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(student_ids))
    if not unique:
        raise ApiProblem(422, "students_not_in_class", NOT_IN_CLASS)
    found = set(
        (
            await scope.session.scalars(
                scope.select(AppUser)
                .with_only_columns(AppUser.id)
                .join(
                    Enrollment,
                    (Enrollment.student_id == AppUser.id) & (Enrollment.org_id == AppUser.org_id),
                )
                .where(
                    Enrollment.class_id == class_id,
                    AppUser.id.in_(unique),
                    AppUser.status == UserStatus.active,
                )
            )
        ).all()
    )
    if found != set(unique):
        raise ApiProblem(422, "students_not_in_class", NOT_IN_CLASS)
    return unique


async def _writable(scope: OrgScope, class_id: uuid.UUID) -> ClassCtx:
    school_class = await scope.get(SchoolClass, class_id)
    if school_class.archived_at is not None:
        raise conflict("class_archived", tenancy.CLASS_ARCHIVED)
    return await class_view.load(scope, class_id, states=False)


def _set_concepts(scope: OrgScope, assignment_id: uuid.UUID, concepts: Sequence[uuid.UUID]) -> None:
    for i, cid in enumerate(concepts):
        scope.session.add(
            scope.new(AssignmentConcept, assignment_id=assignment_id, concept_id=cid, position=i)
        )


def _set_students(scope: OrgScope, assignment_id: uuid.UUID, ids: Sequence[uuid.UUID]) -> None:
    for sid in ids:
        scope.session.add(scope.new(AssignmentStudent, assignment_id=assignment_id, student_id=sid))


async def _one(scope: OrgScope, class_id: uuid.UUID, assignment_id: uuid.UUID) -> AssignmentSummary:
    ctx = await class_view.load(scope, class_id)
    found = await _load(scope, [class_id], assignment_id=assignment_id)
    if not found:
        raise not_found()
    return _summary(ctx, found[0], today_ist(datetime.now(UTC)))[0]


async def create(scope: OrgScope, class_id: uuid.UUID, body: AssignmentIn) -> AssignmentSummary:
    ctx = await _writable(scope, class_id)
    concepts = _resolve_concepts(ctx, body.concepts)
    _check_due(body.due_date)
    note = _clean_note(body.note)
    students = (
        None
        if body.student_ids is None
        else await _check_students(scope, class_id, body.student_ids)
    )
    row = scope.new(
        Assignment,
        class_id=class_id,
        due_date=body.due_date,
        note=note,
        all_students=students is None,
        created_by=scope.user.id,
    )
    scope.session.add(row)
    await scope.session.flush()
    _set_concepts(scope, row.id, concepts)
    _set_students(scope, row.id, students or [])
    await scope.session.commit()
    return await _one(scope, class_id, row.id)


async def _get_row(scope: OrgScope, class_id: uuid.UUID, assignment_id: uuid.UUID) -> Assignment:
    row = await scope.get(Assignment, assignment_id, for_update=True)
    if row.class_id != class_id or row.deleted_at is not None:
        raise not_found()
    return row


async def patch(
    scope: OrgScope, class_id: uuid.UUID, assignment_id: uuid.UUID, body: AssignmentPatch
) -> AssignmentSummary:
    ctx = await _writable(scope, class_id)
    row = await _get_row(scope, class_id, assignment_id)
    fields = body.model_fields_set
    concepts = None
    if "concepts" in fields:
        concepts = _resolve_concepts(ctx, body.concepts or [])
    if "due_date" in fields:
        if body.due_date is None:
            raise _invalid(PICK_DATE)
        if body.due_date != row.due_date:
            _check_due(body.due_date)
        row.due_date = body.due_date
    if "note" in fields:
        row.note = _clean_note(body.note)
    students: list[uuid.UUID] | None = None
    if "student_ids" in fields:
        if body.student_ids is not None:
            students = await _check_students(scope, class_id, body.student_ids)
        row.all_students = body.student_ids is None
    if concepts is not None:
        await scope.session.execute(
            delete(AssignmentConcept).where(
                AssignmentConcept.org_id == scope.org_id,
                AssignmentConcept.assignment_id == row.id,
            )
        )
        _set_concepts(scope, row.id, concepts)
    if "student_ids" in fields:
        await scope.session.execute(
            delete(AssignmentStudent).where(
                AssignmentStudent.org_id == scope.org_id,
                AssignmentStudent.assignment_id == row.id,
            )
        )
        _set_students(scope, row.id, students or [])
    row.updated_at = datetime.now(UTC)
    await scope.session.commit()
    return await _one(scope, class_id, row.id)


async def remove(scope: OrgScope, class_id: uuid.UUID, assignment_id: uuid.UUID) -> None:
    await _writable(scope, class_id)
    row = await _get_row(scope, class_id, assignment_id)
    await scope.session.execute(
        update(Assignment)
        .where(Assignment.org_id == scope.org_id, Assignment.id == row.id)
        .values(deleted_at=func.now(), updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    await scope.session.commit()


# --- the student's Focus Mode ---------------------------------------------------------------------


async def my_assignments(scope: OrgScope) -> list[MyAssignment]:
    """The student's live assignments (spec 010 Focus Mode). A student read: promotes on read and
    commits, like `learn.student_courses`."""
    learn._require_student(scope)
    me = scope.user.id
    classes = list(
        (
            await scope.session.scalars(
                scope.select(SchoolClass)
                .join(
                    Enrollment,
                    (Enrollment.class_id == SchoolClass.id)
                    & (Enrollment.org_id == SchoolClass.org_id),
                )
                .where(Enrollment.student_id == me, SchoolClass.archived_at.is_(None))
            )
        ).all()
    )
    loaded = await _load(scope, [c.id for c in classes])
    if not loaded:
        return []
    graph = await learn._graph(scope)
    by_class = {c.id: c for c in classes}
    items: list[tuple[Loaded, SchoolClass, str, list[uuid.UUID]]] = []
    for a in loaded:
        if not a.row.all_students and me not in a.student_ids:
            continue
        cls = by_class[a.row.class_id]
        course = class_view.class_course(graph, cls)
        own = set(class_view.course_concepts(graph, course))
        targets = [c for c in a.concepts if c in own]
        if course is None or not targets:
            continue
        items.append((a, cls, course.slug, targets))
    if not items:
        return []
    ids = class_view.with_ancestors(graph, [c for *_, ts in items for c in ts])
    front = await frontier.load(scope, ids, graph.prereqs)
    await scope.session.commit()  # a promotion on read
    now = datetime.now(UTC)
    today = today_ist(now)
    out: list[MyAssignment] = []
    for a, cls, course_slug, targets in items:
        e = evaluate(graph, front, targets, a.row, today)
        if e.status == "done_early":
            continue
        if e.status in DONE and e.done_at is not None and now - e.done_at > RECENT_DONE:
            continue
        done = e.status in DONE
        target_set = set(targets)
        nxt = e.next
        out.append(
            MyAssignment(
                id=a.row.id,
                title=title_of(graph, targets),
                class_name=cls.name,
                course=course_slug,
                due_date=a.row.due_date,
                note=a.row.note,
                status=e.status,
                done_at=e.done_at,
                learned=e.learned,
                total=e.total,
                path=[]
                if done
                else [
                    PathStep(
                        concept=graph.nodes[s.concept].ref,
                        course=graph.nodes[s.concept].course_slug,
                        title=graph.nodes[s.concept].title,
                        status=s.status,
                        waiting=s.waiting,
                        target=s.concept in target_set,
                    )
                    for s in e.steps
                ],
                next=None
                if done or nxt is None
                else FocusNext(
                    concept=graph.nodes[nxt.concept].ref,
                    course=graph.nodes[nxt.concept].course_slug,
                    title=graph.nodes[nxt.concept].title,
                    brush_up_id=nxt.brush_up_id if nxt.status == "stuck" else None,
                ),
            )
        )
    out.sort(key=lambda m: (m.status != "overdue", m.due_date, _created(loaded, m.id)))
    return out


def _created(loaded: Sequence[Loaded], aid: uuid.UUID) -> datetime:
    return next(a.row.created_at for a in loaded if a.row.id == aid)
