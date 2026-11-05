"""Teacher dashboard against a real database (spec 010): numbers match a seeded physics class,
out-of-scope students are excluded, reads never write, `class_states` agrees with
`frontier.load`, and every endpoint runs a fixed number of queries."""

import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy import func, select

from app.api.deps import CurrentUser, OrgScope
from app.models import (
    AttemptContext,
    ConceptSource,
    ConceptState,
    ConceptStatus,
    Enrollment,
    Item,
    KpStatus,
    Misconception,
    PracticeSession,
    RemediationState,
    Role,
    SessionKind,
    SessionStatus,
    StudyActivity,
    Subject,
)
from app.models.content import ItemKind
from app.services import frontier, learn
from tests import dashboard_seed as ds
from tests.conftest import DbApp
from tests.learn_helpers import DIST, LIN, SPEED, World, keys, world
from tests.query_count import count_queries
from tests.review_helpers import concept_id, seed_learned

pytestmark = pytest.mark.db


class Seed:
    def __init__(self, w: World) -> None:
        self.w = w
        self.org = w.a.org_id
        self.cls = w.a.class_ids[1]  # 9B physics
        self.teacher = w.a.teacher_id
        self.s3, self.s4, self.s5 = w.a.student_ids[3:6]
        self.s6: uuid.UUID = uuid.uuid4()
        self.gone: uuid.UUID = uuid.uuid4()  # deactivated but enrolled
        self.thread: uuid.UUID = uuid.uuid4()
        self.purged_thread: uuid.UUID = uuid.uuid4()
        self.dist = self.speed = self.lin = uuid.uuid4()
        self.dist_title = ""

    def path(self, tail: str = "") -> str:
        return f"/api/v1/classes/{self.cls}{tail}"


async def _seed(db: DbApp) -> Seed:
    w = await world(db)
    s = Seed(w)
    s.dist, s.speed, s.lin = (
        await concept_id(db, DIST),
        await concept_id(db, SPEED),
        await concept_id(db, LIN),
    )
    # s3: Distance learned 30 days ago (a weak card by now: retrievability ~0.67); Speed stuck
    # (KP 1 failed twice, a due brush-up of Distance).
    await seed_learned(db, s.org, s.s3, [DIST], days_ago=30)
    async with db.sessions() as session:
        speed_kps = await ds.kps_of(session, s.speed)
        dist_kps = await ds.kps_of(session, s.dist)
        s6, gone = await ds.add_students(session, s.org, s.cls, 2, "extra")
        s.s6, s.gone = s6, gone
        await ds.deactivate(session, gone)

        kp1 = speed_kps[0]
        session.add(ds.concept_state(s.org, s.s3, s.speed, ConceptStatus.in_progress))
        session.add(
            ds.kp_progress(
                s.org,
                s.s3,
                kp1.id,
                KpStatus.failed,
                fail_count=2,
                failed_at=ds.NOW,
                reopen_at=ds.NOW + timedelta(days=1),
            )
        )
        session.add(ds.remediation(s.org, s.s3, kp1.id, s.dist, RemediationState.review_due))
        # Distinct end times, newest first: the activity cursor is checked against them.
        failed_ids = [
            await ds.kp_try(
                session,
                s.org,
                s.s3,
                kp1,
                passed=False,
                hints=1,
                ended_at=ds.NOW - timedelta(minutes=i + 1),
            )
            for i in range(3)
        ]
        for i in range(2):
            await ds.kp_try(
                session,
                s.org,
                s.s3,
                dist_kps[0],
                passed=True,
                ended_at=ds.NOW - timedelta(minutes=10 + i),
            )
        # A side-effect close (no attempts) is not a KP try.
        session.add(
            PracticeSession(
                org_id=s.org,
                student_id=s.s3,
                kind=SessionKind.kp,
                current_position=0,
                kp_id=speed_kps[1].id,
                status=SessionStatus.passed,
                ended_at=ds.NOW,
            )
        )
        session.add(ds.study(s.org, s.s3, s.speed, 600, StudyActivity.learn))
        for _ in range(2):  # a row holds at most 600 s
            session.add(ds.study(s.org, s.s3, s.speed, 600, StudyActivity.practice))
        # 30 active minutes: enough XP that `low_xp_rate` doesn't fire (20 / 30 >= 0.5).
        session.add(
            ds.xp_event(s.org, s.s3, s.speed, 20, subject=Subject.physics, day=ds.NOW.date())
        )
        s.thread = await ds.tutor_thread(
            session, s.org, s.s3, failed_ids[0], kp1.item_id, flagged=True
        )

        # s4: rushed (negative XP) and one fail of two tries on Speed.
        await ds.kp_try(session, s.org, s.s4, kp1, passed=True)
        s4_fail = await ds.kp_try(session, s.org, s.s4, kp1, passed=False)
        session.add(
            ds.xp_event(s.org, s.s4, s.speed, -2, subject=Subject.physics, day=ds.NOW.date())
        )
        s.purged_thread = await ds.tutor_thread(
            session, s.org, s.s4, s4_fail, kp1.item_id, purged=True
        )

        # s5: Distance complete but not promoted (every KP passed + practice), Lin learned.
        session.add(ds.concept_state(s.org, s.s5, s.dist, ConceptStatus.in_progress))
        for kp in dist_kps:
            session.add(ds.kp_progress(s.org, s.s5, kp.id, KpStatus.passed, passed_at=ds.NOW))
        session.add(
            PracticeSession(
                org_id=s.org,
                student_id=s.s5,
                kind=SessionKind.practice,
                current_position=0,
                concept_id=s.dist,
                status=SessionStatus.passed,
                ended_at=ds.NOW,
            )
        )
        session.add(ds.concept_state(s.org, s.s5, s.lin, ConceptStatus.learned, learned_at=ds.NOW))
        await ds.kp_try(session, s.org, s.s5, kp1, passed=True)

        # The deactivated student's fails are excluded everywhere.
        for _ in range(3):
            await ds.kp_try(session, s.org, gone, kp1, passed=False)

        # The misconception check of Speed: s3 and s4 pick the tagged distractor, s5 is right.
        check = await session.scalar(
            select(Item).where(
                Item.concept_id == s.speed, Item.kind == ItemKind.misconception_check
            )
        )
        assert check is not None
        option, slug = next(iter(check.answer["misconceptions"].items()))
        misc = await session.scalar(select(Misconception.id).where(Misconception.slug == slug))
        for sid, picked in ((s.s3, True), (s.s4, True), (s.s5, False)):
            session.add(
                ds.attempt(
                    s.org,
                    sid,
                    check.id,
                    correct=not picked,
                    context=AttemptContext.learn,
                    misconception_id=misc if picked else None,
                    response={"option": option if picked else check.answer["correct"]},
                )
            )
        await session.commit()
    async with db.sessions() as session:
        from app.models import Concept

        s.dist_title = str(await session.scalar(select(Concept.title).where(Concept.id == s.dist)))
    return s


