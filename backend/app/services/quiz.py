"""The mixed timed quiz (spec 007).

A quiz is created `pending` after an XP award takes lifetime net XP to the next mark (150, then
the lifetime XP at the last quiz's end + 150). While it's pending or active, no new KP or practice
session can start (409 `quiz_pending`). It is chosen when it starts: up to 10 quick-check KP
questions over the student's learned concepts, lowest retrievability first, interleaved by
subject. One shared timer (1.5 min per question, 30 s grace for answers in flight); no feedback
until the end; finished when every question is answered or lazily, on the student's first read
or write after the deadline. Misses become reviews; XP is one event per subject.

The top of this module is pure (no DB) so the rules are unit-testable.
"""

import secrets
import uuid
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert

from app.api.deps import OrgScope
from app.content import params
from app.core.errors import not_found
from app.grading import QUICK_TYPES
from app.models import (
    Attempt,
    AttemptContext,
    Concept,
    ConceptState,
    ConceptStatus,
    Course,
    Item,
    PracticeSession,
    Quiz,
    QuizItem,
    QuizStatus,
    ReviewCard,
    SessionKind,
    SessionStatus,
    Subject,
)
from app.models.content import ItemKind
from app.schemas.kp import AnswerIn, QuestionPublic
from app.schemas.learn import ConceptRef
from app.schemas.quiz import LastQuizOut, QuizResult, QuizResultItem, QuizSaved, QuizState
from app.services import frontier, kp_flow, learn, srs, xp

# --- pure rules -----------------------------------------------------------------------------------

QUIZ_MARK = 150  # lifetime XP between quizzes
QUIZ_SIZE = 10
SECONDS_PER_QUESTION = 90
GRACE = timedelta(seconds=30)  # answers in flight when the timer ends
MIN_LEARNED = 3  # learned concepts with gradable items before the first quiz


def should_create(lifetime_xp: int, mark: int, learned_gradable: int) -> bool:
    return lifetime_xp >= mark and learned_gradable >= MIN_LEARNED


def next_mark(lifetime_xp_at_end: int) -> int:
    """After a quiz ends (or is cancelled), the next one comes 150 XP later: never back-to-back."""
    return lifetime_xp_at_end + QUIZ_MARK


def minutes_for(total: int) -> float:
    return SECONDS_PER_QUESTION * total / 60


def deadline_for(started_at: datetime, total: int) -> datetime:
    return started_at + timedelta(seconds=SECONDS_PER_QUESTION * total)


def is_over(now: datetime, deadline: datetime) -> bool:
    """Reads after the deadline finish the quiz."""
    return now >= deadline


def is_late(now: datetime, deadline: datetime) -> bool:
    """Answers are accepted until the deadline + 30 s grace."""
    return now > deadline + GRACE


@dataclass(frozen=True)
class Candidate:
    item_id: uuid.UUID
    has_params: bool


@dataclass(frozen=True)
class QuizConcept:
    """A learned concept with its KPs' quick-check items, each KP's in serving order."""

    concept_id: uuid.UUID
    subject: str
    chapter_id: uuid.UUID
    kps: Sequence[Sequence[Candidate]]


@dataclass(frozen=True)
class Pick:
    concept_id: uuid.UUID
    item_id: uuid.UUID
    has_params: bool
    subject: str
    chapter_id: uuid.UUID


def _next_pick(c: QuizConcept, round_: int, used: Collection[uuid.UUID]) -> Pick | None:
    """The concept's next question: from KP `round_ mod n` (then the others), an item not used in
    this quiz; once all are used, a param item again (new numbers)."""
    n = len(c.kps)
    order = [c.kps[(round_ + off) % n] for off in range(n)]
    for fresh in (True, False):
        for pool in order:
            for cand in pool:
                if (cand.item_id not in used) if fresh else cand.has_params:
                    return Pick(
                        c.concept_id, cand.item_id, cand.has_params, c.subject, c.chapter_id
                    )
    return None


