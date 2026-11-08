"""Teacher dashboard (spec 010): read-only class analytics.

Pure rules first (bands, heat states, ranking, at-risk rules, window bounds), then the endpoint
services. Every endpoint runs a fixed number of queries whatever the class size: per-student data
is read with `student_id IN (...)` and grouped in SQL or Python, never in a per-student loop.
Nothing here writes learning state, and nothing reads `item.answer` into a response (answers are
only used server side to know which items offer a misconception).
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, exists, func, literal, or_, select

from app.api.deps import OrgScope
from app.core.errors import not_found
from app.models import (
    Attempt,
    Chapter,
    Concept,
    Course,
    Item,
    KnowledgePoint,
    KpStatus,
    Misconception,
    PracticeSession,
    QuizItem,
    Remediation,
    RemediationState,
    ReviewCard,
    SessionKind,
    SessionStatus,
    StudyActivity,
    StudyTime,
    TutorKind,
    TutorMessage,
    TutorRole,
    TutorSession,
    TutorStatus,
    XpEvent,
)
from app.models.content import ItemKind
from app.schemas.assignments import AssignmentSummary, StudentAssignmentRow
from app.schemas.content import CourseRef
from app.schemas.dashboard import (
    ActivityRow,
    AtRiskReason,
    AtRiskRow,
    Band,
    ClassOverview,
    ConceptDetail,
    ConceptStat,
    ConceptStudents,
    FlaggedThread,
    HeatCell,
    HeatChapter,
    HeatConcept,
    Heatmap,
    HeatRow,
    HeatState,
    HintStudent,
    HintUse,
    ItemStat,
    KpBrief,
    KpStat,
    Memory,
    MisconceptionItem,
    MisconceptionStat,
    PracticeShare,
    StuckStudent,
    StudentDetail,
    StudentRef,
    StudentStats,
    TeacherOutline,
    TeacherOutlineChapter,
    TeacherOutlineConcept,
    ThreadDetail,
    ThreadMessage,
    ThreadRow,
    Window,
)
from app.schemas.learn import Waiting
from app.schemas.quiz import LastQuizOut
from app.services import assignments, class_view, frontier, quiz, srs, xp
from app.services.class_view import ClassCtx

# At-risk thresholds (ARCHITECTURE decision 15); tune in the pilot.
AT_RISK_DAYS = 7
AT_RISK_KP_FAIL_RATE = 0.10
AT_RISK_MIN_KP_TRIES = 5
AT_RISK_XP_PER_MIN = 0.5
AT_RISK_MIN_ACTIVE_MINUTES = 30
AT_RISK_WEAK_CARDS = 2
AT_RISK_INACTIVE_DAYS = 7

STRONG_R = 0.9
WEAK_R = 0.7
MIN_STUDENTS_RANKED = 3
MIN_OFFERED = 3
TOP = 5
ACTIVITY_PAGE = 50
HINT_TOP = 3
HINT_MIN_QUESTIONS = 5

HIDDEN_FROM_TEACHER = (TutorStatus.pending, TutorStatus.late)
CHAT_COUNTED = (TutorStatus.pending, TutorStatus.ok)


# --- pure rules -----------------------------------------------------------------------------------


def window_start(window: Window, now: datetime) -> datetime | None:
    """`7d` = today (IST) and the 6 days before, from IST midnight; `30d` likewise; `all` = None."""
    if window == "all":
        return None
    days = 7 if window == "7d" else 30
    return srs.ist_midnight(srs.ist_day(now) - timedelta(days=days - 1))


def memory_band(r: float | None) -> Band:
    if r is None:
        return "none"
    if r >= STRONG_R:
        return "strong"
    if r >= WEAK_R:
        return "fading"
    return "weak"


def heat_state(view: frontier.ConceptView | None) -> HeatState:
    if view is None:
        return "locked"
    if view.status == "in_progress":
        return "stuck" if stuck_reason(view) is not None else "in_progress"
    return view.status


@dataclass(frozen=True)
class Stuck:
    kind: str  # review_due | relearn | waiting
    prereq: uuid.UUID | None


def stuck_reason(view: frontier.ConceptView) -> Stuck | None:
    """An open remediation beats a waiting KP."""
    if view.status != "in_progress":
        return None
    rems = [r for kp in view.kps for r in kp.remediations]
    if rems:
        due = next((r for r in rems if r.state == RemediationState.review_due), None)
        r = due or rems[0]
        return Stuck(r.state.value, r.prereq_concept_id)
    if any(kp.status == KpStatus.failed and not kp.open for kp in view.kps):
        return Stuck("waiting", None)
    return None


def stuck_label(stuck: Stuck, title: str | None) -> str:
    if stuck.kind == "review_due":
        return f"Brushing up {title}"
    if stuck.kind == "relearn":
        return f"Relearning {title}"
    return "Waiting to retry"


def rank_weakest(stats: Sequence[ConceptStat], order: Mapping[str, int]) -> list[ConceptStat]:
    """Qualified concepts by fail rate desc, then stuck now desc, then course order; the
    unqualified ones last in course order."""
    ranked = sorted(
        (s for s in stats if s.fail_rate is not None),
        key=lambda s: (-(s.fail_rate or 0), -s.stuck_now, order.get(s.concept, 0)),
    )
    rest = sorted((s for s in stats if s.fail_rate is None), key=lambda s: order.get(s.concept, 0))
    return ranked + rest


@dataclass
class RiskInputs:
    kp_ended: int = 0
    kp_failed: int = 0
    negative_xp: int = 0
    net_xp: int = 0
    active_seconds: int = 0
    weak_prereqs: list[str] = field(default_factory=list)  # titles of weak prerequisite cards
    overdue: list[tuple[str, date]] = field(default_factory=list)
    active_recently: bool = True
    enrolled_days: int = 0


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def at_risk_rules(r: RiskInputs) -> list[AtRiskReason]:
    out: list[AtRiskReason] = []
    if r.kp_ended >= AT_RISK_MIN_KP_TRIES and r.kp_failed / r.kp_ended > AT_RISK_KP_FAIL_RATE:
        out.append(
            AtRiskReason(
                code="kp_fail_rate", detail=f"Failed {r.kp_failed} of {r.kp_ended} KP tries"
            )
        )
    if r.negative_xp > 0:
        out.append(
            AtRiskReason(code="negative_xp", detail=f"Lost XP for rushing ({r.negative_xp}\u00d7)")
        )
    minutes = r.active_seconds / 60
    if minutes >= AT_RISK_MIN_ACTIVE_MINUTES and r.net_xp / minutes < AT_RISK_XP_PER_MIN:
        out.append(
            AtRiskReason(
                code="low_xp_rate", detail=f"{r.net_xp / minutes:.1f} XP per active minute"
            )
        )
    if len(r.weak_prereqs) >= AT_RISK_WEAK_CARDS:
        out.append(
            AtRiskReason(code="falling_memory", detail="Weak memory: " + ", ".join(r.weak_prereqs))
        )
    for title, due in r.overdue:
        out.append(
            AtRiskReason(code="overdue_assignment", detail=f"Overdue: {title} (due {_day(due)})")
        )
    if not r.active_recently and r.enrolled_days >= AT_RISK_INACTIVE_DAYS:
        out.append(
            AtRiskReason(code="inactive", detail=f"No activity for {AT_RISK_INACTIVE_DAYS} days")
        )
    return out


def per_10(hints: int, answered: int) -> float | None:
    return None if answered == 0 else round(hints * 10 / answered, 1)


def tagged_misconceptions(answer: Mapping[str, Any]) -> set[str]:
    """Misconception slugs an item's answer spec offers (MCQ options and multistep MCQ steps)."""
    out = {m for m in (answer.get("misconceptions") or {}).values() if m}
    spec = answer.get("spec") or {}
    for step in spec.get("steps") or []:
        mcq = (step.get("answer") or {}).get("mcq") or {}
        out.update(o["misconception"] for o in mcq.get("options") or [] if o.get("misconception"))
    for o in spec.get("options") or []:
        if o.get("misconception"):
            out.add(o["misconception"])
    return out