async def _get(db: DbApp, s: Seed, tail: str) -> Any:
    r = await db.client.get(s.path(tail), headers=db.auth(s.teacher))
    assert r.status_code == 200, r.text
    return r.json()


async def test_overview_numbers_and_scope(db_app: DbApp) -> None:
    s = await _seed(db_app)
    data = await _get(db_app, s, "/overview")
    assert data["students_in_scope"] == 4  # s3, s4, s5, s6 (not the deactivated one)
    [speed] = data["weakest"]
    assert speed["concept"] == SPEED
    assert (speed["tries"], speed["students_tried"], speed["stuck_now"]) == (6, 3, 1)
    assert speed["fail_rate"] == pytest.approx(4 / 6, abs=0.001)

    reasons = {r["student_id"]: [x["code"] for x in r["reasons"]] for r in data["at_risk"]}
    assert reasons[str(s.s3)] == ["kp_fail_rate"]
    assert reasons[str(s.s4)] == ["negative_xp"]
    assert reasons[str(s.s6)] == ["inactive"]
    assert str(s.s5) not in reasons and str(s.gone) not in reasons

    [m] = data["misconceptions"]
    assert (m["chosen"], m["offered"], m["students"]) == (2, 3, 2)
    assert m["concept"] == SPEED
    assert len(m["items"][0]["student_names"]) == 2
    assert m["items"][0]["chosen_text"]

    hints = data["hints"]
    assert hints["hints"] == 3  # one per failed s3 try
    assert hints["chats"] == 4  # student chat rows with status ok or pending (2 threads x 2)
    assert [t["thread_id"] for t in data["flagged"]] == [str(s.thread)]
    assert data["practice_share"] == {"learn_seconds": 600, "practice_seconds": 1200}

    for window in ("30d", "all"):
        other = await _get(db_app, s, f"/overview?window={window}")
        assert other["window"] == window
        assert other["weakest"][0]["tries"] == 6
    r = await db_app.client.get(s.path("/overview?window=9d"), headers=db_app.auth(s.teacher))
    assert r.status_code == 422


