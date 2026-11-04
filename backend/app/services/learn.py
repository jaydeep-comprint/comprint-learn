"""Learn layer (spec 004): student courses, course outlines with borrowed prerequisites, lessons,
the one-try misconception check, progress and study time.

Content is global (read without `OrgScope`); learning state (`attempt`, `lesson_progress`,
`study_time`) is tenant-owned and read/written only through the caller's `OrgScope`. Staff get a
preview: no statuses, no locks, and nothing is ever written for them.

The top of this module is pure (no DB) so the outline algorithm is unit-testable.
"""

import hashlib
import heapq
import random
import uuid
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import any_, case, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, forbidden, not_found
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
    LessonProgress,
    Misconception,
    SchoolClass,
    StudyActivity,
    StudyTime,
    Subject,
)
from app.models.content import ItemKind
from app.schemas.content import CourseRef, ItemPublic, OptionPublic
from app.schemas.learn import (
    CheckPublic,
    CheckResult,
    CheckSubmitted,
    ConceptRef,
    KpOut,
    Lesson,
    LessonStatus,
    LockedPrereq,
    MisconceptionOut,
    Outline,
    OutlineChapter,
    OutlineConcept,
    ProgressOut,
    StudentCourse,
)

MAX_STEP_SECONDS = 600
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


def lesson_status[K: Hashable](
    concept: K, progress: Mapping[K, datetime | None], prereqs: Mapping[K, Collection[K]]
) -> LessonStatus:
    """`progress` maps concept → `finished_at` for every concept the student has a row for."""
    if concept in progress:
        return "finished" if progress[concept] is not None else "in_progress"
    if all(progress.get(p) is not None for p in prereqs.get(concept, ())):
        return "ready"
    return "locked"


def shuffled_order(
    option_ids: Sequence[str], student_id: uuid.UUID, item_id: uuid.UUID
) -> list[str]:
    """A per-student option order that is stable across reloads."""
    seed = hashlib.sha256(f"{student_id}:{item_id}".encode()).digest()
    order = list(option_ids)
    random.Random(seed).shuffle(order)
    return order


def lesson_steps(kp_slugs: Iterable[str], *, has_check: bool) -> list[str]:
    return ["intro", *(["check"] if has_check else []), *(f"kp:{s}" for s in kp_slugs)]


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


def _finished_map(progress: Mapping[uuid.UUID, LessonProgress]) -> dict[uuid.UUID, datetime | None]:
    return {cid: row.finished_at for cid, row in progress.items()}


def _require_student(scope: OrgScope) -> None:
    if scope.user.is_staff:
        raise forbidden()


