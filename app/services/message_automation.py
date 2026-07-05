from __future__ import annotations

import logging
import uuid
from typing import Any

from app.services.action_pipeline import run_action_pipeline
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import (
    MessageAutomationResult,
    MessageAutomationRunSummary,
)
from app.services.email_sync import EmailSyncService
from app.services.llm import llm_configured, llm_not_configured_message
from app.services.scheduled_pipeline import ScheduledPipeline

logger = logging.getLogger(__name__)


def _actions_from_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {
        "folder_path": record.get("folder_path"),
        "folder_moved": bool(record.get("folder_moved")),
        "forwarded_to": record.get("forwarded_to"),
        "ack_sent": bool(record.get("ack_sent")),
        "ack_draft_saved": bool(record.get("ack_draft_saved")),
        "draft_saved": bool(record.get("draft_saved")),
    }


def _actions_from_action_taken(action: dict[str, Any] | None) -> dict[str, Any] | None:
    if not action:
        return None
    return {
        "folder_path": action.get("folder_path"),
        "folder_moved": bool(action.get("folder_moved")),
        "forwarded_to": action.get("forwarded_to"),
        "ack_sent": bool(action.get("ack_sent")),
        "ack_draft_saved": bool(action.get("ack_draft_saved")),
        "draft_saved": bool(action.get("draft_saved")),
    }


def _run_summary(run: dict[str, Any]) -> MessageAutomationRunSummary:
    return MessageAutomationRunSummary(
        id=run["id"],
        thread_id=run["thread_id"],
        status=run["status"],
        dry_run=bool(run.get("dry_run")),
        classification=run.get("classification") or None,
        actions=run.get("actions") or None,
        draft_reply_text=run.get("draft_reply_text"),
        ack_body_text=run.get("ack_body_text"),
        error=run.get("error"),
        created_at=run.get("created_at"),
    )


def _automation_completed(action: dict[str, Any] | None) -> bool:
    return bool(action and action.get("classification"))


def _result_from_db(
    account: str,
    message_id: str,
    action: dict[str, Any] | None,
    runs: list[dict[str, Any]],
    *,
    thread_id: str | None = None,
    status: str | None = None,
    dry_run: bool = False,
    report: dict[str, Any] | None = None,
    error: str | None = None,
) -> MessageAutomationResult:
    classification = None
    actions = None
    draft_reply_text = None
    ack_body_text = None
    processed_at = None
    latest_run = runs[0] if runs else None

    if action:
        classification = action.get("classification")
        actions = {
            "folder_path": action.get("folder_path"),
            "folder_moved": bool(action.get("folder_moved")),
            "forwarded_to": action.get("forwarded_to"),
            "ack_sent": bool(action.get("ack_sent_at")),
            "ack_draft_saved": bool(
                action.get("ack_body_text") and not action.get("ack_sent_at")
            ),
            "draft_saved": bool(action.get("draft_saved")),
        }
        draft_reply_text = action.get("draft_reply_text")
        ack_body_text = action.get("ack_body_text")
        processed_at = action.get("processed_at")
        thread_id = thread_id or action.get("automation_thread_id")
        report = report or action.get("report")
        error = error or action.get("error")
        if not status and _automation_completed(action):
            status = "failed" if action.get("error") else "completed"

    if latest_run:
        if not classification:
            classification = latest_run.get("classification")
        if not actions:
            actions = latest_run.get("actions")
        if not draft_reply_text:
            draft_reply_text = latest_run.get("draft_reply_text")
        if not ack_body_text:
            ack_body_text = latest_run.get("ack_body_text")
        if not status:
            status = latest_run.get("status") or "completed"
        if not thread_id:
            thread_id = latest_run.get("thread_id")

    if runs and not thread_id:
        thread_id = runs[0].get("thread_id")

    return MessageAutomationResult(
        account=account,
        message_id=message_id,
        thread_id=thread_id or "",
        status=status or "skipped",
        dry_run=dry_run,
        classification=classification,
        actions=actions,
        draft_reply_text=draft_reply_text,
        ack_body_text=ack_body_text,
        report=report or {},
        error=error,
        processed_at=processed_at,
        runs=[_run_summary(r) for r in runs],
    )


