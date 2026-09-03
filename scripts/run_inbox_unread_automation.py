#!/usr/bin/env python3
"""Sync and automate unread inbox messages for given accounts."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db.email_repository import require_postgres_database_url
from app.db.pool import close_pool, init_pool
from app.services.scheduled_pipeline import ScheduledPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("inbox_unread_automation")


def _inbox_unread_query(*, hours: int | None) -> tuple[str, str | None]:
    if not hours:
        return "in:inbox is:unread", None
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    after = f"{cutoff.month}/{cutoff.day}/{cutoff.year}"
    return f"in:inbox is:unread after:{after}", cutoff.isoformat()


async def run(accounts: list[str], *, live: bool, hours: int | None) -> dict:
    if live:
        settings.automation_dry_run = False

    query, since = _inbox_unread_query(hours=hours)

    await init_pool(
        require_postgres_database_url(settings.database_url),
        settings=settings,
    )
    pipeline = ScheduledPipeline(settings)
    results: dict[str, object] = {}

    try:
        for account in accounts:
            logger.info(
                "Starting inbox unread automation for %s (query=%s, since=%s)",
                account,
                query,
                since,
            )
            results[account] = await pipeline.run_full_mailbox_automation(
                account,
                query=query,
                process_all=True,
                unanalyzed_since=since,
                unanalyzed_since_only=since is not None,
            )
            logger.info("Finished %s: %s", account, json.dumps(results[account], default=str))
    finally:
        await close_pool()

    return {
        "accounts": accounts,
        "query": query,
        "since": since,
        "hours": hours,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync and automate unread inbox messages for one or more accounts",
    )
    parser.add_argument(
        "accounts",
        nargs="+",
        help="Mailbox email addresses",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=None,
        help="Only sync and automate unread inbox mail from the last N hours",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply Zimbra folder moves and other actions (AUTOMATION_DRY_RUN=false)",
    )
    args = parser.parse_args()

    result = asyncio.run(run(args.accounts, live=args.live, hours=args.hours))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