def choose_items(concepts: Sequence[QuizConcept], size: int = QUIZ_SIZE) -> list[Pick]:
    """`concepts` lowest retrievability first: one question per concept until `size`, cycling
    again (a different KP where possible); fixed items never repeat. Interleaved by subject."""
    concepts = [c for c in concepts if any(c.kps)]
    used: set[uuid.UUID] = set()
    rounds: Counter[uuid.UUID] = Counter()
    picks: list[Pick] = []
    while len(picks) < size:
        added = False
        for c in concepts:
            if len(picks) >= size:
                break
            pick = _next_pick(c, rounds[c.concept_id], used)
            rounds[c.concept_id] += 1
            if pick is not None:
                picks.append(pick)
                used.add(pick.item_id)
                added = True
        if not added:
            break
    return srs.interleave(picks, lambda p: p.subject, lambda p: p.chapter_id)


# --- DB -------------------------------------------------------------------------------------------

_OPEN = (QuizStatus.pending, QuizStatus.active)


async def _open_quiz(scope: OrgScope, *, for_update: bool = False) -> Quiz | None:
    stmt = scope.select(Quiz).where(Quiz.student_id == scope.user.id, Quiz.status.in_(_OPEN))
    if for_update:
        stmt = stmt.with_for_update()
    return await scope.session.scalar(stmt)


async def _mark(scope: OrgScope) -> int:
    """The XP mark of the next quiz (150 with none yet), above every earlier quiz's mark."""
    last = await scope.session.scalar(
        scope.select(Quiz)
        .with_only_columns(Quiz.next_mark)
        .where(Quiz.student_id == scope.user.id, Quiz.next_mark.is_not(None))
        .order_by(Quiz.finished_at.desc().nulls_last(), Quiz.created_at.desc())
        .limit(1)
    )
    highest = await scope.session.scalar(
        scope.select(Quiz)
        .with_only_columns(func.max(Quiz.xp_mark))
        .where(Quiz.student_id == scope.user.id)
    )
    mark = QUIZ_MARK if last is None else int(last)
    return mark if highest is None else max(mark, int(highest) + 1)


async def _learned_gradable(scope: OrgScope) -> list[uuid.UUID]:
    graph = await learn._graph(scope)
    learned = (
        await scope.session.scalars(
            scope.select(ConceptState)
            .with_only_columns(ConceptState.concept_id)
            .where(
                ConceptState.student_id == scope.user.id,
                ConceptState.status == ConceptStatus.learned,
            )
        )
    ).all()
    active = [c for c in learned if c in graph.nodes]
    gradable = await srs.gradable(scope, active)
    return sorted((c for c in active if c in gradable), key=str)


async def maybe_create(scope: OrgScope) -> None:
    """After an award (same transaction): create a pending quiz once lifetime XP reaches the mark
    and the student has >= 3 learned concepts with gradable items."""
    if scope.user.is_staff or await _open_quiz(scope) is not None:
        return
    mark = await _mark(scope)
    lifetime = await xp.lifetime_xp(scope)
    if lifetime < mark:
        return
    if not should_create(lifetime, mark, len(await _learned_gradable(scope))):
        return
    await scope.session.execute(
        insert(Quiz)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            xp_mark=mark,
            status=QuizStatus.pending,
        )
        .on_conflict_do_nothing()
    )


async def ensure_no_pending(scope: OrgScope) -> None:
    """409 `quiz_pending` while a quiz is due (an active one past its deadline finishes first)."""
    quiz = await _open_quiz(scope, for_update=True)
    if quiz is None:
        return
    if await _finish_if_over(scope, quiz, datetime.now(UTC)):
        return
    raise kp_flow._conflict(
        "quiz_pending", "Take your quiz to keep learning.", quiz_id=str(quiz.id)
    )


async def _own(scope: OrgScope, quiz_id: str) -> Quiz:
    """The caller's own quiz, row-locked (404 for anyone else's; staff 403)."""
    learn._require_student(scope)
    try:
        qid = uuid.UUID(quiz_id)
    except ValueError as exc:
        raise not_found() from exc
    quiz = await scope.get(Quiz, qid, for_update=True)
    if quiz.student_id != scope.user.id:
        raise not_found()
    return quiz


