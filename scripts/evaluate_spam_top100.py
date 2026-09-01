#!/usr/bin/env python3
"""Dry-run: judge top N recent emails as sales/marketing spam vs prior labels.

Uses a focused spam-only LLM prompt (not the full classifier) so results stay
reliable. Does NOT move mail on Zimbra.

Usage:
  PYTHONPATH=/opt/zimbra-email-automation \\
    .venv/bin/python scripts/evaluate_spam_top100.py \\
    --account gk07@gkhair.com --limit 100 --concurrency 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

load_dotenv()

from app.config import Settings
from app.db.pool import close_pool, get_pool, init_pool
from app.services.llm import ainvoke_structured, create_chat_llm
from app.services.spam_policy import (
    SALES_MARKETING_SPAM_POLICY,
    apply_spam_confidence_policy,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("evaluate_spam")

BODY_CHARS = 3500


class SpamJudgment(BaseModel):
    is_spam: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    category: str = "general"
    reasoning: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


async def fetch_top_messages(conn, account: str, limit: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT
            m.zimbra_id,
            m.account,
            m.subject,
            m.from_address,
            m.date,
            m.folder,
            m.fragment,
            left(coalesce(m.body, ''), $3) AS body,
            m.analyzed_at,
            a.is_spam AS action_is_spam,
            a.category AS action_category,
            a.folder_path AS action_folder,
            r.is_spam AS run_is_spam,
            r.category AS run_category,
            r.confidence AS run_confidence
        FROM messages m
        LEFT JOIN LATERAL (
            SELECT is_spam, category, folder_path
            FROM message_actions
            WHERE account = m.account AND zimbra_id = m.zimbra_id
            ORDER BY processed_at DESC NULLS LAST
            LIMIT 1
        ) a ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                (classification_json->>'is_spam')::boolean AS is_spam,
                classification_json->>'category' AS category,
                (classification_json->>'confidence')::float AS confidence
            FROM message_automation_runs
            WHERE account = m.account AND zimbra_id = m.zimbra_id
            ORDER BY created_at DESC
            LIMIT 1
        ) r ON TRUE
        WHERE m.account = $1
        ORDER BY m.date DESC NULLS LAST
        LIMIT $2
        """,
        account,
        limit,
        BODY_CHARS,
    )
    return [dict(row) for row in rows]


def prior_marked_spam(row: dict[str, Any]) -> bool:
    if row.get("action_is_spam") is True:
        return True
    if row.get("run_is_spam") is True:
        return True
    folder = str(row.get("folder") or "").strip().lower()
    action_folder = str(row.get("action_folder") or "").strip().lower()
    if folder in {"4", "junk", "spam"} or action_folder in {"junk", "spam"}:
        return True
    category = str(row.get("action_category") or row.get("run_category") or "").lower()
    return category == "spam"


