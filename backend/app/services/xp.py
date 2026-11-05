"""XP, daily goals, streaks and class leaderboards (spec 008).

The top of this module is pure (no DB) so the rules are unit-testable. The DB services below take
an `OrgScope`. XP is awarded once per `practice_session`, by the answer that ends it
(`award_for_session`, called by the KP, brush-up, practice and review answer paths in the same
transaction that ends the session). A quiz (spec 007) earns one event per subject
(`award_for_quiz`), also when it ends by time-out. Other sessions closed as a side effect, previews
and "Practise again" earn nothing. After every award a quiz may become due (`quiz.maybe_create`).
Rows hold ids, numbers and the subject only.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import DateTime, case, delete, exists, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, forbidden, not_found
from app.grading import multistep
from app.models import (
    AppUser,
    Attempt,
    AttemptContext,
    Concept,
    Course,
    Enrollment,
    Item,
    PracticeSession,
    Role,
    SchoolClass,
    SessionKind,
    StudentGoal,
    Subject,
    UserStatus,
    XpDay,
    XpEvent,
    XpGrade,
    XpReason,
)
from app.schemas.quiz import QuizSubjectXp, QuizXpOut
from app.schemas.xp import (
    GoalOut,
    LeaderboardOut,
    LeaderboardRef,
    LeaderboardRow,
    StreakOut,
    XpAwardOut,
    XpSummary,
    XpTodayOut,
)
from app.services import kp_flow, quiz

# --- pure rules -----------------------------------------------------------------------------------

RUSH_FLOOR_MS = 5_000
RUSH_SHARE = Decimal("0.15")  # of the item's expected time
RUSH_PENALTY = Decimal("0.25")  # x base, negated
HINT_COST = Decimal("0.25")  # per hint, positive awards only
MULTIPLIER = {
    XpGrade.perfect: Decimal("1.2"),
    XpGrade.passed: Decimal("1.0"),
    XpGrade.partial: Decimal("0.3"),
    XpGrade.poor: Decimal("0"),
}
MIN_AMOUNT, MAX_AMOUNT = -100, 500  # the ledger's CHECK
GOAL_MIN, GOAL_MAX, GOAL_STEP = 5, 60, 5
STREAK_WINDOW_DAYS = 400


@dataclass(frozen=True)
class PositionXp:
    """One answered item of a session: its expected time, result and time taken (all steps)."""

    expected_minutes: Decimal
    correct: bool
    time_ms: int
    every_step: bool = True  # multistep: every step right (an item can pass with a wrong step)


@dataclass(frozen=True)
class XpCalc:
    amount: int
    grade: XpGrade
    base_minutes: Decimal
    rushed_count: int
    answered: int
    hints: int


def is_rushed(p: PositionXp) -> bool:
    """A wrong answer given faster than a real try could take: under max(5 s, 15 % of expected)."""
    if p.correct:
        return False
    threshold = max(Decimal(RUSH_FLOOR_MS), RUSH_SHARE * p.expected_minutes * 60_000)
    return Decimal(p.time_ms) < threshold


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def session_xp(
    kind: SessionKind,
    outcome: Literal["passed", "failed"],
    positions: Sequence[PositionXp],
    hints: int = 0,
    *,
    first_try: bool = True,
) -> XpCalc:
    """XP for an ended session: sum of expected minutes x grade multiplier x hint factor.

    `first_try` (practice): no earlier failed session on the same item; a later pass is `passed`.
    Rushing (≥ min(2, answered) rushed wrong answers in a failed session) costs 0.25 x base, at
    least 1; a positive product is at least 1."""
    base = sum((p.expected_minutes for p in positions), Decimal(0))
    answered = len(positions)
    rushed = sum(1 for p in positions if is_rushed(p))
    right = sum(1 for p in positions if p.correct)
    if outcome == "passed":
        exact = all(p.every_step for p in positions)
        perfect = right == answered and (kind != SessionKind.practice or (first_try and exact))
        grade = XpGrade.perfect if perfect else XpGrade.passed
    elif answered and rushed >= min(2, answered):
        grade = XpGrade.rushed
    elif kind != SessionKind.practice and answered and 2 * right >= answered:
        grade = XpGrade.partial
    else:
        grade = XpGrade.poor
    if grade == XpGrade.rushed:
        amount = -max(1, _round(RUSH_PENALTY * base))
    else:
        product = base * MULTIPLIER[grade] * max(Decimal(0), 1 - HINT_COST * hints)
        amount = max(1, _round(product)) if product > 0 else 0
    amount = max(MIN_AMOUNT, min(MAX_AMOUNT, amount))
    return XpCalc(amount, grade, base, rushed, answered, hints)


@dataclass(frozen=True)
class QuizPos:
    """One quiz question of a subject (spec 007): unanswered questions count as wrong."""

    expected_minutes: Decimal
    correct: bool
    answered: bool
    time_ms: int = 0


def quiz_xp(positions: Sequence[QuizPos]) -> XpCalc:
    """A subject's share of a quiz. Base = expected minutes of the correct answers: all correct
    x 1.2, some correct x 1.0, none 0. Fewer than half correct with >= min(2, answered wrong)
    answered wrong items rushed costs 0.25 x the subject's expected minutes (at least 1);
    unanswered items are never rushed. No hints in quizzes."""
    right = [p for p in positions if p.correct]
    wrong = [p for p in positions if p.answered and not p.correct]
    rushed = sum(1 for p in wrong if is_rushed(PositionXp(p.expected_minutes, False, p.time_ms)))
    base = sum((p.expected_minutes for p in right), Decimal(0))
    answered = sum(1 for p in positions if p.answered)
    if 2 * len(right) < len(positions) and wrong and rushed >= min(2, len(wrong)):
        total = sum((p.expected_minutes for p in positions), Decimal(0))
        amount = max(MIN_AMOUNT, -max(1, _round(RUSH_PENALTY * total)))
        return XpCalc(amount, XpGrade.rushed, total, rushed, answered, 0)
    if right and len(right) == len(positions):
        grade = XpGrade.perfect
    elif right:
        grade = XpGrade.passed
    else:
        grade = XpGrade.poor
    product = base * MULTIPLIER[grade]
    amount = min(MAX_AMOUNT, max(1, _round(product)) if product > 0 else 0)
    return XpCalc(amount, grade, base, rushed, answered, 0)


def ist_date(now: datetime) -> date:
    return now.astimezone(kp_flow.IST).date()


def ist_week_start(now: datetime) -> date:
    """Monday of the IST week containing `now` (weeks run Monday 00:00 to Sunday 24:00 IST)."""
    today = ist_date(now)
    return today - timedelta(days=today.weekday())


def day_met(rows: Iterable[tuple[int | None, datetime | None]]) -> bool:
    """`(goal, met_at)` rows of one day: met when some row has a goal and every such row is met."""
    goals = [met_at for goal, met_at in rows if goal is not None]
    return bool(goals) and all(m is not None for m in goals)


def streak_from_days(met: Mapping[date, bool], today: date) -> tuple[int, bool]:
    """Consecutive met days ending today (if met) or yesterday: an unfinished today doesn't
    break the streak until IST midnight. Returns `(days, today_met)`."""
    today_met = met.get(today, False)
    day = today if today_met else today - timedelta(days=1)
    days = 0
    while met.get(day, False):
        days += 1
        day -= timedelta(days=1)
    return days, today_met


def valid_goal(goal: int) -> bool:
    return GOAL_MIN <= goal <= GOAL_MAX and goal % GOAL_STEP == 0


def competition_ranks(values: Sequence[int]) -> list[int]:
    """Ranks for values sorted highest first; ties share a rank (1, 1, 3)."""
    ranks: list[int] = []
    for i, v in enumerate(values):
        ranks.append(ranks[-1] if i and v == values[i - 1] else i + 1)
    return ranks


# --- DB: goals ------------------------------------------------------------------------------------


async def goals_for(scope: OrgScope, student_id: uuid.UUID) -> dict[Subject, GoalOut]:
    """Subjects with a goal: the student's active classes (highest class goal) and own goals."""
    class_rows = await scope.session.execute(
        select(SchoolClass.subject, func.max(SchoolClass.daily_goal))
        .join(
            Enrollment,
            (Enrollment.class_id == SchoolClass.id) & (Enrollment.org_id == SchoolClass.org_id),
        )
        .where(
            SchoolClass.org_id == scope.org_id,
            SchoolClass.archived_at.is_(None),
            Enrollment.student_id == student_id,
        )
        .group_by(SchoolClass.subject)
    )
    own_rows = await scope.session.scalars(
        scope.select(StudentGoal).where(StudentGoal.student_id == student_id)
    )
    own = {g.subject: g.goal for g in own_rows.all()}
    class_goals = dict(class_rows.all())
    return {
        s: GoalOut(
            subject=s,
            class_goal=class_goals[s],
            own_goal=own.get(s),
            effective=max(class_goals[s], own.get(s) or 0),
        )
        for s in Subject
        if s in class_goals
    }


