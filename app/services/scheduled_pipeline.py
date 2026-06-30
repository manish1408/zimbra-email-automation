from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.action_graph import build_action_graph
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import MessageDetail
from app.services.email_sync import EmailSyncService
from app.services.routing import RoutingResolver

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _zimbra_after_date(iso_date: str, overlap_minutes: int) -> str:
    """Convert ISO timestamp to Zimbra search after: date with overlap."""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    except ValueError:
        return ""
    dt = dt - timedelta(minutes=overlap_minutes)
    return f"{dt.month}/{dt.day}/{dt.year}"


def build_poll_query(
    settings: Settings,
    last_seen_date: str | None,
) -> str:
    base = settings.sync_inbox_query
    if not last_seen_date:
        return f"{base} is:unread"
    after = _zimbra_after_date(last_seen_date, settings.sync_overlap_minutes)
    if after:
        return f'{base} after:"{after}" sort:desc'
    return f"{base} sort:desc"


class ScheduledPipeline:
    """Syncs a target mailbox to the local DB and runs the automation action pipeline."""

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

    async def run(self, *, skip_analysis: bool = False) -> dict[str, Any]:
        target = self.settings.sync_target_email
        if not target:
            raise ValueError("SYNC_TARGET_EMAIL is not configured")

        conn = await self.repository.connect()
        try:
            sync_stats = await self._poll_and_sync(conn, target)
            result: dict[str, Any] = {"account": target, "sync": sync_stats}

            if skip_analysis:
                result["analysis"] = {"skipped": True}
                return result

            if not self.settings.openai_api_key:
                logger.warning("OPENAI_API_KEY not set; skipping AI analysis")
                result["analysis"] = {"skipped": True, "reason": "OPENAI_API_KEY not configured"}
                return result

            analysis_stats = await self._run_action_pipeline(conn, target)
            result["analysis"] = analysis_stats
            return result
        finally:
            await conn.close()

    async def _poll_and_sync(
        self, conn: asyncpg.Connection, account: str
    ) -> dict[str, Any]:
        state = await self.repository.get_mailbox_state(conn, account)
        last_seen = state.get("last_seen_date") if state else None
        query = build_poll_query(self.settings, last_seen)
        limit = self.settings.agent_inbox_limit

        logger.info("Polling mailbox %s (query=%s)", account, query)

        token = await self.email_service.admin.delegate_auth(account)
        messages, _, _ = await self.email_service.mail.search_messages(
            auth_token=token,
            account_name=account,
            query=query,
            limit=limit,
        )

        inserted = 0
        updated = 0
        newest_date: str | None = last_seen

        for zm in messages:
            summary = self.email_service._to_summary(zm)
            detail = MessageDetail(**summary.model_dump())
            detail.body = zm.body

            if self.settings.sync_fetch_bodies and not detail.body:
                try:
                    full = await self.email_service.get_message(account, zm.id)
                    detail.body = full.body
                except Exception as exc:
                    logger.warning("Failed to fetch body for message %s: %s", zm.id, exc)

            is_new = await self.repository.upsert_message(conn, detail)
            if is_new:
                inserted += 1
            else:
                updated += 1

            if zm.date and (not newest_date or zm.date > newest_date):
                newest_date = zm.date

        await self.repository.upsert_mailbox_state(
            conn,
            account,
            last_seen_date=newest_date,
            last_poll_new_count=inserted,
        )

        total = await self.repository.count_messages(conn, account)
        unanalyzed = await self.repository.count_unanalyzed(conn, account)

        stats = {
            "query": query,
            "fetched": len(messages),
            "inserted": inserted,
            "updated": updated,
            "total_in_db": total,
            "unanalyzed": unanalyzed,
        }
        logger.info("Poll sync complete: %s", stats)
        return stats

    async def _run_action_pipeline(
        self,
        conn: asyncpg.Connection,
        account: str,
    ) -> dict[str, Any]:
        limit = self.settings.agent_inbox_limit
        unanalyzed = await self.repository.get_unanalyzed_messages(conn, account, limit=limit)

        if not unanalyzed:
            logger.info("No unanalyzed messages for %s", account)
            return {"message_count": 0, "skipped": True, "reason": "no unanalyzed messages"}

        logger.info("Running action pipeline on %d messages for %s", len(unanalyzed), account)

        checkpoint_path = self.settings.agent_checkpoint_path
        thread_id = f"scheduled:{account}:{uuid.uuid4().hex[:8]}"

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
                "limit": limit,
                "use_local_db": True,
            }
            result = await graph.ainvoke(initial_state, config=config)

        report = result.get("report") or {}
        run_id = await self.repository.save_analysis_run(
            conn,
            account=account,
            thread_id=thread_id,
            dominant_intent=str(report.get("spam", 0)),
            message_count=report.get("message_count", len(unanalyzed)),
            report=report,
        )

        stats = {
            "thread_id": thread_id,
            "analysis_run_id": run_id,
            "message_count": report.get("message_count", len(unanalyzed)),
            "classified": report.get("classified"),
            "spam": report.get("spam"),
            "forwarded": report.get("forwarded"),
            "acked": report.get("acked"),
            "drafts": report.get("drafts"),
            "errors": report.get("errors"),
            "dry_run": report.get("dry_run"),
            "summary": report,
        }
        logger.info("Action pipeline complete: %s", stats)
        return stats
