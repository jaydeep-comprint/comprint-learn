"""Spaced repetition per concept (spec 007): FSRS cards, implicit credit and Today's reviews.

One card per student x learned concept (`review_card`), always in FSRS's Review state, with
day-scale intervals. Every change to a card writes one `review_log` row with its cause.

The top of this module is pure (no DB) so the rules are unit-testable; the DB functions take an
`OrgScope`, never commit, and write only for the scope's student.
"""

import uuid
from collections.abc import Callable, Collection, Hashable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from fsrs import Card, Rating, Scheduler, State
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import OrgScope
from app.models import (
    ConceptPrereq,
    ConceptState,
    ConceptStatus,
    PracticeSession,
    Remediation,
    RemediationState,
    ReviewCard,
    ReviewDueReason,
    ReviewLog,
    ReviewSource,
    SessionKind,
    SessionStatus,
)
from app.schemas.reviews import ReviewOffer, ReviewQueue
from app.services import frontier, kp_flow, learn

# --- pure rules -----------------------------------------------------------------------------------

# Empty step lists keep every card in the Review state (day-scale intervals only); no fuzzing keeps
# schedules deterministic. The migration 0008 backfill uses the same configuration.
SCHEDULER = Scheduler(
    desired_retention=0.9, learning_steps=(), relearning_steps=(), enable_fuzzing=False
)
DAILY_CAP = 5
CREDIT_EPS = 1e-6
STRUGGLE_DAYS = 30

CreditKind = Literal["kp", "review", "brushup", "practice"]
RATING_NAMES = {Rating.Again: "again", Rating.Hard: "hard", Rating.Good: "good"}


def utc(dt: datetime) -> datetime:
    """py-fsrs requires `tzinfo is timezone.utc` exactly."""
    return dt.astimezone(UTC)


def ist_day(dt: datetime) -> date:
    return dt.astimezone(kp_flow.IST).date()


def ist_midnight(day: date) -> datetime:
    """00:00 IST of `day`, in UTC."""
    return datetime.combine(day, time(0), tzinfo=kp_flow.IST).astimezone(UTC)


def min_tomorrow(due: datetime, now: datetime) -> datetime:
    """The next due date is at least tomorrow (IST): earlier times move to the next 00:00 IST."""
    if ist_day(due) <= ist_day(now):
        return kp_flow.next_midnight_ist(now)
    return due


def rating_for(passed: bool, all_correct: bool) -> Rating:
    """Passed with every answer right → Good; passed after a miss → Hard; failed → Again."""
    if not passed:
        return Rating.Again
    return Rating.Good if all_correct else Rating.Hard


def fsrs_card(stability: float, difficulty: float, due: datetime, last_review: datetime) -> Card:
    return Card(
        card_id=0,
        state=State.Review,
        step=None,
        stability=stability,
        difficulty=difficulty,
        due=utc(due),
        last_review=utc(last_review),
    )


@dataclass(frozen=True)
class Scheduled:
    stability: float
    difficulty: float
    due: datetime


def first_review(at: datetime, rating: Rating = Rating.Good) -> Scheduled:
    """A new card reviewed `Good` at `at` (a concept just learned); `Hard` for a conditional
    placement (spec 012)."""
    card, _ = SCHEDULER.review_card(Card(card_id=0), rating, utc(at))
    assert card.stability is not None and card.difficulty is not None
    return Scheduled(card.stability, card.difficulty, min_tomorrow(card.due, at))


def next_review(
    stability: float,
    difficulty: float,
    due: datetime,
    last_review: datetime,
    rating: Rating,
    at: datetime,
) -> Scheduled:
    card = fsrs_card(stability, difficulty, due, last_review)
    card, _ = SCHEDULER.review_card(card, rating, utc(at))
    assert card.stability is not None and card.difficulty is not None
    return Scheduled(card.stability, card.difficulty, min_tomorrow(card.due, at))


def retrievability(stability: float, last_review: datetime, at: datetime) -> float:
    card = Card(
        card_id=0,
        state=State.Review,
        step=None,
        stability=stability,
        difficulty=5.0,
        due=utc(at),
        last_review=utc(last_review),
    )
    return float(SCHEDULER.get_card_retrievability(card, utc(at)))


