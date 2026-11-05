"""XP, daily goals and class leaderboards (spec 008). Every route goes through `OrgScope`.
`/me/xp` and `/me/goals` are student-only (403 for staff); the leaderboard is for staff always and
for enrolled students only while the teacher has it on (404 otherwise)."""

import uuid

from fastapi import APIRouter

from app.api.deps import Scope
from app.models import Subject
from app.schemas.xp import GoalIn, LeaderboardOut, XpSummary
from app.services import xp

router = APIRouter(tags=["xp"])


@router.get("/me/xp", response_model=XpSummary)
async def my_xp(scope: Scope) -> XpSummary:
    return await xp.summary(scope)


@router.put("/me/goals/{subject}", response_model=XpSummary)
async def set_goal(subject: Subject, body: GoalIn, scope: Scope) -> XpSummary:
    """422 `goal_invalid` / `goal_below_class` / `no_class_for_subject`."""
    return await xp.set_own_goal(scope, subject, body.goal)


@router.get(
    "/classes/{class_id}/leaderboard",
    response_model=LeaderboardOut,
    response_model_exclude_none=True,
)
async def class_leaderboard(class_id: uuid.UUID, scope: Scope) -> LeaderboardOut:
    return await xp.leaderboard(scope, class_id)