async def _session(scope: OrgScope, quiz: Quiz) -> PracticeSession | None:
    return await scope.session.scalar(
        scope.select(PracticeSession).where(PracticeSession.quiz_id == quiz.id).with_for_update()
    )


async def _items(scope: OrgScope, quiz: Quiz) -> list[QuizItem]:
    rows = await scope.session.scalars(
        scope.select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.position)
    )
    return list(rows.all())


async def _attempts(scope: OrgScope, session: PracticeSession | None) -> dict[int, Attempt]:
    if session is None:
        return {}
    rows = await scope.session.scalars(
        scope.select(Attempt).where(Attempt.session_id == session.id)
    )
    return {a.position or 0: a for a in rows.all()}


async def _state(scope: OrgScope, quiz: Quiz, now: datetime) -> QuizState:
    answered = len(await _attempts(scope, await _session(scope, quiz)))
    total = quiz.total if quiz.total is not None else QUIZ_SIZE
    left = None
    if quiz.status == QuizStatus.active and quiz.deadline is not None:
        left = max(0, int((quiz.deadline - now).total_seconds()))
    return QuizState(
        id=str(quiz.id),
        status=quiz.status.value,
        total=total,
        minutes=minutes_for(total),
        deadline=quiz.deadline,
        seconds_left=left,
        answered=answered,
    )


async def _finish_if_over(
    scope: OrgScope, quiz: Quiz, now: datetime, *, grace: bool = False
) -> bool:
    """Finish an active quiz whose time is up (unanswered questions count as wrong)."""
    if quiz.status != QuizStatus.active or quiz.deadline is None:
        return False
    over = is_late(now, quiz.deadline) if grace else is_over(now, quiz.deadline)
    if not over:
        return False
    await _finish(scope, quiz, now)
    return True


async def _subjects(
    scope: OrgScope, concept_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Subject]:
    rows = await scope.session.execute(
        select(Concept.id, Course.subject)
        .join(Course, Course.id == Concept.course_id)
        .where(Concept.id.in_(concept_ids))
    )
    return {cid: subject for cid, subject in rows.all()}


async def _finish(scope: OrgScope, quiz: Quiz, now: datetime) -> None:
    session = await _session(scope, quiz)
    assert session is not None
    items = await _items(scope, quiz)
    attempts = await _attempts(scope, session)
    rows = {
        i.id: i
        for i in (
            await scope.session.scalars(select(Item).where(Item.id.in_([q.item_id for q in items])))
        ).all()
    }
    correct = {q.position: q.position in attempts and attempts[q.position].correct for q in items}
    quiz.correct = sum(correct.values())
    quiz.total = len(items)
    quiz.finished_at = now
    quiz.status = QuizStatus.finished
    session.status = SessionStatus.passed
    session.ended_at = now
    await scope.session.flush()
    missed = {q.concept_id for q in items if not correct[q.position]}
    subject_of = await _subjects(scope, {q.concept_id for q in items})
    parts: dict[Subject, xp.QuizSubject] = {}
    for q in items:
        a = attempts.get(q.position)
        pos = xp.QuizPos(
            rows[q.item_id].expected_minutes,
            correct[q.position],
            answered=a is not None,
            time_ms=0 if a is None else a.time_taken_ms,
        )
        subject = subject_of[q.concept_id]
        if subject not in parts:
            parts[subject] = xp.QuizSubject(q.concept_id, [])
        parts[subject].positions.append(pos)
    await xp.award_for_quiz(scope, session, parts)
    # After the XP rows, as on the review and KP paths (same lock order: xp_day, then cards).
    await srs.mark_quiz_miss(scope, missed, quiz.id)
    quiz.next_mark = next_mark(await xp.lifetime_xp(scope))
    await scope.session.flush()


async def current(scope: OrgScope) -> QuizState | None:
    """The student's pending or active quiz (an active one past its deadline finishes)."""
    learn._require_student(scope)
    quiz = await _open_quiz(scope, for_update=True)
    if quiz is None:
        return None
    now = datetime.now(UTC)
    await _finish_if_over(scope, quiz, now)
    out = await _state(scope, quiz, now)
    await scope.session.commit()
    return None if out.status == "finished" else out


