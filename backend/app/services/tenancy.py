"""Tenancy business rules. Every function takes an `OrgScope`; none takes a raw session + id.

Supabase admin calls happen before our DB writes and are undone (best effort) if the DB write
fails, so a failure never leaves a half-created account. Personal data (names, usernames, emails,
passwords) is never logged; logs carry ids and exception class names only.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.api.deps import OrgScope
from app.core.config import get_settings
from app.core.errors import AUTH_SERVICE_DOWN, ApiProblem, conflict, not_found
from app.core.passwords import temp_password
from app.core.usernames import SUFFIX_DIGITS, username_base, username_candidate
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
from app.schemas.tenancy import (
    ClassOut,
    CreatedStudentOut,
    StudentOut,
    TeacherRef,
    TempPasswordOut,
)
from app.services.supabase_admin import SupabaseAdmin, SupabaseAdminError

logger = logging.getLogger(__name__)

EMAIL_TAKEN = "That email already belongs to a user."
LAST_ADMIN = "A school needs at least one active admin."
ONLY_ACTIVE_STUDENTS = "Only active students can be enrolled."
CLASS_ARCHIVED = "This class is archived. Unarchive it to make changes."
BULK_CREATE_FAILED = "Could not create accounts right now. Nothing was saved; please try again."
STUDENT_EMAIL_DOMAIN = "students.invalid"
# Parallel admin-API calls during bulk create (Supabase rate-limits the admin API).
ADMIN_API_CONCURRENCY = 5


def auth_service_down() -> ApiProblem:
    return ApiProblem(502, "auth_service_unavailable", AUTH_SERVICE_DOWN)


def student_auth_email(username: str, school_code: str) -> str:
    """Internal sign-in email for a student; never shown, never emailed (`.invalid` TLD)."""
    return f"{username}@{school_code.lower()}.{STUDENT_EMAIL_DOMAIN}"


async def _delete_auth_users(admin: SupabaseAdmin, user_ids: Sequence[uuid.UUID]) -> None:
    for uid in user_ids:
        try:
            await admin.delete_user(uid)
        except SupabaseAdminError:
            logger.error("Could not delete orphaned auth user %s", uid)


async def email_taken(scope: OrgScope, email: str) -> bool:
    """Emails are unique across all schools. Returns only a bool, never the other school."""
    stmt = select(exists().where(func.lower(AppUser.email) == email.lower()))
    return bool(await scope.session.scalar(stmt))


# --- me -------------------------------------------------------------------------------------------


async def get_me(scope: OrgScope) -> tuple[AppUser, Organization]:
    user = await scope.get(AppUser, scope.user.id)
    org = await scope.session.get(Organization, scope.org_id)
    assert org is not None
    return user, org


async def change_own_password(scope: OrgScope, admin: SupabaseAdmin, new_password: str) -> None:
    user = await scope.get(AppUser, scope.user.id, for_update=True)
    try:
        # Also revokes the user's sessions; the frontend signs in again with the new password.
        await admin.update_password(user.id, new_password)
    except SupabaseAdminError as exc:
        raise auth_service_down() from exc
    user.must_change_password = False
    # Other devices' access tokens stop working now.
    user.sessions_valid_after = func.clock_timestamp()
    await scope.session.commit()


# --- teachers -------------------------------------------------------------------------------------


async def list_teachers(scope: OrgScope) -> Sequence[AppUser]:
    stmt = (
        scope.select(AppUser)
        .where(AppUser.role == Role.teacher)
        .order_by(func.lower(AppUser.display_name), AppUser.id)
    )
    return (await scope.session.scalars(stmt)).all()


async def _get_teacher(scope: OrgScope, user_id: uuid.UUID, *, for_update: bool = False) -> AppUser:
    user = await scope.get(AppUser, user_id, for_update=for_update)
    if user.role != Role.teacher:
        raise not_found()
    return user


async def _get_student(scope: OrgScope, user_id: uuid.UUID, *, for_update: bool = False) -> AppUser:
    user = await scope.get(AppUser, user_id, for_update=for_update)
    if user.role != Role.student:
        raise not_found()
    return user


async def invite_teacher(
    scope: OrgScope,
    admin: SupabaseAdmin,
    email: str,
    display_name: str,
    *,
    is_admin: bool = False,
) -> AppUser:
    email = email.strip().lower()
    if await email_taken(scope, email):
        raise conflict("email_taken", EMAIL_TAKEN)
    redirect = f"{get_settings().app_url.rstrip('/')}/accept-invite"
    try:
        auth_id = await admin.invite(email, redirect)
    except SupabaseAdminError as exc:
        if exc.status == 422:  # Supabase already has a confirmed user with this email
            raise conflict("email_taken", EMAIL_TAKEN) from exc
        raise auth_service_down() from exc
    user = scope.new(
        AppUser,
        id=auth_id,
        role=Role.teacher,
        is_admin=is_admin,
        display_name=display_name,
        email=email,
        status=UserStatus.invited,
        must_change_password=False,
    )
    try:
        await scope.session.commit()
    except IntegrityError as exc:
        await scope.session.rollback()
        # A concurrent invite of the same email may have committed this very auth user: only
        # delete it if no app_user row owns it.
        if await scope.session.get(AppUser, auth_id) is None:
            await _delete_auth_users(admin, [auth_id])
        raise conflict("email_taken", EMAIL_TAKEN) from exc
    except Exception:
        await scope.session.rollback()
        await _delete_auth_users(admin, [auth_id])
        raise
    return user


async def resend_invite(scope: OrgScope, admin: SupabaseAdmin, user_id: uuid.UUID) -> None:
    user = await _get_teacher(scope, user_id)
    if user.status != UserStatus.invited or user.email is None:
        raise conflict("not_invited", "This teacher has already accepted their invite.")
    redirect = f"{get_settings().app_url.rstrip('/')}/accept-invite"
    try:
        await admin.invite(user.email, redirect)
    except SupabaseAdminError as exc:
        raise auth_service_down() from exc


async def _lock_active_admins(scope: OrgScope) -> list[uuid.UUID]:
    """Locks the school's active admins so two concurrent demotions can't both pass the check."""
    stmt = (
        scope.select(AppUser)
        .where(AppUser.is_admin.is_(True), AppUser.status == UserStatus.active)
        .order_by(AppUser.id)
        .with_for_update()
    )
    return [u.id for u in (await scope.session.scalars(stmt)).all()]


async def _set_status(
    scope: OrgScope, admin: SupabaseAdmin, user: AppUser, status: UserStatus
) -> None:
    """Ban/unban in Supabase first; our row changes only after that call succeeds."""
    if status == user.status or (status == UserStatus.active and user.status == UserStatus.invited):
        return
    try:
        await admin.set_banned(user.id, status == UserStatus.deactivated)
    except SupabaseAdminError as exc:
        raise auth_service_down() from exc
    user.status = status
    if status == UserStatus.deactivated:
        user.sessions_valid_after = func.clock_timestamp()
    logger.info("User %s status -> %s", user.id, status.value)


async def patch_teacher(
    scope: OrgScope,
    admin: SupabaseAdmin,
    user_id: uuid.UUID,
    *,
    is_admin: bool | None,
    status: UserStatus | None,
) -> AppUser:
    # Lock order: all active admins (by id), then the target. Same order in every request, so two
    # admins demoting each other can't deadlock.
    admins = await _lock_active_admins(scope) if is_admin is False or status else []
    user = await _get_teacher(scope, user_id, for_update=True)
    demoting = is_admin is False and user.is_admin
    deactivating = status == UserStatus.deactivated and user.status != UserStatus.deactivated
    if (demoting or deactivating) and user.id in admins and len(admins) <= 1:
        raise conflict("last_admin", LAST_ADMIN)
    if status is not None:
        await _set_status(scope, admin, user, status)
    if is_admin is not None:
        user.is_admin = is_admin
    await scope.session.commit()
    return user


# --- students -------------------------------------------------------------------------------------


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _class_ids_by_student(
    scope: OrgScope, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not student_ids:
        return {}
    stmt = scope.select(Enrollment).where(Enrollment.student_id.in_(student_ids))
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for e in (await scope.session.scalars(stmt)).all():
        out.setdefault(e.student_id, []).append(e.class_id)
    return out


async def list_students(
    scope: OrgScope, q: str | None, class_id: uuid.UUID | None
) -> list[StudentOut]:
    stmt = scope.select(AppUser).where(AppUser.role == Role.student)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                AppUser.display_name.ilike(pattern, escape="\\"),
                AppUser.username.ilike(pattern, escape="\\"),
            )
        )
    if class_id is not None:
        await scope.get(SchoolClass, class_id)
        stmt = stmt.join(
            Enrollment,
            (Enrollment.student_id == AppUser.id) & (Enrollment.org_id == AppUser.org_id),
        ).where(Enrollment.class_id == class_id)
    stmt = stmt.order_by(func.lower(AppUser.display_name), AppUser.username).limit(1000)
    students = (await scope.session.scalars(stmt)).all()
    classes = await _class_ids_by_student(scope, [s.id for s in students])
    return [
        StudentOut(
            id=s.id,
            display_name=s.display_name,
            username=s.username or "",
            status=s.status,
            class_ids=classes.get(s.id, []),
        )
        for s in students
    ]


async def patch_student(
    scope: OrgScope,
    admin: SupabaseAdmin,
    student_id: uuid.UUID,
    *,
    display_name: str | None,
    status: UserStatus | None,
) -> StudentOut:
    student = await _get_student(scope, student_id, for_update=True)
    if display_name is not None:
        student.display_name = display_name
    if status is not None:
        await _set_status(scope, admin, student, status)
    await scope.session.commit()
    classes = await _class_ids_by_student(scope, [student.id])
    return StudentOut(
        id=student.id,
        display_name=student.display_name,
        username=student.username or "",
        status=student.status,
        class_ids=classes.get(student.id, []),
    )


async def reset_student_password(
    scope: OrgScope, admin: SupabaseAdmin, student_id: uuid.UUID
) -> TempPasswordOut:
    student = await _get_student(scope, student_id, for_update=True)
    password = temp_password()
    try:
        # An admin password update also signs the student out of all other sessions.
        await admin.update_password(student.id, password)
    except SupabaseAdminError as exc:
        raise auth_service_down() from exc
    student.must_change_password = True
    # Old access tokens can't claim the account.
    student.sessions_valid_after = func.clock_timestamp()
    await scope.session.commit()
    assert student.username is not None
    return TempPasswordOut(username=student.username, temp_password=password)


async def _username_taken(scope: OrgScope, username: str) -> bool:
    stmt = select(
        exists().where(
            AppUser.org_id == scope.org_id, func.lower(AppUser.username) == username.lower()
        )
    )
    return bool(await scope.session.scalar(stmt))


async def _pick_username(scope: OrgScope, display_name: str, chosen: set[str]) -> str:
    base = username_base(display_name)
    for digits in SUFFIX_DIGITS:
        candidate = username_candidate(base, digits)
        if candidate not in chosen and not await _username_taken(scope, candidate):
            return candidate
    raise ApiProblem(503, "username_exhausted", BULK_CREATE_FAILED)


async def create_students(
    scope: OrgScope, admin: SupabaseAdmin, class_id: uuid.UUID, display_names: Sequence[str]
) -> list[CreatedStudentOut]:
    """All-or-nothing: on any failure, auth users created in this call are deleted again."""
    school_class = await scope.get(SchoolClass, class_id)
    if school_class.archived_at is not None:
        raise conflict("class_archived", CLASS_ARCHIVED)
    org = await scope.session.get(Organization, scope.org_id)
    assert org is not None

    # Serialise username allocation per school until commit (the unique index is the backstop).
    await scope.session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(scope.org_id), 0)))
    )
    chosen: set[str] = set()
    planned: list[tuple[str, str, str]] = []  # (display_name, username, temp_password)
    for name in display_names:
        username = await _pick_username(scope, name, chosen)
        chosen.add(username)
        planned.append((name, username, temp_password()))

    semaphore = asyncio.Semaphore(ADMIN_API_CONCURRENCY)

    async def create(username: str, password: str) -> uuid.UUID:
        async with semaphore:
            return await admin.create_user(student_auth_email(username, org.code), password)

    results = await asyncio.gather(*(create(u, p) for _, u, p in planned), return_exceptions=True)
    created = [r for r in results if isinstance(r, uuid.UUID)]
    if len(created) != len(planned):
        failure = next(r for r in results if isinstance(r, BaseException))
        logger.warning("Bulk create failed (%s); rolling back", type(failure).__name__)
        await scope.session.rollback()
        await _delete_auth_users(admin, created)
        raise ApiProblem(502, "accounts_not_created", BULK_CREATE_FAILED)

    out: list[CreatedStudentOut] = []
    try:
        for (name, username, password), auth_id in zip(planned, created, strict=True):
            scope.new(
                AppUser,
                id=auth_id,
                role=Role.student,
                display_name=name,
                username=username,
                status=UserStatus.active,
                must_change_password=True,
            )
            out.append(
                CreatedStudentOut(
                    id=auth_id, display_name=name, username=username, temp_password=password
                )
            )
        await scope.session.flush()
        for student in out:
            scope.new(Enrollment, class_id=school_class.id, student_id=student.id)
        await scope.session.commit()
    except Exception as exc:
        logger.warning("Bulk create DB write failed (%s); rolling back", type(exc).__name__)
        await scope.session.rollback()
        await _delete_auth_users(admin, created)
        raise ApiProblem(502, "accounts_not_created", BULK_CREATE_FAILED) from exc
    logger.info("Created %d students in class %s", len(out), school_class.id)
    return out


# --- classes --------------------------------------------------------------------------------------


async def _class_out(scope: OrgScope, classes: Sequence[SchoolClass]) -> list[ClassOut]:
    ids = [c.id for c in classes]
    counts: dict[uuid.UUID, int] = {}
    teachers: dict[uuid.UUID, list[TeacherRef]] = {}
    if ids:
        count_stmt = (
            select(Enrollment.class_id, func.count())
            .where(Enrollment.org_id == scope.org_id, Enrollment.class_id.in_(ids))
            .group_by(Enrollment.class_id)
        )
        counts = {cid: n for cid, n in (await scope.session.execute(count_stmt)).all()}
        teacher_stmt = (
            select(ClassTeacher.class_id, AppUser.id, AppUser.display_name)
            .join(
                AppUser,
                (AppUser.id == ClassTeacher.user_id) & (AppUser.org_id == ClassTeacher.org_id),
            )
            .where(ClassTeacher.org_id == scope.org_id, ClassTeacher.class_id.in_(ids))
            .order_by(func.lower(AppUser.display_name))
        )
        for cid, uid, name in (await scope.session.execute(teacher_stmt)).all():
            teachers.setdefault(cid, []).append(TeacherRef(id=uid, display_name=name))
    return [
        ClassOut(
            id=c.id,
            name=c.name,
            subject=c.subject,
            grade=c.grade,
            archived=c.archived_at is not None,
            student_count=counts.get(c.id, 0),
            teachers=teachers.get(c.id, []),
        )
        for c in classes
    ]


async def list_classes(scope: OrgScope, *, mine: bool, archived: bool) -> list[ClassOut]:
    stmt = scope.select(SchoolClass)
    if not archived:
        stmt = stmt.where(SchoolClass.archived_at.is_(None))
    if mine:
        stmt = stmt.where(
            exists().where(
                ClassTeacher.class_id == SchoolClass.id,
                ClassTeacher.org_id == scope.org_id,
                ClassTeacher.user_id == scope.user.id,
            )
        )
    stmt = stmt.order_by(SchoolClass.archived_at.is_not(None), func.lower(SchoolClass.name))
    return await _class_out(scope, (await scope.session.scalars(stmt)).all())


async def get_class(scope: OrgScope, class_id: uuid.UUID) -> ClassOut:
    return (await _class_out(scope, [await scope.get(SchoolClass, class_id)]))[0]


def _class_name_taken(name: str) -> ApiProblem:
    return conflict("class_name_taken", f"A class named {name} already exists.")


async def create_class(scope: OrgScope, name: str, subject: Subject, grade: int) -> ClassOut:
    school_class = scope.new(
        SchoolClass,
        id=uuid.uuid4(),
        name=name,
        subject=subject,
        grade=grade,
        created_by=scope.user.id,
    )
    try:
        await scope.session.flush()
        scope.new(ClassTeacher, class_id=school_class.id, user_id=scope.user.id)
        await scope.session.commit()
    except IntegrityError as exc:
        await scope.session.rollback()
        raise _class_name_taken(name) from exc
    return await get_class(scope, school_class.id)


async def patch_class(
    scope: OrgScope,
    class_id: uuid.UUID,
    *,
    name: str | None,
    subject: Subject | None,
    grade: int | None,
    archived: bool | None,
) -> ClassOut:
    school_class = await scope.get(SchoolClass, class_id, for_update=True)
    if name is not None:
        school_class.name = name
    if subject is not None:
        school_class.subject = subject
    if grade is not None:
        school_class.grade = grade
    if archived is True and school_class.archived_at is None:
        school_class.archived_at = datetime.now(UTC)
    elif archived is False:
        school_class.archived_at = None
    shown_name = school_class.name  # read before commit: rollback expires the instance
    try:
        await scope.session.commit()
    except IntegrityError as exc:
        await scope.session.rollback()
        raise _class_name_taken(shown_name) from exc
    return await get_class(scope, class_id)


async def add_class_teacher(scope: OrgScope, class_id: uuid.UUID, user_id: uuid.UUID) -> None:
    school_class = await scope.get(SchoolClass, class_id)
    user = await _get_teacher(scope, user_id)
    if user.status == UserStatus.deactivated:
        raise ApiProblem(422, "inactive_teacher", "Only active teachers can be added.")
    await scope.session.execute(
        insert(ClassTeacher)
        .values(class_id=school_class.id, user_id=user.id, org_id=scope.org_id)
        .on_conflict_do_nothing()
    )
    await scope.session.commit()


async def remove_class_teacher(scope: OrgScope, class_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await scope.get(SchoolClass, class_id)
    await _get_teacher(scope, user_id)
    await scope.session.execute(
        delete(ClassTeacher).where(
            ClassTeacher.org_id == scope.org_id,
            ClassTeacher.class_id == class_id,
            ClassTeacher.user_id == user_id,
        )
    )
    await scope.session.commit()


async def list_class_students(scope: OrgScope, class_id: uuid.UUID) -> Sequence[AppUser]:
    await scope.get(SchoolClass, class_id)
    stmt = (
        scope.select(AppUser)
        .join(
            Enrollment,
            (Enrollment.student_id == AppUser.id) & (Enrollment.org_id == AppUser.org_id),
        )
        .where(Enrollment.class_id == class_id)
        .order_by(func.lower(AppUser.display_name), AppUser.username)
    )
    return (await scope.session.scalars(stmt)).all()


async def _get_writable_class(scope: OrgScope, class_id: uuid.UUID) -> SchoolClass:
    school_class = await scope.get(SchoolClass, class_id)
    if school_class.archived_at is not None:
        raise conflict("class_archived", CLASS_ARCHIVED)
    return school_class


async def enroll_students(
    scope: OrgScope, class_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
) -> None:
    """Idempotent. Every id is checked first (404 / 422), so nothing changes on any failure."""
    school_class = await _get_writable_class(scope, class_id)
    unique_ids = list(dict.fromkeys(student_ids))
    stmt = scope.select(AppUser).where(AppUser.id.in_(unique_ids))
    found = {u.id: u for u in (await scope.session.scalars(stmt)).all()}
    if len(found) != len(unique_ids):
        raise not_found()
    if any(u.role != Role.student or u.status != UserStatus.active for u in found.values()):
        raise ApiProblem(422, "not_active_student", ONLY_ACTIVE_STUDENTS)
    await scope.session.execute(
        insert(Enrollment)
        .values(
            [
                {"class_id": school_class.id, "student_id": sid, "org_id": scope.org_id}
                for sid in unique_ids
            ]
        )
        .on_conflict_do_nothing()
    )
    await scope.session.commit()


async def unenroll_student(scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    """Removes the link only; the account and its data are kept. Idempotent."""
    await _get_writable_class(scope, class_id)
    await _get_student(scope, student_id)
    await scope.session.execute(
        delete(Enrollment).where(
            Enrollment.org_id == scope.org_id,
            Enrollment.class_id == class_id,
            Enrollment.student_id == student_id,
        )
    )
    await scope.session.commit()
