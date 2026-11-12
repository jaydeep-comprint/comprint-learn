"""Spec 015 §3: one school lab (80 students) + 2 teachers against the local API on the test DB.

Run through `make loadtest` (backend/loadtest/run.py), which seeds, starts the API, sets the
environment below and checks the result:
  LOADTEST_SEED       backend/loadtest/.seed.json (ids written by `app loadtest seed`)
  LOADTEST_JWT_SECRET the API's per-run HS256 secret (SUPABASE_JWT_SECRET)
  SUPABASE_URL        the issuer the API expects
  LOADTEST_DB_URL     the test database, to read seeds and answer keys (answers.py)

Students only do what the app allows: they read the outline and pick a ready or in-progress
concept, take a pending quiz first, fall back to practice or reading when nothing is open, and
treat the expected 409s (`quiz_pending`, a failed KP's cooldown, the review cap) as success.
"""

import itertools
import json
import os
import random
from pathlib import Path
from typing import Any

from locust import HttpUser, between, task

from loadtest.answers import AnswerKey
from loadtest.tokens import mint

API = "/api/v1"
CORRECT_RATE = 0.75
# Answers the app gives on purpose (4xx with these codes are successes). Codes that would mean
# this script got something wrong (`stale_question`, `step_order`, `question_answered`,
# `check_first`, `kp_order`) stay failures: the spec counts the scenario's own mistakes.
EXPECTED_CODES = {
    "quiz_pending",  # a quiz at an XP mark blocks KP and practice sessions
    "kp_waiting",  # a failed KP's cooldown
    "kp_passed",
    "concept_locked",
    "practice_locked",
    "practice_passed",
    "not_due",
    "review_cap",
    "review_not_due",
    "session_closed",
    "quiz_over",
    "quiz_not_started",
    "quiz_not_finished",
}

SEED = json.loads(Path(os.environ.get("LOADTEST_SEED", "loadtest/.seed.json")).read_text())
SECRET = os.environ["LOADTEST_JWT_SECRET"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
KEY = AnswerKey(os.environ["LOADTEST_DB_URL"])

_students = itertools.cycle(
    [
        (sid, c)
        for pair in itertools.zip_longest(
            *[[(s, c) for s in c["students"]] for c in SEED["classes"]]
        )
        for sid, c in pair
        if sid
    ]
)


class Api:
    """Small helpers on top of Locust's client: named requests and expected-error handling."""

    user: HttpUser
    headers: dict[str, str]

    def get(self, path: str, name: str, ok: tuple[int, ...] = ()) -> Any:
        with self.user.client.get(
            API + path, headers=self.headers, name=name, catch_response=True
        ) as r:
            return self._done(r, ok)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        name: str,
        ok: tuple[int, ...] = (),
        expect_correct: bool | None = None,
    ) -> Any:
        with self.user.client.post(
            API + path, json=body, headers=self.headers, name=name, catch_response=True
        ) as r:
            data = self._done(r, ok)
            # An answer worked out to be right but graded wrong (or the reverse) is this
            # script's mistake: count it as a failure so the run can't pass silently.
            if (
                expect_correct is not None
                and isinstance(data, dict)
                and "correct" in data
                and data["correct"] != expect_correct
            ):
                r.failure(f"graded {data['correct']}, expected {expect_correct}")
            return data

    def _done(self, r: Any, ok: tuple[int, ...]) -> Any:
        if r.status_code < 400:
            r.success()
            try:
                return r.json()
            except ValueError:
                return None
        try:
            code = r.json().get("code")
        except (ValueError, AttributeError):
            code = None
        if r.status_code in ok or (r.status_code in (403, 409) and code in EXPECTED_CODES):
            r.success()  # an answer the app gives on purpose, not a failure
            return {"_error": code or r.status_code}
        r.failure(f"{r.status_code} {code}")
        return {"_error": code or r.status_code}


def _err(data: Any) -> bool:
    return not isinstance(data, dict | list) or (isinstance(data, dict) and "_error" in data)


