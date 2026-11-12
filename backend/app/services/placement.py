"""Placement (spec 012): covered chapters, sending diagnostics, taking one, and applying the result.

Teacher side: `overview`, `set_chapters`, `send`, `resend`, `cancel`, `student_outcomes` (staff).
Student side: `current`, `state`, `start`, `question`, `answer`, `result` (students only; another
student's diagnostic, or one for a class the student isn't enrolled in, is 404).

The engine (evidence, next concept, item choice, classification) is pure:
`app/services/placement_engine.py`. A diagnostic earns no XP and writes no study time.
"""

import random
import secrets
import uuid
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, conflict, not_found
from app.grading import QUICK_TYPES
from app.models import (
    Attempt,
    AttemptContext,
    ClassCoveredChapter,
    ConceptPrereq,
    ConceptSource,
    ConceptState,
    ConceptStatus,
    DiagnosticSession,
    DiagnosticStatus,
    Enrollment,
    Item,
    KnowledgePoint,
    PracticeSession,
    SchoolClass,
    SessionKind,
    SessionStatus,
)
from app.models.content import ItemKind
from app.schemas.content import CourseRef
from app.schemas.kp import QuestionPublic
from app.schemas.learn import ConceptRef
from app.schemas.placement import (
    ChaptersIn,
    ConceptOutcome,
    DiagnosticAnswerIn,
    DiagnosticResult,
    DiagnosticSaved,
    DiagnosticState,
    Outcome,
    PlacementChapter,
    PlacementCounts,
    PlacementOverview,
    PlacementStudentRow,
    RangePreview,
    SendIn,
    SendOut,
    StudentOutcomes,
)
from app.services import assignments, class_view, frontier, kp_flow, learn, srs, tenancy
from app.services import placement_engine as eng

NO_CHAPTERS = "Tick at least one covered chapter first."
NO_QUESTIONS = "These chapters have no questions a placement check can ask yet."
NOT_IN_COURSE = "Pick chapters of this class's course."
OPEN = (DiagnosticStatus.sent, DiagnosticStatus.active)


def _invalid(message: str) -> ApiProblem:
    return ApiProblem(422, "placement_invalid", message)


def _closed() -> ApiProblem:
    return conflict("diagnostic_closed", "This placement check is closed.")


def _not_started() -> ApiProblem:
    return conflict("diagnostic_not_started", "Start the placement check first.")


def _stale() -> ApiProblem:
    return kp_flow._conflict("stale_question", "That question is no longer current.")


# --- content: range, edges and askable items ------------------------------------------------------


def _course_ref(course: learn.CourseInfo | None) -> CourseRef | None:
    if course is None:
        return None
    return CourseRef(slug=course.slug, title=course.title, subject=course.subject)


def _course_chapters(graph: learn._Graph, course: learn.CourseInfo | None) -> list[uuid.UUID]:
    if course is None:
        return []
    own = [ch for ch in graph.chapters.values() if ch.course_id == course.id]
    own.sort(key=lambda ch: (ch.position, ch.slug))
    return [ch.id for ch in own]


