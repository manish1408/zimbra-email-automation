from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_email_service
from app.models.schemas import AccountMessages, SyncResult
from app.services.email_sync import EmailSyncService

router = APIRouter(prefix="/sync", tags=["Sync"])


@router.post(
    "",
    response_model=SyncResult,
    summary="Sync all user mailboxes",
    description="Bulk-export messages from all users (or a limited subset) for automation pipelines.",
)
async def sync_all_users(
    query: str | None = Query(
        default=None,
        description="Zimbra search query. Defaults to `in:anywhere`.",
    ),
    max_accounts: int | None = Query(
        default=None,
        ge=1,
        description="Limit number of users processed (recommended while testing).",
    ),
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        return await service.sync_all_mailboxes(query=query, max_accounts=max_accounts)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/users/{user_email}",
    response_model=AccountMessages,
    summary="Sync single user mailbox",
    description="Export all messages for one user. Encode `@` as `%40` in the email path.",
)
async def sync_user_mailbox(
    user_email: str,
    query: str | None = Query(default=None, description="Zimbra search query override"),
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        return await service.sync_user_mailbox(user_email=user_email, query=query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
