from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from app.models.schemas import MessageDetail, MessageSummary

_SCHEMA = Path(__file__).resolve().parent / "migrations" / "001_initial.sql"
_MIGRATION_V2 = Path(__file__).resolve().parent / "migrations" / "002_automation_fields.sql"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PostgresEmailRepository:
    """Async PostgreSQL store for synced mailbox messages and analysis runs."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def connect(self) -> asyncpg.Connection:
        conn = await asyncpg.connect(self.database_url)
        if _SCHEMA.exists():
            await conn.execute(_SCHEMA.read_text())
        if _MIGRATION_V2.exists():
            await conn.execute(_MIGRATION_V2.read_text())
        return conn

    async def upsert_message(self, conn: asyncpg.Connection, message: MessageDetail) -> bool:
        existing = await conn.fetchval(
            "SELECT id FROM messages WHERE zimbra_id = $1 AND account = $2",
            message.id,
            message.account,
        )
        now = _utc_now()
        to_json = json.dumps(message.to_addresses)

        if existing:
            await conn.execute(
                """
                UPDATE messages SET
                    subject = $1, from_address = $2, to_addresses = $3::jsonb,
                    date = $4, fragment = $5, folder = $6, size = $7, is_read = $8,
                    body = COALESCE($9, body), synced_at = $10
                WHERE zimbra_id = $11 AND account = $12
                """,
                message.subject,
                message.from_address,
                to_json,
                message.date,
                message.fragment,
                message.folder,
                message.size,
                message.is_read,
                message.body,
                now,
                message.id,
                message.account,
            )
            return False

        await conn.execute(
            """
            INSERT INTO messages (
                zimbra_id, account, subject, from_address, to_addresses,
                date, fragment, folder, size, is_read, body, synced_at
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12)
            """,
            message.id,
            message.account,
            message.subject,
            message.from_address,
            to_json,
            message.date,
            message.fragment,
            message.folder,
            message.size,
            message.is_read,
            message.body,
            now,
        )
        return True

    async def get_message(
        self, conn: asyncpg.Connection, account: str, zimbra_id: str
    ) -> MessageDetail | None:
        row = await conn.fetchrow(
            "SELECT * FROM messages WHERE account = $1 AND zimbra_id = $2",
            account,
            zimbra_id,
        )
        return self._row_to_detail(row) if row else None

    async def get_unanalyzed_messages(
        self, conn: asyncpg.Connection, account: str, limit: int = 50
    ) -> list[MessageDetail]:
        rows = await conn.fetch(
            """
            SELECT * FROM messages
            WHERE account = $1 AND analyzed_at IS NULL
            ORDER BY date DESC NULLS LAST
            LIMIT $2
            """,
            account,
            limit,
        )
        return [self._row_to_detail(row) for row in rows]

    async def get_messages(
        self,
        conn: asyncpg.Connection,
        account: str,
        limit: int = 50,
        offset: int = 0,
        *,
        analyzed: bool | None = None,
    ) -> tuple[list[MessageDetail], int]:
        where = "account = $1"
        params: list[Any] = [account]
        if analyzed is True:
            where += " AND analyzed_at IS NOT NULL"
        elif analyzed is False:
            where += " AND analyzed_at IS NULL"

        total = await conn.fetchval(f"SELECT COUNT(*) FROM messages WHERE {where}", *params)
        limit_param = len(params) + 1
        offset_param = len(params) + 2
        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT * FROM messages
            WHERE {where}
            ORDER BY date DESC NULLS LAST
            LIMIT ${limit_param} OFFSET ${offset_param}
            """,
            *params,
        )
        return [self._row_to_detail(row) for row in rows], int(total or 0)

    async def mark_analyzed(
        self, conn: asyncpg.Connection, account: str, zimbra_ids: list[str]
    ) -> None:
        if not zimbra_ids:
            return
        await conn.execute(
            """
            UPDATE messages SET analyzed_at = $1
            WHERE account = $2 AND zimbra_id = ANY($3::text[])
            """,
            _utc_now(),
            account,
            zimbra_ids,
        )

    async def update_message_folder(
        self,
        conn: asyncpg.Connection,
        account: str,
        zimbra_id: str,
        folder: str,
    ) -> None:
        await conn.execute(
            """
            UPDATE messages SET folder = $1
            WHERE account = $2 AND zimbra_id = $3
            """,
            folder,
            account,
            zimbra_id,
        )

    async def get_mailbox_state(
        self, conn: asyncpg.Connection, account: str
    ) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            "SELECT * FROM mailbox_state WHERE account = $1", account
        )
        return dict(row) if row else None

    async def upsert_mailbox_state(
        self,
        conn: asyncpg.Connection,
        account: str,
        *,
        last_seen_date: str | None = None,
        last_poll_new_count: int = 0,
    ) -> None:
        now = _utc_now()
        existing = await self.get_mailbox_state(conn, account)
        if existing:
            await conn.execute(
                """
                UPDATE mailbox_state SET
                    last_seen_date = COALESCE($1, last_seen_date),
                    last_poll_at = $2,
                    last_poll_new_count = $3
                WHERE account = $4
                """,
                last_seen_date,
                now,
                last_poll_new_count,
                account,
            )
        else:
            await conn.execute(
                """
                INSERT INTO mailbox_state
                    (account, last_seen_date, last_poll_at, last_poll_new_count)
                VALUES ($1, $2, $3, $4)
                """,
                account,
                last_seen_date,
                now,
                last_poll_new_count,
            )

    async def is_message_processed(
        self, conn: asyncpg.Connection, account: str, zimbra_id: str
    ) -> bool:
        row = await conn.fetchval(
            """
            SELECT 1 FROM message_actions
            WHERE account = $1 AND zimbra_id = $2 AND error IS NULL
            """,
            account,
            zimbra_id,
        )
        return row is not None

    async def save_message_action(
        self,
        conn: asyncpg.Connection,
        account: str,
        zimbra_id: str,
        *,
        category: str | None = None,
        is_spam: bool = False,
        folder_path: str | None = None,
        forwarded_to: str | None = None,
        ack_sent_at: str | datetime | None = None,
        draft_saved: bool = False,
        classification: dict[str, Any] | None = None,
        error: str | None = None,
        draft_reply_text: str | None = None,
        ack_body_text: str | None = None,
        automation_thread_id: str | None = None,
        report_json: dict[str, Any] | None = None,
        thread_summary: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        ack_ts = None
        if ack_sent_at:
            ack_ts = (
                datetime.fromisoformat(str(ack_sent_at).replace("Z", "+00:00"))
                if isinstance(ack_sent_at, str)
                else ack_sent_at
            )
        classification_json = json.dumps(classification) if classification else None
        report_str = json.dumps(report_json, default=str) if report_json else None
        thread_summary_json = json.dumps(thread_summary) if thread_summary else None
        await conn.execute(
            """
            INSERT INTO message_actions (
                zimbra_id, account, category, is_spam, folder_path,
                forwarded_to, ack_sent_at, draft_saved, classification_json,
                error, processed_at, draft_reply_text, ack_body_text,
                automation_thread_id, report_json, thread_summary_json
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
                      $12, $13, $14, $15::jsonb, $16::jsonb)
            ON CONFLICT (zimbra_id, account) DO UPDATE SET
                category = EXCLUDED.category,
                is_spam = EXCLUDED.is_spam,
                folder_path = EXCLUDED.folder_path,
                forwarded_to = EXCLUDED.forwarded_to,
                ack_sent_at = COALESCE(EXCLUDED.ack_sent_at, message_actions.ack_sent_at),
                draft_saved = EXCLUDED.draft_saved,
                classification_json = EXCLUDED.classification_json,
                error = EXCLUDED.error,
                processed_at = EXCLUDED.processed_at,
                draft_reply_text = EXCLUDED.draft_reply_text,
                ack_body_text = EXCLUDED.ack_body_text,
                automation_thread_id = EXCLUDED.automation_thread_id,
                report_json = EXCLUDED.report_json,
                thread_summary_json = COALESCE(
                    EXCLUDED.thread_summary_json, message_actions.thread_summary_json
                )
            """,
            zimbra_id,
            account,
            category,
            is_spam,
            folder_path,
            forwarded_to,
            ack_ts,
            draft_saved,
            classification_json,
            error,
            now,
            draft_reply_text,
            ack_body_text,
            automation_thread_id,
            report_str,
            thread_summary_json,
        )

    async def save_thread_summary(
        self,
        conn: asyncpg.Connection,
        account: str,
        zimbra_id: str,
        thread_summary: dict[str, Any],
    ) -> None:
        now = _utc_now()
        await conn.execute(
            """
            INSERT INTO message_actions (zimbra_id, account, processed_at, thread_summary_json)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (zimbra_id, account) DO UPDATE SET
                thread_summary_json = EXCLUDED.thread_summary_json
            """,
            zimbra_id,
            account,
            now,
            json.dumps(thread_summary),
        )

    async def get_message_action(
        self, conn: asyncpg.Connection, account: str, zimbra_id: str
    ) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            "SELECT * FROM message_actions WHERE account = $1 AND zimbra_id = $2",
            account,
            zimbra_id,
        )
        return self._action_row_to_dict(row) if row else None

    async def save_message_automation_run(
        self,
        conn: asyncpg.Connection,
        account: str,
        zimbra_id: str,
        thread_id: str,
        status: str,
        *,
        dry_run: bool = False,
        classification: dict[str, Any] | None = None,
        actions: dict[str, Any] | None = None,
        draft_reply_text: str | None = None,
        ack_body_text: str | None = None,
        report: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> int:
        run_id = await conn.fetchval(
            """
            INSERT INTO message_automation_runs (
                account, zimbra_id, thread_id, status, dry_run,
                classification_json, actions_json, draft_reply_text,
                ack_body_text, report_json, error, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10::jsonb, $11, $12)
            RETURNING id
            """,
            account,
            zimbra_id,
            thread_id,
            status,
            dry_run,
            json.dumps(classification) if classification else None,
            json.dumps(actions) if actions else None,
            draft_reply_text,
            ack_body_text,
            json.dumps(report, default=str) if report else None,
            error,
            _utc_now(),
        )
        return int(run_id or 0)

    async def get_message_automation_runs(
        self,
        conn: asyncpg.Connection,
        account: str,
        zimbra_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT * FROM message_automation_runs
            WHERE account = $1 AND zimbra_id = $2
            ORDER BY created_at DESC
            LIMIT $3
            """,
            account,
            zimbra_id,
            limit,
        )
        return [self._automation_run_row_to_dict(row) for row in rows]

    async def save_analysis_run(
        self,
        conn: asyncpg.Connection,
        account: str,
        thread_id: str,
        dominant_intent: str | None,
        message_count: int,
        report: dict[str, Any],
    ) -> int:
        run_id = await conn.fetchval(
            """
            INSERT INTO analysis_runs
                (account, thread_id, dominant_intent, message_count, report_json, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            RETURNING id
            """,
            account,
            thread_id,
            dominant_intent,
            message_count,
            json.dumps(report, default=str),
            _utc_now(),
        )
        return int(run_id or 0)

    async def get_analysis_runs(
        self, conn: asyncpg.Connection, account: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT id, account, thread_id, dominant_intent, message_count,
                   report_json, created_at
            FROM analysis_runs
            WHERE account = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            account,
            limit,
        )
        return [self._analysis_row_to_dict(row) for row in rows]

    async def count_messages(self, conn: asyncpg.Connection, account: str) -> int:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE account = $1", account
        )
        return int(val or 0)

    async def count_unanalyzed(self, conn: asyncpg.Connection, account: str) -> int:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE account = $1 AND analyzed_at IS NULL",
            account,
        )
        return int(val or 0)

    async def get_analyzed_at(
        self, conn: asyncpg.Connection, account: str, zimbra_id: str
    ) -> str | None:
        val = await conn.fetchval(
            "SELECT analyzed_at FROM messages WHERE account = $1 AND zimbra_id = $2",
            account,
            zimbra_id,
        )
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    @staticmethod
    def _parse_to_addresses(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            return json.loads(raw)
        return list(raw)

    @staticmethod
    def _row_to_detail(row: asyncpg.Record) -> MessageDetail:
        to_addresses = PostgresEmailRepository._parse_to_addresses(row["to_addresses"])
        return MessageDetail(
            id=row["zimbra_id"],
            account=row["account"],
            subject=row["subject"],
            from_address=row["from_address"],
            to_addresses=to_addresses,
            date=row["date"],
            fragment=row["fragment"],
            folder=row["folder"],
            size=row["size"],
            is_read=row["is_read"],
            body=row["body"],
        )

    @staticmethod
    def _action_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
        data = dict(row)
        classification = data.get("classification_json")
        if isinstance(classification, str):
            classification = json.loads(classification) if classification else None
        report = data.get("report_json")
        if isinstance(report, str):
            report = json.loads(report) if report else None
        thread_summary = data.get("thread_summary_json")
        if isinstance(thread_summary, str):
            thread_summary = json.loads(thread_summary) if thread_summary else None
        ack_sent_at = data.get("ack_sent_at")
        processed_at = data.get("processed_at")
        return {
            "zimbra_id": data["zimbra_id"],
            "account": data["account"],
            "category": data.get("category"),
            "is_spam": data.get("is_spam"),
            "folder_path": data.get("folder_path"),
            "forwarded_to": data.get("forwarded_to"),
            "ack_sent_at": ack_sent_at.isoformat() if hasattr(ack_sent_at, "isoformat") else ack_sent_at,
            "draft_saved": data.get("draft_saved"),
            "classification": classification,
            "draft_reply_text": data.get("draft_reply_text"),
            "ack_body_text": data.get("ack_body_text"),
            "automation_thread_id": data.get("automation_thread_id"),
            "report": report,
            "thread_summary": thread_summary,
            "error": data.get("error"),
            "processed_at": processed_at.isoformat() if hasattr(processed_at, "isoformat") else processed_at,
        }

    @staticmethod
    def _automation_run_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
        def _load(raw: Any) -> dict[str, Any]:
            if isinstance(raw, str) and raw:
                return json.loads(raw)
            if raw is None:
                return {}
            return dict(raw) if not isinstance(raw, dict) else raw

        return {
            "id": row["id"],
            "account": row["account"],
            "zimbra_id": row["zimbra_id"],
            "thread_id": row["thread_id"],
            "status": row["status"],
            "dry_run": row["dry_run"],
            "classification": _load(row["classification_json"]),
            "actions": _load(row["actions_json"]),
            "draft_reply_text": row["draft_reply_text"],
            "ack_body_text": row["ack_body_text"],
            "report": _load(row["report_json"]),
            "error": row["error"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    @staticmethod
    def _analysis_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
        report = row["report_json"]
        if isinstance(report, str):
            report = json.loads(report) if report else {}
        return {
            "id": row["id"],
            "account": row["account"],
            "thread_id": row["thread_id"],
            "dominant_intent": row["dominant_intent"],
            "message_count": row["message_count"],
            "report": report or {},
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    @staticmethod
    def to_summary_dict(message: MessageDetail | MessageSummary) -> dict[str, Any]:
        return message.model_dump(by_alias=True)