async def state(scope: OrgScope, quiz_id: str) -> QuizState:
    quiz = await _own(scope, quiz_id)
    now = datetime.now(UTC)
    await _finish_if_over(scope, quiz, now)
    out = await _state(scope, quiz, now)
    await scope.session.commit()
    return out


async def _candidates(scope: OrgScope) -> list[QuizConcept]:
    """Learned concepts with quick checks, lowest retrievability first (ties by id)."""
    concept_ids = await _learned_gradable(scope)
    if not concept_ids:
        return []
    graph = await learn._graph(scope)
    now = datetime.now(UTC)
    cards = {
        c.concept_id: c
        for c in (
            await scope.session.scalars(
                scope.select(ReviewCard).where(
                    ReviewCard.student_id == scope.user.id, ReviewCard.concept_id.in_(concept_ids)
                )
            )
        ).all()
    }

    def recall(cid: uuid.UUID) -> float:
        card = cards.get(cid)
        return 0.0 if card is None else srs.retrievability(card.stability, card.last_review, now)

    kps = [k for k in await frontier.active_kps(scope, concept_ids) if k.quick]
    items = (
        await scope.session.scalars(
            select(Item)
            .where(
                Item.kp_id.in_([k.id for k in kps]),
                Item.kind == ItemKind.kp_question,
                Item.type.in_(QUICK_TYPES),
                Item.retired_at.is_(None),
            )
            .order_by(Item.position)
        )
    ).all()
    history = dict(
        (
            await scope.session.execute(
                scope.select(Attempt)
                .with_only_columns(Attempt.item_id, func.max(Attempt.created_at))
                .where(
                    Attempt.student_id == scope.user.id, Attempt.item_id.in_([i.id for i in items])
                )
                .group_by(Attempt.item_id)
            )
        ).all()
    )
    floor = datetime.min.replace(tzinfo=UTC)
    out = []
    for cid in sorted(concept_ids, key=lambda c: (recall(c), str(c))):
        pools = []
        for kp in (k for k in kps if k.concept_id == cid):
            pool = [i for i in items if i.kp_id == kp.id]
            order = {
                k: n
                for n, k in enumerate(
                    learn.shuffled_order([str(i.id) for i in pool], scope.user.id, kp.id)
                )
            }

            def key(i: Item, order: dict[str, int] = order) -> tuple[bool, datetime, int]:
                when = history.get(i.id)
                return (when is not None, when or floor, order[str(i.id)])

            pools.append([Candidate(i.id, i.has_params) for i in sorted(pool, key=key)])
        node = graph.nodes[cid]
        out.append(QuizConcept(cid, node.subject.value, node.chapter_id, pools))
    return out


async def start(scope: OrgScope, quiz_id: str) -> QuizState:
    """Start the timer (idempotent): choose and store the questions, open the quiz's session.
    With no learned concept left (all relearning) the quiz is cancelled."""
    quiz = await _own(scope, quiz_id)
    now = datetime.now(UTC)
    if quiz.status == QuizStatus.pending:
        picks = choose_items(await _candidates(scope))
        if not picks:
            quiz.status = QuizStatus.cancelled
            quiz.finished_at = now
            quiz.next_mark = next_mark(await xp.lifetime_xp(scope))
        else:
            for n, p in enumerate(picks, start=1):
                scope.session.add(
                    QuizItem(
                        org_id=scope.org_id,
                        quiz_id=quiz.id,
                        position=n,
                        item_id=p.item_id,
                        concept_id=p.concept_id,
                        seed=secrets.randbelow(2**31) if p.has_params else None,
                    )
                )
            await scope.session.flush()
            first = (await _items(scope, quiz))[0]
            quiz.status = QuizStatus.active
            quiz.started_at = now
            quiz.total = len(picks)
            quiz.deadline = deadline_for(now, len(picks))
            scope.session.add(
                PracticeSession(
                    org_id=scope.org_id,
                    student_id=scope.user.id,
                    kind=SessionKind.quiz,
                    quiz_id=quiz.id,
                    status=SessionStatus.active,
                    current_item_id=first.item_id,
                    current_seed=first.seed,
                    current_position=1,
                    current_served_at=now,
                    started_at=now,
                )
            )
            await scope.session.flush()
    else:
        await _finish_if_over(scope, quiz, now)
    out = await _state(scope, quiz, now)
    await scope.session.commit()
    return out


