#!/usr/bin/env python3
"""Sync recent mail and force-reprocess automation (e.g. after spam rule changes)."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db.email_repository import require_postgres_database_url
from app.db.pool import close_pool, init_pool
from app.services.action_pipeline import run_action_pipeline
from app.services.llm import llm_configured, llm_not_configured_message
from app.services.scheduled_pipeline import ScheduledPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("recent_reprocess")


def _recent_query(hours: int) -> tuple[str, str]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    after = f"{cutoff.month}/{cutoff.day}/{cutoff.year}"
    return f"is:anywhere after:{after}", cutoff.isoformat()


async def _target_message_ids(
    pool,
    account: str,
    since: str,
    *,
    only_unlabeled_or_general: bool,
) -> list[str]:
    if only_unlabeled_or_general:
        sql = """
            SELECT m.zimbra_id
            FROM messages m
            LEFT JOIN message_actions ma
              ON ma.account = m.account
             AND ma.zimbra_id = m.zimbra_id
             AND ma.error IS NULL
            WHERE m.account = $1
              AND m.date >= $2
              AND (ma.zimbra_id IS NULL OR ma.category = 'general')
            ORDER BY m.date DESC
        """
    else:
        sql = """
            SELECT zimbra_id FROM messages
            WHERE account = $1 AND date >= $2
            ORDER BY date DESC
        """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, account, since)
    return [str(row["zimbra_id"]) for row in rows]


async def run(
    accounts: list[str],
    *,
    live: bool,
    hours: int,
    only_unlabeled_or_general: bool = False,
) -> dict:
    if live:
        settings.automation_dry_run = False

    if not llm_configured(settings):
        raise SystemExit(llm_not_configured_message(settings))

    query, since = _recent_query(hours)
    pool = await init_pool(
        require_postgres_database_url(settings.database_url),
        settings=settings,
    )
    pipeline = ScheduledPipeline(settings)
    batch_size = settings.agent_inbox_limit
    results: dict[str, object] = {}

    try:
        for account in accounts:
            logger.info(
                "Force reprocess for %s (query=%s, since=%s)",
                account,
                query,
                since,
            )
            sync_result = await pipeline.email_service.sync_user_mailbox(
                account,
                query=query,
                persist=True,
            )
            message_ids = await _target_message_ids(
                pool,
                account,
                since,
                only_unlabeled_or_general=only_unlabeled_or_general,
            )
            filter_note = (
                " (unlabeled or general only)"
                if only_unlabeled_or_general
                else ""
            )
            logger.info(
                "Synced %d messages; reprocessing %d from last %dh for %s%s",
                sync_result.message_count,
                len(message_ids),
                hours,
                account,
                filter_note,
            )

            batches: list[dict[str, object]] = []
            async with pool.acquire() as conn:
                for offset in range(0, len(message_ids), batch_size):
                    batch = message_ids[offset : offset + batch_size]
                    thread_id = f"reprocess:{account}:{uuid.uuid4().hex[:8]}"
                    logger.info(
                        "Batch %d/%d (%d messages) for %s",
                        offset // batch_size + 1,
                        (len(message_ids) + batch_size - 1) // batch_size,
                        len(batch),
                        account,
                    )
                    result = await run_action_pipeline(
                        {
                            "user_email": account,
                            "limit": len(batch),
                            "message_ids": batch,
                            "force_reprocess": True,
                            "automation_thread_id": thread_id,
                        },
                        email_service=pipeline.email_service,
                        settings=settings,
                        email_repository=pipeline.repository,
                        conn=conn,
                    )
                    report = result.get("report") or {}
                    batches.append(
                        {
                            "message_count": report.get("message_count", len(batch)),
                            "classified": report.get("classified"),
                            "spam": report.get("spam"),
                            "moved": report.get("moved"),
                            "errors": report.get("errors"),
                        }
                    )

            results[account] = {
                "sync": {"query": query, "fetched": sync_result.message_count},
                "since": since,
                "hours": hours,
                "only_unlabeled_or_general": only_unlabeled_or_general,
                "reprocessed": len(message_ids),
                "batches": len(batches),
                "batch_results": batches,
                "dry_run": settings.automation_dry_run,
            }
            logger.info("Finished %s: %s", account, json.dumps(results[account], default=str))
    finally:
        await close_pool()

    return {
        "accounts": accounts,
        "query": query,
        "since": since,
        "hours": hours,
        "only_unlabeled_or_general": only_unlabeled_or_general,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync and force-reprocess recent mail after rule changes",
    )
    parser.add_argument("accounts", nargs="+", help="Mailbox email addresses")
    parser.add_argument(
        "--hours",
        type=int,
        default=72,
        help="Reprocess mail from the last N hours (default: 72 = 3 days)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply Zimbra folder moves and other actions (AUTOMATION_DRY_RUN=false)",
    )
    parser.add_argument(
        "--only-unlabeled-or-general",
        action="store_true",
        help="Reprocess only messages with no automation label or category=general",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run(
            args.accounts,
            live=args.live,
            hours=args.hours,
            only_unlabeled_or_general=args.only_unlabeled_or_general,
        )
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
