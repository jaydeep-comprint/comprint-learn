"""Learn layer (spec 004): student courses, course outlines with borrowed prerequisites, lessons,
the one-try misconception check, progress and study time. Spec 005: statuses come from the
knowledge frontier (`app/services/frontier.py`; "learned" opens dependants) and lessons interleave
each KP's worked example with its questions (`kpq:` steps, `app/services/kp_flow.py`). Spec 006:
lessons end with a required `practice` step (`app/services/practice.py`).

Content is global (read without `OrgScope`); learning state (`attempt`, `lesson_progress`,
`study_time`, `concept_state`, ...) is tenant-owned and read/written only through the caller's
`OrgScope`. Staff get a preview: no statuses, no locks, and nothing is ever written for them.

The top of this module is pure (no DB) so the outline algorithm is unit-testable.
"""

from __future__ import annotations  # frontier and learn import each other (spec 007 import order)

import hashlib
import heapq
import random
import uuid
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import any_, case, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.dml import ReturningInsert

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, forbidden, not_found
from app.grading.mcq import ShownOptions
from app.models import (
    Attempt,
    AttemptContext,
    Chapter,
    Concept,
    ConceptPrereq,
    Course,
    Enrollment,
    Item,
    KnowledgePoint,
    KpStatus,
    LessonProgress,
    Misconception,
    PracticeSession,
    Remediation,
    RemediationState,
    ReviewCard,
    SchoolClass,
    SessionKind,
    SessionStatus,
    StudyActivity,
    StudyTime,
    Subject,
)
from app.models.content import ItemKind
from app.schemas.content import CourseRef, ItemPublic
from app.schemas.learn import (
    CheckPublic,
    CheckResult,
    CheckSubmitted,
    ConceptRef,
    HomeConcept,
    KpOut,
    Lesson,
    LessonPractice,
    LessonWaiting,
    LockedPrereq,
    MisconceptionOut,
    Outline,
    OutlineChapter,
    OutlineConcept,
    ProgressOut,
    RemediationRef,
    StudentCourse,
    Waiting,
)
from app.services import frontier

MAX_STEP_SECONDS = 600
REMEDIATION_STEP = "remediation"  # study time on a brush-up review, logged against the prereq
REVIEW_STEP = "review"  # spec 007: study time on a scheduled review of the concept
MAX_CHECK_MS = 1_800_000
ASSET_URL_PREFIX = "/content-assets/"
SUBJECT_ORDER = {s: i for i, s in enumerate(Subject)}

# --- pure helpers ---------------------------------------------------------------------------------


def build_outline[K: Hashable](
    own: Sequence[K],
    prereqs: Mapping[K, Collection[K]],
    sort_key: Callable[[K], Any],
) -> list[tuple[K, K]]:
    """The outline of a course as `(concept, anchor)` pairs, in display order.

    `own` is the course's concepts in authored order. Every ancestor of an own concept that is not
    itself own is *borrowed*: placed once, immediately before the first own concept that needs it,
    with its own not-yet-placed ancestors before it (topological order; ties by `sort_key`). The
    anchor is the own concept a borrowed one was placed before (an own concept anchors itself).
    """
    own_set = set(own)
    placed: set[K] = set()
    out: list[tuple[K, K]] = []
    for anchor in own:
        borrowed = _ancestors(anchor, prereqs) - own_set - placed
        for concept in _topo_sorted(borrowed, prereqs, sort_key):
            out.append((concept, anchor))
            placed.add(concept)
        out.append((anchor, anchor))
    return out


