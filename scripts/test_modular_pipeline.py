#!/usr/bin/env python3
"""Run modular pipeline on 3 test messages and print results."""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db.pool import close_pool, init_pool
from app.services.message_automation import MessageAutomationService

TEST_MESSAGES = [
    {
        "id": "1342",
        "label": "Rule: MAILER-DAEMON → Undelivered",
        "expect": "rule move, skip LLM",
    },
    {
        "id": "1338",
        "label": "Rule: no-reply@gkhair.com → no action",
        "expect": "no_action, skip LLM, no Zimbra draft",
    },
    {
        "id": "1337",
        "label": "Customer: order shipment (LLM path)",
        "expect": "classify + optional draft",
    },
]

ACCOUNT = os.environ.get("SYNC_TARGET_EMAIL", "info@mail.gkhair.com")


async def main() -> int:
    settings = Settings()

    print(f"dry_run={settings.automation_dry_run}")
    print(f"Account: {ACCOUNT}\n")

    await init_pool(settings.database_url)
    service = MessageAutomationService(settings)
    results: list[dict] = []

    try:
        for spec in TEST_MESSAGES:
            msg_id = spec["id"]
            print("=" * 60)
            print(f"TEST: {spec['label']}")
            print(f"Message id: {msg_id} | Expected: {spec['expect']}")
            print("-" * 60)
            try:
                outcome = await service.run_for_message(ACCOUNT, msg_id, force=True)
                trace = outcome.automation_trace
                classification = outcome.classification or {}
                actions = outcome.actions or {}
                print(f"Status: {outcome.status}")
                print(f"Category: {classification.get('category')}")
                print(
                    f"Source: {classification.get('automation_source')} "
                    f"rule={classification.get('rule_id')}"
                )
                print(f"Spam: {classification.get('is_spam')}")
                print(
                    f"Order Q: {classification.get('is_order_status_question')} | "
                    f"Invoice Q: {classification.get('is_invoice_question')}"
                )
                print(
                    f"Needs response: {classification.get('needs_response_generation')} | "
                    f"Forward: {classification.get('needs_forwarding')}"
                )
                print(
                    f"Folder: {actions.get('folder_path')} | "
                    f"Moved: {actions.get('folder_moved')}"
                )
                print(f"Forwarded: {actions.get('forwarded_to')}")
                print(f"Draft saved: {actions.get('draft_saved')}")
                if outcome.draft_reply_text:
                    preview = outcome.draft_reply_text[:200].replace("\n", " ")
                    print(f"Draft preview: {preview}...")
                if trace and trace.get("steps"):
                    print("Trace steps:")
                    for step in trace["steps"]:
                        print(
                            f"  - {step.get('step')}/{step.get('action')} "
                            f"ok={step.get('success')}"
                        )
                if outcome.error:
                    print(f"Error: {outcome.error}")
                results.append(
                    {
                        "id": msg_id,
                        "status": outcome.status,
                        "ok": outcome.status == "completed",
                    }
                )
            except Exception as exc:
                print(f"FAILED: {exc}")
                results.append({"id": msg_id, "status": "exception", "ok": False})
            print()
    finally:
        await close_pool()

    print("=" * 60)
    print("SUMMARY")
    passed = sum(1 for r in results if r["ok"])
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  [{mark}] {r['id']}: {r['status']}")
    print(f"\n{passed}/{len(results)} completed successfully")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
