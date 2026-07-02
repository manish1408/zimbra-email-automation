from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.models.schemas import MessageDetail, MessageSummary

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zimbra_id TEXT NOT NULL,
    account TEXT NOT NULL,
    subject TEXT,
    from_address TEXT,
    to_addresses TEXT,
    date TEXT,
    fragment TEXT,
    folder TEXT,
    size INTEGER,
    is_read INTEGER,
    body TEXT,
    synced_at TEXT NOT NULL,
    analyzed_at TEXT,
    UNIQUE(zimbra_id, account)
);

CREATE INDEX IF NOT EXISTS idx_messages_account_analyzed
    ON messages(account, analyzed_at);

CREATE TABLE IF NOT EXISTS mailbox_state (
    account TEXT PRIMARY KEY,
    last_seen_date TEXT,
    last_poll_at TEXT,
    last_poll_new_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS message_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zimbra_id TEXT NOT NULL,
    account TEXT NOT NULL,
    category TEXT,
    is_spam INTEGER DEFAULT 0,
    folder_path TEXT,
    forwarded_to TEXT,
    ack_sent_at TEXT,
    draft_saved INTEGER DEFAULT 0,
    classification_json TEXT,
    error TEXT,
    processed_at TEXT NOT NULL,
    UNIQUE(zimbra_id, account)
);

CREATE INDEX IF NOT EXISTS idx_message_actions_account
    ON message_actions(account, processed_at);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    dominant_intent TEXT,
    message_count INTEGER,
    report_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    zimbra_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER DEFAULT 0,
    classification_json TEXT,
    actions_json TEXT,
    draft_reply_text TEXT,
    ack_body_text TEXT,
    report_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_automation_runs_message
    ON message_automation_runs(account, zimbra_id, created_at);