def _over() -> Exception:
    return kp_flow._conflict("quiz_over", "Time's up: this quiz has finished.")


def _not_started() -> Exception:
    return kp_flow._conflict("quiz_not_started", "Start the quiz first.")


async def question(scope: OrgScope, quiz_id: str) -> QuestionPublic:
    """The current question, with no results (no feedback until the end) and the deadline."""
    quiz = await _own(scope, quiz_id)
    if quiz.status == QuizStatus.pending:
        raise _not_started()
    now = datetime.now(UTC)
    await _finish_if_over(scope, quiz, now)
    if quiz.status != QuizStatus.active:
        await scope.session.commit()
        raise _over()
    session = await _session(scope, quiz)
    assert session is not None and session.current_item_id is not None
    item = await scope.session.get(Item, session.current_item_id)
    assert item is not None
    out = await kp_flow._question(
        scope,
        item,
        session.current_seed,
        session_id=session.id,
        position=session.current_position,
        results=[],
    )
    out.deadline = quiz.deadline
    await scope.session.commit()
    return out


async def answer(scope: OrgScope, quiz_id: str, body: AnswerIn) -> QuizSaved:
    """Grade and store the answer; reply only "saved" (correctness comes with the result)."""
    quiz = await _own(scope, quiz_id)
    if quiz.status == QuizStatus.pending:
        raise _not_started()
    now = datetime.now(UTC)
    session = await _session(scope, quiz)
    if await _finish_if_over(scope, quiz, now, grace=True):
        await scope.session.commit()
    attempts = await _attempts(scope, session)
    if quiz.status != QuizStatus.active or session is None:
        if session is not None and body.position in attempts:  # a resend of a saved answer
            return QuizSaved(answered=len(attempts), finished=True)
        raise _over()
    sent = kp_flow._session_uuid(body)
    if sent is not None and sent != session.id:
        raise kp_flow._conflict("stale_question", "That question is no longer current.")
    if body.position != session.current_position or body.position in attempts:
        if body.position in attempts:
            return QuizSaved(answered=len(attempts), finished=False)
        raise kp_flow._conflict("stale_question", "That question is no longer current.")
    assert session.current_item_id is not None
    item = await scope.session.get(Item, session.current_item_id)
    assert item is not None
    graded = await kp_flow._grade_answer(scope, item, session.current_seed, body)
    misconception_id, _ = await kp_flow._misconception(scope, item, graded.result.misconception)
    elapsed = int((now - (session.current_served_at or now)).total_seconds() * 1000)
    inserted = await scope.session.scalar(
        insert(Attempt)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            item_id=item.id,
            item_version=item.version,
            context=AttemptContext.quiz,
            seed=session.current_seed,
            response=graded.response,
            correct=graded.result.correct,
            misconception_id=misconception_id,
            time_taken_ms=max(0, min(body.time_taken_ms, elapsed, kp_flow.MAX_ANSWER_MS)),
            hints_used=0,
            session_id=session.id,
            position=session.current_position,
            step=0,
        )
        .on_conflict_do_nothing(index_elements=[Attempt.session_id, Attempt.position, Attempt.step])
        .returning(Attempt.id)
    )
    if inserted is None:  # can't happen while we hold the quiz lock
        return QuizSaved(answered=len(attempts), finished=False)
    answered = len(attempts) + 1
    items = await _items(scope, quiz)
    finished = session.current_position >= len(items)
    if finished:
        await _finish(scope, quiz, now)
    else:
        nxt = items[session.current_position]  # positions are 1-based
        session.current_item_id = nxt.item_id
        session.current_seed = nxt.seed
        session.current_position = nxt.position
        session.current_served_at = now
    await scope.session.commit()
    return QuizSaved(answered=answered, finished=finished)