def option_text(public: Mapping[str, Any], option: str | None, step: int) -> str | None:
    if option is None:
        return None
    options = public.get("options")
    if options is None:
        steps = public.get("steps") or []
        options = steps[step].get("options") if 0 <= step < len(steps) else None
    for o in options or []:
        if o.get("id") == option:
            return str(o.get("text"))
    return None


# --- queries (each one statement, whatever the number of students) --------------------------------


@dataclass
class ItemRow:
    id: uuid.UUID
    concept_id: uuid.UUID
    kp_id: uuid.UUID | None
    kind: ItemKind
    type: str
    position: int
    public: dict[str, Any]
    tags: set[str]


async def _items(scope: OrgScope, concepts: Sequence[uuid.UUID]) -> dict[uuid.UUID, ItemRow]:
    if not concepts:
        return {}
    rows = await scope.session.execute(
        select(
            Item.id,
            Item.concept_id,
            Item.kp_id,
            Item.kind,
            Item.type,
            Item.position,
            Item.public,
            Item.answer,
        ).where(Item.concept_id.in_(concepts), Item.retired_at.is_(None))
    )
    return {
        r[0]: ItemRow(r[0], r[1], r[2], r[3], r[4].value, r[5], r[6], tagged_misconceptions(r[7]))
        for r in rows.all()
    }


@dataclass
class QStat:
    """Questions answered by one student on one item (multistep counts once)."""

    answered: int = 0
    correct: int = 0
    hints: int = 0
    ms: int = 0


async def _questions(
    scope: OrgScope,
    sids: Sequence[uuid.UUID],
    concepts: Sequence[uuid.UUID],
    since: datetime | None,
) -> dict[tuple[uuid.UUID, uuid.UUID], QStat]:
    """(student, item) -> answered / correct / hints / time, every context."""
    if not sids or not concepts:
        return {}
    inner = (
        scope.select(Attempt)
        .with_only_columns(
            Attempt.student_id.label("sid"),
            Attempt.item_id.label("item_id"),
            func.bool_and(Attempt.correct).label("ok"),
            func.sum(Attempt.hints_used).label("hints"),
            func.sum(Attempt.time_taken_ms).label("ms"),
        )
        .join(Item, Item.id == Attempt.item_id)
        .where(Attempt.student_id.in_(sids), Item.concept_id.in_(concepts))
        .group_by(Attempt.student_id, Attempt.item_id, Attempt.session_id, Attempt.position)
    )
    if since is not None:
        inner = inner.where(Attempt.created_at >= since)
    sub = inner.subquery()
    rows = await scope.session.execute(
        select(
            sub.c.sid,
            sub.c.item_id,
            func.count(),
            func.count().filter(sub.c.ok),
            func.coalesce(func.sum(sub.c.hints), 0),
            func.coalesce(func.sum(sub.c.ms), 0),
        ).group_by(sub.c.sid, sub.c.item_id)
    )
    return {(r[0], r[1]): QStat(int(r[2]), int(r[3]), int(r[4]), int(r[5])) for r in rows.all()}


async def _kp_tries(
    scope: OrgScope,
    sids: Sequence[uuid.UUID],
    concepts: Sequence[uuid.UUID],
    since: datetime | None,
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, bool, int]]:
    """(student, concept, kp, failed, count) of KP tries: kp sessions ended passed/failed with at
    least one attempt (side-effect closes are excluded)."""
    if not sids or not concepts:
        return []
    stmt = (
        scope.select(PracticeSession)
        .with_only_columns(
            PracticeSession.student_id,
            KnowledgePoint.concept_id,
            PracticeSession.kp_id,
            PracticeSession.status == SessionStatus.failed,
            func.count(),
        )
        .join(KnowledgePoint, KnowledgePoint.id == PracticeSession.kp_id)
        .where(
            PracticeSession.student_id.in_(sids),
            PracticeSession.kind == SessionKind.kp,
            PracticeSession.status.in_((SessionStatus.passed, SessionStatus.failed)),
            KnowledgePoint.concept_id.in_(concepts),
            exists().where(Attempt.session_id == PracticeSession.id),
        )
        .group_by(
            PracticeSession.student_id,
            KnowledgePoint.concept_id,
            PracticeSession.kp_id,
            PracticeSession.status,
        )
    )
    if since is not None:
        stmt = stmt.where(PracticeSession.ended_at >= since)
    return [
        (r[0], r[1], r[2], bool(r[3]), int(r[4]))
        for r in (await scope.session.execute(stmt)).all()
        if r[2] is not None
    ]


async def _study(
    scope: OrgScope,
    sids: Sequence[uuid.UUID],
    concepts: Sequence[uuid.UUID],
    since: datetime | None,
) -> dict[uuid.UUID, dict[StudyActivity, int]]:
    if not sids or not concepts:
        return {}
    stmt = (
        scope.select(StudyTime)
        .with_only_columns(
            StudyTime.student_id, StudyTime.activity, func.sum(StudyTime.active_seconds)
        )
        .where(StudyTime.student_id.in_(sids), StudyTime.concept_id.in_(concepts))
        .group_by(StudyTime.student_id, StudyTime.activity)
    )
    if since is not None:
        stmt = stmt.where(StudyTime.created_at >= since)
    out: dict[uuid.UUID, dict[StudyActivity, int]] = defaultdict(dict)
    for sid, activity, seconds in (await scope.session.execute(stmt)).all():
        out[sid][activity] = int(seconds or 0)
    return out