"""

_MIGRATION_V2_COLUMNS = [
    "ALTER TABLE message_actions ADD COLUMN draft_reply_text TEXT",
    "ALTER TABLE message_actions ADD COLUMN ack_body_text TEXT",
    "ALTER TABLE message_actions ADD COLUMN automation_thread_id TEXT",
    "ALTER TABLE message_actions ADD COLUMN report_json TEXT",
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite://"):
        path = database_url[len("sqlite://") :]
        # sqlite:////absolute/path.db
        if path.startswith("//"):
            return Path(path[1:])
        # sqlite:///relative/path.db
        if path.startswith("/"):
            return Path(path.lstrip("/"))
        return Path(path)
    return Path(database_url)


class SqliteEmailRepository:
    """Async SQLite store (default local backend, no server required)."""

    def __init__(self, database_url: str):
        self.db_path = parse_sqlite_path(database_url)

    async def connect(self) -> aiosqlite.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript(_SCHEMA)
        for stmt in _MIGRATION_V2_COLUMNS:
            try:
                await conn.execute(stmt)
            except aiosqlite.OperationalError:
                pass
        await conn.commit()
        return conn

    async def upsert_message(self, conn: aiosqlite.Connection, message: MessageDetail) -> bool:
        cursor = await conn.execute(
            "SELECT id FROM messages WHERE zimbra_id = ? AND account = ?",
            (message.id, message.account),
        )
        existing = await cursor.fetchone()
        now = _utc_now()
        to_json = json.dumps(message.to_addresses)

        if existing:
            await conn.execute(
                """
                UPDATE messages SET
                    subject = ?, from_address = ?, to_addresses = ?, date = ?,
                    fragment = ?, folder = ?, size = ?, is_read = ?,
                    body = COALESCE(?, body), synced_at = ?
                WHERE zimbra_id = ? AND account = ?
                """,
                (
                    message.subject,
                    message.from_address,
                    to_json,
                    message.date,
                    message.fragment,
                    message.folder,
                    message.size,
                    int(message.is_read) if message.is_read is not None else None,
                    message.body,
                    now,
                    message.id,
                    message.account,
                ),
            )
            return False

        await conn.execute(
            """
            INSERT INTO messages (
                zimbra_id, account, subject, from_address, to_addresses,
                date, fragment, folder, size, is_read, body, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.account,
                message.subject,
                message.from_address,
                to_json,
                message.date,
                message.fragment,
                message.folder,
                message.size,
                int(message.is_read) if message.is_read is not None else None,
                message.body,
                now,
            ),
        )
        return True

    async def get_message(
        self, conn: aiosqlite.Connection, account: str, zimbra_id: str
    ) -> MessageDetail | None:
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account = ? AND zimbra_id = ?",
            (account, zimbra_id),
        )
        row = await cursor.fetchone()
        return self._row_to_detail(row) if row else None

    async def get_unanalyzed_messages(
        self, conn: aiosqlite.Connection, account: str, limit: int = 50
    ) -> list[MessageDetail]:
        cursor = await conn.execute(
            """
            SELECT * FROM messages
            WHERE account = ? AND analyzed_at IS NULL
            ORDER BY date DESC
            LIMIT ?
            """,
            (account, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_detail(row) for row in rows]

    async def get_messages(
        self,
        conn: aiosqlite.Connection,
        account: str,
        limit: int = 50,
        offset: int = 0,
        *,
        analyzed: bool | None = None,
    ) -> tuple[list[MessageDetail], int]:
        where = "account = ?"
        params: list[Any] = [account]
        if analyzed is True:
            where += " AND analyzed_at IS NOT NULL"
        elif analyzed is False:
            where += " AND analyzed_at IS NULL"

        cursor = await conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE {where}", params
        )
        total_row = await cursor.fetchone()
        total = int(total_row[0]) if total_row else 0

        params.extend([limit, offset])
        cursor = await conn.execute(
            f"""
            SELECT * FROM messages
            WHERE {where}
            ORDER BY date DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_detail(row) for row in rows], total

    async def mark_analyzed(
        self, conn: aiosqlite.Connection, account: str, zimbra_ids: list[str]
    ) -> None:
        if not zimbra_ids:
            return
        now = _utc_now()
        placeholders = ",".join("?" for _ in zimbra_ids)
        await conn.execute(
            f"""
            UPDATE messages SET analyzed_at = ?
            WHERE account = ? AND zimbra_id IN ({placeholders})
            """,
            [now, account, *zimbra_ids],
        )

    async def update_message_folder(
        self,
        conn: aiosqlite.Connection,
        account: str,
        zimbra_id: str,
        folder: str,
    ) -> None:
        await conn.execute(
            """
            UPDATE messages SET folder = ?
            WHERE account = ? AND zimbra_id = ?
            """,
            (folder, account, zimbra_id),
        )

    async def get_mailbox_state(
        self, conn: aiosqlite.Connection, account: str
    ) -> dict[str, Any] | None:
        cursor = await conn.execute(
            "SELECT * FROM mailbox_state WHERE account = ?", (account,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def upsert_mailbox_state(
        self,
        conn: aiosqlite.Connection,
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
                    last_seen_date = COALESCE(?, last_seen_date),
                    last_poll_at = ?,
                    last_poll_new_count = ?
                WHERE account = ?
                """,
                (last_seen_date, now, last_poll_new_count, account),
            )
        else:
            await conn.execute(
                """
                INSERT INTO mailbox_state
                    (account, last_seen_date, last_poll_at, last_poll_new_count)
                VALUES (?, ?, ?, ?)
                """,
                (account, last_seen_date, now, last_poll_new_count),
            )

    async def is_message_processed(
        self, conn: aiosqlite.Connection, account: str, zimbra_id: str
    ) -> bool:
        cursor = await conn.execute(
            """
            SELECT 1 FROM message_actions
            WHERE account = ? AND zimbra_id = ? AND error IS NULL
            """,
            (account, zimbra_id),
        )
        return await cursor.fetchone() is not None

    async def save_message_action(
        self,
        conn: aiosqlite.Connection,
        account: str,
        zimbra_id: str,
        *,
        category: str | None = None,
        is_spam: bool = False,
        folder_path: str | None = None,
        forwarded_to: str | None = None,
        ack_sent_at: str | None = None,
        draft_saved: bool = False,
        classification: dict[str, Any] | None = None,
        error: str | None = None,
        draft_reply_text: str | None = None,
        ack_body_text: str | None = None,
        automation_thread_id: str | None = None,
        report_json: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        await conn.execute(
            """
            INSERT INTO message_actions (
                zimbra_id, account, category, is_spam, folder_path,
                forwarded_to, ack_sent_at, draft_saved, classification_json,
                error, processed_at, draft_reply_text, ack_body_text,
                automation_thread_id, report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(zimbra_id, account) DO UPDATE SET
                category = excluded.category,
                is_spam = excluded.is_spam,
                folder_path = excluded.folder_path,
                forwarded_to = excluded.forwarded_to,
                ack_sent_at = COALESCE(excluded.ack_sent_at, message_actions.ack_sent_at),
                draft_saved = excluded.draft_saved,
                classification_json = excluded.classification_json,
                error = excluded.error,
                processed_at = excluded.processed_at,
                draft_reply_text = excluded.draft_reply_text,
                ack_body_text = excluded.ack_body_text,
                automation_thread_id = excluded.automation_thread_id,
                report_json = excluded.report_json
            """,
            (
                zimbra_id,
                account,
                category,
                int(is_spam),
                folder_path,
                forwarded_to,
                ack_sent_at,
                int(draft_saved),
                json.dumps(classification) if classification else None,
                error,
                now,
                draft_reply_text,
                ack_body_text,
                automation_thread_id,
                json.dumps(report_json, default=str) if report_json else None,
            ),
        )

    async def get_message_action(
        self, conn: aiosqlite.Connection, account: str, zimbra_id: str
    ) -> dict[str, Any] | None:
        cursor = await conn.execute(
            "SELECT * FROM message_actions WHERE account = ? AND zimbra_id = ?",
            (account, zimbra_id),
        )
        row = await cursor.fetchone()
        return self._parse_action_row(row) if row else None

    async def save_message_automation_run(
        self,
        conn: aiosqlite.Connection,
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
        cursor = await conn.execute(
            """
            INSERT INTO message_automation_runs (
                account, zimbra_id, thread_id, status, dry_run,
                classification_json, actions_json, draft_reply_text,
                ack_body_text, report_json, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account,
                zimbra_id,
                thread_id,
                status,
                int(dry_run),
                json.dumps(classification) if classification else None,
                json.dumps(actions) if actions else None,
                draft_reply_text,
                ack_body_text,
                json.dumps(report, default=str) if report else None,
                error,
                _utc_now(),
            ),
        )
        return cursor.lastrowid or 0

    async def get_message_automation_runs(
        self,
        conn: aiosqlite.Connection,
        account: str,
        zimbra_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        cursor = await conn.execute(
            """
            SELECT * FROM message_automation_runs
            WHERE account = ? AND zimbra_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (account, zimbra_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._parse_automation_run_row(row) for row in rows]

    @staticmethod
    def _parse_action_row(row: aiosqlite.Row) -> dict[str, Any]:
        data = dict(row)
        classification = data.get("classification_json")
        if isinstance(classification, str) and classification:
            data["classification"] = json.loads(classification)
        elif classification:
            data["classification"] = classification
        report = data.get("report_json")
        if isinstance(report, str) and report:
            data["report"] = json.loads(report)
        elif report:
            data["report"] = report
        return data

    @staticmethod
    def _parse_automation_run_row(row: aiosqlite.Row) -> dict[str, Any]:
        def _load(raw: Any) -> dict[str, Any]:
            if isinstance(raw, str) and raw:
                return json.loads(raw)
            return raw or {}

        return {
            "id": row["id"],
            "account": row["account"],
            "zimbra_id": row["zimbra_id"],
            "thread_id": row["thread_id"],
            "status": row["status"],
            "dry_run": bool(row["dry_run"]),
            "classification": _load(row["classification_json"]),
            "actions": _load(row["actions_json"]),
            "draft_reply_text": row["draft_reply_text"],
            "ack_body_text": row["ack_body_text"],
            "report": _load(row["report_json"]),
            "error": row["error"],
            "created_at": row["created_at"],
        }

    async def save_analysis_run(
        self,
        conn: aiosqlite.Connection,
        account: str,
        thread_id: str,
        dominant_intent: str | None,
        message_count: int,
        report: dict[str, Any],
    ) -> int:
        cursor = await conn.execute(
            """
            INSERT INTO analysis_runs
                (account, thread_id, dominant_intent, message_count, report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account,
                thread_id,
                dominant_intent,
                message_count,
                json.dumps(report, default=str),
                _utc_now(),
            ),
        )
        return cursor.lastrowid or 0

    async def get_analysis_runs(
        self, conn: aiosqlite.Connection, account: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        cursor = await conn.execute(
            """
            SELECT id, account, thread_id, dominant_intent, message_count,
                   report_json, created_at
            FROM analysis_runs
            WHERE account = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (account, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "account": row["account"],
                "thread_id": row["thread_id"],
                "dominant_intent": row["dominant_intent"],
                "message_count": row["message_count"],
                "report": json.loads(row["report_json"]) if row["report_json"] else {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def count_messages(self, conn: aiosqlite.Connection, account: str) -> int:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM messages WHERE account = ?", (account,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_unanalyzed(self, conn: aiosqlite.Connection, account: str) -> int:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM messages WHERE account = ? AND analyzed_at IS NULL",
            (account,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_analyzed_at(
        self, conn: aiosqlite.Connection, account: str, zimbra_id: str
    ) -> str | None:
        cursor = await conn.execute(
            "SELECT analyzed_at FROM messages WHERE account = ? AND zimbra_id = ?",
            (account, zimbra_id),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

    @staticmethod
    def _row_to_detail(row: aiosqlite.Row) -> MessageDetail:
        to_addresses = json.loads(row["to_addresses"]) if row["to_addresses"] else []
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
            is_read=bool(row["is_read"]) if row["is_read"] is not None else None,
            body=row["body"],
        )

    @staticmethod
    def to_summary_dict(message: MessageDetail | MessageSummary) -> dict[str, Any]:
        return message.model_dump(by_alias=True)