async def judge_one(
    llm,
    row: dict[str, Any],
    threshold: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        msg_id = str(row["zimbra_id"])
        subject = row.get("subject") or "(no subject)"
        sender = row.get("from_address") or "(unknown)"
        body = _strip_html(str(row.get("body") or row.get("fragment") or ""))[:BODY_CHARS]
        prompt = (
            f"{SALES_MARKETING_SPAM_POLICY}\n\n"
            "Decide if this email should be marked spam under that policy.\n"
            "Return JSON with: is_spam, confidence (0-1), category "
            "('spam' if spam else 'general' or another non-spam label), reasoning.\n\n"
            f"Message id: {msg_id}\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Body:\n{body or '(empty)'}\n"
        )
        try:
            judgment = await ainvoke_structured(
                llm,
                SpamJudgment,
                [
                    SystemMessage(
                        content=(
                            "You detect sales, promotion, and marketing spam. "
                            "Return ONLY JSON."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
            )
            classification = apply_spam_confidence_policy(
                {
                    "message_id": msg_id,
                    "category": judgment.category or ("spam" if judgment.is_spam else "general"),
                    "is_spam": judgment.is_spam,
                    "confidence": judgment.confidence,
                    "reasoning": judgment.reasoning,
                },
                threshold=threshold,
                spam_slug="spam",
            )
            return _row_result(row, classification=classification)
        except Exception as exc:
            logger.warning("Failed %s: %s", msg_id, exc)
            return _row_result(row, error=str(exc))


def _row_result(
    row: dict[str, Any],
    *,
    classification: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    prior = prior_marked_spam(row)
    new_spam = bool((classification or {}).get("is_spam")) if classification else False
    return {
        "zimbra_id": row["zimbra_id"],
        "subject": row.get("subject"),
        "from_address": row.get("from_address"),
        "date": row.get("date"),
        "folder": row.get("folder"),
        "prior_marked_spam": prior,
        "prior_action_is_spam": row.get("action_is_spam"),
        "prior_run_is_spam": row.get("run_is_spam"),
        "prior_category": row.get("action_category") or row.get("run_category"),
        "new_is_spam": new_spam,
        "new_category": (classification or {}).get("category"),
        "new_confidence": (classification or {}).get("confidence"),
        "new_reasoning": (classification or {}).get("reasoning"),
        "newly_caught_spam": (not prior) and new_spam,
        "error": error,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="gk07@gkhair.com")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output", default="data/spam_eval_top100.json")
    args = parser.parse_args()

    settings = Settings()
    threshold = float(settings.spam_confidence_threshold)
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parent.parent / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    await init_pool(settings.database_url)
    pool = get_pool()

    try:
        async with pool.acquire() as conn:
            rows = await fetch_top_messages(conn, args.account, args.limit)

        logger.info(
            "Loaded %d messages for %s (threshold=%.2f, concurrency=%d)",
            len(rows),
            args.account,
            threshold,
            args.concurrency,
        )
        if not rows:
            logger.error("No messages found")
            return 1

        llm = create_chat_llm(settings, temperature=0.1)
        sem = asyncio.Semaphore(max(1, args.concurrency))
        tasks = [judge_one(llm, row, threshold, sem) for row in rows]
        results: list[dict[str, Any]] = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            item = await coro
            results.append(item)
            done += 1
            if done % 5 == 0 or done == len(tasks):
                logger.info("Progress %d/%d", done, len(tasks))

        by_id = {r["zimbra_id"]: r for r in results}
        ordered = [by_id[row["zimbra_id"]] for row in rows if row["zimbra_id"] in by_id]

        classified = [r for r in ordered if not r.get("error")]
        errors = [r for r in ordered if r.get("error")]
        prior_spam = [r for r in classified if r["prior_marked_spam"]]
        prior_not = [r for r in classified if not r["prior_marked_spam"]]
        new_spam = [r for r in classified if r["new_is_spam"]]
        newly_caught = [r for r in classified if r["newly_caught_spam"]]
        still_not = [r for r in prior_not if not r["new_is_spam"]]
        already_spam_confirmed = [r for r in prior_spam if r["new_is_spam"]]

        summary = {
            "account": args.account,
            "limit": args.limit,
            "evaluated": len(classified),
            "errors": len(errors),
            "spam_confidence_threshold": threshold,
            "prior_marked_spam": len(prior_spam),
            "prior_not_spam": len(prior_not),
            "new_spam": len(new_spam),
            "newly_caught_spam": len(newly_caught),
            "still_not_spam": len(still_not),
            "already_spam_confirmed": len(already_spam_confirmed),
            "generated_at": _utc_now(),
        }

        payload = {
            "summary": summary,
            "newly_caught": newly_caught,
            "results": ordered,
        }
        out_path.write_text(json.dumps(payload, indent=2, default=str))
        print(json.dumps(summary, indent=2))
        print(f"\nWrote full report to {out_path}")
        print(f"Newly caught spam (was not spam → now spam): {len(newly_caught)}")
        for item in newly_caught[:40]:
            print(
                f"  - {item['zimbra_id']}: [{item.get('new_confidence')}] "
                f"{(item.get('subject') or '')[:70]} | {item.get('from_address')}"
            )
        return 0 if not errors or classified else 1
    finally:
        await close_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