def _ancestors[K: Hashable](start: K, prereqs: Mapping[K, Collection[K]]) -> set[K]:
    seen: set[K] = set()
    stack = list(prereqs.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen or node == start:
            continue
        seen.add(node)
        stack.extend(prereqs.get(node, ()))
    return seen


def _topo_sorted[K: Hashable](
    nodes: set[K], prereqs: Mapping[K, Collection[K]], sort_key: Callable[[K], Any]
) -> list[K]:
    """Kahn's algorithm within `nodes`, ancestors first; a heap on `sort_key` breaks ties."""
    waiting = {n: {p for p in prereqs.get(n, ()) if p in nodes} for n in nodes}
    needed_by: dict[K, list[K]] = {n: [] for n in nodes}
    for n, ps in waiting.items():
        for p in ps:
            needed_by[p].append(n)
    heap = [(sort_key(n), i, n) for i, n in enumerate(n for n, ps in waiting.items() if not ps)]
    heapq.heapify(heap)
    counter = len(heap)
    out: list[K] = []
    while heap:
        _, _, n = heapq.heappop(heap)
        out.append(n)
        for child in needed_by[n]:
            waiting[child].discard(n)
            if not waiting[child]:
                heapq.heappush(heap, (sort_key(child), counter, child))
                counter += 1
    if len(out) < len(nodes):  # a cycle (the validator forbids them): keep the rest, sorted
        out.extend(sorted(nodes - set(out), key=sort_key))
    return out


def shuffled_order(
    option_ids: Sequence[str], student_id: uuid.UUID, item_id: uuid.UUID
) -> list[str]:
    """A per-student option order that is stable across reloads."""
    seed = hashlib.sha256(f"{student_id}:{item_id}".encode()).digest()
    order = list(option_ids)
    random.Random(seed).shuffle(order)
    return order


PRACTICE_STEP = "practice"


def lesson_steps(
    kp_slugs: Iterable[str], *, has_check: bool, has_practice: bool = False
) -> list[str]:
    """`intro` → `check` → per KP: `kp:<slug>` (worked example) → `kpq:<slug>` (questions) →
    `practice` (spec 006, when the concept has practice items)."""
    kp_steps = [step for slug in kp_slugs for step in (f"kp:{slug}", f"kpq:{slug}")]
    practice = [PRACTICE_STEP] if has_practice else []
    return ["intro", *(["check"] if has_check else []), *kp_steps, *practice]


# --- the content graph (global) -------------------------------------------------------------------


@dataclass(frozen=True)
class _Node:
    id: uuid.UUID
    course_id: uuid.UUID
    course_slug: str
    subject: Subject
    slug: str
    title: str
    summary: str
    chapter_id: uuid.UUID
    chapter_position: int
    position: int

    @property
    def ref(self) -> str:
        return f"{self.course_slug}/{self.slug}"

    def sort_key(self) -> tuple[int, int, int, str]:
        return (SUBJECT_ORDER[self.subject], self.chapter_position, self.position, self.ref)


@dataclass
class _Graph:
    nodes: dict[uuid.UUID, _Node]
    prereqs: dict[uuid.UUID, list[uuid.UUID]]
    by_ref: dict[str, uuid.UUID]
    courses: dict[str, Course]
    chapters: dict[uuid.UUID, Chapter]

    def outline(self, course_slug: str) -> list[tuple[uuid.UUID, uuid.UUID]]:
        course = self.courses[course_slug]
        own = sorted(
            (n for n in self.nodes.values() if n.course_id == course.id),
            key=lambda n: (n.chapter_position, n.position),
        )
        return build_outline(
            [n.id for n in own], self.prereqs, lambda cid: self.nodes[cid].sort_key()
        )


async def _graph(scope: OrgScope) -> _Graph:
    """All active content concepts and edges: three small queries, whatever the course count."""
    session = scope.session
    courses = {
        c.slug: c
        for c in (await session.scalars(select(Course).where(Course.retired_at.is_(None)))).all()
    }
    course_by_id = {c.id: c for c in courses.values()}
    chapters = {
        ch.id: ch
        for ch in (
            await session.scalars(
                select(Chapter).where(
                    Chapter.retired_at.is_(None), Chapter.course_id.in_(course_by_id)
                )
            )
        ).all()
    }
    rows = await session.execute(
        select(
            Concept.id,
            Concept.course_id,
            Concept.slug,
            Concept.title,
            Concept.summary,
            Concept.chapter_id,
            Concept.position,
        ).where(Concept.retired_at.is_(None), Concept.chapter_id.in_(chapters))
    )
    nodes: dict[uuid.UUID, _Node] = {}
    for cid, course_id, slug, title, summary, chapter_id, position in rows.all():
        course = course_by_id[course_id]
        nodes[cid] = _Node(
            id=cid,
            course_id=course_id,
            course_slug=course.slug,
            subject=course.subject,
            slug=slug,
            title=title,
            summary=summary,
            chapter_id=chapter_id,
            chapter_position=chapters[chapter_id].position,
            position=position,
        )
    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {}
    for concept_id, prereq_id in (
        await session.execute(select(ConceptPrereq.concept_id, ConceptPrereq.prereq_id))
    ).all():
        if concept_id in nodes and prereq_id in nodes:
            prereqs.setdefault(concept_id, []).append(prereq_id)
    for ps in prereqs.values():
        ps.sort(key=lambda p: nodes[p].sort_key())
    return _Graph(
        nodes=nodes,
        prereqs=prereqs,
        by_ref={n.ref: n.id for n in nodes.values()},
        courses=courses,
        chapters=chapters,
    )


# --- the student's view ---------------------------------------------------------------------------


async def _student_course_slugs(scope: OrgScope, graph: _Graph) -> list[str]:
    """Active courses for the subjects of the student's non-archived classes, by subject."""
    subjects = set(
        (
            await scope.session.scalars(
                scope.select(SchoolClass)
                .with_only_columns(SchoolClass.subject)
                .join(
                    Enrollment,
                    (Enrollment.class_id == SchoolClass.id)
                    & (Enrollment.org_id == SchoolClass.org_id),
                )
                .where(Enrollment.student_id == scope.user.id, SchoolClass.archived_at.is_(None))
                .distinct()
            )
        ).all()
    )
    courses = [c for c in graph.courses.values() if c.subject in subjects]
    return [c.slug for c in sorted(courses, key=lambda c: SUBJECT_ORDER[c.subject])]


async def _progress(
    scope: OrgScope, concept_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, LessonProgress]:
    if not concept_ids:
        return {}
    rows = await scope.session.scalars(
        scope.select(LessonProgress).where(
            LessonProgress.student_id == scope.user.id,
            LessonProgress.concept_id.in_(concept_ids),
        )
    )
    return {r.concept_id: r for r in rows.all()}


def _require_student(scope: OrgScope) -> None:
    if scope.user.is_staff:
        raise forbidden()


HOME_READY = 5


def _concept_ref(graph: _Graph, cid: uuid.UUID) -> ConceptRef:
    return ConceptRef(id=graph.nodes[cid].ref, title=graph.nodes[cid].title)


async def remediation_refs(
    scope: OrgScope, graph: _Graph, remediations: Sequence[frontier.RemediationView]
) -> list[tuple[frontier.RemediationView, RemediationRef]]:
    """Remediations (whose concepts are still active) with the failing KP's concept."""
    kp_ids = {r.kp_id for r in remediations}
    concept_of = (
        dict(
            (
                await scope.session.execute(
                    select(KnowledgePoint.id, KnowledgePoint.concept_id).where(
                        KnowledgePoint.id.in_(kp_ids)
                    )
                )
            ).all()
        )
        if kp_ids
        else {}
    )
    out = []
    for r in remediations:
        cid = concept_of.get(r.kp_id)
        if cid not in graph.nodes or r.prereq_concept_id not in graph.nodes:
            continue
        out.append(
            (
                r,
                RemediationRef(
                    id=str(r.id),
                    kind="review" if r.state == RemediationState.review_due else "relearn",
                    prereq=_concept_ref(graph, r.prereq_concept_id),
                    concept=_concept_ref(graph, cid),
                ),
            )
        )
    return out


def _home_concept(graph: _Graph, view: frontier.ConceptView) -> HomeConcept:
    waiting = view.waiting
    return HomeConcept(
        id=graph.nodes[view.id].ref,
        title=graph.nodes[view.id].title,
        kps_passed=view.kps_passed,
        kps_total=view.kps_total,
        parts_passed=view.parts_passed,
        parts_total=view.parts_total,
        practice_left=view.practice_left,
        reopen_at=None if waiting is None else waiting.reopen_at,
    )


async def student_courses(scope: OrgScope) -> list[StudentCourse]:
    _require_student(scope)
    graph = await _graph(scope)
    slugs = await _student_course_slugs(scope, graph)
    outlines = {slug: [cid for cid, _ in graph.outline(slug)] for slug in slugs}
    front = await frontier.load(
        scope, {cid for ids in outlines.values() for cid in ids}, graph.prereqs
    )
    rems = await remediation_refs(scope, graph, front.remediations)
    await scope.session.commit()  # a promotion on read (frontier.load)
    out = []
    for slug in slugs:
        ids = outlines[slug]
        views = [front.views[cid] for cid in ids]
        in_outline = set(ids)
        ready = [v for v in views if v.status == "ready"]
        course = graph.courses[slug]
        out.append(
            StudentCourse(
                slug=slug,
                title=course.title,
                subject=course.subject,
                learned=sum(1 for v in views if v.status == "learned"),
                total=len(ids),
                brush_up=[
                    ref
                    for _, ref in rems
                    if graph.by_ref[ref.concept.id] in in_outline
                    or graph.by_ref[ref.prereq.id] in in_outline
                ],
                in_progress=[
                    _home_concept(graph, v)
                    for v in views
                    if v.status == "in_progress" and v.waiting is None
                ],
                ready=[_home_concept(graph, v) for v in ready[:HOME_READY]],
                ready_count=len(ready),
                waiting=[_home_concept(graph, v) for v in views if v.waiting is not None],
            )
        )
    return out


async def outline(scope: OrgScope, course_slug: str) -> Outline:
    graph = await _graph(scope)
    if course_slug not in graph.courses:
        raise not_found()
    staff = scope.user.is_staff
    if not staff and course_slug not in await _student_course_slugs(scope, graph):
        raise not_found()
    pairs = graph.outline(course_slug)
    ids = [c for c, _ in pairs]
    kps_total: dict[uuid.UUID, int] = {}
    with_practice: set[uuid.UUID] = set()
    if staff:
        for kp in await frontier.active_kps(scope, ids):
            kps_total[kp.concept_id] = kps_total.get(kp.concept_id, 0) + 1
        with_practice = await frontier.practice_concepts(scope, ids)
        views: dict[uuid.UUID, frontier.ConceptView] = {}
    else:
        views = (await frontier.load(scope, ids, graph.prereqs)).views
        await scope.session.commit()  # a promotion on read

    chapters: dict[uuid.UUID, list[OutlineConcept]] = {}
    for cid, anchor in pairs:
        node = graph.nodes[cid]
        view = views.get(cid)
        waiting = None if view is None else view.waiting
        chapters.setdefault(graph.nodes[anchor].chapter_id, []).append(
            OutlineConcept(
                id=node.ref,
                title=node.title,
                summary=node.summary,
                status=None if view is None else view.status,
                prereqs=[graph.nodes[p].ref for p in graph.prereqs.get(cid, [])],
                kps_passed=0 if view is None else view.kps_passed,
                kps_total=kps_total.get(cid, 0) if view is None else view.kps_total,
                parts_passed=0 if view is None else view.parts_passed,
                parts_total=(
                    kps_total.get(cid, 0) + (cid in with_practice)
                    if view is None
                    else view.parts_total
                ),
                waiting=None if waiting is None else Waiting(reopen_at=waiting.reopen_at),
                brush_up=False if view is None else view.brush_up,
                brush_up_id=None if view is None else view.brush_up_id,
                placed=view is not None and view.placed,
                conditional=view is not None and view.conditional,
            )
        )
    course = graph.courses[course_slug]
    ordered = sorted(chapters, key=lambda ch_id: graph.chapters[ch_id].position)
    return Outline(
        course=CourseRef(slug=course.slug, title=course.title, subject=course.subject),
        chapters=[
            OutlineChapter(
                slug=graph.chapters[ch_id].slug,
                title=graph.chapters[ch_id].title,
                grade=graph.chapters[ch_id].grade,
                concepts=chapters[ch_id],
            )
            for ch_id in ordered
        ],
    )


# --- one lesson -----------------------------------------------------------------------------------


@dataclass
class _Access:
    graph: _Graph
    node: _Node
    progress: LessonProgress | None
    front: frontier.Frontier | None  # None for staff

    @property
    def view(self) -> frontier.ConceptView | None:
        return None if self.front is None else self.front.views[self.node.id]


def concept_locked(prereqs: list[LockedPrereq]) -> ApiProblem:
    return ApiProblem(
        403,
        "concept_locked",
        "Learn the concepts this one builds on first.",
        extra={"prereqs": [p.model_dump() for p in prereqs]},
    )


async def _access(scope: OrgScope, course_slug: str, concept_slug: str) -> _Access:
    """The concept if this user may open it: 404 if unknown/retired/outside the student's courses,
    403 `concept_locked` if it's locked (a direct prerequisite isn't learned). Staff may open any
    concept."""
    graph = await _graph(scope)
    cid = graph.by_ref.get(f"{course_slug}/{concept_slug}")
    if cid is None:
        raise not_found()
    node = graph.nodes[cid]
    if scope.user.is_staff:
        return _Access(graph, node, None, None)

    reachable = {
        c for slug in await _student_course_slugs(scope, graph) for c, _ in graph.outline(slug)
    }
    if cid not in reachable:
        raise not_found()
    direct = graph.prereqs.get(cid, [])
    front = await frontier.load(scope, [cid, *direct], graph.prereqs)
    if front.status(cid) == "locked":
        raise concept_locked(
            [
                LockedPrereq(
                    id=graph.nodes[p].ref, title=graph.nodes[p].title, status=front.status(p)
                )
                for p in direct
                if front.status(p) != "learned"
            ]
        )
    progress = await _progress(scope, [cid])
    return _Access(graph, node, progress.get(cid), front)


@dataclass
class _LessonContent:
    concept: Concept
    kps: list[KnowledgePoint]
    check: Item | None
    has_practice: bool = False

    @property
    def steps(self) -> list[str]:
        return lesson_steps(
            (kp.slug for kp in self.kps),
            has_check=self.check is not None,
            has_practice=self.has_practice,
        )

    @property
    def kp_steps(self) -> set[str]:
        return {f"kp:{kp.slug}" for kp in self.kps}


async def _content(scope: OrgScope, concept_id: uuid.UUID) -> _LessonContent:
    session = scope.session
    concept = await session.get(Concept, concept_id)
    assert concept is not None
    kps = (
        await session.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.concept_id == concept_id, KnowledgePoint.retired_at.is_(None))
            .order_by(KnowledgePoint.position)
        )
    ).all()
    check = await session.scalar(
        select(Item).where(
            Item.concept_id == concept_id,
            Item.kind == ItemKind.misconception_check,
            Item.retired_at.is_(None),
        )
    )
    has_practice = concept_id in await frontier.practice_concepts(scope, [concept_id])
    return _LessonContent(concept, list(kps), check, has_practice)