class MessageAutomationService:
    """Run the production action pipeline for a single message."""

    def __init__(
        self,
        settings: Settings,
        email_service: EmailSyncService | None = None,
        repository: EmailRepository | None = None,
    ):
        self.settings = settings
        self.email_service = email_service or EmailSyncService(settings)
        self.repository = repository or EmailRepository(settings.database_url)

    async def run_for_message(
        self,
        account: str,
        message_id: str,
        *,
        force: bool = False,
    ) -> MessageAutomationResult:
        if not llm_configured(self.settings):
            raise ValueError(llm_not_configured_message(self.settings))

        if not force:
            conn = await self.repository.connect()
            try:
                if await self.repository.is_message_processed(conn, account, message_id):
                    existing = await self.get_result(account, message_id, conn=conn)
                    if existing:
                        return MessageAutomationResult(
                            account=existing.account,
                            message_id=existing.message_id,
                            thread_id=existing.thread_id,
                            status="skipped",
                            dry_run=existing.dry_run,
                            classification=existing.classification,
                            actions=existing.actions,
                            draft_reply_text=existing.draft_reply_text,
                            ack_body_text=existing.ack_body_text,
                            report=existing.report,
                            error="Message already processed; use force=true to re-run",
                            processed_at=existing.processed_at,
                            runs=existing.runs,
                        )
            finally:
                await conn.close()

        conn = await self.repository.connect()
        try:
            thread_id = f"manual:{account}:{message_id}:{uuid.uuid4().hex[:8]}"
            initial_state = {
                "user_email": account,
                "limit": 1,
                "use_local_db": True,
                "message_ids": [message_id],
                "force_reprocess": force,
                "automation_thread_id": thread_id,
            }
            try:
                result = await run_action_pipeline(
                    initial_state,
                    email_service=self.email_service,
                    settings=self.settings,
                    email_repository=self.repository,
                    conn=conn,
                )
            except Exception as exc:
                logger.exception("Automation pipeline failed for %s", message_id)
                await self._persist_run(
                    account,
                    message_id,
                    thread_id,
                    status="failed",
                    error=str(exc),
                    conn=conn,
                )
                raise

            messages = result.get("messages") or []
            if not messages:
                raise LookupError(f"Message {message_id} not found for {account}")

            report = result.get("report") or {}
            classifications = result.get("classifications") or []
            actions_taken = result.get("actions_taken") or []
            action_errors = result.get("action_errors") or []

            classification = classifications[0] if classifications else None
            action = actions_taken[0] if actions_taken else None

            if action_errors or (action and action.get("error")):
                status = "failed"
                error = "; ".join(action_errors) if action_errors else action.get("error")
            elif not action and not force:
                status = "skipped"
                error = "Message already processed; use force=true to re-run"
            else:
                status = "completed"
                error = None

            dry_run = bool(report.get("dry_run", self.settings.automation_dry_run))
            draft_reply_text = action.get("draft_reply_text") if action else None
            ack_body_text = action.get("ack_body_text") if action else None

            await self._persist_run(
                account,
                message_id,
                thread_id,
                status=status,
                dry_run=dry_run,
                classification=dict(classification) if classification else None,
                actions=_actions_from_action_taken(action),
                draft_reply_text=draft_reply_text,
                ack_body_text=ack_body_text,
                report=report,
                error=error,
                conn=conn,
            )

            return MessageAutomationResult(
                account=account,
                message_id=message_id,
                thread_id=thread_id,
                status=status,
                dry_run=dry_run,
                classification=dict(classification) if classification else None,
                actions=_actions_from_action_taken(action),
                draft_reply_text=draft_reply_text,
                ack_body_text=ack_body_text,
                report=report,
                error=error,
                processed_at=None,
            )
        finally:
            await conn.close()

    async def get_result(
        self,
        account: str,
        message_id: str,
        *,
        include_runs: bool = True,
        runs_limit: int = 10,
        conn: Any | None = None,
    ) -> MessageAutomationResult | None:
        own_conn = conn is None
        if own_conn:
            conn = await self.repository.connect()
        try:
            action = await self.repository.get_message_action(conn, account, message_id)
            runs: list[dict[str, Any]] = []
            if include_runs:
                runs = await self.repository.get_message_automation_runs(
                    conn, account, message_id, limit=runs_limit
                )
        finally:
            if own_conn and conn is not None:
                await conn.close()

        if not _automation_completed(action) and not runs:
            return None

        dry_run = self.settings.automation_dry_run
        if runs:
            dry_run = bool(runs[0].get("dry_run"))

        return _result_from_db(
            account,
            message_id,
            action,
            runs,
            dry_run=dry_run,
        )

    async def list_runs(
        self,
        account: str,
        message_id: str,
        limit: int = 10,
    ) -> list[MessageAutomationRunSummary]:
        conn = await self.repository.connect()
        try:
            runs = await self.repository.get_message_automation_runs(
                conn, account, message_id, limit=limit
            )
        finally:
            await conn.close()
        return [_run_summary(r) for r in runs]

    async def _persist_run(
        self,
        account: str,
        message_id: str,
        thread_id: str,
        *,
        status: str,
        dry_run: bool = False,
        classification: dict[str, Any] | None = None,
        actions: dict[str, Any] | None = None,
        draft_reply_text: str | None = None,
        ack_body_text: str | None = None,
        report: dict[str, Any] | None = None,
        error: str | None = None,
        conn: Any | None = None,
    ) -> None:
        own_conn = conn is None
        if own_conn:
            conn = await self.repository.connect()
        try:
            await self.repository.save_message_automation_run(
                conn,
                account,
                message_id,
                thread_id,
                status,
                dry_run=dry_run,
                classification=classification,
                actions=actions,
                draft_reply_text=draft_reply_text,
                ack_body_text=ack_body_text,
                report=report,
                error=error,
            )
            await conn.commit() if hasattr(conn, "commit") else None
        finally:
            if own_conn and conn is not None:
                await conn.close()

    async def run_for_mailbox(self, account: str) -> dict[str, Any]:
        """Run classify-and-move pipeline on all unanalyzed messages (same as cron job)."""
        if not llm_configured(self.settings):
            raise ValueError(llm_not_configured_message(self.settings))

        conn = await self.repository.connect()
        try:
            pipeline = ScheduledPipeline(
                self.settings,
                self.email_service,
                self.repository,
            )
            return await pipeline.run_action_pipeline(conn, account)
        finally:
            await conn.close()