async def _chats(
    scope: OrgScope,
    sids: Sequence[uuid.UUID],
    concepts: Sequence[uuid.UUID],
    since: datetime | None,
) -> dict[uuid.UUID, int]:
    if not sids or not concepts:
        return {}
    stmt = (
        scope.select(TutorMessage)
        .with_only_columns(TutorMessage.student_id, func.count())
        .join(TutorSession, TutorSession.id == TutorMessage.tutor_session_id)
        .join(Item, Item.id == TutorSession.item_id)
        .where(TutorMessage.student_id.in_(sids), Item.concept_id.in_(concepts))
        .group_by(TutorMessage.student_id)
    )
    stmt = stmt.where(
        TutorMessage.role == TutorRole.student,
        TutorMessage.kind == TutorKind.chat,
        TutorMessage.status.in_(CHAT_COUNTED),
    )
    if since is not None:
        stmt = stmt.where(TutorMessage.created_at >= since)
    return {sid: int(n) for sid, n in (await scope.session.execute(stmt)).all()}


async def _flagged(
    scope: OrgScope,
    ctx: ClassCtx,
    since: datetime | None,
) -> list[FlaggedThread]:
    if not ctx.students or not ctx.concepts:
        return []
    first_flag = func.min(TutorMessage.created_at)
    stmt = (
        scope.select(TutorSession)
        .with_only_columns(TutorSession.id, TutorSession.student_id, Item.concept_id, first_flag)
        .join(TutorMessage, TutorMessage.tutor_session_id == TutorSession.id)
        .join(Item, Item.id == TutorSession.item_id)
        .where(
            TutorSession.student_id.in_(ctx.student_ids),
            Item.concept_id.in_(ctx.concepts),
            TutorMessage.flagged.is_(True),
        )
        .group_by(TutorSession.id, TutorSession.student_id, Item.concept_id)
        .order_by(first_flag.desc())
    )
    if since is not None:
        stmt = stmt.where(TutorMessage.created_at >= since)
    names = {s.id: s.display_name for s in ctx.students}
    return [
        FlaggedThread(
            thread_id=tid,
            student_id=sid,
            display_name=names[sid],
            concept=ctx.ref(cid),
            concept_title=ctx.title(cid),
            created_at=when,
        )
        for tid, sid, cid, when in (await scope.session.execute(stmt)).all()
    ]


async def _chosen(
    scope: OrgScope,
    sids: Sequence[uuid.UUID],
    concepts: Sequence[uuid.UUID],
    since: datetime | None,
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str | None, int]]:
    """(student, item, misconception, chosen option id, step) of attempts that picked a tagged
    distractor."""
    if not sids or not concepts:
        return []
    stmt = (
        scope.select(Attempt)
        .with_only_columns(
            Attempt.student_id,
            Attempt.item_id,
            Attempt.misconception_id,
            Attempt.response["option"].astext,
            Attempt.step,
        )
        .join(Item, Item.id == Attempt.item_id)
        .where(
            Attempt.student_id.in_(sids),
            Item.concept_id.in_(concepts),
            Attempt.misconception_id.is_not(None),
        )
    )
    if since is not None:
        stmt = stmt.where(Attempt.created_at >= since)
    return [
        (r[0], r[1], r[2], r[3], int(r[4]))
        for r in (await scope.session.execute(stmt)).all()
        if r[2] is not None
    ]


async def _misconception_rows(scope: OrgScope, ctx: ClassCtx) -> list[Misconception]:
    if ctx.course is None:
        return []
    rows = await scope.session.scalars(
        select(Misconception)
        .where(Misconception.course_id == ctx.course.id, Misconception.retired_at.is_(None))
        .order_by(Misconception.position)
    )
    return list(rows.all())


@dataclass(frozen=True)
class RemediationRow:
    student_id: uuid.UUID
    kp_id: uuid.UUID
    concept_id: uuid.UUID
    prereq_id: uuid.UUID
    state: RemediationState


async def _remediations_since(
    scope: OrgScope,
    sids: Sequence[uuid.UUID],
    concepts: Sequence[uuid.UUID],
    since: datetime | None,
) -> list[RemediationRow]:
    """Remediations created in the window (any state) on KPs of these concepts, oldest first.
    Ones whose prerequisite is retired are left out, like `frontier.open_remediations`."""
    if not sids or not concepts:
        return []
    stmt = (
        scope.select(Remediation)
        .with_only_columns(
            Remediation.student_id,
            Remediation.kp_id,
            KnowledgePoint.concept_id,
            Remediation.prereq_concept_id,
            Remediation.state,
        )
        .join(KnowledgePoint, KnowledgePoint.id == Remediation.kp_id)
        .join(Concept, Concept.id == Remediation.prereq_concept_id)
        .join(Chapter, Chapter.id == Concept.chapter_id)
        .join(Course, Course.id == Concept.course_id)
        .where(
            Remediation.student_id.in_(sids),
            KnowledgePoint.concept_id.in_(concepts),
            Concept.retired_at.is_(None),
            Chapter.retired_at.is_(None),
            Course.retired_at.is_(None),
        )
        .order_by(Remediation.created_at, Remediation.id)
    )
    if since is not None:
        stmt = stmt.where(Remediation.created_at >= since)
    return [RemediationRow(*r) for r in (await scope.session.execute(stmt)).all()]


@dataclass(frozen=True)
class KpInfo:
    id: uuid.UUID
    concept_id: uuid.UUID
    slug: str
    title: str
    retired: bool


async def kp_info(scope: OrgScope, kp_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, KpInfo]:
    """Titles and slugs of these KPs (content is global), in one query."""
    ids = list(set(kp_ids))
    if not ids:
        return {}
    rows = await scope.session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.concept_id,
            KnowledgePoint.slug,
            KnowledgePoint.title,
            KnowledgePoint.retired_at,
        ).where(KnowledgePoint.id.in_(ids))
    )
    return {r[0]: KpInfo(r[0], r[1], r[2], r[3], r[4] is not None) for r in rows.all()}


# --- assembled pieces -----------------------------------------------------------------------------


def _learned_pct(ctx: ClassCtx, cid: uuid.UUID) -> int:
    if not ctx.students:
        return 0
    n = sum(1 for s in ctx.students if _status(ctx, s.id, cid) == "learned")
    return round(100 * n / len(ctx.students))


