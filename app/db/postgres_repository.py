from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg

from app.db.pool import get_pool
from app.models.schemas import MessageDetail, MessageSummary
from app.services.zimbra.soap import normalize_zimbra_date


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PostgresEmailRepository:
    """Async PostgreSQL store for synced mailbox messages and analysis runs."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def connect(self) -> asyncpg.Connection:
        return await get_pool().acquire()

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
            WHERE account = $1 AND zimbra_id = $2
              AND error IS NULL
              AND classification_json IS NOT NULL
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
        automation_trace: dict[str, Any] | None = None,
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
        trace_str = json.dumps(automation_trace, default=str) if automation_trace else None
        await conn.execute(
            """
            INSERT INTO message_actions (
                zimbra_id, account, category, is_spam, folder_path,
                forwarded_to, ack_sent_at, draft_saved, classification_json,
                error, processed_at, draft_reply_text, ack_body_text,
                automation_thread_id, report_json, automation_trace_json
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
                automation_trace_json = EXCLUDED.automation_trace_json
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
            trace_str,
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
        duration_ms: int | None = None,
        llm_duration_ms: int | None = None,
        automation_trace: dict[str, Any] | None = None,
        subject: str | None = None,
        from_address: str | None = None,
    ) -> int:
        trace_str = (
            json.dumps(automation_trace, default=str) if automation_trace else None
        )
        run_id = await conn.fetchval(
            """
            INSERT INTO message_automation_runs (
                account, zimbra_id, thread_id, status, dry_run,
                classification_json, actions_json, draft_reply_text,
                ack_body_text, report_json, error, created_at,
                duration_ms, llm_duration_ms, automation_trace_json,
                subject, from_address
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10::jsonb, $11, $12,
                $13, $14, $15::jsonb, $16, $17
            )
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
            duration_ms,
            llm_duration_ms,
            trace_str,
            subject,
            from_address,
        )
        return int(run_id or 0)

    async def list_automation_logs(
        self,
        conn: asyncpg.Connection,
        account: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        message_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters: list[str] = ["account = $1"]
        params: list[Any] = [account]

        if status:
            params.append(status)
            filters.append(f"status = ${len(params)}")
        if message_id and message_id.strip():
            params.append(message_id.strip())
            filters.append(f"zimbra_id = ${len(params)}")

        where = " AND ".join(filters)
        count_sql = f"SELECT COUNT(*) FROM message_automation_runs WHERE {where}"
        total = int(await conn.fetchval(count_sql, *params) or 0)

        select_filters = [f"r.{clause}" for clause in filters]
        select_where = " AND ".join(select_filters)
        limit_idx = len(params) + 1
        offset_idx = len(params) + 2
        select_sql = f"""
            SELECT
                r.id, r.account, r.zimbra_id, r.thread_id, r.status, r.dry_run,
                COALESCE(r.subject, m.subject) AS subject,
                COALESCE(r.from_address, m.from_address) AS from_address,
                r.duration_ms, r.llm_duration_ms,
                r.classification_json, r.actions_json, r.error,
                r.automation_trace_json, r.created_at
            FROM message_automation_runs r
            LEFT JOIN messages m
                ON m.account = r.account AND m.zimbra_id = r.zimbra_id
            WHERE {select_where}
            ORDER BY r.created_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
        """
        rows = await conn.fetch(select_sql, *params, limit, offset)
        return [self._automation_log_row_to_dict(row) for row in rows], total

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
            date=normalize_zimbra_date(row["date"]),
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
        automation_trace = data.get("automation_trace_json")
        if isinstance(automation_trace, str):
            automation_trace = json.loads(automation_trace) if automation_trace else None
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
            "automation_trace": automation_trace,
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
            "draft_reply_text": row.get("draft_reply_text"),
            "ack_body_text": row.get("ack_body_text"),
            "report": _load(row.get("report_json")),
            "error": row["error"],
            "duration_ms": row.get("duration_ms"),
            "llm_duration_ms": row.get("llm_duration_ms"),
            "automation_trace": _load(row.get("automation_trace_json")),
            "subject": row.get("subject"),
            "from_address": row.get("from_address"),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    @staticmethod
    def _automation_log_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
        def _load(raw: Any) -> dict[str, Any] | None:
            if isinstance(raw, str) and raw:
                return json.loads(raw)
            if raw is None:
                return None
            return dict(raw) if not isinstance(raw, dict) else raw

        return {
            "id": row["id"],
            "message_id": row["zimbra_id"],
            "thread_id": row["thread_id"],
            "status": row["status"],
            "dry_run": row["dry_run"],
            "subject": row.get("subject"),
            "from_address": row.get("from_address"),
            "duration_ms": row.get("duration_ms"),
            "llm_duration_ms": row.get("llm_duration_ms"),
            "classification": _load(row.get("classification_json")),
            "actions": _load(row.get("actions_json")),
            "error": row.get("error"),
            "automation_trace": _load(row.get("automation_trace_json")),
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

    async def get_agent_training(self, conn: asyncpg.Connection | None = None) -> dict[str, Any]:
        own_conn = conn is None
        if own_conn:
            conn = await self.connect()
        try:
            row = await conn.fetchrow(
                """
                SELECT content, draft_reply_content, updated_at
                FROM agent_training WHERE id = 1
                """
            )
            if not row:
                return {
                    "general_rules": "",
                    "draft_reply_rules": "",
                    "updated_at": None,
                }
            updated_at = row["updated_at"]
            return {
                "general_rules": row["content"] or "",
                "draft_reply_rules": row["draft_reply_content"] or "",
                "updated_at": updated_at.isoformat() if updated_at else None,
            }
        finally:
            if own_conn and conn is not None:
                await conn.close()

    async def upsert_agent_general_rules(
        self, general_rules: str, conn: asyncpg.Connection | None = None
    ) -> dict[str, Any]:
        own_conn = conn is None
        if own_conn:
            conn = await self.connect()
        try:
            now = _utc_now()
            row = await conn.fetchrow(
                """
                INSERT INTO agent_training (id, content, updated_at)
                VALUES (1, $1, $2)
                ON CONFLICT (id) DO UPDATE
                SET content = EXCLUDED.content, updated_at = EXCLUDED.updated_at
                RETURNING content, draft_reply_content, updated_at
                """,
                general_rules,
                now,
            )
            updated_at = row["updated_at"]
            return {
                "general_rules": row["content"] or "",
                "draft_reply_rules": row["draft_reply_content"] or "",
                "updated_at": updated_at.isoformat() if updated_at else None,
            }
        finally:
            if own_conn and conn is not None:
                await conn.close()

    async def upsert_agent_draft_reply_rules(
        self, draft_reply_rules: str, conn: asyncpg.Connection | None = None
    ) -> dict[str, Any]:
        own_conn = conn is None
        if own_conn:
            conn = await self.connect()
        try:
            now = _utc_now()
            row = await conn.fetchrow(
                """
                INSERT INTO agent_training (id, draft_reply_content, updated_at)
                VALUES (1, $1, $2)
                ON CONFLICT (id) DO UPDATE
                SET draft_reply_content = EXCLUDED.draft_reply_content,
                    updated_at = EXCLUDED.updated_at
                RETURNING content, draft_reply_content, updated_at
                """,
                draft_reply_rules,
                now,
            )
            updated_at = row["updated_at"]
            return {
                "general_rules": row["content"] or "",
                "draft_reply_rules": row["draft_reply_content"] or "",
                "updated_at": updated_at.isoformat() if updated_at else None,
            }
        finally:
            if own_conn and conn is not None:
                await conn.close()

    async def get_classification_rules(
        self, conn: asyncpg.Connection | None = None
    ) -> dict[str, Any]:
        own_conn = conn is None
        if own_conn:
            conn = await self.connect()
        try:
            config_row = await conn.fetchrow(
                """
                SELECT spam_folder, default_forward, ack_template,
                       classification_instructions, updated_at
                FROM classification_config WHERE id = 1
                """
            )
            category_rows = await conn.fetch(
                """
                SELECT slug, display_name, classification_hints, folder, forward_to,
                       send_ack, needs_live_agent, is_spam, route_by_person,
                       skip_forward, sort_order, enabled
                FROM classification_categories
                ORDER BY sort_order, slug
                """
            )
            employee_rows = await conn.fetch(
                """
                SELECT id, name, email, aliases
                FROM classification_employees
                ORDER BY name
                """
            )
        finally:
            if own_conn and conn is not None:
                await conn.close()

        if not config_row:
            return {
                "config": {
                    "spam_folder": "Junk",
                    "default_forward": None,
                    "ack_template": "",
                    "classification_instructions": "",
                },
                "categories": [],
                "employees": [],
                "updated_at": None,
            }

        updated_at = config_row["updated_at"]
        employees: list[dict[str, Any]] = []
        for row in employee_rows:
            aliases = row["aliases"]
            if isinstance(aliases, str):
                aliases = json.loads(aliases)
            employees.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "email": row["email"],
                    "aliases": aliases or [],
                }
            )

        return {
            "config": {
                "spam_folder": config_row["spam_folder"],
                "default_forward": config_row["default_forward"],
                "ack_template": config_row["ack_template"] or "",
                "classification_instructions": config_row["classification_instructions"] or "",
            },
            "categories": [
                {
                    "slug": row["slug"],
                    "display_name": row["display_name"],
                    "classification_hints": row["classification_hints"] or "",
                    "folder": row["folder"],
                    "forward_to": row["forward_to"],
                    "send_ack": row["send_ack"],
                    "needs_live_agent": row["needs_live_agent"],
                    "is_spam": row["is_spam"],
                    "route_by_person": row["route_by_person"],
                    "skip_forward": row["skip_forward"],
                    "sort_order": row["sort_order"],
                    "enabled": row["enabled"],
                }
                for row in category_rows
            ],
            "employees": employees,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }

    async def save_classification_rules(
        self, payload: dict[str, Any], conn: asyncpg.Connection | None = None
    ) -> dict[str, Any]:
        config = payload.get("config") or {}
        categories = payload.get("categories") or []
        employees = payload.get("employees") or []
        now = _utc_now()

        own_conn = conn is None
        if own_conn:
            conn = await self.connect()
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO classification_config (
                        id, spam_folder, default_forward, ack_template,
                        classification_instructions, updated_at
                    ) VALUES (1, $1, $2, $3, $4, $5)
                    ON CONFLICT (id) DO UPDATE SET
                        spam_folder = EXCLUDED.spam_folder,
                        default_forward = EXCLUDED.default_forward,
                        ack_template = EXCLUDED.ack_template,
                        classification_instructions = EXCLUDED.classification_instructions,
                        updated_at = EXCLUDED.updated_at
                    """,
                    config.get("spam_folder") or "Junk",
                    config.get("default_forward"),
                    config.get("ack_template") or "",
                    config.get("classification_instructions") or "",
                    now,
                )
                await conn.execute("DELETE FROM classification_categories")
                for item in categories:
                    await conn.execute(
                        """
                        INSERT INTO classification_categories (
                            slug, display_name, classification_hints, folder, forward_to,
                            send_ack, needs_live_agent, is_spam, route_by_person,
                            skip_forward, sort_order, enabled
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        item["slug"],
                        item["display_name"],
                        item.get("classification_hints") or "",
                        item["folder"],
                        item.get("forward_to"),
                        bool(item.get("send_ack", True)),
                        bool(item.get("needs_live_agent", False)),
                        bool(item.get("is_spam", False)),
                        bool(item.get("route_by_person", False)),
                        bool(item.get("skip_forward", False)),
                        int(item.get("sort_order") or 0),
                        bool(item.get("enabled", True)),
                    )
                await conn.execute("DELETE FROM classification_employees")
                for item in employees:
                    await conn.execute(
                        """
                        INSERT INTO classification_employees (name, email, aliases)
                        VALUES ($1, $2, $3::jsonb)
                        """,
                        item["name"],
                        item["email"],
                        json.dumps(list(item.get("aliases") or [])),
                    )
        finally:
            if own_conn and conn is not None:
                await conn.close()

        return await self.get_classification_rules(conn if not own_conn else None)
