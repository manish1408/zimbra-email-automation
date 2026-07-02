from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_email_repository, get_email_service, get_settings
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import AccountSyncResult, MailboxAutomationRunResponse, SyncResult
from app.services.email_sync import EmailSyncService
from app.services.llm import llm_configured, llm_not_configured_message
from app.services.message_automation import MessageAutomationService
from app.services.routing import RoutingResolver

router = APIRouter(prefix="/sync", tags=["Sync"])


def _automation_service(
    config: Settings,
    email_service: EmailSyncService,
    repository: EmailRepository,
) -> MessageAutomationService:
    resolver = RoutingResolver(config, email_service)
    return MessageAutomationService(config, email_service, repository, resolver)


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
    response_model=AccountSyncResult,
    summary="Sync single user mailbox",
    description="Export all messages for one user. Encode `@` as `%40` in the email path.",
)
async def sync_user_mailbox(
    user_email: str,
    query: str | None = Query(default=None, description="Zimbra search query override"),
    run_automation: bool = Query(
        default=False,
        description="After sync, classify unanalyzed messages and move them to folders on Zimbra",
    ),
    service: EmailSyncService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
    repository: EmailRepository = Depends(get_email_repository),
):
    try:
        result = await service.sync_user_mailbox(user_email=user_email, query=query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not run_automation:
        return AccountSyncResult(**result.model_dump())

    if not llm_configured(settings):
        raise HTTPException(status_code=503, detail=llm_not_configured_message(settings))

    automation = _automation_service(settings, service, repository)
    try:
        stats = await automation.run_for_mailbox(user_email)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Sync succeeded but automation failed: {exc}",
        ) from exc

    return AccountSyncResult(
        **result.model_dump(),
        automation=MailboxAutomationRunResponse(
            account=user_email,
            thread_id=stats.get("thread_id"),
            analysis_run_id=stats.get("analysis_run_id"),
            message_count=int(stats.get("message_count") or 0),
            classified=stats.get("classified"),
            moved=stats.get("moved"),
            spam=stats.get("spam"),
            forwarded=stats.get("forwarded"),
            acked=stats.get("acked"),
            drafts=stats.get("drafts"),
            dry_run=bool(stats.get("dry_run", settings.automation_dry_run)),
            move_to_folders=bool(
                stats.get("move_to_folders", settings.automation_move_to_folders)
            ),
            skipped=bool(stats.get("skipped")),
            reason=stats.get("reason"),
            errors=list(stats.get("errors") or []),
            summary=dict(stats.get("summary") or {}),
        ),
    )