def _met_case(xp: object, goal: object, now: datetime) -> object:
    return case((xp >= goal, literal(now, DateTime(timezone=True))), else_=None)  # type: ignore[operator]


async def _raise_today(
    scope: OrgScope, student_ids: object, subject: Subject, goal: int, now: datetime
) -> None:
    """Raise today's existing rows to at least `goal`; a met row stays met."""
    new_goal = func.greatest(XpDay.goal, goal)
    await scope.session.execute(
        update(XpDay)
        .where(
            XpDay.org_id == scope.org_id,
            XpDay.student_id.in_(student_ids),  # type: ignore[arg-type]
            XpDay.day == ist_date(now),
            XpDay.subject == subject,
        )
        .values(
            goal=new_goal,
            met_at=func.coalesce(XpDay.met_at, _met_case(XpDay.xp, new_goal, now)),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )


async def raise_class_goal(
    scope: OrgScope, class_id: uuid.UUID, subject: Subject, goal: int
) -> None:
    """A teacher raised a class goal: today's rows of its students rise with it (no commit)."""
    students = select(Enrollment.student_id).where(
        Enrollment.org_id == scope.org_id, Enrollment.class_id == class_id
    )
    await _raise_today(scope, students, subject, goal, datetime.now(UTC))


def _require_student(scope: OrgScope) -> None:
    if scope.user.is_staff:
        raise forbidden()


async def set_own_goal(scope: OrgScope, subject: Subject, goal: int | None) -> XpSummary:
    _require_student(scope)
    if goal is not None and not valid_goal(goal):
        raise ApiProblem(422, "goal_invalid", "Pick 5–60, in steps of 5.")  # noqa: RUF001
    goals = await goals_for(scope, scope.user.id)
    current = goals.get(subject)
    if current is None:
        raise ApiProblem(422, "no_class_for_subject", "You're not in a class for this subject.")
    if goal is not None and goal < current.class_goal:
        n = current.class_goal
        raise ApiProblem(
            422, "goal_below_class", f"Your teacher's goal is {n} XP; pick {n} or more."
        )
    now = datetime.now(UTC)
    if goal is None:
        await scope.session.execute(
            delete(StudentGoal).where(
                StudentGoal.org_id == scope.org_id,
                StudentGoal.student_id == scope.user.id,
                StudentGoal.subject == subject,
            )
        )
    else:
        stmt = insert(StudentGoal).values(
            org_id=scope.org_id,
            student_id=scope.user.id,
            subject=subject,
            goal=goal,
            updated_at=now,
        )
        await scope.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[StudentGoal.student_id, StudentGoal.subject],
                set_={"goal": stmt.excluded.goal, "updated_at": now},
            )
        )
        await _raise_today(scope, [scope.user.id], subject, max(goal, current.class_goal), now)
    await scope.session.commit()
    return await summary(scope)


