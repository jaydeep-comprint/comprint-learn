"""API shapes for XP, daily goals, streaks and class leaderboards (spec 008).

Displayed totals (`xp`, `week_xp`, `total_xp`) are floored at 0; the ledger keeps real negatives.
Students never see classmates' ids or usernames: leaderboard rows carry `student_id` for staff only.
"""

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.models import Subject, XpGrade


class XpAwardOut(BaseModel):
    """The award for the answer that ended a session (and for a resend of that answer)."""

    amount: int
    grade: XpGrade
    base_minutes: Decimal
    hints: int
    goal_met_today: bool  # this award made today met (the first time)


class XpTodayOut(BaseModel):
    subject: Subject
    xp: int
    goal: int | None
    met: bool


class StreakOut(BaseModel):
    days: int
    today_met: bool


class GoalOut(BaseModel):
    subject: Subject
    class_goal: int
    own_goal: int | None
    effective: int


class LeaderboardRef(BaseModel):
    class_id: uuid.UUID
    class_name: str
    subject: Subject


class XpSummary(BaseModel):
    today: list[XpTodayOut]
    streak: StreakOut
    week_xp: int
    total_xp: int
    goals: list[GoalOut]
    leaderboards: list[LeaderboardRef]


class GoalIn(BaseModel):
    goal: int | None  # validated in the service (422 `goal_invalid`); null = class goal


class LeaderboardRow(BaseModel):
    rank: int
    display_name: str
    week_xp: int
    is_me: bool
    student_id: uuid.UUID | None = None  # staff only


class LeaderboardOut(BaseModel):
    class_name: str
    subject: Subject
    enabled: bool
    week_start: dt.date
    rows: list[LeaderboardRow]