def _view(ctx: ClassCtx, sid: uuid.UUID, cid: uuid.UUID) -> frontier.ConceptView | None:
    front = ctx.states.get(sid)
    return None if front is None else front.views.get(cid)


def _status(ctx: ClassCtx, sid: uuid.UUID, cid: uuid.UUID) -> HeatState:
    return heat_state(_view(ctx, sid, cid))


def _concept_stats(
    ctx: ClassCtx, tries: Iterable[tuple[uuid.UUID, uuid.UUID, uuid.UUID, bool, int]]
) -> list[ConceptStat]:
    ended: Counter[uuid.UUID] = Counter()
    failed: Counter[uuid.UUID] = Counter()
    students: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for sid, cid, _kp, is_failed, n in tries:
        ended[cid] += n
        failed[cid] += n if is_failed else 0
        students[cid].add(sid)
    out = []
    for cid in ctx.concepts:
        node = ctx.graph.nodes[cid]
        tried = len(students[cid])
        out.append(
            ConceptStat(
                concept=node.ref,
                title=node.title,
                chapter=ctx.graph.chapters[node.chapter_id].title,
                tries=ended[cid],
                students_tried=tried,
                fail_rate=(
                    round(failed[cid] / ended[cid], 3)
                    if tried >= MIN_STUDENTS_RANKED and ended[cid]
                    else None
                ),
                stuck_now=sum(1 for s in ctx.students if _status(ctx, s.id, cid) == "stuck"),
                learned_pct=_learned_pct(ctx, cid),
            )
        )
    return rank_weakest(out, {ctx.ref(c): i for i, c in enumerate(ctx.concepts)})


def _misconceptions(
    ctx: ClassCtx,
    miscs: Sequence[Misconception],
    items: Mapping[uuid.UUID, ItemRow],
    questions: Mapping[tuple[uuid.UUID, uuid.UUID], QStat],
    chosen: Sequence[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str | None, int]],
    *,
    only_items: set[uuid.UUID] | None = None,
) -> list[MisconceptionStat]:
    """Every misconception of the course with its counts; `only_items` limits it to those
    offered on these items (concept detail)."""
    answers_by_item: Counter[uuid.UUID] = Counter()
    for (_sid, iid), q in questions.items():
        answers_by_item[iid] += q.answered
    names = {s.id: s.display_name for s in ctx.students}
    out = []
    for m in miscs:
        offering = [i for i in items.values() if m.slug in i.tags]
        if only_items is not None and not any(i.id in only_items for i in offering):
            continue
        offered = sum(answers_by_item[i.id] for i in offering)
        picks = [c for c in chosen if c[2] == m.id and c[1] in items]
        by_concept: Counter[uuid.UUID] = Counter(items[c[1]].concept_id for c in picks)
        if not by_concept:
            by_concept = Counter(
                {i.concept_id: answers_by_item[i.id] for i in offering} if offering else {}
            )
        concept = (
            min(by_concept, key=lambda c: (-by_concept[c], ctx.order(c))) if by_concept else None
        )
        per_item: dict[tuple[uuid.UUID, str | None], set[uuid.UUID]] = defaultdict(set)
        for sid, iid, _m, option, step in picks:
            per_item[(iid, option_text(items[iid].public, option, step))].add(sid)
        out.append(
            MisconceptionStat(
                id=m.id,
                title=m.title,
                concept=None if concept is None else ctx.ref(concept),
                concept_title=None if concept is None else ctx.title(concept),
                chosen=len(picks),
                offered=offered,
                rate=round(len(picks) / offered, 3) if offered else None,
                students=len({p[0] for p in picks}),
                items=[
                    MisconceptionItem(
                        prompt=str(items[iid].public.get("prompt", "")),
                        chosen_text=text_,
                        student_names=sorted(names[s] for s in sids if s in names),
                    )
                    for (iid, text_), sids in per_item.items()
                ],
            )
        )
    return out


def _rank_misconceptions(
    rows: Sequence[MisconceptionStat], *, chosen_only: bool = False
) -> list[MisconceptionStat]:
    """Qualified (offered >= 3), by students desc then rate desc. The Overview's top 5 lists
    only ones somebody chose; "Show all" also lists offered ones nobody fell for."""
    qualified = [r for r in rows if r.offered >= MIN_OFFERED and (r.chosen > 0 or not chosen_only)]
    return sorted(qualified, key=lambda r: (-r.students, -(r.rate or 0), r.title))


def _hint_use(
    ctx: ClassCtx,
    questions: Mapping[tuple[uuid.UUID, uuid.UUID], QStat],
    chats: Mapping[uuid.UUID, int],
) -> HintUse:
    per: dict[uuid.UUID, QStat] = defaultdict(QStat)
    for (sid, _iid), q in questions.items():
        p = per[sid]
        p.answered += q.answered
        p.hints += q.hints
    rows = [
        HintStudent(
            student_id=s.id,
            display_name=s.display_name,
            hints=per[s.id].hints,
            chats=chats.get(s.id, 0),
            answered=per[s.id].answered,
            hints_per_10=per_10(per[s.id].hints, per[s.id].answered),
        )
        for s in ctx.students
    ]
    hints = sum(r.hints for r in rows)
    answered = sum(r.answered for r in rows)
    top = sorted(
        (r for r in rows if r.answered >= HINT_MIN_QUESTIONS and r.hints > 0),
        key=lambda r: (-(r.hints_per_10 or 0), r.display_name),
    )[:HINT_TOP]
    return HintUse(
        hints=hints,
        chats=sum(chats.values()),
        answered=answered,
        hints_per_10=per_10(hints, answered),
        top=top,
    )