# --- DB: awards -----------------------------------------------------------------------------------


async def _subject_of(scope: OrgScope, concept_id: uuid.UUID) -> Subject:
    subject = await scope.session.scalar(
        select(Course.subject)
        .join(Concept, Concept.course_id == Course.id)
        .where(Concept.id == concept_id)
    )
    assert subject is not None
    return subject


async def _positions(scope: OrgScope, session: PracticeSession) -> tuple[list[PositionXp], int]:
    """One entry per answered item (a multi-step item once all its steps are in) + total hints."""
    attempts = (
        await scope.session.scalars(
            scope.select(Attempt)
            .where(Attempt.session_id == session.id)
            .order_by(Attempt.position, Attempt.step)
        )
    ).all()
    ids = {a.item_id for a in attempts}
    items = (
        {i.id: i for i in (await scope.session.scalars(select(Item).where(Item.id.in_(ids)))).all()}
        if ids
        else {}
    )
    by_position: dict[int, list[Attempt]] = {}
    for a in attempts:
        by_position.setdefault(a.position or 0, []).append(a)
    out = []
    for position in sorted(by_position):
        rows = sorted(by_position[position], key=lambda a: a.step)
        item = items[rows[0].item_id]
        if item.type.value == "multistep":
            correct = multistep.multistep_outcome(
                [a.correct for a in rows], multistep.step_count(item.answer)
            )
            if correct is None:
                continue
        else:
            correct = rows[0].correct
        out.append(
            PositionXp(
                item.expected_minutes,
                correct,
                sum(a.time_taken_ms for a in rows),
                every_step=all(a.correct for a in rows),
            )
        )
    return out, sum(a.hints_used for a in attempts)


