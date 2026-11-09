"""Concept statuses and the knowledge frontier (spec 005).

Per student and concept: `learned` / `in_progress` are stored (`concept_state`); `ready` (no row,
every direct prerequisite learned) and `locked` are computed. A concept is learned when every active
KP is passed and (spec 006) it has no active practice item or the student passed a practice
attempt for it. KP state, reopening and remediations come from a fixed number of queries whatever
the number of concepts (no N+1). Used by the outline, home, lesson and KP services.
"""

import logging
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from fsrs import Rating
from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.grading import ALL_TYPES, QUICK_TYPES
from app.models import (
    Chapter,
    Concept,
    ConceptSource,
    ConceptState,
    ConceptStatus,
    Course,
    Item,
    KnowledgePoint,
    KpProgress,
    KpStatus,
    PracticeSession,
    Remediation,
    RemediationOutcome,
    RemediationState,
    ReviewSource,
    SessionKind,
    SessionStatus,
)
from app.models.content import ItemKind
from app.services import kp_flow

log = logging.getLogger(__name__)

Status = Literal["learned", "in_progress", "ready", "locked"]
PracticeStatus = Literal["none", "pending", "passed"]


def concept_status(
    concept: uuid.UUID,
    stored: Mapping[uuid.UUID, ConceptStatus],
    prereqs: Mapping[uuid.UUID, Collection[uuid.UUID]],
) -> Status:
    """Stored rows win (a started concept never re-locks); else ready iff every direct prereq is
    learned."""
    if concept in stored:
        return "learned" if stored[concept] == ConceptStatus.learned else "in_progress"
    learned = ConceptStatus.learned
    if all(stored.get(p) == learned for p in prereqs.get(concept, ())):
        return "ready"
    return "locked"


@dataclass
class RemediationView:
    id: uuid.UUID
    kp_id: uuid.UUID
    prereq_concept_id: uuid.UUID
    state: RemediationState


@dataclass
class KpView:
    id: uuid.UUID
    concept_id: uuid.UUID
    slug: str
    title: str
    gradable: bool  # has at least one active question (any type, spec 006)
    quick: bool = True  # has a numeric/expression/mcq question (brush-up reviews serve only those)
    status: KpStatus = KpStatus.not_started
    fail_count: int = 0
    reopen_at: datetime | None = None
    passed_at: datetime | None = None
    open: bool = True
    remediations: list[RemediationView] = field(default_factory=list)  # unresolved

    @property
    def passed(self) -> bool:
        # A KP with no gradable questions can't be practised (validator error); don't block on it.
        return self.status == KpStatus.passed or not self.gradable


@dataclass
class ConceptView:
    id: uuid.UUID
    status: Status
    kps: list[KpView]
    has_practice: bool = False  # an active practice item exists (spec 006)
    practice_passed: bool = False  # the student passed a practice attempt for it
    placed: bool = False  # spec 012: stored learned with source = diagnostic
    conditional: bool = False  # spec 012: placed on thin evidence, not reviewed yet

    @property
    def practice(self) -> PracticeStatus:
        """A concept learned before its practice existed (or before 006) counts as passed."""
        if not self.has_practice:
            return "none"
        return "passed" if self.practice_passed or self.status == "learned" else "pending"

    @property
    def practice_left(self) -> bool:
        """Every KP passed; Practice is the next part."""
        return self.next_kp is None and self.practice == "pending"

    @property
    def parts_passed(self) -> int:
        """A learned concept shows as complete (spec 012: placed concepts have no KP passes)."""
        if self.status == "learned":
            return self.parts_total
        return self.kps_passed + (self.practice == "passed")

    @property
    def parts_total(self) -> int:
        return self.kps_total + self.has_practice

    @property
    def kps_passed(self) -> int:
        return sum(kp.passed for kp in self.kps)

    @property
    def kps_total(self) -> int:
        return len(self.kps)

    @property
    def next_kp(self) -> KpView | None:
        return next((kp for kp in self.kps if not kp.passed), None)

    @property
    def waiting(self) -> KpView | None:
        """The next KP when it failed and isn't open yet."""
        kp = self.next_kp
        if self.status == "in_progress" and kp is not None and not kp.open:
            return kp
        return None

    @property
    def brush_up(self) -> bool:
        return any(
            r.state == RemediationState.review_due for kp in self.kps for r in kp.remediations
        )

    @property
    def brush_up_id(self) -> uuid.UUID | None:
        """The first due review for one of its KPs (the map's "Brush up first" button)."""
        due = (
            r.id
            for kp in self.kps
            for r in kp.remediations
            if r.state == RemediationState.review_due
        )
        return next(due, None)


