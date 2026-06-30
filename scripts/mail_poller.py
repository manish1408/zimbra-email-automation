#!/usr/bin/env python3
"""Long-running mailbox poller for near-real-time email automation.

Polls SYNC_TARGET_EMAIL every SYNC_POLL_INTERVAL_SECONDS (default 60),
syncs new inbox messages, and runs the action pipeline (classify, route, ack).

Run as a systemd/supervisor service:

    .venv/bin/python scripts/mail_poller.py

Environment: see .env.example (SYNC_TARGET_EMAIL, SYNC_POLL_INTERVAL_SECONDS, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.scheduled_pipeline import ScheduledPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mail_poller")


async def run_once(pipeline: ScheduledPipeline, *, sync_only: bool = False) -> dict:
    return await pipeline.run(skip_analysis=sync_only)


async def poll_loop(
    pipeline: ScheduledPipeline,
    interval: int,
    *,
    sync_only: bool = False,
) -> None:
    logger.info(
        "Starting mail poller for %s (interval=%ds, dry_run=%s)",
        settings.sync_target_email,
        interval,
        settings.automation_dry_run,
    )
    while True:
        try:
            result = await run_once(pipeline, sync_only=sync_only)
            logger.info("Poll cycle complete: %s", json.dumps(result, default=str))
        except Exception:
            logger.exception("Poll cycle failed")
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll mailbox and run email automation")
    parser.add_argument("--account", help="Override SYNC_TARGET_EMAIL")
    parser.add_argument("--sync-only", action="store_true", help="Sync without AI/actions")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle and exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Poll interval in seconds (default: SYNC_POLL_INTERVAL_SECONDS)",
    )
    args = parser.parse_args()

    if not settings.sync_target_email and not args.account:
        raise SystemExit("Set SYNC_TARGET_EMAIL in .env or pass --account")

    if args.account:
        settings.sync_target_email = args.account

    interval = args.interval or settings.sync_poll_interval_seconds
    pipeline = ScheduledPipeline(settings)

    if args.once:
        result = asyncio.run(run_once(pipeline, sync_only=args.sync_only))
        print(json.dumps(result, indent=2, default=str))
        return

    asyncio.run(poll_loop(pipeline, interval, sync_only=args.sync_only))


if __name__ == "__main__":
    main()
