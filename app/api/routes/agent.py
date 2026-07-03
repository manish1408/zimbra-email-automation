from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_email_repository
from app.db.email_repository import EmailRepository
from app.models.schemas import AgentTrainingResponse, AgentTrainingUpdateRequest

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.get(
    "/training",
    response_model=AgentTrainingResponse,
    summary="Get global agent training",
    description="Return organization-wide training text applied to all mailboxes.",
)
async def get_agent_training(
    repository: EmailRepository = Depends(get_email_repository),
) -> AgentTrainingResponse:
    row = await repository.get_agent_training()
    return AgentTrainingResponse(**row)


@router.put(
    "/training",
    response_model=AgentTrainingResponse,
    summary="Save global agent training",
    description="Replace organization-wide training text for all mailboxes.",
)
async def save_agent_training(
    body: AgentTrainingUpdateRequest,
    repository: EmailRepository = Depends(get_email_repository),
) -> AgentTrainingResponse:
    row = await repository.upsert_agent_training(body.content.strip())
    return AgentTrainingResponse(**row)
