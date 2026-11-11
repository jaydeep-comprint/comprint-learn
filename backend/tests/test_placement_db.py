"""Placement (spec 012) against a real database: sending, taking and applying a diagnostic."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fsrs import Rating
from sqlalchemy import delete, select, update

from app.api.deps import CurrentUser, OrgScope
from app.content.importer import import_tree
from app.models import (
    Attempt,
    AttemptContext,
    Chapter,
    ConceptSource,
    ConceptState,
    ConceptStatus,
    Course,
    DiagnosticSession,
    Enrollment,
    PracticeSession,
    ReviewCard,
    ReviewLog,
    ReviewSource,
    Role,
    SessionKind,
    SessionStatus,
    XpEvent,
)
from app.services import dashboard, srs
from app.services.srs import ist_day
from tests import content_fixtures as fx
from tests.conftest import DbApp
from tests.db_seed import seed_school
from tests.learn_helpers import (
    LIN,
    MATHS,
    World,
    answer_check,
    answer_fields,
    count,
    get,
    keys,
    url,
    world,
)
from tests.review_helpers import concept_id, seed_learned

pytestmark = pytest.mark.db

GRAPH = f"{MATHS}/pair-of-linear-equations-graphical"
ALG = f"{MATHS}/pair-of-linear-equations-algebraic"
SECRET_KEYS = {"answer", "correct", "explanation", "spec", "params", "derived"}


def tab(class_id: uuid.UUID, tail: str = "") -> str:
    return f"/api/v1/classes/{class_id}/placement{tail}"


def diag_path(did: str, tail: str = "") -> str:
    return f"/api/v1/diagnostics/{did}{tail}"


async def chapter_id(db: DbApp, course: str, slug: str) -> uuid.UUID:
    async with db.sessions() as session:
        cid = await session.scalar(
            select(Chapter.id)
            .join(Course, Course.id == Chapter.course_id)
            .where(Course.slug == course, Chapter.slug == slug)
        )
        assert cid is not None
        return cid


async def put_chapters(db: DbApp, w: World, chapters: list[uuid.UUID]) -> Any:
    r = await db.client.put(
        tab(w.a.class_ids[0], "/chapters"),
        json={"chapter_ids": [str(c) for c in chapters]},
        headers=db.auth(w.a.teacher_id),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def send_all(db: DbApp, w: World) -> Any:
    r = await db.client.post(
        tab(w.a.class_ids[0], "/send"), json={"all_students": True}, headers=db.auth(w.a.teacher_id)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def setup_sent(db: DbApp) -> World:
    """Real content; maths chapter 2 (graphical + algebraic, with linear equations as the
    prerequisite from chapter 1) covered and sent to the maths class."""
    w = await world(db)
    await put_chapters(db, w, [await chapter_id(db, MATHS, "pair-of-linear-equations")])
    assert (await send_all(db, w)) == {"sent": 3, "skipped": 0}
    return w


async def open_id(db: DbApp, student: uuid.UUID) -> str:
    current = await get(db, student, "/api/v1/diagnostics/current")
    assert len(current) == 1
    return str(current[0]["id"])


async def run(db: DbApp, student: uuid.UUID, did: str, *, mode: str = "correct") -> list[Any]:
    """Start and answer every question (`correct`, `wrong` or `idk`); returns the replies."""
    r = await db.client.post(diag_path(did, "/start"), headers=db.auth(student))
    assert r.status_code == 200, r.text
    replies = []
    for _ in range(30):
        if r.json().get("finished") or r.json().get("status") == "finished":
            break
        q = await get(db, student, diag_path(did, "/question"))
        assert not keys(q) & SECRET_KEYS and q["results"] == []
        body: dict[str, Any] = {"position": q["position"], "time_taken_ms": 2000}
        if mode == "idk":
            body |= {"session_id": q["session_id"], "idk": True}
        else:
            body |= await answer_fields(db, q, correct=mode == "correct")
        r = await db.client.post(diag_path(did, "/answer"), json=body, headers=db.auth(student))
        assert r.status_code == 200, r.text
        assert set(r.json()) == {"finished", "answered"}
        replies.append(r.json())
    assert replies and replies[-1]["finished"]
    return replies


async def states(db: DbApp, student: uuid.UUID) -> dict[uuid.UUID, ConceptState]:
    async with db.sessions() as session:
        rows = (
            await session.scalars(select(ConceptState).where(ConceptState.student_id == student))
        ).all()
        return {r.concept_id: r for r in rows}


def scope_for(session: Any, w: World, student: uuid.UUID) -> OrgScope:
    return OrgScope(session, CurrentUser(student, w.a.org_id, Role.student, False, False))


# --- teacher ----------------------------------------------------------------------------------


async def test_send_needs_chapters_and_skips_existing(db_app: DbApp) -> None:
    w = await world(db_app)
    cid, teacher = w.a.class_ids[0], db_app.auth(w.a.teacher_id)
    r = await db_app.client.post(tab(cid, "/send"), json={"all_students": True}, headers=teacher)
    assert (
        r.status_code == 422 and r.json()["message"] == "Tick at least one covered chapter first."
    )

    physics_ch = await chapter_id(db_app, "physics-9-10", "motion")
    r = await db_app.client.put(
        tab(cid, "/chapters"), json={"chapter_ids": [str(physics_ch)]}, headers=teacher
    )
    assert r.status_code == 422 and r.json()["code"] == "chapter_not_in_course"

    ch2 = await chapter_id(db_app, MATHS, "pair-of-linear-equations")
    data = await put_chapters(db_app, w, [ch2])
    covered = {c["slug"]: c["covered"] for c in data["chapters"]}
    assert covered.pop("pair-of-linear-equations") is True
    assert covered and not any(covered.values())
    assert data["range"] == {"concepts": 3, "prereqs": 1, "askable": 3}
    assert {s["status"] for s in data["students"]} == {"not_sent"}

    assert await send_all(db_app, w) == {"sent": 3, "skipped": 0}
    assert await send_all(db_app, w) == {"sent": 0, "skipped": 3}
    one = await db_app.client.post(
        tab(cid, "/send"), json={"student_ids": [str(w.a.student_ids[0])]}, headers=teacher
    )
    assert one.json() == {"sent": 0, "skipped": 1}
    other = await db_app.client.post(
        tab(cid, "/send"), json={"student_ids": [str(w.a.student_ids[3])]}, headers=teacher
    )
    assert other.status_code == 422 and other.json()["code"] == "students_not_in_class"
    overview = await get(db_app, w.a.teacher_id, tab(cid))
    assert {s["status"] for s in overview["students"]} == {"sent"}


async def test_cancel_and_resend_rules(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    cid, s, teacher = w.a.class_ids[0], w.a.student_ids[0], db_app.auth(w.a.teacher_id)
    student_tab = tab(cid, f"/students/{s}")

    r = await db_app.client.post(f"{student_tab}/resend", headers=teacher)
    assert r.status_code == 409 and r.json()["code"] == "diagnostic_open"
    did = await open_id(db_app, s)
    r = await db_app.client.post(f"{student_tab}/cancel", headers=teacher)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert await get(db_app, s, "/api/v1/diagnostics/current") == []
    r = await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    assert r.status_code == 409 and r.json()["code"] == "diagnostic_closed"
    r = await db_app.client.post(f"{student_tab}/cancel", headers=teacher)
    assert r.status_code == 409 and r.json()["code"] == "diagnostic_closed"

    # Sending to the class again offers a new one only to the cancelled student.
    assert await send_all(db_app, w) == {"sent": 1, "skipped": 2}
    await db_app.client.post(f"{student_tab}/cancel", headers=teacher)
    r = await db_app.client.post(f"{student_tab}/resend", headers=teacher)
    assert r.status_code == 200 and r.json()["status"] == "sent"

    # A finished one needs Re-send; the results applied stay.
    await run(db_app, s, await open_id(db_app, s))
    assert await send_all(db_app, w) == {"sent": 0, "skipped": 3}
    r = await db_app.client.post(f"{student_tab}/resend", headers=teacher)
    assert r.status_code == 200 and r.json()["status"] == "sent"
    assert r.json()["counts"] is not None and r.json()["result_at"] is not None
    assert await count(db_app, DiagnosticSession, student_id=s) == 4


# --- taking it ----------------------------------------------------------------------------------


async def test_all_correct_places_concepts_without_xp(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    did = await open_id(db_app, s)
    await run(db_app, s, did)

    rows = await states(db_app, s)
    ids = {ref: await concept_id(db_app, ref) for ref in (LIN, GRAPH, ALG)}
    assert all(rows[c].status == ConceptStatus.learned for c in ids.values())
    assert all(rows[c].source == ConceptSource.diagnostic for c in ids.values())
    assert await count(db_app, XpEvent, student_id=s) == 0
    assert await count(db_app, Attempt, student_id=s, context=AttemptContext.diagnostic) >= 1

    today = datetime.now(UTC)
    async with db_app.sessions() as session:
        cards = {c.concept_id: c for c in (await session.scalars(select(ReviewCard))).all()}
        logs = (await session.scalars(select(ReviewLog).where(ReviewLog.student_id == s))).all()
    assert {log.source for log in logs} == {ReviewSource.placed}
    for cid in ids.values():
        rating = Rating.Hard if rows[cid].conditional else Rating.Good
        assert ist_day(cards[cid].due) == ist_day(srs.first_review(today, rating).due)

    result = await get(db_app, s, diag_path(did, "/result"))
    placed = {c["id"] for c in result["learned"] + result["conditional"]}
    assert placed == {LIN, GRAPH, ALG} and result["to_learn"] == []
    assert {c["id"] for c in result["conditional"]} == {
        ref for ref, cid in ids.items() if rows[cid].conditional
    }
    outline = await get(db_app, s, f"/api/v1/learn/courses/{MATHS}/outline")
    concepts = [c for ch in outline["chapters"] for c in ch["concepts"] if c["id"] in placed]
    assert len(concepts) == 3
    assert all(c["placed"] and c["parts_passed"] == c["parts_total"] for c in concepts)

    teacher = await get(db_app, w.a.teacher_id, tab(w.a.class_ids[0], f"/students/{s}"))
    assert {c["outcome"] for c in teacher["concepts"]} <= {"learned", "conditional"}
    row = next(
        r
        for r in (await get(db_app, w.a.teacher_id, tab(w.a.class_ids[0])))["students"]
        if r["student_id"] == str(s)
    )
    assert row["status"] == "finished"
    assert row["counts"]["learned"] + row["counts"]["conditional"] == 3


async def test_idk_demotes_a_lesson_learned_concept(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[1]
    await seed_learned(db_app, w.a.org_id, s, [LIN])
    did = await open_id(db_app, s)
    await run(db_app, s, did, mode="idk")

    lin = (await states(db_app, s))[await concept_id(db_app, LIN)]
    assert lin.status == ConceptStatus.in_progress and lin.relearn_count == 1
    result = await get(db_app, s, diag_path(did, "/result"))
    assert result["learned"] == result["conditional"] == []
    assert {c["id"] for c in result["to_learn"]} == {LIN, GRAPH, ALG}
    async with db_app.sessions() as session:
        idk = (
            await session.scalars(
                select(Attempt.response).where(Attempt.context == AttemptContext.diagnostic)
            )
        ).all()
    assert idk and all(r == {"idk": True} for r in idk)


async def test_pause_resend_and_stale_answers(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    did = await open_id(db_app, s)
    r = await db_app.client.get(diag_path(did, "/question"), headers=db_app.auth(s))
    assert r.status_code == 409 and r.json()["code"] == "diagnostic_not_started"
    await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    again = await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    assert again.json()["status"] == "active"  # idempotent

    q1 = await get(db_app, s, diag_path(did, "/question"))
    assert await get(db_app, s, diag_path(did, "/question")) == q1  # a reload: the same question
    body = {"position": q1["position"], "time_taken_ms": 1000} | await answer_fields(db_app, q1)
    first = await db_app.client.post(diag_path(did, "/answer"), json=body, headers=db_app.auth(s))
    resent = await db_app.client.post(diag_path(did, "/answer"), json=body, headers=db_app.auth(s))
    assert resent.json() == {"finished": False, "answered": 1} == first.json()
    assert await count(db_app, Attempt, student_id=s) == 1

    future = body | {"position": q1["position"] + 5}
    r = await db_app.client.post(diag_path(did, "/answer"), json=future, headers=db_app.auth(s))
    assert r.status_code == 409 and r.json()["code"] == "stale_question"
    other = body | {"session_id": str(uuid.uuid4()), "position": q1["position"] + 1}
    r = await db_app.client.post(diag_path(did, "/answer"), json=other, headers=db_app.auth(s))
    assert r.status_code == 409 and r.json()["code"] == "stale_question"

    # Finish; a network retry of the final answer gets the same reply.
    last: dict[str, Any] = {}
    for _ in range(30):
        q = await get(db_app, s, diag_path(did, "/question"))
        last = {"position": q["position"], "time_taken_ms": 1000} | await answer_fields(db_app, q)
        reply = await db_app.client.post(
            diag_path(did, "/answer"), json=last, headers=db_app.auth(s)
        )
        if reply.json()["finished"]:
            break
    n = await count(db_app, Attempt, student_id=s)
    retry = await db_app.client.post(diag_path(did, "/answer"), json=last, headers=db_app.auth(s))
    assert retry.status_code == 200 and retry.json()["finished"] is True
    assert await count(db_app, Attempt, student_id=s) == n
    async with db_app.sessions() as session:
        ps = await session.scalar(
            select(PracticeSession).where(PracticeSession.kind == SessionKind.diagnostic)
        )
        assert ps is not None and ps.status == SessionStatus.passed


async def test_promoting_an_in_progress_concept_ends_its_lesson_session(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[2]
    await get(db_app, s, url(LIN))  # opens the lesson (in progress)
    await answer_check(db_app, s, LIN)
    await get(db_app, s, url(LIN, "/kps/kp1/question"))  # an active KP session
    await run(db_app, s, await open_id(db_app, s))
    lin = (await states(db_app, s))[await concept_id(db_app, LIN)]
    assert lin.status == ConceptStatus.learned and lin.source == ConceptSource.diagnostic
    async with db_app.sessions() as session:
        kp_sessions = (
            await session.scalars(
                select(PracticeSession.status).where(PracticeSession.kind == SessionKind.kp)
            )
        ).all()
    assert kp_sessions == [SessionStatus.failed]
    assert await count(db_app, XpEvent, student_id=s) == 0


async def test_conditional_clears_on_the_first_review(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    await run(db_app, s, await open_id(db_app, s))
    lin = await concept_id(db_app, LIN)
    async with db_app.sessions() as session:
        await session.execute(
            update(ConceptState).where(ConceptState.student_id == s).values(conditional=True)
        )
        await session.commit()
    async with db_app.sessions() as session:
        info = await srs.apply_review(
            scope_for(session, w, s),
            lin,
            passed=True,
            all_correct=True,
            source=ReviewSource.review,
            session_id=None,
        )
        await session.commit()
    assert info is not None
    rows = await states(db_app, s)
    assert rows[lin].conditional is False
    assert any(r.conditional for cid, r in rows.items() if cid != lin)


async def test_tutor_is_off_in_a_diagnostic(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    did = await open_id(db_app, s)
    await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    q = await get(db_app, s, diag_path(did, "/question"))
    r = await db_app.client.get(
        f"/api/v1/tutor/{q['session_id']}/{q['position']}", headers=db_app.auth(s)
    )
    assert r.status_code == 409 and r.json()["code"] == "tutor_not_here"


async def test_diagnostic_attempts_stay_out_of_dashboard_accuracy(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    await run(db_app, s, await open_id(db_app, s), mode="wrong")
    ids = [await concept_id(db_app, ref) for ref in (LIN, GRAPH, ALG)]
    async with db_app.sessions() as session:
        staff = OrgScope(
            session, CurrentUser(w.a.teacher_id, w.a.org_id, Role.teacher, False, False)
        )
        assert await dashboard._questions(staff, [s], ids, None) == {}


# --- access ---------------------------------------------------------------------------------------


async def test_other_schools_students_and_unenrolled_are_404(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    did = await open_id(db_app, s)
    other_teacher = db_app.auth(w.b.teacher_id)
    assert (
        await db_app.client.get(tab(w.a.class_ids[0]), headers=other_teacher)
    ).status_code == 404
    r = await db_app.client.post(
        tab(w.b.class_ids[0], f"/students/{s}/cancel"), headers=other_teacher
    )
    assert r.status_code == 404
    for user in (w.a.student_ids[1], w.b.student_ids[0]):
        r = await db_app.client.get(diag_path(did), headers=db_app.auth(user))
        assert r.status_code == 404
    r = await db_app.client.get("/api/v1/diagnostics/current", headers=db_app.auth(w.a.teacher_id))
    assert r.status_code == 403
    r = await db_app.client.get(diag_path("not-a-uuid"), headers=db_app.auth(s))
    assert r.status_code == 404

    async with db_app.sessions() as session:
        await session.execute(
            delete(Enrollment).where(
                Enrollment.student_id == s, Enrollment.class_id == w.a.class_ids[0]
            )
        )
        await session.commit()
    assert await get(db_app, s, "/api/v1/diagnostics/current") == []
    r = await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    assert r.status_code == 404
    # The teacher can still cancel the left student's open one.
    r = await db_app.client.post(
        tab(w.a.class_ids[0], f"/students/{s}/cancel"), headers=db_app.auth(w.a.teacher_id)
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


async def test_empty_range_at_start_finishes_at_once(db_app: DbApp) -> None:
    w = await setup_sent(db_app)
    s = w.a.student_ids[0]
    await put_chapters(db_app, w, [])  # unticked after sending
    did = await open_id(db_app, s)
    r = await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    assert r.json()["status"] == "finished" and r.json()["empty"] is True
    result = await get(db_app, s, diag_path(did, "/result"))
    assert result == {"answered": 0, "learned": [], "conditional": [], "to_learn": []}
    assert await states(db_app, s) == {}


async def test_range_crosses_courses_and_is_frozen_at_start(db_app: DbApp, tmp_path: Path) -> None:
    maths = fx.course("maths", "maths", concepts=[fx.concept("m1")])
    physics = fx.course(
        "physics", "physics", concepts=[fx.concept("p1", [{"concept": "maths/m1", "weight": 0.5}])]
    )
    _, report = await import_tree(
        fx.write(tmp_path / "t", fx.tree(maths, physics)), db_app.sessions
    )
    assert report is not None
    async with db_app.sessions() as session:
        school = await seed_school(session, "CCC")
    w = World(school, school)
    pclass, s = school.class_ids[1], school.student_ids[3]
    teacher = db_app.auth(school.teacher_id)
    ch = await chapter_id(db_app, "physics", "ch1")
    r = await db_app.client.put(
        tab(pclass, "/chapters"), json={"chapter_ids": [str(ch)]}, headers=teacher
    )
    assert r.json()["range"] == {"concepts": 2, "prereqs": 1, "askable": 2}
    await db_app.client.post(tab(pclass, "/send"), json={"all_students": True}, headers=teacher)
    did = await open_id(db_app, s)
    await db_app.client.post(diag_path(did, "/start"), headers=db_app.auth(s))
    await db_app.client.put(tab(pclass, "/chapters"), json={"chapter_ids": []}, headers=teacher)
    async with db_app.sessions() as session:
        diag = await session.get(DiagnosticSession, uuid.UUID(did))
        assert diag is not None and diag.range_ids is not None
        assert set(diag.range_ids) == {
            await concept_id(db_app, "maths/m1"),
            await concept_id(db_app, "physics/p1"),
        }
    q = await get(db_app, s, diag_path(did, "/question"))  # still served from the frozen range
    assert q["session_id"]
    _ = w