def _shown_options(scope: OrgScope, item: Item) -> ShownOptions:
    public = ItemPublic.from_row(item)
    options = list(public.options or [])
    if scope.user.is_staff or not public.shuffle:
        return ShownOptions(options)
    by_id = {o.id: o for o in options}
    return ShownOptions([by_id[i] for i in shuffled_order(list(by_id), scope.user.id, item.id)])


async def _result(
    scope: OrgScope,
    item: Item,
    chosen: str,
    misconception_id: uuid.UUID | None,
    correct: bool | None = None,
) -> CheckResult:
    """`chosen` is an authored id; the result speaks the client's ids (`ShownOptions`).

    `correct` is the stored grade for an existing attempt (else graded against the key now)."""
    shown = _shown_options(scope, item)
    title = None
    if misconception_id is not None:
        title = await scope.session.scalar(
            select(Misconception.title).where(Misconception.id == misconception_id)
        )
    return CheckResult(
        correct=chosen == item.answer.get("correct") if correct is None else correct,
        chosen=shown.to_client(chosen),
        correct_option=shown.to_client(item.answer.get("correct")),
        explanation_md=item.answer.get("explanation"),
        misconception=None if title is None else MisconceptionOut(title=title),
    )


async def _stored_attempt(scope: OrgScope, item_id: uuid.UUID) -> Attempt | None:
    return await scope.session.scalar(
        scope.select(Attempt).where(
            Attempt.student_id == scope.user.id,
            Attempt.item_id == item_id,
            Attempt.context == AttemptContext.learn,
        )
    )