def range_for(
    graph: learn._Graph, course: learn.CourseInfo | None, chapter_ids: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    """The covered chapters' active concepts plus all their prerequisite ancestors, in outline
    order: the class course first, then other courses by slug; (chapter, concept) position."""
    chapters = set(chapter_ids)
    own = [n.id for n in graph.nodes.values() if n.chapter_id in chapters]
    ids = set(class_view.with_ancestors(graph, own))
    course_id = None if course is None else course.id

    def key(cid: uuid.UUID) -> tuple[int, str, int, int, str]:
        n = graph.nodes[cid]
        return (
            int(n.course_id != course_id),
            n.course_slug,
            n.chapter_position,
            n.position,
            n.slug,
        )

    return sorted(ids, key=key)


async def _edges(
    scope: OrgScope, ids: Collection[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, float]]:
    if not ids:
        return []
    rows = await scope.session.execute(
        select(
            ConceptPrereq.concept_id, ConceptPrereq.prereq_id, ConceptPrereq.encompassing_weight
        ).where(ConceptPrereq.concept_id.in_(ids), ConceptPrereq.prereq_id.in_(ids))
    )
    return [(c, p, float(w)) for c, p, w in rows.all()]


@dataclass
class _Items:
    """Active quick `kp_question` items of the range: per concept, item ids per KP (KP order)."""

    by_concept: dict[uuid.UUID, list[list[uuid.UUID]]]
    concept_of: dict[uuid.UUID, uuid.UUID]
    has_params: dict[uuid.UUID, bool]


async def _items(scope: OrgScope, ids: Collection[uuid.UUID]) -> _Items:
    out = _Items({}, {}, {})
    if not ids:
        return out
    rows = await scope.session.execute(
        select(Item.id, Item.has_params, KnowledgePoint.id, KnowledgePoint.concept_id)
        .join(KnowledgePoint, KnowledgePoint.id == Item.kp_id)
        .where(
            KnowledgePoint.concept_id.in_(ids),
            KnowledgePoint.retired_at.is_(None),
            Item.kind == ItemKind.kp_question,
            Item.type.in_(QUICK_TYPES),
            Item.retired_at.is_(None),
        )
        .order_by(KnowledgePoint.concept_id, KnowledgePoint.position, Item.position)
    )
    per_kp: dict[uuid.UUID, dict[uuid.UUID, list[uuid.UUID]]] = defaultdict(dict)
    for item_id, has_params, kp_id, concept_id in rows.all():
        per_kp[concept_id].setdefault(kp_id, []).append(item_id)
        out.concept_of[item_id] = concept_id
        out.has_params[item_id] = has_params
    out.by_concept = {c: list(kps.values()) for c, kps in per_kp.items()}
    return out


async def _covered(
    scope: OrgScope, class_id: uuid.UUID, graph: learn._Graph, course: learn.CourseInfo | None
) -> list[uuid.UUID]:
    """Covered chapters of the class's *current* course (rows of another course are ignored)."""
    own = _course_chapters(graph, course)
    if not own:
        return []
    rows = set(
        (
            await scope.session.scalars(
                scope.select(ClassCoveredChapter)
                .with_only_columns(ClassCoveredChapter.chapter_id)
                .where(ClassCoveredChapter.class_id == class_id)
            )
        ).all()
    )
    return [ch for ch in own if ch in rows]


def _ref(graph: learn._Graph, cid: uuid.UUID) -> ConceptRef:
    node = graph.nodes[cid]
    return ConceptRef(id=node.ref, title=node.title)


# --- teacher --------------------------------------------------------------------------------------


async def _writable(scope: OrgScope, class_id: uuid.UUID) -> class_view.ClassCtx:
    return await assignments._writable(scope, class_id)


def _counts(results: dict[str, object] | None) -> PlacementCounts | None:
    if results is None:
        return None
    raw = results.get("counts")
    if not isinstance(raw, dict):
        return None
    return PlacementCounts(
        learned=int(raw.get("learned", 0)),
        conditional=int(raw.get("conditional", 0)),
        demoted=int(raw.get("demoted", 0)),
    )


async def _diagnostics(
    scope: OrgScope, class_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[DiagnosticSession]]:
    """Each student's diagnostics for the class, newest first."""
    if not student_ids:
        return {}
    rows = (
        await scope.session.scalars(
            scope.select(DiagnosticSession)
            .where(
                DiagnosticSession.class_id == class_id,
                DiagnosticSession.student_id.in_(student_ids),
            )
            .order_by(DiagnosticSession.sent_at.desc(), DiagnosticSession.id)
        )
    ).all()
    out: dict[uuid.UUID, list[DiagnosticSession]] = defaultdict(list)
    for d in rows:
        out[d.student_id].append(d)
    return out


def _row(sid: uuid.UUID, name: str, diags: Sequence[DiagnosticSession]) -> PlacementStudentRow:
    latest = diags[0] if diags else None
    done = next((d for d in diags if d.status == DiagnosticStatus.finished), None)
    return PlacementStudentRow(
        student_id=sid,
        display_name=name,
        status="not_sent" if latest is None else latest.status.value,
        diagnostic_id=None if latest is None else latest.id,
        sent_at=None if latest is None else latest.sent_at,
        started_at=None if latest is None else latest.started_at,
        finished_at=None if latest is None else latest.finished_at,
        answered=0 if latest is None else latest.answered,
        result_at=None if done is None else done.finished_at,
        counts=None if done is None else _counts(done.results),
    )


async def overview(scope: OrgScope, class_id: uuid.UUID) -> PlacementOverview:
    ctx = await class_view.load(scope, class_id, states=False)
    graph, course = ctx.graph, ctx.course
    covered = await _covered(scope, class_id, graph, course)
    rng = range_for(graph, course, covered)
    askable = await _items(scope, rng)
    covered_set = set(covered)
    diags = await _diagnostics(scope, class_id, ctx.student_ids)
    return PlacementOverview(
        course=_course_ref(course),
        archived=ctx.cls.archived_at is not None,
        chapters=[
            PlacementChapter(
                id=ch,
                slug=graph.chapters[ch].slug,
                title=graph.chapters[ch].title,
                grade=graph.chapters[ch].grade,
                covered=ch in covered_set,
            )
            for ch in _course_chapters(graph, course)
        ],
        range=RangePreview(
            concepts=len(rng),
            prereqs=sum(1 for c in rng if graph.nodes[c].chapter_id not in covered_set),
            askable=len(askable.by_concept),
        ),
        students=[_row(s.id, s.display_name, diags.get(s.id, [])) for s in ctx.students],
    )


async def set_chapters(scope: OrgScope, class_id: uuid.UUID, body: ChaptersIn) -> PlacementOverview:
    ctx = await _writable(scope, class_id)
    own = _course_chapters(ctx.graph, ctx.course)
    wanted = list(dict.fromkeys(body.chapter_ids))
    if any(ch not in own for ch in wanted):
        raise ApiProblem(422, "chapter_not_in_course", NOT_IN_COURSE)
    if own:
        await scope.session.execute(
            delete(ClassCoveredChapter).where(
                ClassCoveredChapter.org_id == scope.org_id,
                ClassCoveredChapter.class_id == class_id,
                ClassCoveredChapter.chapter_id.in_(own),
            )
        )
    if wanted:  # a concurrent save of the same chapters is a no-op, not a PK error
        await scope.session.execute(
            insert(ClassCoveredChapter)
            .values(
                [
                    {
                        "org_id": scope.org_id,
                        "class_id": class_id,
                        "chapter_id": ch,
                        "created_by": scope.user.id,
                    }
                    for ch in wanted
                ]
            )
            .on_conflict_do_nothing()
        )
    await scope.session.commit()
    return await overview(scope, class_id)


async def _check_sendable(scope: OrgScope, ctx: class_view.ClassCtx) -> None:
    covered = await _covered(scope, ctx.cls.id, ctx.graph, ctx.course)
    if not covered:
        raise _invalid(NO_CHAPTERS)
    if not (await _items(scope, range_for(ctx.graph, ctx.course, covered))).by_concept:
        raise _invalid(NO_QUESTIONS)


async def _create(scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID) -> bool:
    """A new `sent` diagnostic; False when the student already has an open one (race-safe)."""
    created = await scope.session.scalar(
        insert(DiagnosticSession)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=student_id,
            class_id=class_id,
            status=DiagnosticStatus.sent,
            sent_by=scope.user.id,
        )
        .on_conflict_do_nothing()
        .returning(DiagnosticSession.id)
    )
    return created is not None


