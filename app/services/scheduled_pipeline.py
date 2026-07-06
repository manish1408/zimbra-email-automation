from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from app.services.action_pipeline import run_action_pipeline
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import MessageDetail
from app.services.email_sync import EmailSyncService
from app.services.llm import llm_configured, llm_not_configured_message

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
    """Build inbox poll query. Avoid sort: — many Zimbra builds return HTTP 500 for sort:desc."""
    base = settings.sync_inbox_query
    if not last_seen_date:
        return f"{base} is:unread"
    after = _zimbra_after_date(last_seen_date, settings.sync_overlap_minutes)
    if after:
        return f"{base} after:{after}"
    return base


class ScheduledPipeline:
    """Syncs a target mailbox to the local DB and runs the automation action pipeline."""

    def __init__(
        self,
        settings: Settings,
        email_service: EmailSyncService | None = None,
        repository: EmailRepository | None = None,
    ):
        self.settings = settings
        self.email_service = email_service or EmailSyncService(settings)
        self.repository = repository or EmailRepository(settings.database_url)

    async def run(
        self,
        *,
        skip_analysis: bool = False,
        process_all: bool = False,
    ) -> dict[str, Any]:
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

            if not llm_configured(self.settings):
                logger.warning("LLM not configured; skipping AI analysis")
                result["analysis"] = {
                    "skipped": True,
                    "reason": llm_not_configured_message(self.settings),
                }
                return result

            if process_all:
                batches: list[dict[str, Any]] = []
                while True:
                    stats = await self.run_action_pipeline(conn, target)
                    batches.append(stats)
                    if stats.get("skipped") or int(stats.get("message_count") or 0) == 0:
                        break
                remaining = await self.repository.count_unanalyzed(conn, target)
                result["analysis"] = {
                    "batches": len(batches),
                    "batch_results": batches,
                    "remaining_unanalyzed": remaining,
                    "dry_run": self.settings.automation_dry_run,
                }
            else:
                analysis_stats = await self.run_action_pipeline(conn, target)
                result["analysis"] = analysis_stats
            return result
        finally:
            await conn.close()

    async def run_action_pipeline(
        self,
        conn: asyncpg.Connection | Any,
        account: str,
    ) -> dict[str, Any]:
        """Classify unanalyzed messages and move them to category folders on Zimbra."""
        return await self._run_action_pipeline(conn, account)

    async def run_full_mailbox_automation(
        self,
        account: str,
        *,
        query: str = "is:anywhere",
        process_all: bool = True,
    ) -> dict[str, Any]:
        """Sync entire mailbox to DB, then run automation on all unanalyzed messages."""
        conn = await self.repository.connect()
        try:
            logger.info("Full sync for %s (query=%s)", account, query)
            sync_result = await self.email_service.sync_user_mailbox(
                account,
                query=query,
                persist=True,
            )
            total = await self.repository.count_messages(conn, account)
            unanalyzed = await self.repository.count_unanalyzed(conn, account)
            result: dict[str, Any] = {
                "account": account,
                "sync": {
                    "query": query,
                    "fetched": sync_result.message_count,
                    "total_in_db": total,
                    "unanalyzed": unanalyzed,
                },
                "dry_run": self.settings.automation_dry_run,
            }

            if not llm_configured(self.settings):
                result["analysis"] = {
                    "skipped": True,
                    "reason": llm_not_configured_message(self.settings),
                }
                return result

            batches: list[dict[str, Any]] = []
            while True:
                stats = await self._run_action_pipeline(conn, account)
                batches.append(stats)
                if not process_all:
                    result["analysis"] = stats
                    break
                if stats.get("skipped") or int(stats.get("message_count") or 0) == 0:
                    break

            if process_all:
                remaining = await self.repository.count_unanalyzed(conn, account)
                processed = await self.repository.count_messages(conn, account) - remaining
                result["analysis"] = {
                    "batches": len(batches),
                    "batch_results": batches,
                    "processed": processed,
                    "remaining_unanalyzed": remaining,
                    "dry_run": self.settings.automation_dry_run,
                }
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

        thread_id = f"scheduled:{account}:{uuid.uuid4().hex[:8]}"
        initial_state = {
            "user_email": account,
            "limit": limit,
            "use_local_db": True,
            "automation_thread_id": thread_id,
        }
        result = await run_action_pipeline(
            initial_state,
            email_service=self.email_service,
            settings=self.settings,
            email_repository=self.repository,
            conn=conn,
        )

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
            "moved": report.get("moved"),
            "forwarded": report.get("forwarded"),
            "acked": report.get("acked"),
            "drafts": report.get("drafts"),
            "errors": report.get("errors"),
            "dry_run": report.get("dry_run"),
            "move_to_folders": report.get("move_to_folders"),
            "summary": report,
        }
        logger.info("Action pipeline complete: %s", stats)
        return stats