def _progress_out(row: LessonProgress | None) -> ProgressOut | None:
    if row is None:
        return None
    return ProgressOut(
        seen_steps=row.seen_steps, last_step=row.last_step, finished_at=row.finished_at
    )


async def lesson(scope: OrgScope, course_slug: str, concept_slug: str) -> Lesson:
    access = await _access(scope, course_slug, concept_slug)
    content = await _content(scope, access.node.id)
    check_result = None
    check = None
    if content.check is not None:
        public = ItemPublic.from_row(content.check)
        check = CheckPublic(
            item_id=str(content.check.id),
            prompt=public.prompt,
            options=_shown_options(scope, content.check).public(),
        )
        if not scope.user.is_staff:
            attempt = await _stored_attempt(scope, content.check.id)
            if attempt is not None:
                check_result = await _result(
                    scope,
                    content.check,
                    attempt.response["option"],
                    attempt.misconception_id,
                    attempt.correct,
                )
    asset_path = content.concept.asset_path
    view = access.view
    kp_views = {} if view is None else {k.id: k for k in view.kps}
    active = await _active_kp_sessions(scope, list(kp_views))
    waiting = None
    if view is not None and (wkp := view.waiting) is not None:
        refs = await remediation_refs(scope, access.graph, wkp.remediations)
        waiting = LessonWaiting(
            kp=wkp.slug, reopen_at=wkp.reopen_at, remediations=[ref for _, ref in refs]
        )
    practice = LessonPractice(
        status=(("pending" if content.has_practice else "none") if view is None else view.practice),
        active=view is not None and await _active_practice(scope, access.node.id),
    )
    await scope.session.commit()  # a promotion on read (frontier.load in _access)
    return Lesson(
        id=access.node.ref,
        title=content.concept.title,
        summary=content.concept.summary,
        asset_base=f"{ASSET_URL_PREFIX}{asset_path}/" if asset_path else "",
        intro_md=content.concept.intro_md,
        check=check,
        kps=[_kp_out(k, kp_views.get(k.id), k.id in active) for k in content.kps],
        steps=content.steps,
        progress=_progress_out(access.progress),
        check_result=check_result,
        preview=scope.user.is_staff,
        concept_status=None if view is None else view.status,
        placed=view is not None and view.placed,
        waiting=waiting,
        practice=practice,
    )


