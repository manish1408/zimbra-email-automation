from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from app.services.action_pipeline import run_action_pipeline
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.models.schemas import MessageDetail, User
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


def _poll_folder_bases(settings: Settings) -> list[str]:
    bases = [settings.sync_inbox_query]
    junk = (settings.sync_junk_query or "").strip()
    if settings.sync_include_junk and junk:
        inbox = (settings.sync_inbox_query or "").strip().lower()
        if junk.lower() not in inbox and "in:junk" not in inbox and "in:spam" not in inbox:
            bases.append(junk)
    return [base for base in bases if base.strip()]


def build_poll_queries(
    settings: Settings,
    last_seen_date: str | None = None,
) -> list[str]:
    """Build poll queries for inbox (and optionally Junk).

    Avoid sort: — many Zimbra builds return HTTP 500 for sort:desc.
    Date-only after:M/D/Y misses same-day mail on many Zimbra builds, so we
    poll unread mail per folder instead. Each folder is queried separately so
    AGENT_INBOX_LIMIT applies per folder (Junk is not starved by Inbox unread).
    """
    del last_seen_date  # retained for call-site compatibility; unused on purpose
    return [f"{base} is:unread" for base in _poll_folder_bases(settings)]


def build_poll_query_specs(settings: Settings) -> list[tuple[str, int]]:
    """Return (query, limit) pairs with recent-window unread queries first."""
    bases = _poll_folder_bases(settings)
    fetch_limit = max(1, settings.sync_poll_fetch_limit)
    specs: list[tuple[str, int]] = []
    recent_after = _zimbra_after_date(
        (datetime.now(UTC) - timedelta(hours=settings.sync_recent_hours)).isoformat(),
        settings.sync_overlap_minutes,
    )
    if recent_after:
        for base in bases:
            specs.append((f"{base} is:unread after:{recent_after}", fetch_limit))
    for base in bases:
        query = f"{base} is:unread"
        if not any(existing == query for existing, _ in specs):
            specs.append((query, fetch_limit))
    return specs


def build_poll_query(
    settings: Settings,
    last_seen_date: str | None,
) -> str:
    """Build a single poll query (first folder). Prefer build_poll_queries()."""
    queries = build_poll_queries(settings, last_seen_date)
    return queries[0] if queries else "in:inbox is:unread"


def _is_active_mailbox(user: User) -> bool:
    status = (user.status or "").strip().lower()
    return not status or status == "active"


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

    async def list_poll_accounts(self) -> list[str]:
        """Return active mailbox emails to poll.

        When SYNC_MAILBOXES is set, only those accounts are returned (allowlist
        order). Otherwise all active mailboxes are returned, sorted.
        """
        users = (await self.email_service.list_users()).users
        active = [user.email for user in users if _is_active_mailbox(user)]
        allowlist = self.settings.sync_mailbox_allowlist
        if not allowlist:
            return sorted(active)

        active_by_email = {email.lower(): email for email in active}
        selected: list[str] = []
        missing: list[str] = []
        for wanted in allowlist:
            match = active_by_email.get(wanted)
            if match:
                selected.append(match)
            else:
                missing.append(wanted)
        if missing:
            logger.warning(
                "SYNC_MAILBOXES not found or inactive: %s", ", ".join(missing)
            )
        return selected

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
            return await self._run_for_account(
                conn,
                target,
                skip_analysis=skip_analysis,
                process_all=process_all,
            )
        finally:
            await conn.close()

    async def run_all(
        self,
        *,
        skip_analysis: bool = False,
        process_all: bool = False,
    ) -> dict[str, Any]:
        accounts = await self.list_poll_accounts()
        result: dict[str, Any] = {
            "mode": "all",
            "accounts_total": len(accounts),
            "accounts_succeeded": 0,
            "accounts_failed": 0,
            "results": {},
            "errors": {},
        }

        if not accounts:
            logger.warning("No active mailboxes found to poll")
            return result

        conn = await self.repository.connect()
        try:
            for account in accounts:
                try:
                    account_result = await self._run_for_account(
                        conn,
                        account,
                        skip_analysis=skip_analysis,
                        process_all=process_all,
                    )
                    result["results"][account] = account_result
                    result["accounts_succeeded"] += 1
                except Exception as exc:
                    logger.exception("Poll cycle failed for %s", account)
                    result["errors"][account] = str(exc)
                    result["accounts_failed"] += 1
        finally:
            await conn.close()

        return result

    async def _run_for_account(
        self,
        conn: asyncpg.Connection,
        account: str,
        *,
        skip_analysis: bool = False,
        process_all: bool = False,
    ) -> dict[str, Any]:
        sync_stats = await self._poll_and_sync(conn, account)
        result: dict[str, Any] = {"account": account, "sync": sync_stats}

        if skip_analysis:
            result["analysis"] = {"skipped": True}
            return result

        if not llm_configured(self.settings):
            logger.warning("LLM not configured; skipping AI analysis for %s", account)
            result["analysis"] = {
                "skipped": True,
                "reason": llm_not_configured_message(self.settings),
            }
            return result

        if process_all:
            batches: list[dict[str, Any]] = []
            while True:
                stats = await self.run_action_pipeline(conn, account)
                batches.append(stats)
                if stats.get("skipped") or int(stats.get("message_count") or 0) == 0:
                    break
            remaining = await self.repository.count_unanalyzed(conn, account)
            result["analysis"] = {
                "batches": len(batches),
                "batch_results": batches,
                "remaining_unanalyzed": remaining,
                "dry_run": self.settings.automation_dry_run,
            }
        else:
            analysis_stats = await self.run_action_pipeline(conn, account)
            result["analysis"] = analysis_stats
        return result

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
        query_specs = build_poll_query_specs(self.settings)
        queries = [query for query, _ in query_specs]

        token = await self.email_service.admin.delegate_auth(account)

        inserted = 0
        updated = 0
        fetched = 0
        newest_date: str | None = last_seen
        seen_ids: set[str] = set()

        for query, fetch_limit in query_specs:
            logger.info(
                "Polling mailbox %s (query=%s, limit=%d)",
                account,
                query,
                fetch_limit,
            )
            messages, _, _ = await self.email_service.mail.search_messages(
                auth_token=token,
                account_name=account,
                query=query,
                limit=fetch_limit,
            )

            for zm in messages:
                if zm.id in seen_ids:
                    continue
                seen_ids.add(zm.id)
                fetched += 1

                summary = self.email_service._to_summary(zm)
                detail = MessageDetail(**summary.model_dump())
                detail.body = zm.body

                if self.settings.sync_fetch_bodies and not detail.body:
                    try:
                        full = await self.email_service.get_message(account, zm.id)
                        detail.body = full.body
                    except Exception as exc:
                        logger.warning(
                            "Failed to fetch body for message %s: %s", zm.id, exc
                        )

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
            "queries": queries,
            "query": " | ".join(queries),
            "fetched": fetched,
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
        recent_since = (
            datetime.now(UTC) - timedelta(hours=self.settings.sync_recent_hours)
        ).isoformat()
        unanalyzed = await self.repository.get_unanalyzed_messages(
            conn,
            account,
            limit=limit,
            since=recent_since,
        )
        if not unanalyzed:
            unanalyzed = await self.repository.get_unanalyzed_messages(
                conn, account, limit=limit
            )

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
            "unanalyzed_since": recent_since,
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
            "drafts": report.get("drafts"),
            "errors": report.get("errors"),
            "dry_run": report.get("dry_run"),
            "move_to_folders": report.get("move_to_folders"),
            "summary": report,
        }
        logger.info("Action pipeline complete: %s", stats)
        return stats
