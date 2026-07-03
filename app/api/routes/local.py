from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_db_connection, get_email_repository
from app.db.email_repository import DbConnection, EmailRepository
from app.models.schemas import (
    AnalysisRunListResponse,
    AnalysisRunSummary,
    LocalMailboxStats,
    LocalMessageListResponse,
    MessageDetail,
    MessageMetadata,
    MessageSummary,
)

router = APIRouter(prefix="/local/users/{user_email}", tags=["Local Data"])


@router.get(
    "/messages",
    response_model=LocalMessageListResponse,
    summary="List synced messages from local database",
)
async def list_local_messages(
    user_email: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    analyzed: bool | None = Query(default=None, description="Filter by analyzed status"),
    repository: EmailRepository = Depends(get_email_repository),
    conn: DbConnection = Depends(get_db_connection),
):
    try:
        messages, total = await repository.get_messages(
            conn, user_email, limit=limit, offset=offset, analyzed=analyzed
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    summaries = [MessageSummary(**m.model_dump()) for m in messages]
    return LocalMessageListResponse(
        account=user_email,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(summaries)) < total,
        messages=summaries,
    )


@router.get(
    "/messages/{message_id}",
    response_model=MessageDetail,
    summary="Get synced message from local database",
)
async def get_local_message(
    user_email: str,
    message_id: str,
    repository: EmailRepository = Depends(get_email_repository),
    conn: DbConnection = Depends(get_db_connection),
):
    try:
        message = await repository.get_message(conn, user_email, message_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    if not message:
        raise HTTPException(status_code=404, detail="Message not found in local database")
    return message


@router.get(
    "/messages/{message_id}/metadata",
    response_model=MessageMetadata,
    summary="Get automation metadata for a synced message",
)
async def get_message_metadata(
    user_email: str,
    message_id: str,
    repository: EmailRepository = Depends(get_email_repository),
    conn: DbConnection = Depends(get_db_connection),
):
    try:
        action = await repository.get_message_action(conn, user_email, message_id)
        analyzed_at = await repository.get_analyzed_at(conn, user_email, message_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    if not action and not analyzed_at:
        raise HTTPException(status_code=404, detail="No metadata found for this message")

    if action:
        return MessageMetadata(
            zimbra_id=action["zimbra_id"],
            account=action["account"],
            category=action.get("category"),
            is_spam=bool(action.get("is_spam")),
            folder_path=action.get("folder_path"),
            forwarded_to=action.get("forwarded_to"),
            ack_sent_at=action.get("ack_sent_at"),
            draft_saved=bool(action.get("draft_saved")),
            classification=action.get("classification"),
            draft_reply_text=action.get("draft_reply_text"),
            ack_body_text=action.get("ack_body_text"),
            thread_summary=action.get("thread_summary"),
            report=action.get("report"),
            error=action.get("error"),
            processed_at=action.get("processed_at"),
            analyzed_at=analyzed_at,
        )

    return MessageMetadata(
        zimbra_id=message_id,
        account=user_email,
        analyzed_at=analyzed_at,
    )


@router.get(
    "/stats",
    response_model=LocalMailboxStats,
    summary="Local sync statistics for a mailbox",
)
async def get_local_stats(
    user_email: str,
    repository: EmailRepository = Depends(get_email_repository),
    conn: DbConnection = Depends(get_db_connection),
):
    try:
        total = await repository.count_messages(conn, user_email)
        unanalyzed = await repository.count_unanalyzed(conn, user_email)
        state = await repository.get_mailbox_state(conn, user_email)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    last_poll_at = None
    if state and state.get("last_poll_at"):
        val = state["last_poll_at"]
        last_poll_at = val.isoformat() if hasattr(val, "isoformat") else str(val)

    return LocalMailboxStats(
        account=user_email,
        total=total,
        unanalyzed=unanalyzed,
        last_seen_date=state.get("last_seen_date") if state else None,
        last_poll_at=last_poll_at,
        last_poll_new_count=int(state.get("last_poll_new_count") or 0) if state else 0,
    )


@router.get(
    "/analysis-runs",
    response_model=AnalysisRunListResponse,
    summary="Recent agent analysis runs for a mailbox",
)
async def list_analysis_runs(
    user_email: str,
    limit: int = Query(default=20, ge=1, le=100),
    repository: EmailRepository = Depends(get_email_repository),
    conn: DbConnection = Depends(get_db_connection),
):
    try:
        runs = await repository.get_analysis_runs(conn, user_email, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    return AnalysisRunListResponse(
        account=user_email,
        runs=[AnalysisRunSummary(**run) for run in runs],
    )
