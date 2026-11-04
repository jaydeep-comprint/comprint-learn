"""The lesson's Practice step (spec 006): one multi-step problem or Python task per attempt.

Practice opens once every active KP is passed (409 `practice_locked`). Each attempt is a
`practice_session` (kind `practice`) holding one item; it passes or fails with that item. A pass
makes the concept learned. A fail allows an immediate retry: a code task comes back as the same
item with the last submitted code; a multi-step problem draws the next item (or new numbers).
Staff previews and "Practise again" on a learned concept grade without writing anything.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import text

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, not_found
from app.models import (
    Attempt,
    AttemptContext,
    Item,
    PracticeSession,
    SessionKind,
    SessionStatus,
)
from app.models.content import ItemKind, ItemType
from app.schemas.kp import AnswerIn, AnswerResult, QuestionPublic
from app.schemas.learn import ConceptRef
from app.services import frontier, kp_flow, learn

# Index predicate as a SQL literal, never a bound parameter (see learn.LEARN_ATTEMPT_INDEX_WHERE).
_ACTIVE_PRACTICE_WHERE = text("status = 'active' AND kind = 'practice'")


def _conflict(code: str, detail: str) -> ApiProblem:
    return ApiProblem(409, code, detail)


async def _pool(scope: OrgScope, concept_id: uuid.UUID) -> list[Item]:
    """The concept's active practice items, in authored order."""
    rows = await scope.session.scalars(
        select(Item)
        .where(
            Item.concept_id == concept_id,
            Item.kind == ItemKind.practice,
            Item.retired_at.is_(None),
        )
        .order_by(Item.position)
    )
    return list(rows.all())


async def _locked_session(scope: OrgScope, concept_id: uuid.UUID) -> PracticeSession | None:
    """The student's latest practice session for this concept, row-locked."""
    return await scope.session.scalar(
        scope.select(PracticeSession)
        .where(
            PracticeSession.student_id == scope.user.id,
            PracticeSession.kind == SessionKind.practice,
            PracticeSession.concept_id == concept_id,
        )
        .order_by(PracticeSession.started_at.desc())
        .limit(1)
        .with_for_update()
    )


def _preview_mode(scope: OrgScope, view: "frontier.ConceptView | None", again: bool) -> bool:
    """Staff always preview; a student previews ("Practise again") once the concept is learned."""
    if scope.user.is_staff:
        return True
    assert view is not None
    if view.status == "learned" or view.practice == "passed":
        if again:
            return True
        raise _conflict("practice_passed", "You've already passed this practice.")
    return False


def _gate(view: "frontier.ConceptView") -> None:
    if view.next_kp is not None:
        raise _conflict("practice_locked", "Pass every part first, then practise.")


async def _last_code(scope: OrgScope, item: Item) -> str | None:
    """The student's last submitted code for this practice item (the editor starts from it)."""
    if item.type != ItemType.code:
        return None
    response = await scope.session.scalar(
        scope.select(Attempt)
        .with_only_columns(Attempt.response)
        .where(
            Attempt.student_id == scope.user.id,
            Attempt.item_id == item.id,
            Attempt.context == AttemptContext.practice,
        )
        .order_by(Attempt.created_at.desc())
        .limit(1)
    )
    code = None if response is None else response.get("code")
    return code if isinstance(code, str) else None


async def _choose(
    scope: OrgScope, concept_id: uuid.UUID, pool: list[Item], last: PracticeSession | None
) -> Item:
    """After a failed code task: the same item (unless retired). Otherwise the least recently
    answered item in this student's order (`choose_next_item`); one item repeats with new
    numbers."""
    if last is not None and last.status == SessionStatus.failed:
        same = next((i for i in pool if i.id == last.current_item_id), None)
        if same is not None and same.type == ItemType.code:
            return same
    history = dict(
        (
            await scope.session.execute(
                scope.select(Attempt)
                .with_only_columns(Attempt.item_id, Attempt.created_at)
                .where(
                    Attempt.student_id == scope.user.id,
                    Attempt.item_id.in_([i.id for i in pool]),
                )
                .order_by(Attempt.created_at)
            )
        ).all()
    )
    by_id = {str(i.id): i for i in pool}
    order = [by_id[k].id for k in learn.shuffled_order(list(by_id), scope.user.id, concept_id)]
    chosen = kp_flow.choose_next_item(order, history, set(), {i.id for i in pool})
    if chosen is None:  # no param items and every item was served: any item may come again
        chosen = kp_flow.choose_next_item(order, history, set(), set(order))
    assert chosen is not None
    return next(i for i in pool if i.id == chosen)