async def _first_try(scope: OrgScope, session: PracticeSession) -> bool:
    """Practice: no answer to this item in an earlier (so failed) practice session."""
    if session.kind != SessionKind.practice or session.current_item_id is None:
        return True
    earlier = await scope.session.scalar(
        select(
            exists().where(
                Attempt.org_id == scope.org_id,
                Attempt.student_id == session.student_id,
                Attempt.context == AttemptContext.practice,
                Attempt.item_id == session.current_item_id,
                Attempt.session_id != session.id,
            )
        )
    )
    return not earlier


async def _bump_days(
    scope: OrgScope, student_id: uuid.UUID, day: date, subject: Subject, amount: int, now: datetime
) -> None:
    """Upsert the day's rows: the event's subject (+ amount) and every subject with a goal.

    A goal is frozen at the day's first XP and only ever raised; once met, a row stays met."""
    goals = await goals_for(scope, student_id)
    for s in Subject:
        if s != subject and s not in goals:
            continue
        add = amount if s == subject else 0
        goal = goals[s].effective if s in goals else None
        stmt = insert(XpDay).values(
            org_id=scope.org_id,
            student_id=student_id,
            day=day,
            subject=s,
            xp=add,
            goal=goal,
            met_at=now if goal is not None and add >= goal else None,
            updated_at=now,
        )
        new_xp = XpDay.xp + stmt.excluded.xp
        new_goal = func.greatest(XpDay.goal, stmt.excluded.goal)
        await scope.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[XpDay.student_id, XpDay.day, XpDay.subject],
                set_={
                    "xp": new_xp,
                    "goal": new_goal,
                    "met_at": func.coalesce(XpDay.met_at, _met_case(new_xp, new_goal, now)),
                    "updated_at": now,
                },
            )
        )


async def _goal_met_by(scope: OrgScope, student_id: uuid.UUID, day: date, at: datetime) -> bool:
    """Did the award written at `at` make its day met? (Its rows' latest `met_at` is `at`.)"""
    rows = (
        await scope.session.execute(
            select(XpDay.goal, XpDay.met_at).where(
                XpDay.org_id == scope.org_id, XpDay.student_id == student_id, XpDay.day == day
            )
        )
    ).all()
    if not day_met(rows):
        return False
    return max(m for g, m in rows if g is not None and m is not None) == at


