"""Concept statuses and the knowledge frontier (spec 005).

Per student and concept: `learned` / `in_progress` are stored (`concept_state`); `ready` (no row,
every direct prerequisite learned) and `locked` are computed. A concept is learned when every active
KP is passed. KP state, reopening and remediations come from a fixed number of queries whatever
the number of concepts (no N+1). Used by the outline, home, lesson and KP services.
"""

import logging
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.grading import QUICK_TYPES
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
    SessionKind,
    SessionStatus,
)
from app.models.content import ItemKind
from app.services import kp_flow

log = logging.getLogger(__name__)

Status = Literal["learned", "in_progress", "ready", "locked"]


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
    gradable: bool  # has at least one numeric/expression/mcq question
    status: KpStatus = KpStatus.not_started
    fail_count: int = 0
    reopen_at: datetime | None = None
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

    def status(self, concept: uuid.UUID) -> Status:
        view = self.views.get(concept)
        return view.status if view is not None else "locked"


def open_remediations(scope: OrgScope) -> Select[Remediation]:
    """The student's unresolved remediations that can still block a KP. One on retired content
    can never resolve, so it doesn't count."""
    return (
        scope.select(Remediation)
        .join(Concept, Concept.id == Remediation.prereq_concept_id)
        .join(Chapter, Chapter.id == Concept.chapter_id)
        .join(Course, Course.id == Concept.course_id)
        .where(
            Remediation.student_id == scope.user.id,
            Remediation.state != RemediationState.resolved,
            Concept.retired_at.is_(None),
            Chapter.retired_at.is_(None),
            Course.retired_at.is_(None),
        )
    )


async def active_kps(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> list[KpView]:
    """Active KPs of these concepts in position order, with whether each has gradable questions."""
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
    gradable = set(
        (
            await scope.session.scalars(
                select(Item.kp_id)
                .where(
                    Item.kp_id.in_(kp_ids),
                    Item.kind == ItemKind.kp_question,
                    Item.type.in_(QUICK_TYPES),
                    Item.retired_at.is_(None),
                )
                .distinct()
            )
        ).all()
    )
    out = []
    for kp_id, concept_id, slug, title in rows:
        if kp_id not in gradable:
            log.warning("KP %s has no gradable questions; treating it as passed", kp_id)
        out.append(KpView(kp_id, concept_id, slug, title, kp_id in gradable))
    return out


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
    stored = {
        cid: status
        for cid, status in (
            await scope.session.execute(
                scope.select(ConceptState)
                .with_only_columns(ConceptState.concept_id, ConceptState.status)
                .where(ConceptState.student_id == student)
            )
        ).all()
    }
    kps = await active_kps(scope, concept_ids)
    kp_ids = [kp.id for kp in kps]
    progress = {
        row.kp_id: row
        for row in (
            await scope.session.scalars(
                scope.select(KpProgress).where(
                    KpProgress.student_id == student, KpProgress.kp_id.in_(kp_ids)
                )
            )
        ).all()
    }
    remediations = [
        RemediationView(r.id, r.kp_id, r.prereq_concept_id, r.state)
        for r in (
            await scope.session.scalars(open_remediations(scope).order_by(Remediation.created_at))
        ).all()
    ]
    by_kp: dict[uuid.UUID, list[RemediationView]] = {}
    for r in remediations:
        by_kp.setdefault(r.kp_id, []).append(r)

    failed = [p for p in progress.values() if p.status == KpStatus.failed]
    passed_kp_by_concept: dict[uuid.UUID, datetime] = {}
    last_review_pass: datetime | None = None
    if failed:
        passed_kp_by_concept, last_review_pass = await _passes(scope)

    now = datetime.now(UTC)
    kp_concept = {kp.id: kp.concept_id for kp in kps}
    for kp in kps:
        row = progress.get(kp.id)
        kp.remediations = by_kp.get(kp.id, [])
        if row is None:
            continue
        kp.status, kp.fail_count, kp.reopen_at = row.status, row.fail_count, row.reopen_at
        if row.status == KpStatus.failed:
            since = row.failed_at or now
            kp.open = kp_flow.is_open(
                failed=True,
                reopen_at=row.reopen_at,
                unresolved_remediations=len(kp.remediations),
                passed_other_concept_since_fail=any(
                    c != kp.concept_id and when > since for c, when in passed_kp_by_concept.items()
                ),
                passed_review_since_fail=last_review_pass is not None and last_review_pass > since,
                now=now,
            )

    kps_by_concept: dict[uuid.UUID, list[KpView]] = {}
    for kp in kps:
        kps_by_concept.setdefault(kp.concept_id, []).append(kp)

    if promote:
        for cid in concept_ids:
            ckps = kps_by_concept.get(cid, [])
            if (
                stored.get(cid) == ConceptStatus.in_progress
                and ckps
                and all(k.passed for k in ckps)
            ):
                await mark_learned(scope, cid)
                stored[cid] = ConceptStatus.learned

    views = {
        cid: ConceptView(cid, concept_status(cid, stored, prereqs), kps_by_concept.get(cid, []))
        for cid in concept_ids
    }
    return Frontier(stored, views, remediations, kp_concept)


async def _passes(scope: OrgScope) -> tuple[dict[uuid.UUID, datetime], datetime | None]:
    """(concept -> last passed KP session end, last passed remediation review end)."""
    student = scope.user.id
    kp_rows = (
        await scope.session.execute(
            scope.select(PracticeSession)
            .with_only_columns(KnowledgePoint.concept_id, func.max(PracticeSession.ended_at))
            .join(KnowledgePoint, KnowledgePoint.id == PracticeSession.kp_id)
            .where(
                PracticeSession.student_id == student,
                PracticeSession.kind == SessionKind.kp,
                PracticeSession.status == SessionStatus.passed,
            )
            .group_by(KnowledgePoint.concept_id)
        )
    ).all()
    review = await scope.session.scalar(
        scope.select(PracticeSession)
        .with_only_columns(func.max(PracticeSession.ended_at))
        .where(
            PracticeSession.student_id == student,
            PracticeSession.kind == SessionKind.remediation,
            PracticeSession.status == SessionStatus.passed,
        )
    )
    return {cid: when for cid, when in kp_rows if when is not None}, review


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


async def mark_learned(scope: OrgScope, concept_id: uuid.UUID) -> None:
    """Concept learned; remediations waiting on it being relearned resolve."""
    await close_review_sessions(scope, concept_id)
    await scope.session.execute(
        update(ConceptState)
        .where(
            ConceptState.org_id == scope.org_id,
            ConceptState.student_id == scope.user.id,
            ConceptState.concept_id == concept_id,
        )
        .values(
            status=ConceptStatus.learned,
            learned_at=func.now(),
            source=ConceptSource.lesson,
            updated_at=func.now(),
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
