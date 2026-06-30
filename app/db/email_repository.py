from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from app.models.schemas import MessageDetail, MessageSummary

DbConnection = asyncpg.Connection

_SCHEMA = Path(__file__).resolve().parent / "migrations" / "001_initial.sql"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EmailRepository:
    """Async PostgreSQL store for synced mailbox messages and analysis runs."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def connect(self) -> DbConnection:
        conn = await asyncpg.connect(self.database_url)
        if _SCHEMA.exists():
            await conn.execute(_SCHEMA.read_text())
        return conn

    async def upsert_message(self, conn: DbConnection, message: MessageDetail) -> bool:
        """Insert or update a message. Returns True if newly inserted."""
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
        self,
        conn: DbConnection,
        account: str,
        zimbra_id: str,
    ) -> MessageDetail | None:
        row = await conn.fetchrow(
            "SELECT * FROM messages WHERE account = $1 AND zimbra_id = $2",
            account,
            zimbra_id,
        )
        return self._row_to_detail(row) if row else None

    async def get_unanalyzed_messages(
        self,
        conn: DbConnection,
        account: str,
        limit: int = 50,
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
        conn: DbConnection,
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

        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages WHERE {where}",
            *params,
        )
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
        self,
        conn: DbConnection,
        account: str,
        zimbra_ids: list[str],
    ) -> None:
        if not zimbra_ids:
            return
        now = _utc_now()
        await conn.execute(
            """
            UPDATE messages SET analyzed_at = $1
            WHERE account = $2 AND zimbra_id = ANY($3::text[])
            """,
            now,
            account,
            zimbra_ids,
        )

    async def get_mailbox_state(
        self, conn: DbConnection, account: str
    ) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            "SELECT * FROM mailbox_state WHERE account = $1", account
        )
        if not row:
            return None
        return dict(row)

    async def upsert_mailbox_state(
        self,
        conn: DbConnection,
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
        self, conn: DbConnection, account: str, zimbra_id: str
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
        conn: DbConnection,
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
        await conn.execute(
            """
            INSERT INTO message_actions (
                zimbra_id, account, category, is_spam, folder_path,
                forwarded_to, ack_sent_at, draft_saved, classification_json,
                error, processed_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
            ON CONFLICT (zimbra_id, account) DO UPDATE SET
                category = EXCLUDED.category,
                is_spam = EXCLUDED.is_spam,
                folder_path = EXCLUDED.folder_path,
                forwarded_to = EXCLUDED.forwarded_to,
                ack_sent_at = COALESCE(EXCLUDED.ack_sent_at, message_actions.ack_sent_at),
                draft_saved = EXCLUDED.draft_saved,
                classification_json = EXCLUDED.classification_json,
                error = EXCLUDED.error,
                processed_at = EXCLUDED.processed_at
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
        )

    async def get_message_action(
        self, conn: DbConnection, account: str, zimbra_id: str
    ) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            "SELECT * FROM message_actions WHERE account = $1 AND zimbra_id = $2",
            account,
            zimbra_id,
        )
        return self._action_row_to_dict(row) if row else None

    async def save_analysis_run(
        self,
        conn: DbConnection,
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
        self,
        conn: DbConnection,
        account: str,
        limit: int = 20,
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

    async def count_messages(self, conn: DbConnection, account: str) -> int:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE account = $1", account
        )
        return int(val or 0)

    async def count_unanalyzed(self, conn: DbConnection, account: str) -> int:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE account = $1 AND analyzed_at IS NULL",
            account,
        )
        return int(val or 0)

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
        to_addresses = EmailRepository._parse_to_addresses(row["to_addresses"])
        analyzed_at = row["analyzed_at"]
        synced_at = row["synced_at"]
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
        classification = row["classification_json"]
        if isinstance(classification, str):
            classification = json.loads(classification) if classification else None
        return {
            "zimbra_id": row["zimbra_id"],
            "account": row["account"],
            "category": row["category"],
            "is_spam": row["is_spam"],
            "folder_path": row["folder_path"],
            "forwarded_to": row["forwarded_to"],
            "ack_sent_at": row["ack_sent_at"].isoformat() if row["ack_sent_at"] else None,
            "draft_saved": row["draft_saved"],
            "classification": classification,
            "error": row["error"],
            "processed_at": row["processed_at"].isoformat() if row["processed_at"] else None,
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