async def student_courses(scope: OrgScope) -> list[StudentCourse]:
    _require_student(scope)
    graph = await _graph(scope)
    slugs = await _student_course_slugs(scope, graph)
    outlines = {slug: [cid for cid, _ in graph.outline(slug)] for slug in slugs}
    progress = await _progress(scope, {cid for ids in outlines.values() for cid in ids})
    finished = _finished_map(progress)
    out = []
    for slug in slugs:
        ids = outlines[slug]
        statuses = {cid: lesson_status(cid, finished, graph.prereqs) for cid in ids}
        in_progress = [cid for cid in ids if statuses[cid] == "in_progress"]
        if in_progress:
            next_id: uuid.UUID | None = max(in_progress, key=lambda cid: progress[cid].updated_at)
        else:
            next_id = next((cid for cid in ids if statuses[cid] == "ready"), None)
        course = graph.courses[slug]
        out.append(
            StudentCourse(
                slug=slug,
                title=course.title,
                subject=course.subject,
                finished=sum(1 for s in statuses.values() if s == "finished"),
                total=len(ids),
                continue_=(
                    None
                    if next_id is None
                    else ConceptRef(id=graph.nodes[next_id].ref, title=graph.nodes[next_id].title)
                ),
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
    finished = {} if staff else _finished_map(await _progress(scope, [c for c, _ in pairs]))

    chapters: dict[uuid.UUID, list[OutlineConcept]] = {}
    for cid, anchor in pairs:
        node = graph.nodes[cid]
        chapters.setdefault(graph.nodes[anchor].chapter_id, []).append(
            OutlineConcept(
                id=node.ref,
                title=node.title,
                summary=node.summary,
                status=None if staff else lesson_status(cid, finished, graph.prereqs),
                prereqs=[graph.nodes[p].ref for p in graph.prereqs.get(cid, [])],
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


def concept_locked(prereqs: list[LockedPrereq]) -> ApiProblem:
    return ApiProblem(
        403,
        "concept_locked",
        "Finish the lessons this one builds on first.",
        extra={"prereqs": [p.model_dump() for p in prereqs]},
    )


async def _access(scope: OrgScope, course_slug: str, concept_slug: str) -> _Access:
    """The concept if this user may open it: 404 if unknown/retired/outside the student's courses,
    403 `concept_locked` if a direct prerequisite isn't finished. Staff may open any concept."""
    graph = await _graph(scope)
    cid = graph.by_ref.get(f"{course_slug}/{concept_slug}")
    if cid is None:
        raise not_found()
    node = graph.nodes[cid]
    if scope.user.is_staff:
        return _Access(graph, node, None)

    reachable = {
        c for slug in await _student_course_slugs(scope, graph) for c, _ in graph.outline(slug)
    }
    if cid not in reachable:
        raise not_found()
    direct = graph.prereqs.get(cid, [])
    progress = await _progress(scope, [cid, *direct])
    finished = _finished_map(progress)
    if lesson_status(cid, finished, graph.prereqs) == "locked":
        raise concept_locked(
            [
                LockedPrereq(
                    id=graph.nodes[p].ref,
                    title=graph.nodes[p].title,
                    status=lesson_status(p, finished, graph.prereqs),
                )
                for p in direct
                if finished.get(p) is None
            ]
        )
    return _Access(graph, node, progress.get(cid))


@dataclass
class _LessonContent:
    concept: Concept
    kps: list[KnowledgePoint]
    check: Item | None

    @property
    def steps(self) -> list[str]:
        return lesson_steps((kp.slug for kp in self.kps), has_check=self.check is not None)

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
    return _LessonContent(concept, list(kps), check)


def _shown_options(scope: OrgScope, item: Item) -> list[OptionPublic]:
    public = ItemPublic.from_row(item)
    options = list(public.options or [])
    if scope.user.is_staff or not public.shuffle:
        return options
    by_id = {o.id: o for o in options}
    return [by_id[i] for i in shuffled_order(list(by_id), scope.user.id, item.id)]


async def _result(
    scope: OrgScope,
    item: Item,
    chosen: str,
    misconception_id: uuid.UUID | None,
    correct: bool | None = None,
) -> CheckResult:
    """`correct` is the stored grade for an existing attempt (else graded against the key now)."""
    title = None
    if misconception_id is not None:
        title = await scope.session.scalar(
            select(Misconception.title).where(Misconception.id == misconception_id)
        )
    return CheckResult(
        correct=chosen == item.answer.get("correct") if correct is None else correct,
        chosen=chosen,
        correct_option=str(item.answer.get("correct")),
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
            options=_shown_options(scope, content.check),
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
    return Lesson(
        id=access.node.ref,
        title=content.concept.title,
        summary=content.concept.summary,
        asset_base=f"{ASSET_URL_PREFIX}{asset_path}/" if asset_path else "",
        intro_md=content.concept.intro_md,
        check=check,
        kps=[
            KpOut(slug=k.slug, title=k.title, worked_example_md=k.worked_example_md)
            for k in content.kps
        ],
        steps=content.steps,
        progress=_progress_out(access.progress),
        check_result=check_result,
        preview=scope.user.is_staff,
    )


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
    if step not in content.steps:
        raise ApiProblem(422, "invalid_step", "That step isn't part of this lesson.")
    row = await _touch_progress(scope, access.node.id, step)
    seconds = min(active_seconds, MAX_STEP_SECONDS)
    if seconds > 0:
        scope.new(
            StudyTime,
            student_id=scope.user.id,
            concept_id=access.node.id,
            activity=StudyActivity.learn,
            step=step,
            active_seconds=seconds,
        )
    row = await _maybe_finish(scope, row, content)
    out = _progress_out(row)
    await scope.session.commit()
    assert out is not None
    return out


async def submit_check(
    scope: OrgScope, course_slug: str, concept_slug: str, option_id: str, time_taken_ms: int
) -> CheckSubmitted:
    access = await _access(scope, course_slug, concept_slug)
    content = await _content(scope, access.node.id)
    item = content.check
    if item is None:
        raise not_found()
    shown = _shown_options(scope, item)
    if option_id not in {o.id for o in shown}:
        raise ApiProblem(422, "invalid_option", "That isn't one of the options.")

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
        insert(Attempt)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            item_id=item.id,
            item_version=item.version,
            context=AttemptContext.learn,
            seed=None,
            response={"option": option_id, "order": [o.id for o in shown]},
            correct=option_id == item.answer.get("correct"),
            misconception_id=misconception_id,
            time_taken_ms=max(0, min(time_taken_ms, MAX_CHECK_MS)),
            hints_used=0,
        )
        .on_conflict_do_nothing(
            index_elements=[Attempt.student_id, Attempt.item_id],
            index_where=Attempt.context == AttemptContext.learn,
        )
        .returning(Attempt.id)
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