def _award_out(event: XpEvent, goal_met_today: bool) -> XpAwardOut:
    return XpAwardOut(
        amount=event.amount,
        grade=event.grade,
        base_minutes=event.base_minutes,
        hints=event.hints,
        goal_met_today=goal_met_today,
    )


async def event_out(scope: OrgScope, session_id: uuid.UUID) -> XpAwardOut | None:
    """The award stored for a session (a resent or already-answered result)."""
    event = await scope.session.scalar(
        scope.select(XpEvent).where(XpEvent.session_id == session_id).order_by(XpEvent.id).limit(1)
    )
    if event is None:
        return None
    met = await _goal_met_by(scope, event.student_id, event.day, event.created_at)
    return _award_out(event, met)


async def award_for_session(
    scope: OrgScope,
    session: PracticeSession,
    outcome: Literal["passed", "failed"],
    concept_id: uuid.UUID,
) -> XpAwardOut:
    """Write the one `xp_event` for a session an answer just ended, and its `xp_day` rows, in the
    caller's transaction. `concept_id`: the session's concept (a brush-up: the prerequisite)."""
    positions, hints = await _positions(scope, session)
    calc = session_xp(
        session.kind, outcome, positions, hints, first_try=await _first_try(scope, session)
    )
    subject = await _subject_of(scope, concept_id)
    now = datetime.now(UTC)
    day = ist_date(now)
    inserted = await scope.session.scalar(
        insert(XpEvent)
        .values(
            org_id=scope.org_id,
            student_id=session.student_id,
            session_id=session.id,
            reason=XpReason(session.kind.value),
            concept_id=concept_id,
            subject=subject,
            amount=calc.amount,
            grade=calc.grade,
            base_minutes=calc.base_minutes,
            answered=calc.answered,
            rushed_count=calc.rushed_count,
            hints=calc.hints,
            day=day,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[XpEvent.session_id, XpEvent.subject], index_where=_SESSION_WHERE
        )
        .returning(XpEvent.id)
    )
    if inserted is None:  # can't happen while the session row is locked; be safe anyway
        existing = await event_out(scope, session.id)
        assert existing is not None
        return existing
    await _bump_days(scope, session.student_id, day, subject, calc.amount, now)
    met = await _goal_met_by(scope, session.student_id, day, now)
    await quiz.maybe_create(scope)  # spec 007: every ~150 lifetime XP
    return XpAwardOut(
        amount=calc.amount,
        grade=calc.grade,
        base_minutes=calc.base_minutes,
        hints=calc.hints,
        goal_met_today=met,
    )


_SESSION_WHERE = text("session_id IS NOT NULL")


@dataclass(frozen=True)
class QuizSubject:
    """A subject's questions in a quiz: the concept of its first item and its positions."""

    concept_id: uuid.UUID
    positions: list[QuizPos]


async def award_for_quiz(
    scope: OrgScope, session: PracticeSession, subjects: Mapping[Subject, QuizSubject]
) -> QuizXpOut:
    """One `xp_event` per subject in a finished quiz (spec 007), each counting towards that
    subject's day like any other work. Doesn't create the next quiz (the caller sets the mark)."""
    now = datetime.now(UTC)
    day = ist_date(now)
    out = []
    for subject in Subject:
        part = subjects.get(subject)
        if part is None:
            continue
        calc = quiz_xp(part.positions)
        inserted = await scope.session.scalar(
            insert(XpEvent)
            .values(
                org_id=scope.org_id,
                student_id=session.student_id,
                session_id=session.id,
                reason=XpReason.quiz,
                concept_id=part.concept_id,
                subject=subject,
                amount=calc.amount,
                grade=calc.grade,
                base_minutes=calc.base_minutes,
                answered=calc.answered,
                rushed_count=calc.rushed_count,
                hints=0,
                day=day,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[XpEvent.session_id, XpEvent.subject], index_where=_SESSION_WHERE
            )
            .returning(XpEvent.id)
        )
        if inserted is not None:
            await _bump_days(scope, session.student_id, day, subject, calc.amount, now)
        out.append((subject, calc))
    met = await _goal_met_by(scope, session.student_id, day, now)
    return _quiz_out([(s, c.amount, c.grade, c.base_minutes) for s, c in out], met)


