from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_email_repository
from app.db.email_repository import EmailRepository
from app.models.schemas import (
    AgentTrainingDraftReplyUpdateRequest,
    AgentTrainingGeneralUpdateRequest,
    AgentTrainingResponse,
    ClassificationRulesResponse,
    ClassificationRulesUpdateRequest,
)
from app.services.classification_rules import (
    ClassificationRules,
    save_classification_rules,
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


@router.get(
    "/classification-rules",
    response_model=ClassificationRulesResponse,
    summary="Get classification and routing rules",
    description=(
        "Return category definitions, folder moves, forwarding targets, spam handling, "
        "and employee routing used by all automation runs."
    ),
)
async def get_classification_rules(
    repository: EmailRepository = Depends(get_email_repository),
) -> ClassificationRulesResponse:
    row = await repository.get_classification_rules()
    return ClassificationRulesResponse(**row)


@router.put(
    "/classification-rules",
    response_model=ClassificationRulesResponse,
    summary="Save classification and routing rules",
    description="Replace classification and routing rules applied to all automation runs.",
)
async def save_classification_rules_endpoint(
    body: ClassificationRulesUpdateRequest,
    repository: EmailRepository = Depends(get_email_repository),
) -> ClassificationRulesResponse:
    if not body.categories:
        raise HTTPException(status_code=400, detail="At least one category is required")

    slugs = [c.slug.strip() for c in body.categories]
    if len(slugs) != len(set(slugs)):
        raise HTTPException(status_code=400, detail="Category slugs must be unique")

    rules = ClassificationRules.from_api_dict(body.model_dump())
    saved = await save_classification_rules(repository, rules)
    return ClassificationRulesResponse(**saved.to_api_dict())