async def _concept_refs(scope: OrgScope, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, ConceptRef]:
    rows = await scope.session.execute(
        select(Concept.id, Concept.slug, Concept.title, Course.slug)
        .join(Course, Course.id == Concept.course_id)
        .where(Concept.id.in_(ids))
    )
    return {
        cid: ConceptRef(id=f"{course}/{slug}", title=title) for cid, slug, title, course in rows
    }


async def _texts(
    scope: OrgScope, item: Item, seed: int | None, attempt: Attempt | None
) -> tuple[str | None, str]:
    """(the student's answer, the correct answer for their numbers) as display text."""
    kind = item.type.value
    if kind == "mcq":
        texts = {o.id: o.text for o in learn._shown_options(scope, item).authored}
        chosen = None if attempt is None else texts.get(str(attempt.response.get("option")), "")
        return chosen, texts.get(str(item.answer.get("correct")), "")
    values = params.sample_answer(item.answer, seed)
    raw: Any = "" if attempt is None else attempt.response.get("raw", "")
    unit = None if attempt is None else attempt.response.get("unit")
    graded = await kp_flow._grade_quick(kind, item.answer, values, str(raw), unit, None)
    if attempt is None:
        return None, graded.display_answer
    shown = str(raw) if not unit else f"{raw} {unit}"
    return shown, graded.display_answer


async def result(scope: OrgScope, quiz_id: str) -> QuizResult:
    quiz = await _own(scope, quiz_id)
    now = datetime.now(UTC)
    await _finish_if_over(scope, quiz, now)
    if quiz.status != QuizStatus.finished:
        await scope.session.commit()
        raise kp_flow._conflict("quiz_not_finished", "This quiz hasn't finished yet.")
    session = await _session(scope, quiz)
    assert session is not None
    items = await _items(scope, quiz)
    attempts = await _attempts(scope, session)
    rows = {
        i.id: i
        for i in (
            await scope.session.scalars(select(Item).where(Item.id.in_([q.item_id for q in items])))
        ).all()
    }
    refs = await _concept_refs(scope, {q.concept_id for q in items})
    out_items = []
    missed: list[uuid.UUID] = []
    for q in items:
        item = rows[q.item_id]
        attempt = attempts.get(q.position)
        correct = attempt is not None and attempt.correct
        shown = await kp_flow._question(
            scope, item, q.seed, session_id=None, position=q.position, results=[]
        )
        response, display = await _texts(scope, item, q.seed, attempt)
        out_items.append(
            QuizResultItem(
                position=q.position,
                concept=refs[q.concept_id],
                type=item.type.value,
                prompt_md=shown.prompt_md,
                response=response,
                correct=correct,
                display_answer=display,
                explanation_md=kp_flow._explanation(
                    item, params.sample_answer(item.answer, q.seed)
                ),
            )
        )
        if not correct and q.concept_id not in missed:
            missed.append(q.concept_id)
    out = QuizResult(
        correct=quiz.correct or 0,
        total=quiz.total or len(items),
        xp=await xp.quiz_events_out(scope, session.id),
        items=out_items,
        review_concepts=[refs[c] for c in missed],
    )
    await scope.session.commit()
    return out


async def last_quiz_stats(
    scope: OrgScope, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, LastQuizOut]:
    """Staff roster: each student's last finished quiz. Read-only."""
    if not student_ids:
        return {}
    rows = (
        await scope.session.scalars(
            scope.select(Quiz)
            .where(Quiz.student_id.in_(student_ids), Quiz.status == QuizStatus.finished)
            .order_by(Quiz.student_id, Quiz.finished_at.desc())
            .ext(distinct_on(Quiz.student_id))
        )
    ).all()
    out = {}
    for q in rows:
        if q.finished_at is None or not q.total:
            continue
        out[q.student_id] = LastQuizOut(
            score_pct=round(100 * (q.correct or 0) / q.total), finished_on=q.finished_at
        )
    return out