class StudentUser(HttpUser, Api):
    wait_time = between(3, 12)
    weight = 40

    def on_start(self) -> None:
        self.user = self
        self.student_id, cls = next(_students)
        self.course = cls["course"]
        self.class_id = cls["id"]
        self.headers = {"Authorization": f"Bearer {mint(self.student_id, SECRET, SUPABASE_URL)}"}
        self.home()

    # --- pages -----------------------------------------------------------------------------------

    @task(3)
    def home(self) -> None:
        self.get("/me", "/me")
        self.get("/me/xp", "/me/xp")
        self.get(f"/learn/courses/{self.course}/outline", "/learn/courses/[c]/outline")
        self.get("/me/assignments", "/me/assignments")
        self.get("/quizzes/current", "/quizzes/current")
        self.get("/reviews", "/reviews")

    @task(1)
    def graph(self) -> None:
        self.get(f"/courses/{self.course}/graph", "/courses/[c]/graph")

    @task(1)
    def leaderboard(self) -> None:
        # 404 when the teacher hasn't switched it on: an answer, not a failure.
        self.get(f"/classes/{self.class_id}/leaderboard", "/classes/[id]/leaderboard", ok=(404,))

    # --- learning --------------------------------------------------------------------------------

    @task(8)
    def learn(self) -> None:
        if self.take_pending_quiz():
            return
        outline = self.get(f"/learn/courses/{self.course}/outline", "/learn/courses/[c]/outline")
        if _err(outline):
            return
        concepts = [c for ch in outline["chapters"] for c in ch["concepts"]]
        open_ = [c for c in concepts if c["status"] == "in_progress"] or [
            c for c in concepts if c["status"] == "ready"
        ]
        if not open_:
            self.get(f"/courses/{self.course}/graph", "/courses/[c]/graph")
            return
        concept = random.choice(open_[:3])
        self.lesson(concept["id"])

    def lesson(self, ref: str) -> None:
        base = f"/learn/concepts/{ref}"
        lesson = self.get(base, "/learn/concepts/[c]/[k]")
        if _err(lesson):
            return
        self.post(
            f"{base}/progress",
            {"step": "intro", "active_seconds": random.randint(20, 90)},
            "/learn/concepts/[c]/[k]/progress",
        )
        if lesson.get("check") and lesson.get("check_result") is None:
            option = KEY.option_for_check(lesson["check"], correct=random.random() < 0.85)
            self.post(
                f"{base}/check",
                {"option_id": option, "time_taken_ms": random.randint(8000, 30000)},
                "/learn/concepts/[c]/[k]/check",
            )
        # The first KP not passed: a failed one is waiting (cooldown), so the lesson stops there.
        kp = next((k for k in lesson["kps"] if k["status"] != "passed"), None)
        if kp is not None and kp["status"] == "failed":
            return
        if kp is not None:
            self.post(
                f"{base}/progress",
                {"step": f"kp:{kp['slug']}", "active_seconds": random.randint(30, 120)},
                "/learn/concepts/[c]/[k]/progress",
            )
            self.run_session(f"{base}/kps/{kp['slug']}", "/learn/concepts/[c]/[k]/kps/[kp]")
        elif (lesson.get("practice") or {}).get("status") == "pending":
            self.post(
                f"{base}/progress",
                {"step": "practice", "active_seconds": random.randint(30, 120)},
                "/learn/concepts/[c]/[k]/progress",
            )
            self.run_session(f"{base}/practice", "/learn/concepts/[c]/[k]/practice")

    @task(2)
    def review(self) -> None:
        queue = self.get("/reviews", "/reviews")
        if _err(queue) or not queue.get("offered"):
            return
        r = random.choice(queue["offered"])
        self.run_session(f"/reviews/{r['course']}/{r['concept']}", "/reviews/[c]/[k]")

    def take_pending_quiz(self) -> bool:
        current = self.get("/quizzes/current", "/quizzes/current")
        if _err(current) or not current or current.get("status") not in ("pending", "active"):
            return False
        qid = current["id"]
        if current["status"] == "pending":
            started = self.post(f"/quizzes/{qid}/start", {}, "/quizzes/[id]/start")
            if _err(started):
                return True
        for _ in range(12):
            q = self.get(f"/quizzes/{qid}/question", "/quizzes/[id]/question")
            if _err(q) or not q:
                break
            fields = KEY.fields(q, correct=random.random() < CORRECT_RATE)
            if fields is None:
                break
            body = {
                "position": q["position"],
                "time_taken_ms": random.randint(15000, 60000),
            } | fields
            saved = self.post(f"/quizzes/{qid}/answer", body, "/quizzes/[id]/answer")
            if _err(saved) or saved.get("finished"):
                break
            self.wait()  # think between quiz questions too
        self.get(f"/quizzes/{qid}/result", "/quizzes/[id]/result", ok=(404, 409))
        return True

    def run_session(self, path: str, name: str) -> None:
        """Answer questions until the session ends (pass, fail or a 409 the app means)."""
        for _ in range(12):
            q = self.get(f"{path}/question", f"{name}/question")
            if _err(q) or not q:
                return
            correct = random.random() < CORRECT_RATE
            fields = KEY.fields(q, correct=correct)
            if fields is None:
                return
            body = {
                "position": q["position"],
                "time_taken_ms": random.randint(15000, 90000),
            } | fields
            result = self.post(f"{path}/answer", body, f"{name}/answer", expect_correct=correct)
            if _err(result) or result.get("session_status") not in (None, "active"):
                return
            self.wait()


class TeacherUser(HttpUser, Api):
    """Class overview, Students tab + heatmap and one student page, every 60 s."""

    wait_time = between(55, 65)
    fixed_count = 2

    def on_start(self) -> None:
        self.user = self
        self.headers = {"Authorization": f"Bearer {mint(SEED['teacher_id'], SECRET, SUPABASE_URL)}"}
        self.get("/me", "/me")

    @task
    def dashboard(self) -> None:
        cls = random.choice(SEED["classes"])
        cid = cls["id"]
        self.get(f"/classes/{cid}", "/classes/[id]")
        self.get(f"/classes/{cid}/students", "/classes/[id]/students")
        self.get("/courses", "/courses")
        self.get(f"/classes/{cid}/overview?window=7d", "/classes/[id]/overview")
        self.get(f"/classes/{cid}/summary?window=7d", "/classes/[id]/summary", ok=(404, 503))
        self.get(f"/classes/{cid}/heatmap", "/classes/[id]/heatmap")
        sid = random.choice(cls["students"])
        self.get(f"/classes/{cid}/students/{sid}", "/classes/[id]/students/[sid]")
        self.get(f"/classes/{cid}/students/{sid}/outline", "/classes/[id]/students/[sid]/outline")
