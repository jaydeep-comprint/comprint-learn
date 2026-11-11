"""Seed data for DB tests: a school with an admin, a teacher, 2 classes and 3 students in each."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppUser,
    ClassTeacher,
    Enrollment,
    Organization,
    Role,
    SchoolClass,
    Subject,
    UserStatus,
)
from app.privacy import NOTICE_VERSION


@dataclass
class School:
    org_id: uuid.UUID
    code: str
    admin_id: uuid.UUID
    teacher_id: uuid.UUID
    class_ids: list[uuid.UUID] = field(default_factory=list)
    student_ids: list[uuid.UUID] = field(default_factory=list)


def staff(org_id: uuid.UUID, email: str, *, is_admin: bool = False, **kw: object) -> AppUser:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "org_id": org_id,
        "role": Role.teacher,
        "is_admin": is_admin,
        "display_name": email.split("@")[0],
        "email": email,
        "status": UserStatus.active,
        "must_change_password": False,
    }
    values.update(kw)
    return AppUser(**values)


def student(org_id: uuid.UUID, username: str, **kw: object) -> AppUser:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "org_id": org_id,
        "role": Role.student,
        "display_name": username.title(),
        "username": username,
        "status": UserStatus.active,
        "must_change_password": False,
    }
    values.update(kw)
    return AppUser(**values)


async def seed_school(session: AsyncSession, code: str) -> School:
    """One flush per dependency level (no ORM relationships, so we order the inserts ourselves)."""
    org = Organization(id=uuid.uuid4(), name=f"School {code}", code=code)
    admin = staff(org.id, f"admin@{code.lower()}.in", is_admin=True)
    teacher = staff(org.id, f"teacher@{code.lower()}.in")
    school = School(org.id, code, admin.id, teacher.id)
    classes: list[SchoolClass] = []
    students: list[AppUser] = []
    links: list[ClassTeacher | Enrollment] = []
    for i, subject in enumerate([Subject.maths, Subject.physics]):
        cls = SchoolClass(
            id=uuid.uuid4(),
            org_id=org.id,
            name=f"9{'AB'[i]} {subject.value}",
            subject=subject,
            grade=9,
            created_by=teacher.id,
        )
        classes.append(cls)
        links.append(ClassTeacher(org_id=org.id, class_id=cls.id, user_id=teacher.id))
        school.class_ids.append(cls.id)
        for j in range(3):
            s = student(org.id, f"{code.lower()}{i}{j}")
            students.append(s)
            links.append(Enrollment(org_id=org.id, class_id=cls.id, student_id=s.id))
            school.student_ids.append(s.id)
    for level in ([org], [admin, teacher, *students], classes, links):
        session.add_all(level)
        await session.flush()
    await session.commit()
    return school


async def grant_consent(
    session: AsyncSession, school: School, student_ids: list[uuid.UUID] | None = None
) -> None:
    """Spec 014: record AI-tutor consent (by the school's teacher) for these students, default
    all of the school's students. Students start with no consent."""
    await session.execute(
        update(AppUser)
        .where(
            AppUser.org_id == school.org_id,
            AppUser.id.in_(student_ids if student_ids is not None else school.student_ids),
        )
        .values(
            tutor_consent_at=func.now(),
            tutor_consent_by=school.teacher_id,
            tutor_consent_form=NOTICE_VERSION,
        )
    )
    await session.commit()
