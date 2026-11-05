"""AI tutor routes (spec 009). Students only (staff get 403); every route builds the org scope."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.ai.client import TutorClient, get_tutor_client
from app.api.deps import StudentScope
from app.schemas.tutor import ChatIn, HintIn, TutorReply, TutorThread
from app.services import tutor

router = APIRouter(prefix="/tutor", tags=["tutor"])
Client = Annotated[TutorClient | None, Depends(get_tutor_client)]


@router.get("/{session_id}/{position}", response_model=TutorThread)
async def get_thread(
    session_id: uuid.UUID, position: int, scope: StudentScope, client: Client
) -> TutorThread:
    return await tutor.get_thread(scope, session_id, position, client)


@router.post("/{session_id}/{position}/hint", response_model=TutorReply)
async def hint(
    session_id: uuid.UUID, position: int, body: HintIn, scope: StudentScope, client: Client
) -> TutorReply:
    return await tutor.request_hint(scope, session_id, position, client, body.draft)


@router.post("/{session_id}/{position}/messages", response_model=TutorReply)
async def message(
    session_id: uuid.UUID, position: int, body: ChatIn, scope: StudentScope, client: Client
) -> TutorReply:
    return await tutor.send_message(scope, session_id, position, client, body.text, body.draft)
