from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_email_repository, get_email_service, get_settings
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import (
    MailboxAutomationRunResponse,
    MessageAutomationResult,
    MessageAutomationRunListResponse,
    MessageAutomationRunRequest,
    ThreadSummaryResponse,
)
from app.services.email_sync import EmailSyncService
from app.services.llm import llm_configured, llm_not_configured_message
from app.services.message_automation import MessageAutomationService
from app.services.routing import RoutingResolver

router = APIRouter(prefix="/automation/users/{user_email}", tags=["Automation"])


def get_automation_service(
    config: Settings = Depends(get_settings),
    email_service: EmailSyncService = Depends(get_email_service),
    repository: EmailRepository = Depends(get_email_repository),
) -> MessageAutomationService:
    resolver = RoutingResolver(config, email_service)
    return MessageAutomationService(config, email_service, repository, resolver)


@router.post(
    "/messages/{message_id}/run",
    response_model=MessageAutomationResult,
    summary="Run automation pipeline for one message",
)
async def run_message_automation(
    user_email: str,
    message_id: str,
    body: MessageAutomationRunRequest | None = None,
    service: MessageAutomationService = Depends(get_automation_service),
    settings: Settings = Depends(get_settings),
):
    if not llm_configured(settings):
        raise HTTPException(status_code=503, detail=llm_not_configured_message(settings))

    force = body.force if body else False
    try:
        return await service.run_for_message(user_email, message_id, force=force)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Automation pipeline failed: {exc}",
        ) from exc


@router.get(
    "/messages/{message_id}",
    response_model=MessageAutomationResult,
    summary="Latest automation result for a message",
)
async def get_message_automation(
    user_email: str,
    message_id: str,
    service: MessageAutomationService = Depends(get_automation_service),
):
    try:
        result = await service.get_result(user_email, message_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    if not result:
        raise HTTPException(status_code=404, detail="No automation result for this message")
    return result


@router.get(
    "/messages/{message_id}/runs",
    response_model=MessageAutomationRunListResponse,
    summary="Automation run history for a message",
)
async def list_message_automation_runs(
    user_email: str,
    message_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    service: MessageAutomationService = Depends(get_automation_service),
):
    try:
        runs = await service.list_runs(user_email, message_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    return MessageAutomationRunListResponse(
        account=user_email,
        message_id=message_id,
        runs=runs,
    )


@router.post(
    "/run",
    response_model=MailboxAutomationRunResponse,
    summary="Run classify-and-move pipeline for a mailbox",
    description=(
        "Classifies unanalyzed messages and moves them to category folders on Zimbra. "
        "Uses the same pipeline as the scheduled cron job."
    ),
)
async def run_mailbox_automation(
    user_email: str,
    service: MessageAutomationService = Depends(get_automation_service),
    settings: Settings = Depends(get_settings),
):
    if not llm_configured(settings):
        raise HTTPException(status_code=503, detail=llm_not_configured_message(settings))

    try:
        stats = await service.run_for_mailbox(user_email)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Mailbox automation failed: {exc}",
        ) from exc

    return MailboxAutomationRunResponse(
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
    )


@router.get(
    "/messages/{message_id}/thread-summary",
    response_model=ThreadSummaryResponse,
    summary="Get point-wise thread summary for a message",
    description=(
        "Returns a cached thread summary when available, otherwise generates one. "
        "Personal details are redacted before summarization."
    ),
)
async def get_message_thread_summary(
    user_email: str,
    message_id: str,
    refresh: bool = Query(default=False, description="Regenerate even if cached"),
    service: MessageAutomationService = Depends(get_automation_service),
    settings: Settings = Depends(get_settings),
):
    if not llm_configured(settings):
        raise HTTPException(status_code=503, detail=llm_not_configured_message(settings))

    try:
        return await service.get_thread_summary(
            user_email, message_id, refresh=refresh
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread summary failed: {exc}",
        ) from exc