async def at_risk(scope: OrgScope, ctx: ClassCtx) -> dict[uuid.UUID, list[AtRiskReason]]:
    """At-risk reasons per in-scope student, over the last 7 IST days (fixed query count)."""
    sids = ctx.student_ids
    if not sids:
        return {}
    now = datetime.now(UTC)
    since = srs.ist_midnight(srs.ist_day(now) - timedelta(days=AT_RISK_DAYS - 1))
    inputs = {sid: RiskInputs() for sid in sids}
    for sid, _cid, _kp, is_failed, n in await _kp_tries(scope, sids, ctx.concepts, since):
        inputs[sid].kp_ended += n
        inputs[sid].kp_failed += n if is_failed else 0
    xp_rows = await scope.session.execute(
        scope.select(XpEvent)
        .with_only_columns(
            XpEvent.student_id,
            func.coalesce(func.sum(XpEvent.amount), 0),
            func.count().filter(XpEvent.amount < 0),
        )
        .where(
            XpEvent.student_id.in_(sids),
            XpEvent.subject == ctx.cls.subject,
            XpEvent.day >= srs.ist_day(since),
        )
        .group_by(XpEvent.student_id)
    )
    for sid, net, negative in xp_rows.all():
        inputs[sid].net_xp = int(net)
        inputs[sid].negative_xp = int(negative)
    for sid, by_activity in (await _study(scope, sids, ctx.concepts, since)).items():
        inputs[sid].active_seconds = sum(by_activity.values())

    dependants = {p for ps in ctx.graph.prereqs.values() for p in ps}
    watched = [c for c in ctx.concepts if c in dependants]
    if watched:
        cards = await scope.session.execute(
            scope.select(ReviewCard)
            .with_only_columns(
                ReviewCard.student_id,
                ReviewCard.concept_id,
                ReviewCard.stability,
                ReviewCard.last_review,
            )
            .where(ReviewCard.student_id.in_(sids), ReviewCard.concept_id.in_(watched))
        )
        weak: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for sid, cid, stability, last in cards.all():
            if _status(ctx, sid, cid) != "learned":
                continue
            if srs.retrievability(stability, last, now) < WEAK_R:
                weak[sid].append(cid)
        for sid, cids in weak.items():
            inputs[sid].weak_prereqs = [ctx.title(c) for c in sorted(cids, key=ctx.order)]

    for sid, rows in (await assignments.overdue_by_student(scope, ctx)).items():
        if sid in inputs:
            inputs[sid].overdue = rows

    active: set[uuid.UUID] = set(
        (
            await scope.session.scalars(
                scope.select(Attempt)
                .with_only_columns(Attempt.student_id)
                .where(Attempt.student_id.in_(sids), Attempt.created_at >= since)
                .distinct()
            )
        ).all()
    )
    active |= set(
        (
            await scope.session.scalars(
                scope.select(StudyTime)
                .with_only_columns(StudyTime.student_id)
                .where(StudyTime.student_id.in_(sids), StudyTime.created_at >= since)
                .distinct()
            )
        ).all()
    )
    for s in ctx.students:
        inputs[s.id].active_recently = s.id in active
        inputs[s.id].enrolled_days = (now - s.enrolled_at).days
    return {sid: at_risk_rules(r) for sid, r in inputs.items()}


def _at_risk_rows(
    ctx: ClassCtx, reasons: Mapping[uuid.UUID, list[AtRiskReason]]
) -> list[AtRiskRow]:
    rows = [
        AtRiskRow(student_id=s.id, display_name=s.display_name, reasons=reasons[s.id])
        for s in ctx.students
        if reasons.get(s.id)
    ]
    rows.sort(key=lambda r: (-len(r.reasons), r.display_name.lower()))
    return rows


# --- endpoints ------------------------------------------------------------------------------------


@dataclass
class ClassSnapshot:
    """The intermediate results behind the Overview, shared by the dashboard and spec 011's
    fact builder so both see the same numbers."""

    ctx: ClassCtx
    window: Window
    now: datetime
    since: datetime | None
    tries: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, bool, int]]
    items: dict[uuid.UUID, ItemRow]
    questions: dict[tuple[uuid.UUID, uuid.UUID], QStat]
    chosen: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str | None, int]]
    miscs: list[Misconception]
    chats: dict[uuid.UUID, int]
    study: dict[uuid.UUID, dict[StudyActivity, int]]
    reasons: dict[uuid.UUID, list[AtRiskReason]]
    summaries: list[AssignmentSummary]
    today: date
    concept_stats: list[ConceptStat] = field(default_factory=list)
    misconception_stats: list[MisconceptionStat] = field(default_factory=list)
    hint_use: HintUse | None = None

    @property
    def weakest(self) -> list[ConceptStat]:
        return [s for s in self.concept_stats if s.fail_rate is not None][:TOP]

    @property
    def top_misconceptions(self) -> list[MisconceptionStat]:
        return _rank_misconceptions(self.misconception_stats)[:TOP]

    @property
    def practice_share(self) -> PracticeShare:
        return PracticeShare(
            learn_seconds=sum(s.get(StudyActivity.learn, 0) for s in self.study.values()),
            practice_seconds=sum(s.get(StudyActivity.practice, 0) for s in self.study.values()),
        )

    @property
    def assignments_due(self) -> list[AssignmentSummary]:
        return [s for s in self.summaries if s.active and s.content_available][:3]

    @property
    def overdue(self) -> list[AssignmentSummary]:
        return [s for s in self.summaries if s.due_date < self.today and s.counts.overdue > 0]


async def class_snapshot(scope: OrgScope, ctx: ClassCtx, window: Window) -> ClassSnapshot:
    now = datetime.now(UTC)
    since = window_start(window, now)
    sids, concepts = ctx.student_ids, ctx.concepts
    snap = ClassSnapshot(
        ctx=ctx,
        window=window,
        now=now,
        since=since,
        tries=await _kp_tries(scope, sids, concepts, since),
        items=await _items(scope, concepts),
        questions=await _questions(scope, sids, concepts, since),
        chosen=await _chosen(scope, sids, concepts, since),
        miscs=await _misconception_rows(scope, ctx),
        chats=await _chats(scope, sids, concepts, since),
        study=await _study(scope, sids, concepts, since),
        reasons=await at_risk(scope, ctx),
        summaries=await assignments.summaries(scope, ctx),
        today=assignments.today_ist(now),
    )
    snap.concept_stats = _concept_stats(ctx, snap.tries)
    snap.misconception_stats = _misconceptions(
        ctx, snap.miscs, snap.items, snap.questions, snap.chosen
    )
    snap.hint_use = _hint_use(ctx, snap.questions, snap.chats)
    return snap


async def overview(scope: OrgScope, class_id: uuid.UUID, window: Window) -> ClassOverview:
    ctx = await class_view.load(scope, class_id)
    snap = await class_snapshot(scope, ctx, window)
    assert snap.hint_use is not None
    return ClassOverview(
        window=window,
        students_in_scope=len(ctx.student_ids),
        has_course=ctx.course is not None,
        weakest=snap.weakest,
        at_risk=_at_risk_rows(ctx, snap.reasons),
        misconceptions=snap.top_misconceptions,
        hints=snap.hint_use,
        flagged=await _flagged(scope, ctx, snap.since),
        practice_share=snap.practice_share,
        assignments_due=snap.assignments_due,
        overdue_assignments=len(snap.overdue),
    )


