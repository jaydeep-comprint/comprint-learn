"""Load-test seed (spec 015 §3): `uv run app loadtest seed`, test environment only.

Rebuilds the test project's schema (alembic downgrade base → upgrade head, like the DB tests),
imports `content/`, then creates school `LOADTEST`: 1 teacher, classes "Maths 9" and "Physics 9"
(courses `maths-9-10` and `physics-9-10`) with 40 students each. Students are inserted directly
(active, no temp password, no Supabase auth user: the load-test API verifies HS256 tokens minted
by Locust). Each student gets a spread of state: 0-3 concepts learned (a prefix of the course's
prerequisite order, so most of the course stays unlearned) and, for half of them, the review
cards made due now so reviews have work.
"""

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import CurrentUser, OrgScope
from app.content.importer import import_tree
from app.core.config import Settings
from app.models import (
    AppUser,
    ClassTeacher,
    Enrollment,
    Organization,
    ReviewCard,
    Role,
    SchoolClass,
    Subject,
    UserStatus,
)
from app.models.content import Chapter, Concept, ConceptPrereq, Course
from app.services import frontier

ORG_CODE = "LOADTEST"
STUDENTS_PER_CLASS = 40
CLASSES = (
    ("Maths 9", Subject.maths, "maths-9-10", "m"),
    ("Physics 9", Subject.physics, "physics-9-10", "p"),
)
BACKEND_DIR = Path(__file__).resolve().parents[1]

WRONG_ENV = "app loadtest seed runs only with ENVIRONMENT=test."
WRONG_DB = (
    "app loadtest seed needs DATABASE_URL equal to TEST_DATABASE_URL (it rebuilds the schema): "
    "run it through `make loadtest`, never against the dev database."
)


class SeedRefused(RuntimeError):  # noqa: N818 - a refusal, reported to the operator
    pass


def check_target(settings: Settings, environ: dict[str, str] | None = None) -> str:
    """The test database URL, or `SeedRefused`."""
    env = os.environ if environ is None else environ
    if settings.environment != "test" or env.get("ENVIRONMENT") == "production":
        raise SeedRefused(WRONG_ENV)
    test_url = settings.test_database_url
    if not test_url or settings.database_url != test_url:
        raise SeedRefused(WRONG_DB)
    return test_url


def rebuild_schema(url: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )


def prereq_order(
    concepts: list[tuple[uuid.UUID, int, int]], edges: set[tuple[uuid.UUID, uuid.UUID]]
) -> list[uuid.UUID]:
    """Concept ids so every in-course prerequisite comes first; ties in outline order.
    `concepts` are (id, chapter position, concept position); `edges` (concept, prereq)."""
    ids = {c[0] for c in concepts}
    key = {c[0]: (c[1], c[2]) for c in concepts}
    needs = {cid: {p for (c, p) in edges if c == cid and p in ids} for cid in ids}
    order: list[uuid.UUID] = []
    done: set[uuid.UUID] = set()
    while len(order) < len(ids):
        ready = sorted((c for c in ids - done if needs[c] <= done), key=key.__getitem__)
        if not ready:  # pragma: no cover - the content validator rejects cycles
            raise RuntimeError("prerequisite cycle")
        order.append(ready[0])
        done.add(ready[0])
    return order


@dataclass
class SeedResult:
    org_id: uuid.UUID
    teacher_id: uuid.UUID
    classes: list[dict[str, Any]]

    def as_json(self) -> dict[str, Any]:
        return {
            "org_id": str(self.org_id),
            "teacher_id": str(self.teacher_id),
            "classes": self.classes,
        }


async def _course_order(session: AsyncSession, slug: str) -> list[uuid.UUID]:
    course = await session.scalar(
        select(Course).where(Course.slug == slug, Course.retired_at.is_(None))
    )
    if course is None:
        raise SeedRefused(f"course {slug} is not imported")
    rows = (
        await session.execute(
            select(Concept.id, Chapter.position, Concept.position)
            .join(Chapter, Chapter.id == Concept.chapter_id)
            .where(Concept.course_id == course.id, Concept.retired_at.is_(None))
        )
    ).all()
    edges = {
        (c, p)
        for c, p in (
            await session.execute(select(ConceptPrereq.concept_id, ConceptPrereq.prereq_id))
        ).all()
    }
    return prereq_order([(r[0], r[1], r[2]) for r in rows], edges)


async def seed(sessions: async_sessionmaker[AsyncSession]) -> SeedResult:
    """The school and its students (content must already be imported)."""
    org = Organization(id=uuid.uuid4(), name="Load test school", code=ORG_CODE)
    teacher = AppUser(
        id=uuid.uuid4(),
        org_id=org.id,
        role=Role.teacher,
        is_admin=True,
        display_name="Load Teacher",
        email="loadtest-teacher@example.invalid",
        status=UserStatus.active,
        must_change_password=False,
    )
    classes: list[SchoolClass] = []
    students: list[tuple[AppUser, SchoolClass, str]] = []
    links: list[ClassTeacher | Enrollment] = []
    for name, subject, course, tag in CLASSES:
        cls = SchoolClass(
            id=uuid.uuid4(),
            org_id=org.id,
            name=name,
            subject=subject,
            grade=9,
            created_by=teacher.id,
        )
        classes.append(cls)
        links.append(ClassTeacher(org_id=org.id, class_id=cls.id, user_id=teacher.id))
        for i in range(STUDENTS_PER_CLASS):
            s = AppUser(
                id=uuid.uuid4(),
                org_id=org.id,
                role=Role.student,
                is_admin=False,
                display_name=f"Student {tag.upper()}{i:02d}",
                username=f"lt-{tag}{i:02d}",
                status=UserStatus.active,
                must_change_password=False,
            )
            students.append((s, cls, course))
            links.append(Enrollment(org_id=org.id, class_id=cls.id, student_id=s.id))
    async with sessions() as session:
        for level in ([org], [teacher, *(s for s, _, _ in students)], classes, links):
            session.add_all(level)
            await session.flush()
        await session.commit()
        orders = {course: await _course_order(session, course) for _, _, course, _ in CLASSES}

    now = datetime.now(UTC)
    for i, (student, _cls, course) in enumerate(students):
        learned = orders[course][: i % 4]  # 0-3 concepts, a prerequisite-closed prefix
        if not learned:
            continue
        async with sessions() as session:
            scope = OrgScope(session, CurrentUser(student.id, org.id, Role.student, False, False))
            for concept_id in learned:
                await frontier.mark_learned(scope, concept_id)
            if i % 2 == 0:
                await session.execute(
                    update(ReviewCard)
                    .where(ReviewCard.student_id == student.id)
                    .values(due=now - timedelta(hours=1))
                )
            await session.commit()

    out_classes = []
    for name, subject, course, _ in CLASSES:
        cls = next(c for c in classes if c.subject == subject)
        out_classes.append(
            {
                "id": str(cls.id),
                "name": name,
                "subject": subject.value,
                "course": course,
                "students": [str(s.id) for s, c, _ in students if c.id == cls.id],
            }
        )
    return SeedResult(org.id, teacher.id, out_classes)


async def run(sessions: async_sessionmaker[AsyncSession], content_root: Path) -> SeedResult:
    issues, report = await import_tree(content_root, sessions)
    if report is None:
        raise SeedRefused("content import failed: " + "; ".join(str(i) for i in issues[:5]))
    return await seed(sessions)
