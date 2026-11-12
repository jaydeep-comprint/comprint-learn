"""API shapes for the AI tutor (spec 009). No answer values, ids of other students or names."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.ai import limits
from app.schemas.learn import ConceptRef


class TutorMessageOut(BaseModel):
    id: str
    role: Literal["student", "tutor"]
    kind: Literal["hint", "chat"]
    rung: int | None
    text: str | None  # null for a hint request, or after the 180-day purge
    link: ConceptRef | None  # rung 2: the prerequisite to open
    created_at: datetime


class TutorThread(BaseModel):
    enabled: bool
    consent: bool  # spec 014: tutor consent recorded (always present, also when disabled)
    mode: Literal["before", "after"]
    closed: bool  # POSTs get 409 `session_closed` (finished question / after-mode window over)
    hints_used: int
    hints_left: int  # 0 in after mode
    next_rung: int | None  # null after 3 hints and in after mode
    chat_left: int
    daily_left: int
    resets_at: datetime  # next 00:00 Asia/Kolkata
    messages: list[TutorMessageOut]


class TutorReply(BaseModel):
    message: TutorMessageOut
    thread: TutorThread


class HintIn(BaseModel):
    draft: str | None = Field(default=None, max_length=limits.MAX_DRAFT)
    step: int | None = Field(default=None, ge=0, le=20)


class ChatIn(BaseModel):
    # The 500-character limit is checked by the service (422 `message_too_long`).
    text: str = Field(min_length=1, max_length=4 * limits.MAX_MESSAGE)
    draft: str | None = Field(default=None, max_length=limits.MAX_DRAFT)
