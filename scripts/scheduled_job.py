#!/usr/bin/env python3
"""Scheduled sync + AI analysis job for cron.

Syncs the mailbox configured in SYNC_TARGET_EMAIL to a local SQLite database,
then runs the LangGraph agent on unanalyzed messages.

Cron example (every 6 hours — adjust SYNC_INTERVAL_HOURS in .env to match):

    0 */6 * * * cd /path/to/zimbra-email-automation && .venv/bin/python scripts/scheduled_job.py >> logs/scheduled_job.log 2>&1

Other intervals:
    Every 4 hours:  0 */4 * * *
    Every 12 hours: 0 */12 * * *
    Every 6 hours:  0 */6 * * *   (default SYNC_INTERVAL_HOURS=6)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Allow running as `python scripts/scheduled_job.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.scheduled_pipeline import ScheduledPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scheduled_job")


async def run(args: argparse.Namespace) -> dict:
    if not settings.sync_target_email and not args.account:
        raise SystemExit(
            "Set SYNC_TARGET_EMAIL in .env or pass --account user@example.com"
        )

    if args.account:
        settings.sync_target_email = args.account

    if args.dry_run:
        settings.automation_dry_run = True
    elif args.live:
        settings.automation_dry_run = False

    pipeline = ScheduledPipeline(settings)
    if args.full_mailbox:
        account = args.account or settings.sync_target_email
        if not account:
            raise SystemExit("Set SYNC_TARGET_EMAIL or pass --account")
        return await pipeline.run_full_mailbox_automation(
            account,
            query=args.query,
            process_all=True,
        )
    return await pipeline.run(skip_analysis=args.sync_only)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync target mailbox to local DB and run AI analysis"
    )
    parser.add_argument(
        "--account",
        help="Override SYNC_TARGET_EMAIL for this run",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Sync to local DB without running AI analysis",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force AUTOMATION_DRY_RUN=true for this run",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply Zimbra folder moves and other actions (AUTOMATION_DRY_RUN=false)",
    )
    parser.add_argument(
        "--full-mailbox",
        action="store_true",
        help="Sync all messages (is:anywhere) then process every unanalyzed message",
    )
    parser.add_argument(
        "--query",
        default="is:anywhere",
        help="Zimbra search query for --full-mailbox (default: is:anywhere)",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        help="Print suggested cron expression for this interval (does not run the job)",
    )
    args = parser.parse_args()

    if args.interval_hours is not None:
        hours = int(args.interval_hours) if args.interval_hours == int(args.interval_hours) else args.interval_hours
        print(f"# Run every {hours} hour(s)")
        if isinstance(hours, int) and 24 % hours == 0:
            print(f"0 */{hours} * * * cd $(pwd) && .venv/bin/python scripts/scheduled_job.py")
        else:
            print(f"# For non-divisor intervals, use a wrapper or systemd timer")
            print(f"# SYNC_INTERVAL_HOURS={hours}")
        return

    result = asyncio.run(run(args))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