async def test_heatmap_states_and_reads_never_write(db_app: DbApp) -> None:
    s = await _seed(db_app)

    async def states() -> int:
        async with db_app.sessions() as session:
            return int(await session.scalar(select(func.count()).select_from(ConceptState)) or 0)

    before = await states()
    data = await _get(db_app, s, "/heatmap")
    flat = [c["concept"] for ch in data["chapters"] for c in ch["concepts"]]
    rows = {r["student_id"]: dict(zip(flat, r["cells"], strict=True)) for r in data["students"]}
    assert set(rows) == {str(x) for x in (s.s3, s.s4, s.s5, s.s6)}
    assert rows[str(s.s3)][DIST]["state"] == "learned"
    assert rows[str(s.s3)][DIST]["band"] == "weak"
    assert rows[str(s.s3)][SPEED] == {"state": "stuck", "band": None}
    # Complete but not promoted: learned for itself and for its dependants' ready/locked.
    assert rows[str(s.s5)][DIST] == {"state": "learned", "band": "none"}
    assert rows[str(s.s5)][SPEED]["state"] == "ready"
    assert rows[str(s.s6)][DIST]["state"] == "ready"
    assert rows[str(s.s6)][SPEED]["state"] == "locked"
    # Nothing was promoted on read.
    for tail in ("/overview", "/concepts", f"/students/{s.s5}", f"/students/{s.s5}/outline"):
        await _get(db_app, s, tail)
    assert await states() == before
    async with db_app.sessions() as session:
        st = await session.scalar(
            select(ConceptState.status).where(
                ConceptState.student_id == s.s5, ConceptState.concept_id == s.dist
            )
        )
    assert st == ConceptStatus.in_progress


async def test_class_states_parity_with_frontier_load(db_app: DbApp) -> None:
    s = await _seed(db_app)
    async with db_app.sessions() as session:
        speed_kps = await ds.kps_of(session, s.speed)
        waiting, relearn = await ds.add_students(session, s.org, s.cls, 2, "parity")
        # A plain waiting KP: failed once, cooldown until tomorrow, no remediation.
        session.add(ds.concept_state(s.org, waiting, s.speed, ConceptStatus.in_progress))
        session.add(
            ds.kp_progress(
                s.org,
                waiting,
                speed_kps[0].id,
                KpStatus.failed,
                fail_count=1,
                failed_at=ds.NOW,
                reopen_at=ds.NOW + timedelta(days=1),
            )
        )
        # A relearn after a failed review: back in progress, KPs reset, the earlier practice
        # pass still counts.
        session.add(
            ConceptState(
                org_id=s.org,
                student_id=relearn,
                concept_id=s.dist,
                status=ConceptStatus.in_progress,
                source=ConceptSource.lesson,
                relearn_count=1,
            )
        )
        session.add(
            PracticeSession(
                org_id=s.org,
                student_id=relearn,
                kind=SessionKind.practice,
                current_position=0,
                concept_id=s.dist,
                status=SessionStatus.passed,
                ended_at=ds.NOW - timedelta(days=20),
            )
        )
        await session.commit()
    students = [s.s3, s.s5, s.s6, waiting, relearn]
    async with db_app.sessions() as session:
        staff = OrgScope(session, CurrentUser(s.teacher, s.org, Role.teacher, False, False))
        graph = await learn._graph(staff)
        ids = list(graph.nodes)
        batched = await frontier.class_states(staff, students, ids, graph.prereqs)
        assert batched[waiting].views[s.speed].waiting is not None
        assert batched[relearn].status(s.dist) == "in_progress"
        assert batched[relearn].views[s.dist].practice == "passed"
        for sid in students:
            me = OrgScope(session, CurrentUser(sid, s.org, Role.student, False, False))
            single = await frontier.load(me, ids, graph.prereqs)  # promotes in the session
            got, want = batched[sid], single
            for cid in ids:
                assert got.status(cid) == want.status(cid), (sid, graph.nodes[cid].ref)
                gv, wv = got.views[cid], want.views[cid]
                assert (gv.waiting is None) == (wv.waiting is None)
                assert gv.brush_up_id == wv.brush_up_id
                assert gv.parts_passed == wv.parts_passed
        await session.rollback()  # leave the stored rows as seeded


async def test_concept_detail_and_misconceptions_never_carry_answers(db_app: DbApp) -> None:
    s = await _seed(db_app)
    detail = await _get(db_app, s, f"/concepts/{SPEED}")
    assert detail["kps"][0]["tries"] == 6
    assert detail["kps"][0]["hints"] == 3
    stuck = detail["students"]["stuck"]
    assert [x["student_id"] for x in stuck] == [str(s.s3)]
    assert stuck[0]["reason"] == f"Brushing up {s.dist_title}"
    assert detail["students"]["ready"] == 1  # s5
    assert detail["students"]["locked"] == 2  # s4, s6
    forbidden = {"answer", "correct", "solution", "spec", "explanation", "misconceptions_map"}
    assert not (keys(detail) & forbidden)
    full = await _get(db_app, s, "/misconceptions?window=all")
    assert not (keys(full) & forbidden)
    texts = [i["chosen_text"] for m in full for i in m["items"]]
    async with db_app.sessions() as session:
        check = await session.scalar(
            select(Item).where(
                Item.concept_id == s.speed, Item.kind == ItemKind.misconception_check
            )
        )
        assert check is not None
        right = next(
            o["text"] for o in check.public["options"] if o["id"] == check.answer["correct"]
        )
    assert texts and right not in texts
    r = await db_app.client.get(s.path(f"/concepts/{LIN}"), headers=db_app.auth(s.teacher))
    assert r.status_code == 404  # a concept outside the class course