async def _start(
    scope: OrgScope, concept_id: uuid.UUID, pool: list[Item], last: PracticeSession | None
) -> PracticeSession:
    session_id = await scope.session.scalar(
        insert(PracticeSession)
        .values(
            id=uuid.uuid4(),
            org_id=scope.org_id,
            student_id=scope.user.id,
            kind=SessionKind.practice,
            concept_id=concept_id,
            status=SessionStatus.active,
            current_position=1,
        )
        .on_conflict_do_nothing(
            index_elements=[PracticeSession.student_id, PracticeSession.concept_id],
            index_where=_ACTIVE_PRACTICE_WHERE,
        )
        .returning(PracticeSession.id)
    )
    if session_id is None:  # another tab started it first: use that one
        winner = await _locked_session(scope, concept_id)
        assert winner is not None
        return winner
    await frontier.ensure_started(scope, concept_id)
    session = await scope.session.get(PracticeSession, session_id)
    assert session is not None
    item = await _choose(scope, concept_id, pool, last)
    await kp_flow.serve_item(scope, session, item, 1)
    return session


async def practice_question(
    scope: OrgScope, course: str, concept: str, *, again: bool = False
) -> QuestionPublic:
    """The active attempt's question (the same one on reload), or a new attempt.

    409 `practice_locked` until every KP is passed; 409 `practice_passed` once passed (unless
    `again`, which previews without writing)."""
    access = await learn._access(scope, course, concept)
    cid = access.node.id
    pool = await _pool(scope, cid)
    if not pool:
        raise not_found()
    view = access.view
    if _preview_mode(scope, view, again):
        return await kp_flow.preview_question(scope, pool)
    assert view is not None
    _gate(view)

    session = await _locked_session(scope, cid)
    if session is None or session.status != SessionStatus.active:
        session = await _start(scope, cid, pool, session)
    elif session.current_item_id not in {i.id for i in pool}:  # retired mid-attempt
        item = await _choose(scope, cid, pool, None)
        await kp_flow.serve_item(scope, session, item, session.current_position)
    current = await scope.session.get(Item, session.current_item_id)
    assert current is not None
    out = await kp_flow.session_question(scope, session, prefill=await _last_code(scope, current))
    await scope.session.commit()
    return out


async def practice_answer(
    scope: OrgScope, course: str, concept: str, body: AnswerIn, *, again: bool = False
) -> AnswerResult:
    access = await learn._access(scope, course, concept)
    cid = access.node.id
    pool = await _pool(scope, cid)
    if not pool:
        raise not_found()
    view = access.view
    if not again and view is not None and view.practice == "passed":
        # A resent passing answer (lost response) still gets its stored result.
        session = await _locked_session(scope, cid)
        if session is not None and session.status != SessionStatus.active:
            try:
                stored = await kp_flow.answer_in_session(
                    scope,
                    session,
                    body,
                    AttemptContext.practice,
                    kp_flow.single_item_outcome,
                    "on_pass",
                )
            except ApiProblem:
                stored = None  # not a repeat: 409 practice_passed below
            if isinstance(stored, AnswerResult):
                await scope.session.rollback()
                return stored
    if _preview_mode(scope, view, again):
        return await kp_flow.preview_answer(scope, pool, body)
    assert view is not None

    session = await _locked_session(scope, cid)
    answered = await kp_flow.answer_in_session(
        scope,
        session,
        body,
        AttemptContext.practice,
        kp_flow.single_item_outcome,
        rule="on_pass",
    )
    if isinstance(answered, AnswerResult):
        await scope.session.rollback()
        return answered
    out = answered.result
    if answered.outcome == "passed":
        out.concept_learned, out.unlocked = await _on_practice_passed(scope, access)
    await scope.session.commit()
    return out


async def _on_practice_passed(
    scope: OrgScope, access: "learn._Access"
) -> tuple[bool, list[ConceptRef]]:
    """Practice passed: the concept is learned once its KPs are too (they are: Practice opens
    only then, but a KP added since keeps it in progress)."""
    graph = access.graph
    cid = access.node.id
    front = await frontier.load(scope, [cid], graph.prereqs, promote=False)
    view = front.views[cid]
    if view.status == "learned" or not frontier.complete(view):
        return False, []
    return True, await kp_flow.learned_and_unlocked(scope, graph, cid)
