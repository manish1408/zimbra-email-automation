from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_email_service
from app.models.schemas import (
    FolderListResponse,
    InboxResponse,
    MessageDetail,
    MessageSearchResponse,
)
from app.services.email_sync import EmailSyncService

router = APIRouter(prefix="/users/{user_email}", tags=["Mailboxes"])


@router.get(
    "/inbox",
    response_model=InboxResponse,
    summary="View user inbox",
    description=(
        "Returns paginated inbox messages for any user via admin DelegateAuth. "
        "Encode `@` in the email as `%40`."
    ),
)
async def get_user_inbox(
    user_email: str,
    limit: int = Query(default=50, ge=1, le=500, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        return await service.get_inbox(user_email=user_email, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/messages",
    response_model=MessageSearchResponse,
    summary="Search user messages",
    description=(
        "Search a user's mailbox with Zimbra query syntax. "
        "Examples: `in:inbox`, `in:sent`, `from:someone@domain.com`, `subject:invoice`."
    ),
)
async def search_user_messages(
    user_email: str,
    query: str = Query(default="in:anywhere", description="Zimbra search query"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        return await service.search_user_messages(
            user_email=user_email,
            query=query,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/messages/{message_id}",
    response_model=MessageDetail,
    summary="Get message by ID",
    description="Fetch full message content for a specific message in the user's mailbox.",
)
async def get_user_message(
    user_email: str,
    message_id: str,
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        return await service.get_message(user_email=user_email, message_id=message_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/folders",
    response_model=FolderListResponse,
    summary="List mailbox folders",
    description="Returns folder tree for the user's mailbox (Inbox, Sent, Drafts, etc.).",
)
async def list_user_folders(
    user_email: str,
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        return await service.list_folders(user_email=user_email)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