async def concepts(scope: OrgScope, class_id: uuid.UUID, window: Window) -> list[ConceptStat]:
    ctx = await class_view.load(scope, class_id)
    since = window_start(window, datetime.now(UTC))
    return _concept_stats(ctx, await _kp_tries(scope, ctx.student_ids, ctx.concepts, since))


async def misconceptions(
    scope: OrgScope, class_id: uuid.UUID, window: Window
) -> list[MisconceptionStat]:
    ctx = await class_view.load(scope, class_id, states=False)
    since = window_start(window, datetime.now(UTC))
    sids, cs = ctx.student_ids, ctx.concepts
    items = await _items(scope, cs)
    rows = _misconceptions(
        ctx,
        await _misconception_rows(scope, ctx),
        items,
        await _questions(scope, sids, cs, since),
        await _chosen(scope, sids, cs, since),
    )
    return _rank_misconceptions(rows)


def _concept_in_course(ctx: ClassCtx, course: str, concept: str) -> uuid.UUID:
    cid = ctx.graph.by_ref.get(f"{course}/{concept}")
    if cid is None or cid not in ctx.concept_set:
        raise not_found()
    return cid


KIND_ORDER = {ItemKind.misconception_check: 0, ItemKind.kp_question: 1, ItemKind.practice: 2}


async def concept_detail(
    scope: OrgScope, class_id: uuid.UUID, course: str, concept: str, window: Window
) -> ConceptDetail:
    ctx = await class_view.load(scope, class_id)
    cid = _concept_in_course(ctx, course, concept)
    since = window_start(window, datetime.now(UTC))
    sids = ctx.student_ids
    tries = await _kp_tries(scope, sids, [cid], since)
    items = await _items(scope, [cid])
    questions = await _questions(scope, sids, [cid], since)
    chosen = await _chosen(scope, sids, [cid], since)
    kps = await frontier.active_kps(scope, [cid])

    per_item: dict[uuid.UUID, QStat] = defaultdict(QStat)
    for (_sid, iid), q in questions.items():
        p = per_item[iid]
        p.answered += q.answered
        p.correct += q.correct
        p.hints += q.hints
        p.ms += q.ms
    kp_rows = []
    for kp in kps:
        ended = sum(n for _s, _c, k, _f, n in tries if k == kp.id)
        failed = sum(n for _s, _c, k, f, n in tries if k == kp.id and f)
        kp_rows.append(
            KpStat(
                title=kp.title,
                tries=ended,
                fail_rate=round(failed / ended, 3) if ended else None,
                hints=sum(per_item[i.id].hints for i in items.values() if i.kp_id == kp.id),
            )
        )
    kp_pos = {kp.id: i for i, kp in enumerate(kps)}
    ordered = sorted(
        items.values(),
        key=lambda i: (
            KIND_ORDER.get(i.kind, 3),
            kp_pos.get(i.kp_id, 0) if i.kp_id else 0,
            i.position,
        ),
    )
    item_rows = [
        ItemStat(
            prompt=str(i.public.get("prompt", "")),
            kind=i.kind.value,
            type=i.type,
            answers=per_item[i.id].answered,
            correct_pct=(
                round(100 * per_item[i.id].correct / per_item[i.id].answered)
                if per_item[i.id].answered
                else None
            ),
            avg_seconds=(
                round(per_item[i.id].ms / 1000 / per_item[i.id].answered, 1)
                if per_item[i.id].answered
                else None
            ),
        )
        for i in ordered
    ]
    students = ConceptStudents(stuck=[], in_progress=[], learned=[], ready=0, locked=0)
    for s in ctx.students:
        view = _view(ctx, s.id, cid)
        state = heat_state(view)
        ref = StudentRef(student_id=s.id, display_name=s.display_name)
        if state == "stuck" and view is not None:
            reason = stuck_reason(view)
            assert reason is not None
            node = ctx.graph.nodes.get(reason.prereq) if reason.prereq else None
            title = None if node is None else node.title
            students.stuck.append(
                StuckStudent(**ref.model_dump(), reason=stuck_label(reason, title))
            )
        elif state == "in_progress":
            students.in_progress.append(ref)
        elif state == "learned":
            students.learned.append(ref)
        elif state == "ready":
            students.ready += 1
        else:
            students.locked += 1
    misc_rows = _misconceptions(
        ctx,
        await _misconception_rows(scope, ctx),
        items,
        questions,
        chosen,
        only_items=set(items),
    )
    return ConceptDetail(
        concept=ctx.ref(cid),
        title=ctx.title(cid),
        kps=kp_rows,
        items=item_rows,
        misconceptions=sorted(misc_rows, key=lambda r: (-r.students, -(r.rate or 0), r.title)),
        students=students,
    )


async def _cards(
    scope: OrgScope, sids: Sequence[uuid.UUID], concepts: Sequence[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[float, datetime, datetime]]:
    """(student, concept) -> (stability, last review, due)."""
    if not sids or not concepts:
        return {}
    rows = await scope.session.execute(
        scope.select(ReviewCard)
        .with_only_columns(
            ReviewCard.student_id,
            ReviewCard.concept_id,
            ReviewCard.stability,
            ReviewCard.last_review,
            ReviewCard.due,
        )
        .where(ReviewCard.student_id.in_(sids), ReviewCard.concept_id.in_(concepts))
    )
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows.all()}


def _band(
    state: HeatState,
    card: tuple[float, datetime, datetime] | None,
    now: datetime,
) -> tuple[Band | None, float | None]:
    if state != "learned":
        return None, None
    if card is None:
        return "none", None
    r = srs.retrievability(card[0], card[1], now)
    return memory_band(r), r


async def heatmap(scope: OrgScope, class_id: uuid.UUID) -> Heatmap:
    ctx = await class_view.load(scope, class_id)
    now = datetime.now(UTC)
    cards = await _cards(scope, ctx.student_ids, ctx.concepts)
    chapters: dict[uuid.UUID, list[uuid.UUID]] = {}
    for cid in ctx.concepts:
        chapters.setdefault(ctx.graph.nodes[cid].chapter_id, []).append(cid)
    flat = [c for cs in chapters.values() for c in cs]
    rows = []
    for s in ctx.students:
        cells = []
        for cid in flat:
            state = _status(ctx, s.id, cid)
            band, _r = _band(state, cards.get((s.id, cid)), now)
            cells.append(HeatCell(state=state, band=band))
        rows.append(HeatRow(student_id=s.id, display_name=s.display_name, cells=cells))
    return Heatmap(
        chapters=[
            HeatChapter(
                title=ctx.graph.chapters[ch].title,
                grade=ctx.graph.chapters[ch].grade,
                concepts=[
                    HeatConcept(
                        concept=ctx.ref(c), title=ctx.title(c), learned_pct=_learned_pct(ctx, c)
                    )
                    for c in cs
                ],
            )
            for ch, cs in chapters.items()
        ],
        students=rows,
    )