def earliness(last_review: datetime, due: datetime, now: datetime) -> float:
    """How far through its interval the card is: 0 right after a review, 1 when due or overdue."""
    span = (due - last_review).total_seconds()
    if span <= 0:
        return 1.0
    return min(1.0, max(0.0, (now - last_review).total_seconds() / span))


def implicit_share(weight: float, n_kps: int, kind: CreditKind) -> float:
    """A passed KP in C gives each prerequisite w / n (n = C's active KPs, so all of C ≈ w);
    a passed review or brush-up of C gives w; practice gives nothing."""
    if kind == "kp":
        return weight / n_kps if n_kps > 0 else 0.0
    if kind in ("review", "brushup"):
        return weight
    return 0.0


def credit_step(credit: float, added: float) -> tuple[float, bool]:
    """(new credit, fire): at 1.0 an implicit `Good` fires and credit resets (overflow dropped)."""
    total = credit + added
    if total >= 1 - CREDIT_EPS:
        return 0.0, True
    return total, False


def struggling(consecutive_fails: int, last_relearn_at: datetime | None, now: datetime) -> bool:
    """No implicit credit after a failed explicit review, or within 30 days of a relearn."""
    if consecutive_fails > 0:
        return True
    return last_relearn_at is not None and now - last_relearn_at < timedelta(days=STRUGGLE_DAYS)


def cap_left(done_today: int, cap: int = DAILY_CAP) -> int:
    return max(0, cap - done_today)


def interleave[T](
    items: Sequence[T], subject: Callable[[T], Hashable], chapter: Callable[[T], Hashable]
) -> list[T]:
    """Round-robin by subject (in order of each subject's first item), keeping each subject's
    order, and never putting two items of one chapter next to each other when another choice
    exists. Deterministic: same input, same output."""
    queues: dict[Hashable, list[T]] = {}
    for it in items:
        queues.setdefault(subject(it), []).append(it)
    out: list[T] = []
    subjects = list(queues)
    i = 0
    while subjects:
        s = subjects[i % len(subjects)]
        queue = queues[s]
        last = chapter(out[-1]) if out else None
        pick = next((k for k, it in enumerate(queue) if chapter(it) != last), 0)
        out.append(queue.pop(pick))
        if not queue:
            subjects.remove(s)
            if subjects:
                i %= len(subjects)
            continue
        i += 1
    return out


@dataclass(frozen=True)
class QueueCard:
    concept_id: uuid.UUID
    subject: str
    chapter_id: uuid.UUID
    retrievability: float


def order_queue(cards: Sequence[QueueCard]) -> list[QueueCard]:
    """Lowest retrievability first (ties by concept id), then interleaved by subject/chapter."""
    ranked = sorted(cards, key=lambda c: (c.retrievability, str(c.concept_id)))
    return interleave(ranked, lambda c: c.subject, lambda c: c.chapter_id)


# --- DB: cards ------------------------------------------------------------------------------------