@dataclass
class Frontier:
    """Everything the student-facing services need about one student's progress."""

    stored: dict[uuid.UUID, ConceptStatus]
    views: dict[uuid.UUID, ConceptView]
    remediations: list[RemediationView]  # all unresolved, oldest first
    kp_concept: dict[uuid.UUID, uuid.UUID]  # kp id -> concept id, for the loaded KPs
    learned_at: dict[uuid.UUID, datetime | None] = field(default_factory=dict)  # stored rows
    practice_passed_at: dict[uuid.UUID, datetime] = field(default_factory=dict)  # last pass
    source: dict[uuid.UUID, ConceptSource] = field(default_factory=dict)  # stored rows
    conditional: set[uuid.UUID] = field(default_factory=set)  # spec 012

    def status(self, concept: uuid.UUID) -> Status:
        view = self.views.get(concept)
        return view.status if view is not None else "locked"


def open_remediations(
    scope: OrgScope, student_ids: Collection[uuid.UUID] | None = None
) -> Select[Remediation]:
    """The student's (or these students') unresolved remediations that can still block a KP. One
    on retired content can never resolve, so it doesn't count."""
    students = [scope.user.id] if student_ids is None else list(student_ids)
    return (
        scope.select(Remediation)
        .join(Concept, Concept.id == Remediation.prereq_concept_id)
        .join(Chapter, Chapter.id == Concept.chapter_id)
        .join(Course, Course.id == Concept.course_id)
        .where(
            Remediation.student_id.in_(students),
            Remediation.state != RemediationState.resolved,
            Concept.retired_at.is_(None),
            Chapter.retired_at.is_(None),
            Course.retired_at.is_(None),
        )
    )