async def test_student_page_routes(db_app: DbApp) -> None:
    s = await _seed(db_app)
    detail = await _get(db_app, s, f"/students/{s.s3}")
    assert [r["code"] for r in detail["at_risk"]] == ["kp_fail_rate"]
    assert detail["stats"]["practice_seconds"] == 1200
    # 3 hints over 11 questions (10 KP questions + the Learn check).
    assert detail["stats"]["hints_per_10"] == pytest.approx(2.7)
    outline = await _get(db_app, s, f"/students/{s.s3}/outline")
    concepts = {c["id"]: c for ch in outline["chapters"] for c in ch["concepts"]}
    assert concepts[SPEED]["state"] == "stuck"
    assert concepts[DIST]["memory"]["band"] == "weak"
    assert LIN in concepts  # the cross-course prerequisite, as the student sees it
    activity = await _get(db_app, s, f"/students/{s.s3}/activity")
    assert len(activity) == 5  # 3 failed Speed tries + 2 passed Distance tries
    assert activity[0]["ended_at"] >= activity[-1]["ended_at"]
    before = activity[1]["ended_at"]
    older = await _get(db_app, s, f"/students/{s.s3}/activity?before={quote(before)}")
    assert [a["ended_at"] for a in older] == [a["ended_at"] for a in activity[2:]]
    threads = await _get(db_app, s, f"/students/{s.s3}/tutor")
    assert [(t["id"], t["flagged"]) for t in threads] == [(str(s.thread), True)]
    msgs = (await _get(db_app, s, f"/students/{s.s3}/tutor/{s.thread}"))["messages"]
    assert [m["role"] for m in msgs] == ["student", "tutor"]  # the pending row is hidden
    purged = (await _get(db_app, s, f"/students/{s.s4}/tutor/{s.purged_thread}"))["messages"]
    assert all(m["purged"] and m["text"] is None for m in purged)
    # A deactivated but enrolled student renders.
    gone = await _get(db_app, s, f"/students/{s.gone}")
    assert gone["status"] == "deactivated"


async def test_student_routes_404(db_app: DbApp) -> None:
    s = await _seed(db_app)
    maths_student = s.w.maths_student  # not in the physics class
    other_school = s.w.b.student_ids[3]
    for sid in (maths_student, other_school, uuid.uuid4()):
        for tail in ("", "/outline", "/activity", "/tutor"):
            r = await db_app.client.get(
                s.path(f"/students/{sid}{tail}"), headers=db_app.auth(s.teacher)
            )
            assert r.status_code == 404, (sid, tail)
    # Another student's thread.
    r = await db_app.client.get(
        s.path(f"/students/{s.s4}/tutor/{s.thread}"), headers=db_app.auth(s.teacher)
    )
    assert r.status_code == 404
    # Students can't read the dashboard.
    r = await db_app.client.get(s.path("/overview"), headers=db_app.auth(s.s3))
    assert r.status_code == 403


ENDPOINTS = [
    "/overview",
    "/concepts",
    "/misconceptions",
    "/heatmap",
    f"/concepts/{SPEED}",
    "/students",
    "/assignments",
]


async def _counts(db: DbApp, s: Seed) -> dict[str, int]:
    out = {}
    for tail in ENDPOINTS:
        with count_queries() as c:
            await _get(db, s, tail)
        out[tail] = c.n
    return out


async def test_fixed_query_count_regardless_of_class_size(db_app: DbApp) -> None:
    s = await _seed(db_app)
    r = await db_app.client.post(
        s.path("/assignments"),
        json={"concepts": [SPEED], "due_date": str(ds.NOW.date() + timedelta(days=3))},
        headers=db_app.auth(s.teacher),
    )
    assert r.status_code == 201, r.text
    small = await _counts(db_app, s)
    async with db_app.sessions() as session:
        kp1 = (await ds.kps_of(session, s.speed))[0]
        extra = await ds.add_students(session, s.org, s.cls, 36, "bulk")
        for sid in extra:
            await ds.kp_try(session, s.org, sid, kp1, passed=False)
            session.add(ds.concept_state(s.org, sid, s.speed, ConceptStatus.in_progress))
        await session.commit()
    large = await _counts(db_app, s)
    assert large == small
    assert await _enrolled(db_app, s) == 41


async def _enrolled(db: DbApp, s: Seed) -> int:
    async with db.sessions() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(Enrollment).where(Enrollment.class_id == s.cls)
            )
            or 0
        )
