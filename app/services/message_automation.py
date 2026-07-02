from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.action_graph import build_action_graph
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import (
    MessageAutomationResult,
    MessageAutomationRunSummary,
    ThreadSummaryResponse,
)
from app.services.email_sync import EmailSyncService
from app.services.llm import llm_configured, llm_not_configured_message
from app.services.routing import RoutingResolver
from app.services.scheduled_pipeline import ScheduledPipeline
from app.services.thread_summary import ThreadSummaryService

logger = logging.getLogger(__name__)


def _actions_from_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {
        "folder_path": record.get("folder_path"),
        "folder_moved": bool(record.get("folder_moved")),
        "forwarded_to": record.get("forwarded_to"),
        "ack_sent": bool(record.get("ack_sent")),
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
    thread_summary = None
    processed_at = None

    if action:
        classification = action.get("classification")
        actions = {
            "folder_path": action.get("folder_path"),
            "folder_moved": bool(action.get("folder_moved")),
            "forwarded_to": action.get("forwarded_to"),
            "ack_sent": bool(action.get("ack_sent_at")),
            "draft_saved": bool(action.get("draft_saved")),
        }
        draft_reply_text = action.get("draft_reply_text")
        ack_body_text = action.get("ack_body_text")
        thread_summary = action.get("thread_summary")
        processed_at = action.get("processed_at")
        thread_id = thread_id or action.get("automation_thread_id")
        report = report or action.get("report")
        error = error or action.get("error")
        if not status:
            status = "failed" if action.get("error") else "completed"

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
        thread_summary=thread_summary,
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
        resolver: RoutingResolver | None = None,
    ):
        self.settings = settings
        self.email_service = email_service or EmailSyncService(settings)
        self.repository = repository or EmailRepository(settings.database_url)
        self.resolver = resolver or RoutingResolver(settings, self.email_service)

    async def run_for_message(
        self,
        account: str,
        message_id: str,
        *,
        force: bool = False,
    ) -> MessageAutomationResult:
        if not llm_configured(self.settings):
            raise ValueError(llm_not_configured_message(self.settings))

        thread_id = f"manual:{account}:{message_id}:{uuid.uuid4().hex[:8]}"
        checkpoint_path = self.settings.agent_checkpoint_path

        async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
            await checkpointer.setup()
            graph = build_action_graph(
                email_service=self.email_service,
                settings=self.settings,
                checkpointer=checkpointer,
                email_repository=self.repository,
                resolver=self.resolver,
            )
            config = {"configurable": {"thread_id": thread_id}}
            initial_state = {
                "user_email": account,
                "limit": 1,
                "use_local_db": True,
                "message_ids": [message_id],
                "force_reprocess": force,
                "automation_thread_id": thread_id,
            }
            try:
                result = await graph.ainvoke(initial_state, config=config)
            except Exception as exc:
                logger.exception("Automation pipeline failed for %s", message_id)
                await self._persist_run(
                    account,
                    message_id,
                    thread_id,
                    status="failed",
                    error=str(exc),
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
        thread_summaries = result.get("thread_summaries") or []
        thread_summary = (
            thread_summaries[0]
            if thread_summaries
            else (action.get("thread_summary") if action else None)
        )

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
            thread_summary=thread_summary,
            report=report,
            error=error,
            processed_at=None,
        )

    async def get_thread_summary(
        self,
        account: str,
        message_id: str,
        *,
        refresh: bool = False,
    ) -> ThreadSummaryResponse:
        if not llm_configured(self.settings):
            raise ValueError(llm_not_configured_message(self.settings))

        conn = await self.repository.connect()
        try:
            if not refresh:
                action = await self.repository.get_message_action(conn, account, message_id)
                if action and action.get("thread_summary"):
                    summary = action["thread_summary"]
                    return ThreadSummaryResponse(
                        account=account,
                        message_id=message_id,
                        history_points=summary.get("history_points") or [],
                        current_points=summary.get("current_points") or [],
                        focus=summary.get("focus") or "",
                    )
        finally:
            await conn.close()

        message = await self._load_message_dict(account, message_id)
        if not message:
            raise LookupError(f"Message {message_id} not found for {account}")

        related: list[dict[str, Any]] = []
        try:
            thread_messages = await self.email_service.search_thread_messages(
                account,
                message.get("subject"),
                exclude_id=message_id,
                limit=4,
            )
            related = [item.model_dump(by_alias=True) for item in thread_messages]
        except Exception:
            related = []

        summary = await ThreadSummaryService(self.settings).summarize(message, related)

        conn = await self.repository.connect()
        try:
            await self.repository.save_thread_summary(conn, account, message_id, summary)
            if hasattr(conn, "commit"):
                await conn.commit()
        finally:
            await conn.close()

        return ThreadSummaryResponse(
            account=account,
            message_id=message_id,
            history_points=summary.get("history_points") or [],
            current_points=summary.get("current_points") or [],
            focus=summary.get("focus") or "",
        )

    async def _load_message_dict(
        self, account: str, message_id: str
    ) -> dict[str, Any] | None:
        conn = await self.repository.connect()
        try:
            detail = await self.repository.get_message(conn, account, message_id)
            if detail:
                if not detail.body:
                    try:
                        full = await self.email_service.get_message(account, message_id)
                        detail.body = full.body
                    except Exception:
                        pass
                return EmailRepository.to_summary_dict(detail)
        finally:
            await conn.close()

        try:
            detail = await self.email_service.get_message(account, message_id)
            return detail.model_dump(by_alias=True)
        except Exception:
            return None

    async def get_result(
        self,
        account: str,
        message_id: str,
        *,
        include_runs: bool = True,
        runs_limit: int = 10,
    ) -> MessageAutomationResult | None:
        conn = await self.repository.connect()
        try:
            action = await self.repository.get_message_action(conn, account, message_id)
            runs: list[dict[str, Any]] = []
            if include_runs:
                runs = await self.repository.get_message_automation_runs(
                    conn, account, message_id, limit=runs_limit
                )
        finally:
            await conn.close()

        if not action and not runs:
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
    ) -> None:
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
                self.resolver,
            )
            return await pipeline.run_action_pipeline(conn, account)
        finally:
            await conn.close()