def _kp_out(kp: KnowledgePoint, view: frontier.KpView | None, active: bool) -> KpOut:
    if view is None:  # staff
        return KpOut(
            slug=kp.slug,
            title=kp.title,
            worked_example_md=kp.worked_example_md,
            status=None,
            open=True,
            reopen_at=None,
            active=False,
        )
    return KpOut(
        slug=kp.slug,
        title=kp.title,
        worked_example_md=kp.worked_example_md,
        status="passed" if view.passed else view.status.value,
        open=view.open,
        reopen_at=view.reopen_at if view.status == KpStatus.failed else None,
        active=active,
    )


async def _active_kp_sessions(scope: OrgScope, kp_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not kp_ids:
        return set()
    rows = await scope.session.scalars(
        scope.select(PracticeSession)
        .with_only_columns(PracticeSession.kp_id)
        .where(
            PracticeSession.student_id == scope.user.id,
            PracticeSession.kp_id.in_(kp_ids),
            PracticeSession.status == SessionStatus.active,
        )
    )
    return {kp_id for kp_id in rows.all() if kp_id is not None}


async def _active_practice(scope: OrgScope, concept_id: uuid.UUID) -> bool:
    row = await scope.session.scalar(
        scope.select(PracticeSession)
        .with_only_columns(PracticeSession.id)
        .where(
            PracticeSession.student_id == scope.user.id,
            PracticeSession.kind == SessionKind.practice,  # not a review (spec 007)
            PracticeSession.concept_id == concept_id,
            PracticeSession.status == SessionStatus.active,
        )
        .limit(1)
    )
    return row is not None


async def _touch_progress(scope: OrgScope, concept_id: uuid.UUID, step: str) -> LessonProgress:
    """Create or update the row: `step` added to `seen_steps` (once), `last_step` = `step`.

    The upsert locks the row until commit, so a concurrent check submit and progress post
    serialise here and the later one sees the earlier one's writes when deciding `finished_at`.
    """
    seen = LessonProgress.seen_steps
    stmt = (
        insert(LessonProgress)
        .values(
            org_id=scope.org_id,
            student_id=scope.user.id,
            concept_id=concept_id,
            seen_steps=[step],
            last_step=step,
        )
        .on_conflict_do_update(
            index_elements=[LessonProgress.student_id, LessonProgress.concept_id],
            set_={
                "seen_steps": case(
                    (literal(step) == any_(seen), seen),
                    else_=func.array_append(seen, step),
                ),
                "last_step": step,
                "updated_at": func.now(),
            },
            where=LessonProgress.org_id == scope.org_id,
        )
        .returning(LessonProgress)
        .execution_options(populate_existing=True)
    )
    row = (await scope.session.scalars(stmt)).one()
    await frontier.ensure_started(scope, concept_id)
    return row


async def _maybe_finish(
    scope: OrgScope, row: LessonProgress, content: _LessonContent
) -> LessonProgress:
    """Sets `finished_at` once: when the check is answered and every current KP step is seen."""
    if row.finished_at is not None or not content.kp_steps <= set(row.seen_steps):
        return row
    if content.check is not None and await _stored_attempt(scope, content.check.id) is None:
        return row
    finished_at = await scope.session.scalar(
        update(LessonProgress)
        .where(
            LessonProgress.org_id == scope.org_id,
            LessonProgress.student_id == row.student_id,
            LessonProgress.concept_id == row.concept_id,
            LessonProgress.finished_at.is_(None),
        )
        .values(finished_at=func.now())
        .returning(LessonProgress.finished_at)
        .execution_options(synchronize_session=False)
    )
    if finished_at is not None:
        row.finished_at = finished_at
    return row


async def record_progress(
    scope: OrgScope, course_slug: str, concept_slug: str, step: str, active_seconds: int
) -> ProgressOut | None:
    """Staff: None (nothing written). Students: the updated progress."""
    access = await _access(scope, course_slug, concept_slug)
    if scope.user.is_staff:
        return None
    content = await _content(scope, access.node.id)
    remediation = step == REMEDIATION_STEP
    if remediation and not await _review_due_on(scope, access.node.id):
        raise ApiProblem(422, "invalid_step", "There's no brush-up due on this concept.")
    review = step == REVIEW_STEP
    if review and not await _has_card(scope, access.node.id):
        raise ApiProblem(422, "invalid_step", "There's no review on this concept.")
    if step not in content.steps and not remediation and not review:
        raise ApiProblem(422, "invalid_step", "That step isn't part of this lesson.")
    seconds = min(active_seconds, MAX_STEP_SECONDS)
    if seconds > 0:
        practice = remediation or review or step.startswith("kpq:") or step == PRACTICE_STEP
        scope.new(
            StudyTime,
            student_id=scope.user.id,
            concept_id=access.node.id,
            activity=StudyActivity.practice if practice else StudyActivity.learn,
            step=step,
            active_seconds=seconds,
        )
    if remediation or review:  # time on a brush-up or review of this concept: no lesson progress
        await scope.session.commit()
        return _progress_out(access.progress) or ProgressOut(
            seen_steps=[], last_step="", finished_at=None
        )
    row = await _touch_progress(scope, access.node.id, step)
    row = await _maybe_finish(scope, row, content)
    out = _progress_out(row)
    await scope.session.commit()
    assert out is not None
    return out


async def _has_card(scope: OrgScope, concept_id: uuid.UUID) -> bool:
    found = await scope.session.scalar(
        scope.select(ReviewCard)
        .with_only_columns(ReviewCard.concept_id)
        .where(ReviewCard.student_id == scope.user.id, ReviewCard.concept_id == concept_id)
    )
    return found is not None


async def _review_due_on(scope: OrgScope, concept_id: uuid.UUID) -> bool:
    """Brush-up time is logged only while a review on this prerequisite is due, or just ended
    (the page reports its time when the last answer comes back, after the review closed)."""
    on_prereq = scope.select(Remediation).where(
        Remediation.student_id == scope.user.id,
        Remediation.prereq_concept_id == concept_id,
    )
    due = await scope.session.scalar(
        on_prereq.with_only_columns(Remediation.id)
        .where(Remediation.state == RemediationState.review_due)
        .limit(1)
    )
    if due is not None:
        return True
    recent = await scope.session.scalar(
        scope.select(PracticeSession)
        .with_only_columns(PracticeSession.id)
        .where(
            PracticeSession.student_id == scope.user.id,
            PracticeSession.remediation_id.in_(on_prereq.with_only_columns(Remediation.id)),
            PracticeSession.ended_at >= func.now() - timedelta(seconds=MAX_STEP_SECONDS),
        )
        .limit(1)
    )
    return recent is not None


# The partial unique index's predicate, as a SQL literal. Never a bound parameter: once Postgres
# switches a prepared statement to a generic plan (after ~5 runs on a pooled connection) it can't
# prove `context = $1` implies the index, and ON CONFLICT fails with "no unique constraint".
LEARN_ATTEMPT_INDEX_WHERE = text("context = 'learn'")


def learn_attempt_insert(**values: Any) -> ReturningInsert[tuple[uuid.UUID]]:
    """Insert one Learn-check attempt; a second one for the same student and item does nothing."""
    return (
        insert(Attempt)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[Attempt.student_id, Attempt.item_id],
            index_where=LEARN_ATTEMPT_INDEX_WHERE,
        )
        .returning(Attempt.id)
    )