def _quiz_out(rows: Sequence[tuple[Subject, int, XpGrade, Decimal]], met: bool) -> QuizXpOut:
    return QuizXpOut(
        amount=sum(a for _, a, _, _ in rows),
        base_minutes=sum((b for _, _, _, b in rows), Decimal(0)),
        goal_met_today=met,
        subjects=[QuizSubjectXp(subject=s, amount=a, grade=g) for s, a, g, _ in rows],
    )


async def quiz_events_out(scope: OrgScope, session_id: uuid.UUID) -> QuizXpOut | None:
    """The stored per-subject awards of a finished quiz (the result page)."""
    events = (
        await scope.session.scalars(scope.select(XpEvent).where(XpEvent.session_id == session_id))
    ).all()
    if not events:
        return None
    order = list(Subject)
    events = sorted(events, key=lambda e: order.index(e.subject))
    first = events[0]
    met = await _goal_met_by(scope, first.student_id, first.day, first.created_at)
    return _quiz_out([(e.subject, e.amount, e.grade, e.base_minutes) for e in events], met)


async def lifetime_xp(scope: OrgScope) -> int:
    """The student's net XP over all subjects (negatives count, not floored)."""
    total = await scope.session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
            XpEvent.org_id == scope.org_id, XpEvent.student_id == scope.user.id
        )
    )
    return int(total or 0)


# --- DB: reads ------------------------------------------------------------------------------------


async def _met_days(
    scope: OrgScope, student_ids: Sequence[uuid.UUID], today: date
) -> dict[uuid.UUID, dict[date, bool]]:
    if not student_ids:
        return {}
    rows = await scope.session.execute(
        select(XpDay.student_id, XpDay.day, XpDay.goal, XpDay.met_at).where(
            XpDay.org_id == scope.org_id,
            XpDay.student_id.in_(student_ids),
            XpDay.day > today - timedelta(days=STREAK_WINDOW_DAYS),
        )
    )
    grouped: dict[uuid.UUID, dict[date, list[tuple[int | None, datetime | None]]]] = {}
    for sid, day, goal, met_at in rows.all():
        grouped.setdefault(sid, {}).setdefault(day, []).append((goal, met_at))
    return {sid: {d: day_met(r) for d, r in days.items()} for sid, days in grouped.items()}


async def _week_xp(
    scope: OrgScope, student_ids: Sequence[uuid.UUID], since: date, subject: Subject | None = None
) -> dict[uuid.UUID, int]:
    """Net XP since `since` per student (not floored)."""
    if not student_ids:
        return {}
    stmt = (
        select(XpEvent.student_id, func.sum(XpEvent.amount))
        .where(
            XpEvent.org_id == scope.org_id,
            XpEvent.student_id.in_(student_ids),
            XpEvent.day >= since,
        )
        .group_by(XpEvent.student_id)
    )
    if subject is not None:
        stmt = stmt.where(XpEvent.subject == subject)
    return {sid: int(n) for sid, n in (await scope.session.execute(stmt)).all()}


