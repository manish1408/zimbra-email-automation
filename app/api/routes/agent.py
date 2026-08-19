from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_email_repository
from app.db.email_repository import EmailRepository
from app.models.schemas import (
    AgentTrainingDraftReplyUpdateRequest,
    AgentTrainingGeneralUpdateRequest,
    AgentTrainingResponse,
)

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.get(
    "/training",
    response_model=AgentTrainingResponse,
    summary="Get general and draft-reply training rules",
)
async def get_agent_training(
    repository: EmailRepository = Depends(get_email_repository),
) -> AgentTrainingResponse:
    row = await repository.get_agent_training()
    return AgentTrainingResponse(**row)


@router.put(
    "/training/general-rules",
    response_model=AgentTrainingResponse,
    summary="Save general agent rules",
)
async def save_general_rules(
    body: AgentTrainingGeneralUpdateRequest,
    repository: EmailRepository = Depends(get_email_repository),
) -> AgentTrainingResponse:
    row = await repository.upsert_agent_general_rules(body.general_rules.strip())
    return AgentTrainingResponse(**row)


@router.put(
    "/training/draft-reply-rules",
    response_model=AgentTrainingResponse,
    summary="Save draft reply rules",
)
async def save_draft_reply_rules(
    body: AgentTrainingDraftReplyUpdateRequest,
    repository: EmailRepository = Depends(get_email_repository),
) -> AgentTrainingResponse:
    row = await repository.upsert_agent_draft_reply_rules(body.draft_reply_rules.strip())
    return AgentTrainingResponse(**row)
