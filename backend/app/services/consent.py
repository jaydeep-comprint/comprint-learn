"""AI-tutor consent (spec 014): school-attested, per student, recorded or withdrawn by staff.

Current state lives on `app_user` (`tutor_consent_at/by/form`); history is in `audit_event`.
Withdrawal nulls the student's tutor chat text at once. Both take the tutor's per-student advisory
locks (sorted ids) and then the `app_user` rows in id order, so a reply that is still running stores
no text once a withdrawal has committed.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from app.api.deps import OrgScope
from app.core.errors import ApiProblem, not_found
from app.models import AppUser, AuditAction, Role, UserStatus
from app.privacy import NOTICE_VERSION
from app.schemas.tenancy import StudentOut
from app.services import audit, tenancy, tutor

has_consent = tutor.has_consent

CONSENT_NOT_ALLOWED = "Consent can't be recorded for a student whose erasure is pending."


async def apply(
    scope: OrgScope, student_ids: Sequence[uuid.UUID], action: Literal["record", "withdraw"]
) -> list[StudentOut]:
    """All-or-nothing: any unknown, other-school, teacher or erased id → 404; for `record`, a
    pending erasure → 422 `consent_not_allowed`. Students already in the target state are left
    unchanged (no event)."""
    ids = sorted(set(student_ids))
    await tutor.lock_students(scope.session, ids)
    stmt = scope.select(AppUser).where(AppUser.id.in_(ids)).order_by(AppUser.id).with_for_update()
    students = list((await scope.session.scalars(stmt)).all())
    if len(students) != len(ids) or any(
        s.role != Role.student or s.status == UserStatus.erased for s in students
    ):
        raise not_found()
    now = datetime.now(UTC)
    if action == "record":
        blocked = [
            s.id
            for s in students
            if s.erase_requested_at is not None
            or s.status not in (UserStatus.active, UserStatus.deactivated)
        ]
        if blocked:
            raise ApiProblem(
                422,
                "consent_not_allowed",
                CONSENT_NOT_ALLOWED,
                extra={"student_ids": [str(i) for i in blocked]},
            )
        for s in students:
            if s.tutor_consent_at is not None:
                continue
            s.tutor_consent_at = now
            s.tutor_consent_by = scope.user.id
            s.tutor_consent_form = NOTICE_VERSION
            audit.record(scope, AuditAction.consent_recorded, s.id, {"form": NOTICE_VERSION})
    else:
        for s in students:
            if s.tutor_consent_at is None:
                continue
            form = s.tutor_consent_form
            s.tutor_consent_at = None
            s.tutor_consent_by = None
            s.tutor_consent_form = None
            purged = await tutor.purge_student_text(scope, s.id, now)
            audit.record(
                scope,
                AuditAction.consent_withdrawn,
                s.id,
                {"form": form, "messages_purged": purged},
            )
    await scope.session.commit()
    classes = await tenancy.class_ids_by_student(scope, ids)
    return [tenancy.student_out(s, classes.get(s.id, [])) for s in students]
