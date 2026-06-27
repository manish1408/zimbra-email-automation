#!/usr/bin/env python3
"""Export Zimbra mailboxes to a JSON file without running the API server."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import settings
from app.services.email_sync import EmailSyncService


async def run(args: argparse.Namespace) -> None:
    service = EmailSyncService(settings)
    if args.account:
        result = await service.sync_user_mailbox(user_email=args.account, query=args.query)
        payload = {
            "accounts_processed": 1,
            "total_messages": result.message_count,
            "accounts": [result.model_dump(by_alias=True)],
        }
    else:
        sync = await service.sync_all_mailboxes(
            query=args.query,
            max_accounts=args.max_accounts,
        )
        payload = sync.model_dump(by_alias=True)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Exported {payload['total_messages']} messages to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Zimbra emails to JSON")
    parser.add_argument("--account", help="Single mailbox to export")
    parser.add_argument("--query", help="Zimbra search query override")
    parser.add_argument("--max-accounts", type=int, help="Limit accounts when syncing all")
    parser.add_argument(
        "--output",
        default="data/export.json",
        help="Output JSON path (default: data/export.json)",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