async def summary(scope: OrgScope) -> XpSummary:
    _require_student(scope)
    me = scope.user.id
    now = datetime.now(UTC)
    today = ist_date(now)
    goals = await goals_for(scope, me)
    day_rows = {
        r.subject: r
        for r in (
            await scope.session.scalars(
                scope.select(XpDay).where(XpDay.student_id == me, XpDay.day == today)
            )
        ).all()
    }
    today_out = []
    for s in Subject:
        row = day_rows.get(s)
        if row is None and s not in goals:
            continue
        goal = row.goal if row is not None and row.goal is not None else None
        if goal is None and s in goals:
            goal = goals[s].effective
        today_out.append(
            XpTodayOut(
                subject=s,
                xp=max(0, row.xp) if row is not None else 0,
                goal=goal,
                met=row is not None and row.met_at is not None,
            )
        )
    days, today_met = streak_from_days((await _met_days(scope, [me], today)).get(me, {}), today)
    week = (await _week_xp(scope, [me], ist_week_start(now))).get(me, 0)
    total = await scope.session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
            XpEvent.org_id == scope.org_id, XpEvent.student_id == me
        )
    )
    boards = (
        await scope.session.scalars(
            scope.select(SchoolClass)
            .join(
                Enrollment,
                (Enrollment.class_id == SchoolClass.id) & (Enrollment.org_id == SchoolClass.org_id),
            )
            .where(
                Enrollment.student_id == me,
                SchoolClass.archived_at.is_(None),
                SchoolClass.leaderboard_enabled.is_(True),
            )
            .order_by(func.lower(SchoolClass.name))
        )
    ).all()
    return XpSummary(
        today=today_out,
        streak=StreakOut(days=days, today_met=today_met),
        week_xp=max(0, week),
        total_xp=max(0, int(total or 0)),
        goals=list(goals.values()),
        leaderboards=[
            LeaderboardRef(class_id=c.id, class_name=c.name, subject=c.subject) for c in boards
        ],
    )


async def _active_students(scope: OrgScope, class_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    rows = await scope.session.execute(
        select(AppUser.id, AppUser.display_name)
        .join(
            Enrollment,
            (Enrollment.student_id == AppUser.id) & (Enrollment.org_id == AppUser.org_id),
        )
        .where(
            AppUser.org_id == scope.org_id,
            AppUser.role == Role.student,
            AppUser.status == UserStatus.active,
            Enrollment.class_id == class_id,
        )
    )
    return list(rows.all())


async def leaderboard(scope: OrgScope, class_id: uuid.UUID) -> LeaderboardOut:
    """This week's XP in the class's subject. Staff always; students only while it's on, the
    class is active and they're enrolled (else 404)."""
    school_class = await scope.get(SchoolClass, class_id)
    staff = scope.user.is_staff
    if not staff:
        enrolled = await scope.session.scalar(
            select(
                exists().where(
                    Enrollment.org_id == scope.org_id,
                    Enrollment.class_id == class_id,
                    Enrollment.student_id == scope.user.id,
                )
            )
        )
        if not (enrolled and school_class.leaderboard_enabled and school_class.archived_at is None):
            raise not_found()
    week_start = ist_week_start(datetime.now(UTC))
    students = await _active_students(scope, class_id)
    week = await _week_xp(scope, [sid for sid, _ in students], week_start, school_class.subject)
    ranked = sorted(
        ((sid, name, max(0, week.get(sid, 0))) for sid, name in students),
        key=lambda r: (-r[2], r[1].lower(), str(r[0])),
    )
    ranks = competition_ranks([xp for _, _, xp in ranked])
    return LeaderboardOut(
        class_name=school_class.name,
        subject=school_class.subject,
        enabled=school_class.leaderboard_enabled,
        week_start=week_start,
        rows=[
            LeaderboardRow(
                rank=rank,
                display_name=name,
                week_xp=xp,
                is_me=sid == scope.user.id,
                student_id=sid if staff else None,
            )
            for rank, (sid, name, xp) in zip(ranks, ranked, strict=True)
        ],
    )


async def roster_stats(
    scope: OrgScope, school_class: SchoolClass, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Per student: this week's XP in the class's subject (floored at 0) and the streak."""
    now = datetime.now(UTC)
    today = ist_date(now)
    week = await _week_xp(scope, student_ids, ist_week_start(now), school_class.subject)
    met = await _met_days(scope, student_ids, today)
    return {
        sid: (max(0, week.get(sid, 0)), streak_from_days(met.get(sid, {}), today)[0])
        for sid in student_ids
    }