# --- one student ----------------------------------------------------------------------------------


@dataclass
class StudentSnapshot:
    """What the student page header computes (last 7 days), shared with spec 011."""

    ctx: ClassCtx
    student: class_view.Student
    now: datetime
    since: datetime | None
    reasons: list[AtRiskReason]
    week_xp: int
    streak_days: int
    reviews_due: int
    last_quiz: LastQuizOut | None
    study: dict[StudyActivity, int]
    tries: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, bool, int]]
    questions: dict[tuple[uuid.UUID, uuid.UUID], QStat]
    assignment_rows: list[StudentAssignmentRow]

    @property
    def kp_ended(self) -> int:
        return sum(t[4] for t in self.tries)

    @property
    def kp_failed(self) -> int:
        return sum(t[4] for t in self.tries if t[3])

    @property
    def hints(self) -> int:
        return sum(q.hints for q in self.questions.values())

    @property
    def answered(self) -> int:
        return sum(q.answered for q in self.questions.values())

    @property
    def learned(self) -> int:
        return sum(
            1 for c in self.ctx.concepts if _status(self.ctx, self.student.id, c) == "learned"
        )


async def student_snapshot(scope: OrgScope, ctx: ClassCtx) -> StudentSnapshot:
    """`ctx` is loaded for one student (`class_view.load(..., student_id=...)`)."""
    s = ctx.students[0]
    now = datetime.now(UTC)
    since = window_start("7d", now)
    reasons = (await at_risk(scope, ctx)).get(s.id, [])
    stats = await xp.roster_stats(scope, ctx.cls, [s.id])
    due = await srs.due_count(scope, [s.id])
    quizzes = await quiz.last_quiz_stats(scope, [s.id])
    study = (await _study(scope, [s.id], ctx.concepts, since)).get(s.id, {})
    tries = await _kp_tries(scope, [s.id], ctx.concepts, since)
    questions = await _questions(scope, [s.id], ctx.concepts, since)
    week_xp, streak = stats[s.id]
    return StudentSnapshot(
        ctx=ctx,
        student=s,
        now=now,
        since=since,
        reasons=reasons,
        week_xp=week_xp,
        streak_days=streak,
        reviews_due=due.get(s.id, 0),
        last_quiz=quizzes.get(s.id),
        study=study,
        tries=tries,
        questions=questions,
        assignment_rows=await assignments.student_rows(scope, ctx),
    )