async def active_kps(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> list[KpView]:
    """Active KPs of these concepts in position order, with whether each has questions (and
    quick-check questions for reviews)."""
    if not concept_ids:
        return []
    rows = (
        await scope.session.execute(
            select(
                KnowledgePoint.id,
                KnowledgePoint.concept_id,
                KnowledgePoint.slug,
                KnowledgePoint.title,
            )
            .where(KnowledgePoint.concept_id.in_(concept_ids), KnowledgePoint.retired_at.is_(None))
            .order_by(KnowledgePoint.concept_id, KnowledgePoint.position)
        )
    ).all()
    kp_ids = [r[0] for r in rows]
    types: dict[uuid.UUID, set[str]] = {}
    for kp_id, item_type in (
        await scope.session.execute(
            select(Item.kp_id, Item.type)
            .where(
                Item.kp_id.in_(kp_ids),
                Item.kind == ItemKind.kp_question,
                Item.type.in_(ALL_TYPES),
                Item.retired_at.is_(None),
            )
            .distinct()
        )
    ).all():
        if kp_id is not None:
            types.setdefault(kp_id, set()).add(item_type.value)
    out = []
    for kp_id, concept_id, slug, title in rows:
        kinds = types.get(kp_id, set())
        if not kinds:
            log.warning("KP %s has no questions; treating it as passed", kp_id)
        out.append(
            KpView(kp_id, concept_id, slug, title, bool(kinds), quick=bool(kinds & QUICK_TYPES))
        )
    return out


async def practice_concepts(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """The concepts among `concept_ids` that have an active practice item (spec 006)."""
    if not concept_ids:
        return set()
    rows = await scope.session.scalars(
        select(Item.concept_id)
        .where(
            Item.concept_id.in_(concept_ids),
            Item.kind == ItemKind.practice,
            Item.retired_at.is_(None),
        )
        .distinct()
    )
    return set(rows.all())


async def _practice_passed(
    scope: OrgScope, student_ids: Collection[uuid.UUID], concept_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, dict[uuid.UUID, datetime]]:
    """student -> concept -> the last passed practice session's end."""
    out: dict[uuid.UUID, dict[uuid.UUID, datetime]] = {}
    if not concept_ids or not student_ids:
        return out
    rows = await scope.session.execute(
        scope.select(PracticeSession)
        .with_only_columns(
            PracticeSession.student_id,
            PracticeSession.concept_id,
            func.max(PracticeSession.ended_at),
        )
        .where(
            PracticeSession.student_id.in_(student_ids),
            PracticeSession.kind == SessionKind.practice,
            PracticeSession.status == SessionStatus.passed,
            PracticeSession.concept_id.in_(concept_ids),
        )
        .group_by(PracticeSession.student_id, PracticeSession.concept_id)
    )
    for sid, cid, when in rows.all():
        if cid is not None:
            out.setdefault(sid, {})[cid] = when or datetime.min.replace(tzinfo=UTC)
    return out


def complete(view: "ConceptView") -> bool:
    """Every active KP passed and the practice (if any) passed: the concept is learned."""
    return view.next_kp is None and view.practice != "pending"


@dataclass
class Content:
    """The student-independent part of a frontier: active KPs and which concepts have practice."""

    concept_ids: list[uuid.UUID]
    kps: list[KpView]  # templates; `build` copies them per student
    with_practice: set[uuid.UUID]


@dataclass
class StudentRows:
    """One student's stored learning state, as read by `fetch`."""

    stored: dict[uuid.UUID, ConceptStatus] = field(default_factory=dict)
    learned_at: dict[uuid.UUID, datetime | None] = field(default_factory=dict)
    source: dict[uuid.UUID, ConceptSource] = field(default_factory=dict)
    conditional: set[uuid.UUID] = field(default_factory=set)
    progress: dict[uuid.UUID, KpProgress] = field(default_factory=dict)
    remediations: list[RemediationView] = field(default_factory=list)  # oldest first
    kp_passes: dict[uuid.UUID, datetime] = field(default_factory=dict)  # concept -> last KP pass
    last_review_pass: datetime | None = None
    practice_passed: dict[uuid.UUID, datetime] = field(default_factory=dict)


async def load_content(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> Content:
    kps = await active_kps(scope, concept_ids)
    return Content(list(concept_ids), kps, await practice_concepts(scope, concept_ids))


async def fetch(
    scope: OrgScope,
    content: Content,
    student_ids: Sequence[uuid.UUID],
    *,
    passes_if_needed: bool = False,
) -> dict[uuid.UUID, StudentRows]:
    """Every listed student's rows in a fixed number of queries (no per-student loop).

    With `passes_if_needed` the pass times (only used to reopen failed KPs) are read only when
    some KP has failed: the single-student path keeps its old query count."""
    rows = {sid: StudentRows() for sid in student_ids}
    if not student_ids:
        return rows
    for sid, cid, status, learned_at, source, conditional in (
        await scope.session.execute(
            scope.select(ConceptState)
            .with_only_columns(
                ConceptState.student_id,
                ConceptState.concept_id,
                ConceptState.status,
                ConceptState.learned_at,
                ConceptState.source,
                ConceptState.conditional,
            )
            .where(ConceptState.student_id.in_(student_ids))
        )
    ).all():
        rows[sid].stored[cid] = status
        rows[sid].learned_at[cid] = learned_at
        rows[sid].source[cid] = source
        if conditional:
            rows[sid].conditional.add(cid)
    kp_ids = [kp.id for kp in content.kps]
    if kp_ids:
        for p in (
            await scope.session.scalars(
                scope.select(KpProgress).where(
                    KpProgress.student_id.in_(student_ids), KpProgress.kp_id.in_(kp_ids)
                )
            )
        ).all():
            rows[p.student_id].progress[p.kp_id] = p
    for r in (
        await scope.session.scalars(
            open_remediations(scope, student_ids).order_by(Remediation.created_at)
        )
    ).all():
        rows[r.student_id].remediations.append(
            RemediationView(r.id, r.kp_id, r.prereq_concept_id, r.state)
        )
    any_failed = any(
        p.status == KpStatus.failed for row in rows.values() for p in row.progress.values()
    )
    if any_failed or not passes_if_needed:
        kp_passes, review_passes = await _passes(scope, student_ids)
        for sid, by_concept in kp_passes.items():
            rows[sid].kp_passes = by_concept
        for sid, when in review_passes.items():
            rows[sid].last_review_pass = when
    for sid, by_concept in (
        await _practice_passed(scope, student_ids, content.with_practice)
    ).items():
        rows[sid].practice_passed = by_concept
    return rows


def build(
    content: Content,
    rows: StudentRows,
    prereqs: Mapping[uuid.UUID, Sequence[uuid.UUID]],
    now: datetime,
) -> Frontier:
    """One student's frontier from their rows (pure; never writes)."""
    by_kp: dict[uuid.UUID, list[RemediationView]] = {}
    for r in rows.remediations:
        by_kp.setdefault(r.kp_id, []).append(r)
    kps = [replace(kp, remediations=by_kp.get(kp.id, [])) for kp in content.kps]
    for kp in kps:
        row = rows.progress.get(kp.id)
        if row is None:
            continue
        kp.status, kp.fail_count, kp.reopen_at = row.status, row.fail_count, row.reopen_at
        kp.passed_at = row.passed_at
        if row.status == KpStatus.failed:
            since = row.failed_at or now
            kp.open = kp_flow.is_open(
                failed=True,
                reopen_at=row.reopen_at,
                unresolved_remediations=len(kp.remediations),
                passed_other_concept_since_fail=any(
                    c != kp.concept_id and when > since for c, when in rows.kp_passes.items()
                ),
                passed_review_since_fail=(
                    rows.last_review_pass is not None and rows.last_review_pass > since
                ),
                now=now,
            )
    kps_by_concept: dict[uuid.UUID, list[KpView]] = {}
    for kp in kps:
        kps_by_concept.setdefault(kp.concept_id, []).append(kp)
    stored = dict(rows.stored)
    views = {
        cid: ConceptView(
            cid,
            concept_status(cid, stored, prereqs),
            kps_by_concept.get(cid, []),
            has_practice=cid in content.with_practice,
            practice_passed=cid in rows.practice_passed,
            placed=(
                stored.get(cid) == ConceptStatus.learned
                and rows.source.get(cid) == ConceptSource.diagnostic
            ),
            conditional=stored.get(cid) == ConceptStatus.learned and cid in rows.conditional,
        )
        for cid in content.concept_ids
    }
    return Frontier(
        stored,
        views,
        list(rows.remediations),
        {kp.id: kp.concept_id for kp in kps},
        learned_at=dict(rows.learned_at),
        practice_passed_at=dict(rows.practice_passed),
        source=dict(rows.source),
        conditional=set(rows.conditional),
    )


def promotable(front: Frontier) -> list[uuid.UUID]:
    """In-progress concepts whose active KPs and practice are all complete (learned on read)."""
    return [
        cid
        for cid, v in front.views.items()
        if front.stored.get(cid) == ConceptStatus.in_progress and v.kps and complete(v)
    ]


def _restatus(front: Frontier, prereqs: Mapping[uuid.UUID, Sequence[uuid.UUID]]) -> None:
    for cid, v in front.views.items():
        v.status = concept_status(cid, front.stored, prereqs)


def effective(front: Frontier, prereqs: Mapping[uuid.UUID, Sequence[uuid.UUID]]) -> Frontier:
    """Teacher reads (spec 010): complete-but-not-promoted concepts count as learned, for their
    own status and for their dependants' ready/locked. Changes `front` in memory only."""
    for cid in promotable(front):
        front.stored[cid] = ConceptStatus.learned
    _restatus(front, prereqs)
    return front


def done_at(front: Frontier, concept: uuid.UUID) -> datetime | None:
    """When a learned concept was learned: `learned_at`, or for a complete-but-not-promoted one
    the latest KP pass / practice pass."""
    stored = front.learned_at.get(concept)
    if stored is not None:
        return stored
    view = front.views.get(concept)
    times = [kp.passed_at for kp in view.kps if kp.passed_at] if view else []
    if concept in front.practice_passed_at:
        times.append(front.practice_passed_at[concept])
    return max(times, default=None)


async def load(
    scope: OrgScope,
    concept_ids: Collection[uuid.UUID],
    prereqs: Mapping[uuid.UUID, Sequence[uuid.UUID]],
    *,
    promote: bool = True,
) -> Frontier:
    """The student's frontier for `concept_ids` (statuses need the prereqs' states too).

    With `promote`, an in-progress concept whose active KPs are all passed (e.g. a KP was retired)
    is marked learned here; the caller commits."""
    student = scope.user.id
    content = await load_content(scope, concept_ids)
    rows = (await fetch(scope, content, [student], passes_if_needed=True))[student]
    front = build(content, rows, prereqs, datetime.now(UTC))
    if promote:
        for cid in promotable(front):
            await mark_learned(scope, cid)
            front.stored[cid] = ConceptStatus.learned
        _restatus(front, prereqs)
    return front


async def class_states(
    scope: OrgScope,
    student_ids: Sequence[uuid.UUID],
    concept_ids: Collection[uuid.UUID],
    prereqs: Mapping[uuid.UUID, Sequence[uuid.UUID]],
) -> dict[uuid.UUID, Frontier]:
    """Read-only frontiers for many students (teacher dashboard, spec 010), in a fixed number of
    queries. Complete-but-not-promoted concepts count as learned (`effective`); nothing is
    written."""
    content = await load_content(scope, concept_ids)
    rows = await fetch(scope, content, student_ids)
    now = datetime.now(UTC)
    return {sid: effective(build(content, rows[sid], prereqs, now), prereqs) for sid in student_ids}


async def _passes(
    scope: OrgScope, student_ids: Collection[uuid.UUID]
) -> tuple[dict[uuid.UUID, dict[uuid.UUID, datetime]], dict[uuid.UUID, datetime]]:
    """(student -> concept -> last passed KP session end, student -> last passed remediation
    review end)."""
    kp_rows = (
        await scope.session.execute(
            scope.select(PracticeSession)
            .with_only_columns(
                PracticeSession.student_id,
                KnowledgePoint.concept_id,
                func.max(PracticeSession.ended_at),
            )
            .join(KnowledgePoint, KnowledgePoint.id == PracticeSession.kp_id)
            .where(
                PracticeSession.student_id.in_(student_ids),
                PracticeSession.kind == SessionKind.kp,
                PracticeSession.status == SessionStatus.passed,
            )
            .group_by(PracticeSession.student_id, KnowledgePoint.concept_id)
        )
    ).all()
    kp: dict[uuid.UUID, dict[uuid.UUID, datetime]] = {}
    for sid, cid, when in kp_rows:
        if when is not None:
            kp.setdefault(sid, {})[cid] = when
    review_rows = (
        await scope.session.execute(
            scope.select(PracticeSession)
            .with_only_columns(PracticeSession.student_id, func.max(PracticeSession.ended_at))
            .where(
                PracticeSession.student_id.in_(student_ids),
                PracticeSession.kind == SessionKind.remediation,
                PracticeSession.status == SessionStatus.passed,
            )
            .group_by(PracticeSession.student_id)
        )
    ).all()
    return kp, {sid: when for sid, when in review_rows if when is not None}


async def ensure_started(scope: OrgScope, concept_id: uuid.UUID) -> None:
    """The concept's `in_progress` row, created the first time the student opens the lesson."""
    await scope.session.execute(
        insert(ConceptState)
        .values(
            org_id=scope.org_id,
            student_id=scope.user.id,
            concept_id=concept_id,
            status=ConceptStatus.in_progress,
            source=ConceptSource.lesson,
        )
        .on_conflict_do_nothing(index_elements=[ConceptState.student_id, ConceptState.concept_id])
    )


async def close_review_sessions(scope: OrgScope, concept_id: uuid.UUID) -> None:
    """End the active review sessions of open remediations on this prerequisite (its state is
    about to change, so a review left open in another tab must not be answerable)."""
    open_ids = (
        scope.select(Remediation)
        .with_only_columns(Remediation.id)
        .where(
            Remediation.student_id == scope.user.id,
            Remediation.prereq_concept_id == concept_id,
            Remediation.state != RemediationState.resolved,
        )
    )
    await scope.session.execute(
        update(PracticeSession)
        .where(
            PracticeSession.org_id == scope.org_id,
            PracticeSession.student_id == scope.user.id,
            PracticeSession.remediation_id.in_(open_ids),
            PracticeSession.status == SessionStatus.active,
        )
        .values(status=SessionStatus.failed, ended_at=func.now())
        .execution_options(synchronize_session="fetch")
    )


async def mark_learned(
    scope: OrgScope,
    concept_id: uuid.UUID,
    *,
    source: ConceptSource = ConceptSource.lesson,
    conditional: bool = False,
) -> None:
    """Concept learned; remediations waiting on it being relearned resolve. Spec 007: its review
    card is created (or, after a relearn, reviewed `Good` again). Spec 012: an upsert (a placed
    concept usually has no row yet); a diagnostic places with `source = diagnostic`, and a
    conditional placement starts its card at `Hard`."""
    await close_review_sessions(scope, concept_id)
    values = {
        "status": ConceptStatus.learned,
        "learned_at": func.now(),
        "source": source,
        "conditional": conditional,
        "updated_at": func.now(),
    }
    await scope.session.execute(
        insert(ConceptState)
        .values(org_id=scope.org_id, student_id=scope.user.id, concept_id=concept_id, **values)
        .on_conflict_do_update(
            index_elements=[ConceptState.student_id, ConceptState.concept_id], set_=values
        )
        .execution_options(synchronize_session=False)
    )
    await scope.session.execute(
        update(Remediation)
        .where(
            Remediation.org_id == scope.org_id,
            Remediation.student_id == scope.user.id,
            Remediation.prereq_concept_id == concept_id,
            Remediation.state == RemediationState.relearn,
        )
        .values(
            state=RemediationState.resolved,
            outcome=RemediationOutcome.relearned,
            resolved_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    from app.services import srs

    placed = source == ConceptSource.diagnostic
    await srs.on_learned(
        scope,
        concept_id,
        rating=Rating.Hard if conditional else Rating.Good,
        source=ReviewSource.placed if placed else ReviewSource.learned,
    )