async def submit_check(
    scope: OrgScope, course_slug: str, concept_slug: str, option_id: str, time_taken_ms: int
) -> CheckSubmitted:
    access = await _access(scope, course_slug, concept_slug)
    content = await _content(scope, access.node.id)
    item = content.check
    if item is None:
        raise not_found()
    shown = _shown_options(scope, item)
    authored = shown.to_authored(option_id)
    if authored is None:
        raise ApiProblem(422, "invalid_option", "That isn't one of the options.")
    option_id = authored

    misconception_id = None
    slug = (item.answer.get("misconceptions") or {}).get(option_id)
    if slug is not None:
        misconception_id = await scope.session.scalar(
            select(Misconception.id).where(
                Misconception.course_id == content.concept.course_id, Misconception.slug == slug
            )
        )
    if scope.user.is_staff:  # graded, never stored
        result = await _result(scope, item, option_id, misconception_id)
        return CheckSubmitted(**result.model_dump(), already_answered=False)

    inserted = await scope.session.scalar(
        learn_attempt_insert(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            item_id=item.id,
            item_version=item.version,
            context=AttemptContext.learn,
            seed=None,
            response={"option": option_id, "order": [o.id for o in shown.authored]},
            correct=option_id == item.answer.get("correct"),
            misconception_id=misconception_id,
            time_taken_ms=max(0, min(time_taken_ms, MAX_CHECK_MS)),
            hints_used=0,
        )
    )
    if inserted is None:  # already answered (double submit, two tabs): the stored result
        attempt = await _stored_attempt(scope, item.id)
        assert attempt is not None
        result = await _result(
            scope, item, attempt.response["option"], attempt.misconception_id, attempt.correct
        )
        return CheckSubmitted(**result.model_dump(), already_answered=True)

    row = await _touch_progress(scope, access.node.id, "check")
    await _maybe_finish(scope, row, content)
    result = await _result(scope, item, option_id, misconception_id)
    await scope.session.commit()
    return CheckSubmitted(**result.model_dump(), already_answered=False)
