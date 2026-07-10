from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_email_repository, get_email_service, get_settings
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import AutomationLogEntry, AutomationLogListResponse
from app.services.email_sync import EmailSyncService
from app.services.message_automation import MessageAutomationService

router = APIRouter(prefix="/automation", tags=["Automation"])


def get_automation_service(
    config: Settings = Depends(get_settings),
    email_service: EmailSyncService = Depends(get_email_service),
    repository: EmailRepository = Depends(get_email_repository),
) -> MessageAutomationService:
    return MessageAutomationService(config, email_service, repository)


@router.get(
    "/logs",
    response_model=AutomationLogListResponse,
    summary="List automation run logs across all mailboxes",
)
async def list_all_automation_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter by status"),
    message_id: str | None = Query(
        default=None, description="Filter by Zimbra message ID (exact match)"
    ),
    service: MessageAutomationService = Depends(get_automation_service),
):
    try:
        logs, total = await service.list_all_automation_logs(
            limit=limit,
            offset=offset,
            status=status,
            message_id=message_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    entries = [AutomationLogEntry(**log) for log in logs]
    return AutomationLogListResponse(
        account="*",
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(entries)) < total,
        logs=entries,
    )
