"""Erasure (spec 014): an admin requests it, the student is deactivated at once, and a scheduled
job (`app privacy run-due`) anonymises them 7 days later unless the request is cancelled.

Kept after erasure (by decision): the anonymous `app_user` row and every learning row, including
`attempt.response`; only tutor chat text is wiped. Enrolment and assignment links are deleted, so
the student appears nowhere per-student. Extension point: wiping `attempt.response` too would be
one more UPDATE in `_anonymise`.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, conflict
from app.models import (
    AppUser,
    AssignmentStudent,
    AuditAction,
    Enrollment,
    Role,
    UserStatus,
)
from app.schemas.tenancy import StudentOut
from app.services import audit, tenancy, tutor
from app.services.supabase_admin import SupabaseAdmin, SupabaseAdminError

logger = logging.getLogger(__name__)

GRACE = timedelta(days=7)
ERASED_NAME = "Erased student"
CONFIRM_MISMATCH = "Type the student's username exactly to confirm."
PENDING = "An erasure is already scheduled for this student."
NOT_PENDING = "No erasure is scheduled for this student."


async def _out(scope: OrgScope, student: AppUser) -> StudentOut:
    classes = await tenancy.class_ids_by_student(scope, [student.id])
    return tenancy.student_out(student, classes.get(student.id, []))


async def request(
    scope: OrgScope, admin: SupabaseAdmin, student_id: uuid.UUID, confirm_username: str
) -> StudentOut:
    """Ban in Supabase first (502 and nothing changed if that fails), then deactivate and schedule
    the erasure for now + 7 days, with one `erase_requested` event."""
    student = await tenancy.get_student(scope, student_id, for_update=True)
    if confirm_username.strip().lower() != (student.username or "").lower():
        raise ApiProblem(422, "confirm_mismatch", CONFIRM_MISMATCH)
    if student.erase_requested_at is not None:
        raise conflict("erasure_pending", PENDING)
    was_active = student.status == UserStatus.active
    try:
        await admin.set_banned(student.id, True)  # always, also when already deactivated
    except SupabaseAdminError as exc:
        raise tenancy.auth_service_down() from exc
    now = datetime.now(UTC)
    student.status = UserStatus.deactivated
    student.sessions_valid_after = func.clock_timestamp()
    student.erase_requested_at = now
    student.erase_requested_by = scope.user.id
    student.erase_due_at = now + GRACE
    audit.record(
        scope,
        AuditAction.erase_requested,
        student.id,
        {"due_at": student.erase_due_at.isoformat(), "was_active": was_active},
    )
    await scope.session.commit()
    await scope.session.refresh(student)
    logger.info("Erasure requested for user %s", student.id)
    return await _out(scope, student)


async def cancel(scope: OrgScope, student_id: uuid.UUID) -> StudentOut:
    """Clears the request; the student stays deactivated (an admin reactivates them)."""
    student = await tenancy.get_student(scope, student_id, for_update=True)
    if student.erase_requested_at is None:
        raise conflict("no_erasure_pending", NOT_PENDING)
    student.erase_requested_at = None
    student.erase_requested_by = None
    student.erase_due_at = None
    audit.record(scope, AuditAction.erase_cancelled, student.id)
    await scope.session.commit()
    return await _out(scope, student)


@dataclass
class DueResult:
    done: list[uuid.UUID] = field(default_factory=list)
    failed: list[uuid.UUID] = field(default_factory=list)


def _is_due(now: datetime) -> list[ColumnElement[bool]]:
    return [
        AppUser.role == Role.student,
        AppUser.status == UserStatus.deactivated,
        AppUser.erase_due_at.is_not(None),
        AppUser.erase_due_at <= now,
    ]


async def _anonymise(scope: OrgScope, student: AppUser, now: datetime) -> None:
    student.display_name = ERASED_NAME
    # Random, not derived from the id: the old username becomes free and nothing links back.
    student.username = f"erased-{secrets.token_hex(6)}"
    student.status = UserStatus.erased
    student.must_change_password = False
    student.tutor_consent_at = None
    student.tutor_consent_by = None
    student.tutor_consent_form = None
    student.erase_requested_at = None
    student.erase_requested_by = None
    student.erase_due_at = None
    student.erased_at = now
    await tutor.purge_student_text(scope, student.id, now)
    for model in (Enrollment, AssignmentStudent):
        await scope.session.execute(
            delete(model).where(model.org_id == scope.org_id, model.student_id == student.id)
        )
    audit.record(scope, AuditAction.erase_completed, student.id, actor_id=None)


async def complete_due(session: AsyncSession, admin: SupabaseAdmin, now: datetime) -> DueResult:
    """Every school: one transaction per due student. Lock order as in consent withdrawal: the
    tutor advisory lock, then the row (`FOR UPDATE SKIP LOCKED`, re-checking that it is still
    due, so a concurrent run skips it). The Supabase auth user is deleted with the lock held (a
    404 counts as done); any other failure rolls that student back, is reported by id only, and
    is retried on the next run."""
    result = DueResult()
    tried: set[uuid.UUID] = set()
    while True:
        stmt = select(AppUser.id, AppUser.org_id).where(*_is_due(now))
        if tried:
            stmt = stmt.where(AppUser.id.not_in(tried))
        candidate = (await session.execute(stmt.order_by(AppUser.erase_due_at).limit(1))).first()
        await session.rollback()
        if candidate is None:
            return result
        sid, org_id = candidate
        tried.add(sid)
        scope = OrgScope.system(session, org_id)
        try:
            await tutor.lock_students(session, [sid])
            student = await session.scalar(
                select(AppUser)
                .where(AppUser.id == sid, *_is_due(now))
                .with_for_update(skip_locked=True)
            )
            if student is None:  # cancelled, reactivated or claimed by another run meanwhile
                await session.rollback()
                continue
            try:
                await admin.delete_user(sid)
            except SupabaseAdminError as exc:
                if exc.status != 404:  # already deleted (e.g. by hand in the dashboard) = done
                    raise
            await _anonymise(scope, student, now)
            await session.commit()
            result.done.append(sid)
            logger.info("Erasure completed for user %s", sid)
        except Exception:
            await session.rollback()
            result.failed.append(sid)
            logger.error("Erasure failed for user %s; retried on the next run", sid)
