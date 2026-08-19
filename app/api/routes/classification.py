from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_email_repository
from app.db.email_repository import EmailRepository
from app.models.schemas import (
    ClassificationRulesResponse,
    ClassificationRulesUpdateRequest,
    MailboxClassificationRulesResponse,
    MailboxClassificationRulesUpdateRequest,
)
from app.services.classification_rules import (
    ClassificationRules,
    save_global_classification_rules,
    save_mailbox_classification_rules,
    seed_mailbox_classification_rules,
)

router = APIRouter(prefix="/classification", tags=["Classification"])


def _unique_slugs(categories: list) -> list[str]:
    slugs = [c.slug.strip() for c in categories]
    if len(slugs) != len(set(slugs)):
        raise HTTPException(status_code=400, detail="Category slugs must be unique")
    return slugs


@router.get(
    "/global",
    response_model=ClassificationRulesResponse,
    summary="Get global classification rules",
    description="Spam filtering, shared classification instructions, and employee routing.",
)
async def get_global_rules(
    repository: EmailRepository = Depends(get_email_repository),
) -> ClassificationRulesResponse:
    row = await repository.get_global_classification_rules()
    return ClassificationRulesResponse(**row)


@router.put(
    "/global",
    response_model=ClassificationRulesResponse,
    summary="Save global classification rules",
)
async def save_global_rules(
    body: ClassificationRulesUpdateRequest,
    repository: EmailRepository = Depends(get_email_repository),
) -> ClassificationRulesResponse:
    if not body.categories:
        raise HTTPException(status_code=400, detail="At least one spam category is required")
    _unique_slugs(body.categories)
    if any(not category.is_spam for category in body.categories):
        raise HTTPException(
            status_code=400,
            detail="Global categories must be spam filters (is_spam=true)",
        )
    if any(not category.slug.strip() for category in body.categories):
        raise HTTPException(status_code=400, detail="Category slugs are required")

    rules = ClassificationRules.from_api_dict(body.model_dump())
    saved = await save_global_classification_rules(repository, rules)
    return ClassificationRulesResponse(**saved.to_api_dict())


@router.get(
    "/mailboxes/{user_email}",
    response_model=MailboxClassificationRulesResponse,
    summary="Get classification rules for one mailbox",
)
async def get_mailbox_rules(
    user_email: str,
    repository: EmailRepository = Depends(get_email_repository),
) -> MailboxClassificationRulesResponse:
    row = await repository.get_mailbox_classification_rules(user_email)
    return MailboxClassificationRulesResponse(**row)


@router.put(
    "/mailboxes/{user_email}",
    response_model=MailboxClassificationRulesResponse,
    summary="Save classification rules for one mailbox",
)
async def save_mailbox_rules(
    user_email: str,
    body: MailboxClassificationRulesUpdateRequest,
    repository: EmailRepository = Depends(get_email_repository),
) -> MailboxClassificationRulesResponse:
    _unique_slugs(body.categories)
    if any(category.is_spam for category in body.categories):
        raise HTTPException(
            status_code=400,
            detail="Inbox categories cannot be marked as spam; spam filtering is global",
        )
    if any(not category.slug.strip() or not category.folder.strip() for category in body.categories):
        raise HTTPException(status_code=400, detail="Category slug and folder are required")

    saved = await save_mailbox_classification_rules(
        repository, user_email, body.model_dump()
    )
    return MailboxClassificationRulesResponse(**saved)


@router.post(
    "/mailboxes/{user_email}/seed",
    response_model=MailboxClassificationRulesResponse,
    summary="Copy starter categories onto a mailbox",
)
async def seed_mailbox_rules(
    user_email: str,
    repository: EmailRepository = Depends(get_email_repository),
) -> MailboxClassificationRulesResponse:
    saved = await seed_mailbox_classification_rules(repository, user_email)
    return MailboxClassificationRulesResponse(**saved)