async def gradable(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Concepts with an active KP that has an active quick-check question (reviews serve those)."""
    return {k.concept_id for k in await frontier.active_kps(scope, concept_ids) if k.quick}


async def _locked_card(scope: OrgScope, concept_id: uuid.UUID) -> ReviewCard | None:
    return await scope.session.scalar(
        scope.select(ReviewCard)
        .where(ReviewCard.student_id == scope.user.id, ReviewCard.concept_id == concept_id)
        .with_for_update()
    )


def _log(
    scope: OrgScope,
    concept_id: uuid.UUID,
    source: ReviewSource,
    *,
    rating: Rating | None = None,
    before: ReviewCard | None = None,
    after: ReviewCard | None = None,
    due_before: datetime | None = None,
    stability_before: float | None = None,
    due_reason: ReviewDueReason | None = None,
    session_id: uuid.UUID | None = None,
    quiz_id: uuid.UUID | None = None,
    credit_added: float | None = None,
    due_after: datetime | None = None,
    at: datetime | None = None,
) -> None:
    scope.session.add(
        ReviewLog(
            org_id=scope.org_id,
            student_id=scope.user.id,
            concept_id=concept_id,
            source=source,
            rating=None if rating is None else int(rating),
            session_id=session_id,
            quiz_id=quiz_id,
            due_reason=due_reason,
            due_before=due_before,
            due_after=due_after if after is None else after.due,
            stability_before=stability_before,
            stability_after=None if after is None else after.stability,
            credit_added=None if credit_added is None else Decimal(str(round(credit_added, 6))),
            created_at=at or datetime.now(UTC),
        )
    )


def _rate(card: ReviewCard, rating: Rating, at: datetime) -> tuple[datetime, float]:
    """Apply an FSRS review to the row; returns (due before, stability before)."""
    before = (card.due, card.stability)
    nxt = next_review(card.stability, card.difficulty, card.due, card.last_review, rating, at)
    card.stability, card.difficulty, card.due = nxt.stability, nxt.difficulty, nxt.due
    card.last_review = at
    card.reps += 1
    if rating == Rating.Again:
        card.lapses += 1
    card.updated_at = at
    return before


async def on_learned(
    scope: OrgScope,
    concept_id: uuid.UUID,
    at: datetime | None = None,
    *,
    rating: Rating = Rating.Good,
    source: Literal[ReviewSource.learned, ReviewSource.placed] = ReviewSource.learned,
) -> None:
    """A concept became learned: create its card (a first `Good`), or, when one exists, this is a
    relearn: `Good` again with the fail count, credit and reason reset. No gradable KP items → no
    card. Spec 012: a placement logs `placed` for both (never `relearned`, so it doesn't count as
    struggling) and rates `Hard` when conditional."""
    at = at or datetime.now(UTC)
    if not await gradable(scope, [concept_id]):
        return
    card = await _locked_card(scope, concept_id)
    if card is None:
        first = first_review(at, rating)
        created = await scope.session.scalar(
            insert(ReviewCard)
            .values(
                org_id=scope.org_id,
                student_id=scope.user.id,
                concept_id=concept_id,
                stability=first.stability,
                difficulty=first.difficulty,
                due=first.due,
                last_review=at,
                reps=1,
                created_at=at,
                updated_at=at,
            )
            .on_conflict_do_nothing(index_elements=[ReviewCard.student_id, ReviewCard.concept_id])
            .returning(ReviewCard.concept_id)
        )
        if created is not None:
            scope.session.add(
                ReviewLog(
                    org_id=scope.org_id,
                    student_id=scope.user.id,
                    concept_id=concept_id,
                    source=source,
                    rating=int(rating),
                    due_after=first.due,
                    stability_after=first.stability,
                    created_at=at,
                )
            )
        return
    old_reason = card.due_reason
    due_before, stab_before = _rate(card, rating, at)
    card.consecutive_fails = 0
    card.credit = 0.0
    card.due_reason = ReviewDueReason.schedule
    _log(
        scope,
        concept_id,
        ReviewSource.placed if source == ReviewSource.placed else ReviewSource.relearned,
        rating=rating,
        after=card,
        due_before=due_before,
        stability_before=stab_before,
        due_reason=old_reason,
        at=at,
    )


@dataclass(frozen=True)
class ReviewInfo:
    rating: Rating
    next_due: date
    consecutive_fails: int
    due_reason: ReviewDueReason  # the card's reason before this review


async def apply_review(
    scope: OrgScope,
    concept_id: uuid.UUID,
    *,
    passed: bool,
    all_correct: bool,
    source: Literal[ReviewSource.review, ReviewSource.brushup],
    session_id: uuid.UUID | None,
) -> ReviewInfo | None:
    """An explicit review (a review or a brush-up) ended: rate the card. None when it has none.
    Spec 012: the first review outcome clears a conditional placement."""
    await clear_conditional(scope, [concept_id])
    card = await _locked_card(scope, concept_id)
    if card is None:
        return None
    now = datetime.now(UTC)
    rating = rating_for(passed, all_correct)
    old_reason = card.due_reason
    due_before, stab_before = _rate(card, rating, now)
    card.consecutive_fails = 0 if passed else card.consecutive_fails + 1
    card.due_reason = ReviewDueReason.schedule
    _log(
        scope,
        concept_id,
        source,
        rating=rating,
        after=card,
        due_before=due_before,
        stability_before=stab_before,
        due_reason=old_reason,
        session_id=session_id,
        at=now,
    )
    return ReviewInfo(rating, ist_day(card.due), card.consecutive_fails, old_reason)


async def clear_conditional(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> None:
    """Spec 012: a conditional placement becomes a normal learned concept."""
    if not concept_ids:
        return
    await scope.session.execute(
        update(ConceptState)
        .where(
            ConceptState.org_id == scope.org_id,
            ConceptState.student_id == scope.user.id,
            ConceptState.concept_id.in_(list(concept_ids)),
            ConceptState.conditional.is_(True),
        )
        .values(conditional=False, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )


async def _conditional(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    if not concept_ids:
        return set()
    return set(
        (
            await scope.session.scalars(
                scope.select(ConceptState)
                .with_only_columns(ConceptState.concept_id)
                .where(
                    ConceptState.student_id == scope.user.id,
                    ConceptState.concept_id.in_(list(concept_ids)),
                    ConceptState.conditional.is_(True),
                )
            )
        ).all()
    )


async def _last_relearn(scope: OrgScope, concept_id: uuid.UUID) -> datetime | None:
    return await scope.session.scalar(
        scope.select(ReviewLog)
        .with_only_columns(func.max(ReviewLog.created_at))
        .where(
            ReviewLog.student_id == scope.user.id,
            ReviewLog.concept_id == concept_id,
            ReviewLog.source == ReviewSource.relearned,
        )
    )


async def give_implicit_credit(scope: OrgScope, concept_id: uuid.UUID, kind: CreditKind) -> None:
    """One-level implicit credit to each direct prerequisite of `concept_id` (any course).

    Skipped for a prerequisite with no card, not learned, retired, due from a quiz miss, or
    struggling. Nothing passes further up the graph."""
    if kind == "practice":
        return
    edges = (
        await scope.session.execute(
            select(ConceptPrereq.prereq_id, ConceptPrereq.encompassing_weight).where(
                ConceptPrereq.concept_id == concept_id
            )
        )
    ).all()
    if not edges:
        return
    n_kps = len(await frontier.active_kps(scope, [concept_id])) if kind == "kp" else 0
    graph = await learn._graph(scope)  # active content only (retired prereqs aren't in it)
    learned = await _learned(scope, [p for p, _ in edges])
    shaky = await _conditional(scope, [p for p, _ in edges])  # spec 012: treated as struggling
    now = datetime.now(UTC)
    for prereq_id, weight in sorted(edges, key=lambda e: str(e[0])):
        share = implicit_share(float(weight), n_kps, kind)
        if share <= 0 or prereq_id not in graph.nodes or prereq_id not in learned:
            continue
        if prereq_id in shaky:
            continue
        card = await _locked_card(scope, prereq_id)
        if card is None or card.due_reason == ReviewDueReason.quiz_miss:
            continue
        if struggling(card.consecutive_fails, await _last_relearn(scope, prereq_id), now):
            continue
        added = share * earliness(card.last_review, card.due, now)
        if added <= 0:
            continue
        credit, fire = credit_step(card.credit, added)
        if fire:
            due_before, stab_before = _rate(card, Rating.Good, now)
            card.credit = 0.0
            _log(
                scope,
                prereq_id,
                ReviewSource.implicit,
                rating=Rating.Good,
                after=card,
                due_before=due_before,
                stability_before=stab_before,
                credit_added=added,
                at=now,
            )
        else:
            card.credit = credit
            card.updated_at = now
            _log(scope, prereq_id, ReviewSource.implicit, credit_added=added, at=now)


async def mark_quiz_miss(
    scope: OrgScope, concept_ids: Collection[uuid.UUID], quiz_id: uuid.UUID
) -> None:
    """Each missed concept's card is due now, outside the cap (FSRS state untouched). Spec 012: a
    quiz miss clears a conditional placement."""
    await clear_conditional(scope, concept_ids)
    now = datetime.now(UTC)
    for cid in sorted(concept_ids, key=str):
        card = await _locked_card(scope, cid)
        if card is None:
            continue
        due_before = card.due
        card.due = now
        card.due_reason = ReviewDueReason.quiz_miss
        card.updated_at = now
        _log(
            scope,
            cid,
            ReviewSource.quiz_miss,
            due_before=due_before,
            quiz_id=quiz_id,
            due_reason=ReviewDueReason.quiz_miss,
            due_after=now,
            at=now,
        )


async def _learned(scope: OrgScope, concept_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    if not concept_ids:
        return set()
    rows = await scope.session.scalars(
        scope.select(ConceptState)
        .with_only_columns(ConceptState.concept_id)
        .where(
            ConceptState.student_id == scope.user.id,
            ConceptState.concept_id.in_(concept_ids),
            ConceptState.status == ConceptStatus.learned,
        )
    )
    return set(rows.all())


# --- DB: Today's reviews --------------------------------------------------------------------------


@dataclass
class _QueueState:
    graph: "learn._Graph"
    offered: list[tuple[ReviewCard, bool]]  # (card, active session)
    beyond_cap: set[uuid.UUID]  # due scheduled cards hidden by the cap
    done_today: int
    next_due_on: date | None
    has_cards: bool


async def done_today(scope: OrgScope, now: datetime) -> int:
    """Scheduled reviews ended today (IST): they count against the daily cap."""
    n = await scope.session.scalar(
        scope.select(ReviewLog)
        .with_only_columns(func.count())
        .where(
            ReviewLog.student_id == scope.user.id,
            ReviewLog.source == ReviewSource.review,
            ReviewLog.due_reason == ReviewDueReason.schedule,
            ReviewLog.created_at >= ist_midnight(ist_day(now)),
        )
    )
    return int(n or 0)


async def _review_due_brushups(
    scope: OrgScope, student_ids: Collection[uuid.UUID]
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    rows = await scope.session.execute(
        scope.select(Remediation)
        .with_only_columns(Remediation.student_id, Remediation.prereq_concept_id)
        .where(
            Remediation.student_id.in_(student_ids),
            Remediation.state == RemediationState.review_due,
        )
    )
    return {(s, c) for s, c in rows.all()}


async def _state(scope: OrgScope, *, create_missing: bool = True) -> _QueueState:
    graph = await learn._graph(scope)
    me = scope.user.id
    now = datetime.now(UTC)
    learned_rows = (
        await scope.session.execute(
            scope.select(ConceptState)
            .with_only_columns(ConceptState.concept_id, ConceptState.conditional)
            .where(ConceptState.student_id == me, ConceptState.status == ConceptStatus.learned)
        )
    ).all()
    learned = {cid for cid, _ in learned_rows}
    conditional = {cid for cid, cond in learned_rows if cond}
    cards = {
        c.concept_id: c
        for c in (
            await scope.session.scalars(scope.select(ReviewCard).where(ReviewCard.student_id == me))
        ).all()
    }
    missing = [c for c in learned if c in graph.nodes and c not in cards]
    if create_missing and missing:  # gradable items appeared since the concept was learned
        for cid in await gradable(scope, missing):
            await on_learned(
                scope, cid, now, rating=Rating.Hard if cid in conditional else Rating.Good
            )
        await scope.session.flush()
        cards = {
            c.concept_id: c
            for c in (
                await scope.session.scalars(
                    scope.select(ReviewCard).where(ReviewCard.student_id == me)
                )
            ).all()
        }
    blocked = {c for _, c in await _review_due_brushups(scope, [me])}
    active = set(
        (
            await scope.session.scalars(
                scope.select(PracticeSession)
                .with_only_columns(PracticeSession.concept_id)
                .where(
                    PracticeSession.student_id == me,
                    PracticeSession.kind == SessionKind.review,
                    PracticeSession.status == SessionStatus.active,
                )
            )
        ).all()
    )
    candidates = [
        c
        for c in cards.values()
        if c.concept_id in graph.nodes and c.concept_id in learned and c.concept_id not in blocked
    ]
    # A card whose quick checks were all retired can't be reviewed: never offer it.
    askable = await gradable(scope, [c.concept_id for c in candidates])
    eligible = [c for c in candidates if c.concept_id in askable]
    today = ist_day(now)
    at = ist_midnight(today)

    def queue_card(c: ReviewCard) -> QueueCard:
        node = graph.nodes[c.concept_id]
        return QueueCard(
            c.concept_id,
            node.subject.value,
            node.chapter_id,
            retrievability(c.stability, c.last_review, at),
        )

    by_id = {c.concept_id: c for c in eligible}
    misses = [c for c in eligible if c.due_reason == ReviewDueReason.quiz_miss]
    sched = [
        c
        for c in eligible
        if c.due_reason == ReviewDueReason.schedule
        and (ist_day(c.due) <= today or c.concept_id in active)
    ]
    done = await done_today(scope, now)
    ordered_misses = [by_id[q.concept_id] for q in order_queue([queue_card(c) for c in misses])]
    # The cap keeps the weakest memories (lowest retrievability), then they're interleaved.
    weakest = sorted(
        (queue_card(c) for c in sched), key=lambda q: (q.retrievability, str(q.concept_id))
    )
    started = [q for q in weakest if q.concept_id in active]
    rest = [q for q in weakest if q.concept_id not in active]
    slots = cap_left(done + len(started))
    shown = [by_id[q.concept_id] for q in order_queue(started + rest[:slots])]
    beyond = {q.concept_id for q in rest[slots:]}
    offered = [(c, c.concept_id in active) for c in ordered_misses + shown]
    next_due: date | None = None
    if not offered:
        if beyond:
            next_due = today + timedelta(days=1)
        else:
            later = [ist_day(c.due) for c in eligible if c.due_reason == ReviewDueReason.schedule]
            next_due = min(later) if later else None
    return _QueueState(graph, offered, beyond, done, next_due, bool(cards))


async def queue(scope: OrgScope) -> ReviewQueue:
    learn._require_student(scope)
    state = await _state(scope)
    graph = state.graph
    offers = []
    for card, active in state.offered:
        node = graph.nodes[card.concept_id]
        offers.append(
            ReviewOffer(
                course=node.course_slug,
                concept=learn._concept_ref(graph, card.concept_id),
                subject=node.subject,
                reason=card.due_reason.value,
                due_on=ist_day(card.due),
                active=active,
            )
        )
    return ReviewQueue(
        cap=DAILY_CAP,
        done_today=state.done_today,
        offered=offers,
        more_due=len(state.beyond_cap),
        next_due_on=state.next_due_on,
        has_cards=state.has_cards,
    )


async def offer_status(
    scope: OrgScope, concept_id: uuid.UUID
) -> Literal["offered", "cap", "not_due"]:
    state = await _state(scope)
    if any(c.concept_id == concept_id for c, _ in state.offered):
        return "offered"
    if concept_id in state.beyond_cap:
        return "cap"
    return "not_due"


async def due_count(scope: OrgScope, student_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Staff roster: due, offerable cards today per student, uncapped (quiz misses included).
    Read-only."""
    if not student_ids:
        return {}
    graph = await learn._graph(scope)
    today = ist_day(datetime.now(UTC))
    rows = (
        await scope.session.execute(
            scope.select(ReviewCard)
            .with_only_columns(
                ReviewCard.student_id, ReviewCard.concept_id, ReviewCard.due, ReviewCard.due_reason
            )
            .join(
                ConceptState,
                (ConceptState.student_id == ReviewCard.student_id)
                & (ConceptState.concept_id == ReviewCard.concept_id)
                & (ConceptState.org_id == ReviewCard.org_id),
            )
            .where(
                ReviewCard.student_id.in_(student_ids),
                ConceptState.status == ConceptStatus.learned,
            )
        )
    ).all()
    blocked = await _review_due_brushups(scope, student_ids)
    askable = await gradable(scope, {cid for _, cid, _, _ in rows if cid in graph.nodes})
    out = dict.fromkeys(student_ids, 0)
    for sid, cid, due, reason in rows:
        if cid not in askable or (sid, cid) in blocked:
            continue
        if reason == ReviewDueReason.quiz_miss or ist_day(due) <= today:
            out[sid] += 1
    return out