async def send(scope: OrgScope, class_id: uuid.UUID, body: SendIn) -> SendOut:
    ctx = await _writable(scope, class_id)
    await _check_sendable(scope, ctx)
    if body.all_students or body.student_ids is None:
        targets = ctx.student_ids
    else:
        targets = await assignments._check_students(scope, class_id, body.student_ids)
    diags = await _diagnostics(scope, class_id, targets)
    sent = skipped = 0
    for sid in targets:
        if any(d.status != DiagnosticStatus.cancelled for d in diags.get(sid, [])):
            skipped += 1
        elif await _create(scope, class_id, sid):
            sent += 1
        else:
            skipped += 1
    await scope.session.commit()
    return SendOut(sent=sent, skipped=skipped)


async def _student_row(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> PlacementStudentRow:
    user = await tenancy.get_student(scope, student_id)
    diags = await _diagnostics(scope, class_id, [student_id])
    return _row(student_id, user.display_name, diags.get(student_id, []))


async def resend(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> PlacementStudentRow:
    ctx = await _writable(scope, class_id)
    if student_id not in ctx.student_ids:
        raise not_found()
    diags = (await _diagnostics(scope, class_id, [student_id])).get(student_id, [])
    if any(d.status in OPEN for d in diags):
        raise conflict("diagnostic_open", "This student already has a placement check open.")
    await _check_sendable(scope, ctx)
    if not await _create(scope, class_id, student_id):
        raise conflict("diagnostic_open", "This student already has a placement check open.")
    await scope.session.commit()
    return await _student_row(scope, class_id, student_id)


async def cancel(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> PlacementStudentRow:
    """Discard the open diagnostic (nothing is applied; answers stay as attempts). Works for a
    student who has left the class too."""
    school_class = await scope.get(SchoolClass, class_id)
    if school_class.archived_at is not None:
        raise conflict("class_archived", tenancy.CLASS_ARCHIVED)
    user = await tenancy.get_student(scope, student_id)
    diag = await scope.session.scalar(
        scope.select(DiagnosticSession)
        .where(
            DiagnosticSession.class_id == class_id,
            DiagnosticSession.student_id == user.id,
        )
        .order_by(DiagnosticSession.sent_at.desc(), DiagnosticSession.id)
        .limit(1)
        .with_for_update()
    )
    if diag is None:
        raise not_found()
    if diag.status not in OPEN:
        raise _closed()
    now = datetime.now(UTC)
    diag.status = DiagnosticStatus.cancelled
    diag.cancelled_at = now
    session = await _session(scope, diag)
    if session is not None and session.status == SessionStatus.active:
        session.status = SessionStatus.failed
        session.ended_at = now
    await scope.session.commit()
    return await _student_row(scope, class_id, student_id)


async def student_outcomes(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> StudentOutcomes:
    ctx = await class_view.load(scope, class_id, student_id=student_id, states=False)
    student = ctx.students[0]
    diags = (await _diagnostics(scope, class_id, [student.id])).get(student.id, [])
    done = next((d for d in diags if d.status == DiagnosticStatus.finished), None)
    concepts: list[ConceptOutcome] = []
    if done is not None:
        results = done.results or {}
        by: dict[str, Outcome] = {}
        outcomes: tuple[Outcome, ...] = ("learned", "conditional", "demoted")
        for outcome in outcomes:
            for cid in results.get(outcome, []):
                by[cid] = outcome
        for cid in done.range_ids or []:
            if cid in ctx.graph.nodes:
                concepts.append(
                    ConceptOutcome(
                        concept=_ref(ctx.graph, cid), outcome=by.get(str(cid), "unchanged")
                    )
                )
    return StudentOutcomes(
        student_id=student.id,
        display_name=student.display_name,
        diagnostic_id=None if done is None else done.id,
        finished_at=None if done is None else done.finished_at,
        concepts=concepts,
    )


# --- student --------------------------------------------------------------------------------------


async def _enrolled(scope: OrgScope, class_id: uuid.UUID) -> SchoolClass | None:
    """The class when the caller is enrolled in it and it isn't archived."""
    row = await scope.session.scalar(
        scope.select(SchoolClass)
        .join(
            Enrollment,
            (Enrollment.class_id == SchoolClass.id) & (Enrollment.org_id == SchoolClass.org_id),
        )
        .where(
            SchoolClass.id == class_id,
            Enrollment.student_id == scope.user.id,
            SchoolClass.archived_at.is_(None),
        )
    )
    return row


async def _own(
    scope: OrgScope, diagnostic_id: str, *, for_update: bool = True
) -> tuple[DiagnosticSession, SchoolClass]:
    learn._require_student(scope)
    try:
        did = uuid.UUID(diagnostic_id)
    except ValueError as exc:
        raise not_found() from exc
    diag = await scope.get(DiagnosticSession, did, for_update=for_update)
    if diag.student_id != scope.user.id:
        raise not_found()
    school_class = await _enrolled(scope, diag.class_id)
    if school_class is None:
        raise not_found()
    return diag, school_class


async def _session(scope: OrgScope, diag: DiagnosticSession) -> PracticeSession | None:
    return await scope.session.scalar(
        scope.select(PracticeSession)
        .where(
            PracticeSession.kind == SessionKind.diagnostic,
            PracticeSession.diagnostic_id == diag.id,
        )
        .with_for_update()
    )


def _state(
    diag: DiagnosticSession, school_class: SchoolClass, graph: learn._Graph
) -> DiagnosticState:
    course = class_view.class_course(graph, school_class)
    return DiagnosticState(
        id=diag.id,
        status=diag.status.value,
        class_name=school_class.name,
        course=_course_ref(course),
        answered=diag.answered,
        max_questions=eng.MAX_QUESTIONS,
        empty=diag.status == DiagnosticStatus.finished and not diag.range_ids,
    )


async def current(scope: OrgScope) -> list[DiagnosticState]:
    """The caller's open diagnostics, in enrolled, unarchived classes."""
    learn._require_student(scope)
    rows = (
        await scope.session.execute(
            scope.select(DiagnosticSession)
            .add_columns(SchoolClass)
            .join(
                SchoolClass,
                (SchoolClass.id == DiagnosticSession.class_id)
                & (SchoolClass.org_id == DiagnosticSession.org_id),
            )
            .join(
                Enrollment,
                (Enrollment.class_id == SchoolClass.id)
                & (Enrollment.org_id == SchoolClass.org_id)
                & (Enrollment.student_id == DiagnosticSession.student_id),
            )
            .where(
                DiagnosticSession.student_id == scope.user.id,
                DiagnosticSession.status.in_(OPEN),
                SchoolClass.archived_at.is_(None),
            )
            .order_by(DiagnosticSession.sent_at, DiagnosticSession.id)
        )
    ).all()
    if not rows:
        return []
    graph = await learn._graph(scope)
    return [_state(d, c, graph) for d, c in rows]


async def state(scope: OrgScope, diagnostic_id: str) -> DiagnosticState:
    diag, school_class = await _own(scope, diagnostic_id, for_update=False)
    return _state(diag, school_class, await learn._graph(scope))


@dataclass
class _Run:
    """A started diagnostic's engine state, rebuilt per request from the frozen range."""

    graph: eng.RangeGraph
    ev: eng.Evidence
    items: _Items

    def askable(self, served: Collection[uuid.UUID]) -> set[uuid.UUID]:
        taken = set(served)
        return {
            c
            for c, kps in self.items.by_concept.items()
            if c in self.ev and any(i not in taken for items in kps for i in items)
        }


async def _run(scope: OrgScope, diag: DiagnosticSession) -> _Run:
    ids = list(diag.range_ids or [])
    graph = eng.RangeGraph.build(ids, await _edges(scope, ids))
    return _Run(graph, eng.load_evidence(diag.evidence), await _items(scope, ids))


def _serve_next(
    diag: DiagnosticSession, session: PracticeSession, run: _Run, position: int
) -> bool:
    """Pick the next concept and item and store them on the session (before returning, so
    reloads get the same question). False when nothing askable is undecided."""
    rng = random.Random(secrets.randbits(64))
    served = list(diag.served_item_ids or [])
    askable = run.askable(served)
    while True:
        cid = eng.next_concept(run.graph, run.ev, askable)
        if cid is None:
            return False
        item_id = eng.pick_item(run.items.by_concept.get(cid, []), set(served), rng)
        if item_id is None:  # every quick item of it was served: no longer askable
            askable.discard(cid)
            continue
        diag.served_item_ids = [*served, item_id]
        session.current_item_id = item_id
        session.current_seed = (
            secrets.randbelow(2**31) if run.items.has_params.get(item_id) else None
        )
        session.current_position = position
        session.current_served_at = datetime.now(UTC)
        return True


async def start(scope: OrgScope, diagnostic_id: str) -> DiagnosticState:
    """Freeze the range and serve the first question (idempotent once active)."""
    diag, school_class = await _own(scope, diagnostic_id)
    graph = await learn._graph(scope)
    if diag.status == DiagnosticStatus.active:
        return _state(diag, school_class, graph)
    if diag.status != DiagnosticStatus.sent:
        raise _closed()
    course = class_view.class_course(graph, school_class)
    covered = await _covered(scope, school_class.id, graph, course)
    ids = range_for(graph, course, covered)
    items = await _items(scope, ids)
    now = datetime.now(UTC)
    diag.status = DiagnosticStatus.active
    diag.started_at = now
    diag.chapter_ids = covered
    if not items.by_concept:  # nothing to check right now: finished at once, nothing applied
        diag.range_ids = []
        diag.evidence = {}
        diag.status = DiagnosticStatus.finished
        diag.finished_at = now
        diag.results = _results(eng.Results())
        await scope.session.commit()
        return _state(diag, school_class, graph)
    learned = set(
        (
            await scope.session.scalars(
                scope.select(ConceptState)
                .with_only_columns(ConceptState.concept_id)
                .where(
                    ConceptState.student_id == scope.user.id,
                    ConceptState.concept_id.in_(ids),
                    ConceptState.status == ConceptStatus.learned,
                )
            )
        ).all()
    )
    diag.range_ids = ids
    rgraph = eng.RangeGraph.build(ids, await _edges(scope, ids))
    ev = eng.initial(rgraph, learned)
    diag.evidence = eng.dump_evidence(ev)
    session = scope.new(
        PracticeSession,
        student_id=scope.user.id,
        kind=SessionKind.diagnostic,
        diagnostic_id=diag.id,
        status=SessionStatus.active,
        current_position=1,
    )
    scope.session.add(session)
    await scope.session.flush()
    if not _serve_next(diag, session, _Run(rgraph, ev, items), 1):
        await _finish(scope, diag, session, _Run(rgraph, ev, items), now)
    await scope.session.commit()
    return _state(diag, school_class, graph)


async def question(scope: OrgScope, diagnostic_id: str) -> QuestionPublic:
    diag, _ = await _own(scope, diagnostic_id)
    if diag.status == DiagnosticStatus.sent:
        raise _not_started()
    if diag.status != DiagnosticStatus.active:
        raise _closed()
    session = await _session(scope, diag)
    if session is None:
        raise _closed()
    item = None
    if session.current_item_id is not None:
        item = await scope.session.get(Item, session.current_item_id)
    if item is None or item.retired_at is not None:  # retired mid-run: replace it in place
        run = await _run(scope, diag)
        if not _serve_next(diag, session, run, session.current_position):
            await _finish(scope, diag, session, run, datetime.now(UTC))
            await scope.session.commit()
            raise _closed()
        await scope.session.commit()
        assert session.current_item_id is not None
        item = await scope.session.get(Item, session.current_item_id)
        assert item is not None
    return await kp_flow._question(
        scope,
        item,
        session.current_seed,
        session_id=session.id,
        position=session.current_position,
        results=[],
    )


async def _answered_positions(scope: OrgScope, session: PracticeSession) -> set[int]:
    return {
        p
        for p in (
            await scope.session.scalars(
                scope.select(Attempt)
                .with_only_columns(Attempt.position)
                .where(Attempt.session_id == session.id)
            )
        ).all()
        if p is not None
    }


async def answer(scope: OrgScope, diagnostic_id: str, body: DiagnosticAnswerIn) -> DiagnosticSaved:
    """Store the answer and serve the next question; never says whether it was right. The
    answer that ends the run finishes and applies it in the same transaction."""
    diag, _ = await _own(scope, diagnostic_id)
    if diag.status == DiagnosticStatus.sent:
        raise _not_started()
    session = await _session(scope, diag)
    if session is None:
        raise _closed()
    positions = await _answered_positions(scope, session)
    if diag.status != DiagnosticStatus.active:
        if diag.status == DiagnosticStatus.finished and body.position in positions:
            return DiagnosticSaved(finished=True, answered=diag.answered)  # a resend
        raise _closed()
    sent = kp_flow._session_uuid(body)
    if sent != session.id:
        raise _stale()
    if body.position in positions:
        return DiagnosticSaved(finished=False, answered=diag.answered)
    if body.position != session.current_position or session.current_item_id is None:
        raise _stale()
    item = await scope.session.get(Item, session.current_item_id)
    assert item is not None
    now = datetime.now(UTC)
    if body.idk:
        correct, response, misconception_id = False, {"idk": True}, None
    else:
        graded = await kp_flow._grade_answer(scope, item, session.current_seed, body)
        correct, response = graded.result.correct, graded.response
        misconception_id, _ = await kp_flow._misconception(scope, item, graded.result.misconception)
    elapsed = int((now - (session.current_served_at or now)).total_seconds() * 1000)
    await scope.session.execute(
        insert(Attempt)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            item_id=item.id,
            item_version=item.version,
            context=AttemptContext.diagnostic,
            seed=session.current_seed,
            response=response,
            correct=correct,
            misconception_id=misconception_id,
            time_taken_ms=max(0, min(body.time_taken_ms, elapsed, kp_flow.MAX_ANSWER_MS)),
            hints_used=0,
            session_id=session.id,
            position=session.current_position,
            step=0,
        )
        .on_conflict_do_nothing(index_elements=[Attempt.session_id, Attempt.position, Attempt.step])
    )
    run = await _run(scope, diag)
    concept_id = await scope.session.scalar(
        select(KnowledgePoint.concept_id).where(KnowledgePoint.id == item.kp_id)
    )
    if concept_id in run.ev:
        run.ev = eng.apply_answer(run.graph, run.ev, concept_id, correct)
    diag.evidence = eng.dump_evidence(run.ev)
    diag.answered = diag.answered + 1
    finished = eng.finished(diag.answered, run.ev, run.askable(diag.served_item_ids or []))
    if not finished:
        finished = not _serve_next(diag, session, run, session.current_position + 1)
    if finished:
        await _finish(scope, diag, session, run, now)
    await scope.session.commit()
    return DiagnosticSaved(finished=finished, answered=diag.answered)


def _results(res: eng.Results) -> dict[str, object]:
    return {
        "learned": [str(c) for c in res.learned],
        "conditional": [str(c) for c in res.conditional],
        "demoted": [str(c) for c in res.demoted],
        "confirmed": [str(c) for c in res.confirmed],
        "counts": {
            "learned": len(res.learned),
            "conditional": len(res.conditional),
            "demoted": len(res.demoted),
        },
    }


async def _finish(
    scope: OrgScope,
    diag: DiagnosticSession,
    session: PracticeSession,
    run: _Run,
    now: datetime,
) -> None:
    """Apply the result against the student's current state: promotions in topological order
    (through `frontier.mark_learned`), then demotions (`kp_flow._relearn`). No XP, no implicit
    credit, no quiz mark change."""
    await scope.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"placement:{scope.user.id}"},
    )
    graph = await learn._graph(scope)
    active = [c for c in run.graph.concepts if c in graph.nodes]  # retired since start: skipped
    stored = {
        cid: (status, cond)
        for cid, status, cond in (
            await scope.session.execute(
                scope.select(ConceptState)
                .with_only_columns(
                    ConceptState.concept_id, ConceptState.status, ConceptState.conditional
                )
                .where(
                    ConceptState.student_id == scope.user.id,
                    ConceptState.concept_id.in_(active),
                )
                .order_by(ConceptState.concept_id)
                .with_for_update()
            )
        ).all()
    }
    learned = {c for c, (s, _) in stored.items() if s == ConceptStatus.learned}
    conditional = {c for c, (s, cond) in stored.items() if s == ConceptStatus.learned and cond}
    ev = {c: x for c, x in run.ev.items() if c in set(active)}
    res = eng.classify(run.graph, ev, learned=learned, conditional=conditional)
    # Conditional needs a review card to clear it; a concept with no quick-check item gets none,
    # so it's placed as plainly learned (it can't come back for a check).
    shaky = set(res.conditional) & await srs.gradable(scope, res.conditional)
    res.learned = eng.topo(
        run.graph, [*res.learned, *(c for c in res.conditional if c not in shaky)]
    )
    res.conditional = [c for c in res.conditional if c in shaky]  # the stored results match
    for cid in eng.topo(run.graph, [*res.learned, *res.conditional]):
        if cid in stored:  # in progress: its open KP/practice work ends
            await kp_flow.end_concept_work(scope, cid)
        await frontier.mark_learned(
            scope, cid, source=ConceptSource.diagnostic, conditional=cid in shaky
        )
    await srs.clear_conditional(scope, res.confirmed)
    for cid in res.demoted:
        await kp_flow._relearn(scope, cid)
    diag.results = _results(res)
    diag.status = DiagnosticStatus.finished
    diag.finished_at = now
    session.status = SessionStatus.passed
    session.ended_at = now


async def result(scope: OrgScope, diagnostic_id: str) -> DiagnosticResult:
    diag, _ = await _own(scope, diagnostic_id, for_update=False)
    if diag.status != DiagnosticStatus.finished:
        raise conflict("diagnostic_not_finished", "This placement check isn't finished yet.")
    graph = await learn._graph(scope)
    results = diag.results or {}

    def refs(key: str) -> list[ConceptRef]:
        ids = [uuid.UUID(c) for c in results.get(key, [])]
        return [_ref(graph, c) for c in ids if c in graph.nodes]

    ids = [c for c in diag.range_ids or [] if c in graph.nodes]
    learned_now = set(
        (
            await scope.session.scalars(
                scope.select(ConceptState)
                .with_only_columns(ConceptState.concept_id)
                .where(
                    ConceptState.student_id == scope.user.id,
                    ConceptState.concept_id.in_(ids),
                    ConceptState.status == ConceptStatus.learned,
                )
            )
        ).all()
    )
    return DiagnosticResult(
        answered=diag.answered,
        learned=refs("learned"),
        conditional=refs("conditional"),
        to_learn=[_ref(graph, c) for c in ids if c not in learned_now],
    )