async def student_detail(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> StudentDetail:
    ctx = await class_view.load(scope, class_id, student_id=student_id)
    snap = await student_snapshot(scope, ctx)
    s = snap.student
    ended, failed = snap.kp_ended, snap.kp_failed
    return StudentDetail(
        student_id=s.id,
        display_name=s.display_name,
        status=s.status,
        at_risk=snap.reasons,
        week_xp=snap.week_xp,
        streak_days=snap.streak_days,
        reviews_due=snap.reviews_due,
        last_quiz=snap.last_quiz,
        stats=StudentStats(
            learn_seconds=snap.study.get(StudyActivity.learn, 0),
            practice_seconds=snap.study.get(StudyActivity.practice, 0),
            kp_fail_rate=round(failed / ended, 3) if ended else None,
            hints_per_10=per_10(snap.hints, snap.answered),
            learned=snap.learned,
            total=len(ctx.concepts),
        ),
        assignments=snap.assignment_rows,
    )


async def outline_states(
    scope: OrgScope, ctx: ClassCtx
) -> tuple[
    list[tuple[uuid.UUID, uuid.UUID]],
    frontier.Frontier,
    dict[tuple[uuid.UUID, uuid.UUID], tuple[float, datetime, datetime]],
]:
    """The student's outline (class course + cross-course prerequisites, with each concept's
    anchor), its read-only frontier and review cards. `ctx` is loaded for one student with a
    course."""
    assert ctx.course is not None
    pairs = ctx.graph.outline(ctx.course.slug)
    ids = [c for c, _ in pairs]
    sid = ctx.students[0].id
    front = (await frontier.class_states(scope, [sid], ids, ctx.graph.prereqs))[sid]
    return pairs, front, await _cards(scope, [sid], ids)


async def student_outline(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> TeacherOutline:
    """The class course as the student sees it (cross-course prerequisites included), with the
    teacher's 5 states, memory and KP statuses. Read-only."""
    ctx = await class_view.load(scope, class_id, student_id=student_id, states=False)
    if ctx.course is None:  # no active course for the class subject: an empty state
        return TeacherOutline(course=None, chapters=[])
    graph = ctx.graph
    sid = ctx.students[0].id
    pairs, front, cards = await outline_states(scope, ctx)
    now = datetime.now(UTC)
    chapters: dict[uuid.UUID, list[TeacherOutlineConcept]] = {}
    for cid, anchor in pairs:
        node = graph.nodes[cid]
        view = front.views[cid]
        state = heat_state(view)
        card = cards.get((sid, cid))
        band, r = _band(state, card, now)
        waiting = view.waiting
        chapters.setdefault(graph.nodes[anchor].chapter_id, []).append(
            TeacherOutlineConcept(
                id=node.ref,
                title=node.title,
                summary=node.summary,
                status=view.status,
                prereqs=[graph.nodes[p].ref for p in graph.prereqs.get(cid, [])],
                kps_passed=view.kps_passed,
                kps_total=view.kps_total,
                parts_passed=view.parts_passed,
                parts_total=view.parts_total,
                waiting=None if waiting is None else Waiting(reopen_at=waiting.reopen_at),
                brush_up=view.brush_up,
                brush_up_id=view.brush_up_id,
                state=state,
                memory=(
                    None
                    if band is None
                    else Memory(
                        band=band, retrievability=r, next_due=None if card is None else card[2]
                    )
                ),
                kps=[
                    KpBrief(
                        title=kp.title,
                        status=kp.status.value,
                        fail_count=kp.fail_count,
                        reopen_at=kp.reopen_at if kp.status.value == "failed" else None,
                    )
                    for kp in view.kps
                ],
            )
        )
    course = ctx.course
    ordered = sorted(chapters, key=lambda ch: graph.chapters[ch].position)
    return TeacherOutline(
        course=CourseRef(slug=course.slug, title=course.title, subject=course.subject),
        chapters=[
            TeacherOutlineChapter(
                slug=graph.chapters[ch].slug,
                title=graph.chapters[ch].title,
                grade=graph.chapters[ch].grade,
                concepts=chapters[ch],
            )
            for ch in ordered
        ],
    )


ACTIVITY_TITLES = {
    SessionKind.kp: "KP try",
    SessionKind.remediation: "Brush-up",
    SessionKind.practice: "Practice",
    SessionKind.review: "Review",
    SessionKind.quiz: "Mixed quiz",
}


async def student_activity(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID, before: datetime | None
) -> list[ActivityRow]:
    """The last ended sessions (with at least one answer) on the class course, newest first."""
    ctx = await class_view.load(scope, class_id, student_id=student_id, states=False)
    sid = ctx.students[0].id
    if not ctx.concepts:
        return []
    concept = func.coalesce(
        PracticeSession.concept_id, KnowledgePoint.concept_id, Remediation.prereq_concept_id
    )
    agg = (
        scope.select(Attempt)
        .with_only_columns(
            Attempt.session_id.label("session_id"),
            func.coalesce(func.sum(Attempt.hints_used), 0).label("hints"),
            func.count(func.distinct(Attempt.position)).label("answered"),
            func.coalesce(func.sum(Attempt.time_taken_ms), 0).label("ms"),
        )
        .where(Attempt.student_id == sid, Attempt.session_id.is_not(None))
        .group_by(Attempt.session_id)
        .subquery()
    )
    xp_sum = (
        scope.select(XpEvent)
        .with_only_columns(
            XpEvent.session_id.label("session_id"), func.sum(XpEvent.amount).label("xp")
        )
        .where(XpEvent.student_id == sid, XpEvent.subject == ctx.cls.subject)
        .group_by(XpEvent.session_id)
        .subquery()
    )
    in_course_quiz = exists().where(
        QuizItem.quiz_id == PracticeSession.quiz_id, QuizItem.concept_id.in_(ctx.concepts)
    )
    stmt = (
        scope.select(PracticeSession)
        .with_only_columns(
            PracticeSession.kind,
            concept,
            PracticeSession.status,
            xp_sum.c.xp,
            agg.c.hints,
            agg.c.answered,
            agg.c.ms,
            PracticeSession.ended_at,
        )
        .join(agg, agg.c.session_id == PracticeSession.id)
        .outerjoin(xp_sum, xp_sum.c.session_id == PracticeSession.id)
        .outerjoin(KnowledgePoint, KnowledgePoint.id == PracticeSession.kp_id)
        .outerjoin(Remediation, Remediation.id == PracticeSession.remediation_id)
        .where(
            PracticeSession.student_id == sid,
            PracticeSession.status.in_((SessionStatus.passed, SessionStatus.failed)),
            PracticeSession.ended_at.is_not(None),
            or_(
                and_(PracticeSession.kind == SessionKind.quiz, in_course_quiz),
                concept.in_(ctx.concepts),
            ),
        )
        .order_by(PracticeSession.ended_at.desc())
        .limit(ACTIVITY_PAGE)
    )
    if before is not None:
        if before.tzinfo is None:
            before = before.replace(tzinfo=UTC)
        stmt = stmt.where(PracticeSession.ended_at < before)
    out = []
    for kind, cid, status, xp_amount, hints, answered, ms, ended in (
        await scope.session.execute(stmt)
    ).all():
        known = cid is not None and cid in ctx.graph.nodes
        out.append(
            ActivityRow(
                kind=kind.value,
                concept=ctx.ref(cid) if known else None,
                title=ctx.title(cid) if known else ACTIVITY_TITLES[kind],
                outcome=status.value,
                xp=None if xp_amount is None else int(xp_amount),
                hints=int(hints),
                answered=int(answered),
                seconds=round(int(ms) / 1000),
                ended_at=ended,
            )
        )
    return out


async def tutor_threads(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID
) -> list[ThreadRow]:
    ctx = await class_view.load(scope, class_id, student_id=student_id, states=False)
    sid = ctx.students[0].id
    if not ctx.concepts:
        return []
    flagged = exists().where(
        TutorMessage.tutor_session_id == TutorSession.id, TutorMessage.flagged.is_(True)
    )
    stmt = (
        scope.select(TutorSession)
        .with_only_columns(
            TutorSession.id,
            Item.concept_id,
            KnowledgePoint.title,
            TutorSession.created_at,
            TutorSession.hints_used,
            TutorSession.chat_count,
            case((flagged, literal(True)), else_=literal(False)),
        )
        .join(Item, Item.id == TutorSession.item_id)
        .outerjoin(KnowledgePoint, KnowledgePoint.id == Item.kp_id)
        .where(TutorSession.student_id == sid, Item.concept_id.in_(ctx.concepts))
        .order_by(TutorSession.created_at.desc())
    )
    return [
        ThreadRow(
            id=r[0],
            concept=ctx.ref(r[1]),
            concept_title=ctx.title(r[1]),
            kp_title=r[2],
            created_at=r[3],
            hints_used=r[4],
            chat_count=r[5],
            flagged=bool(r[6]),
        )
        for r in (await scope.session.execute(stmt)).all()
    ]


async def tutor_thread(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID, thread_id: uuid.UUID
) -> ThreadDetail:
    ctx = await class_view.load(scope, class_id, student_id=student_id, states=False)
    thread = await scope.get(TutorSession, thread_id)
    if thread.student_id != ctx.students[0].id:
        raise not_found()
    concept_id = await scope.session.scalar(
        select(Item.concept_id).where(Item.id == thread.item_id)
    )
    if concept_id is None or concept_id not in ctx.concept_set:
        raise not_found()
    rows = await scope.session.scalars(
        scope.select(TutorMessage)
        .where(
            TutorMessage.tutor_session_id == thread.id,
            TutorMessage.status.not_in(HIDDEN_FROM_TEACHER),
        )
        .order_by(TutorMessage.created_at, TutorMessage.role)
    )
    return ThreadDetail(
        id=thread.id,
        concept=ctx.ref(concept_id),
        concept_title=ctx.title(concept_id),
        messages=[
            ThreadMessage(
                role=m.role.value,
                kind=m.kind.value,
                text=m.text,
                status=m.status.value,
                purged=m.purged_at is not None,
                created_at=m.created_at,
            )
            for m in rows.all()
        ],
    )


async def roster_at_risk(scope: OrgScope, class_id: uuid.UUID) -> dict[uuid.UUID, list[str]]:
    """Roster column: at-risk codes per in-scope student."""
    ctx = await class_view.load(scope, class_id)
    return {sid: [r.code for r in rs] for sid, rs in (await at_risk(scope, ctx)).items()}
