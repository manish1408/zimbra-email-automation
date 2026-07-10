from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.db.postgres_repository import PostgresEmailRepository
from app.services.automation_run_logs import (
    _run_status,
    finalize_trace_summaries,
    persist_message_automation_logs,
)
from app.services.llm import get_llm_duration_ms, reset_llm_duration
from app.services.message_automation import _result_from_db


class _RecordingConn:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self._rows = rows or []

    async def fetchval(self, sql: str, *params: Any) -> int:
        self.queries.append((sql, params))
        return len(self._rows)

    async def fetch(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        self.queries.append((sql, params))
        return self._rows


def _sample_log_row(message_id: str = "100") -> dict[str, Any]:
    return {
        "id": 1,
        "account": "user@example.com",
        "zimbra_id": message_id,
        "thread_id": "thread-1",
        "status": "completed",
        "dry_run": False,
        "subject": "Help",
        "from_address": "c@example.com",
        "duration_ms": 500,
        "llm_duration_ms": 200,
        "classification_json": None,
        "actions_json": None,
        "error": None,
        "automation_trace_json": None,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


@pytest.mark.asyncio
async def test_list_automation_logs_filters_by_message_id():
    repo = PostgresEmailRepository("postgresql://test")
    conn = _RecordingConn(rows=[_sample_log_row("msg-42")])

    logs, total = await repo.list_automation_logs(
        conn,
        "user@example.com",
        message_id="msg-42",
    )

    assert total == 1
    assert len(logs) == 1
    assert logs[0]["message_id"] == "msg-42"
    count_sql, count_params = conn.queries[0]
    select_sql, select_params = conn.queries[1]
    assert "zimbra_id = $2" in count_sql
    assert count_params == ("user@example.com", "msg-42")
    assert "r.zimbra_id = $2" in select_sql
    assert select_params == ("user@example.com", "msg-42", 50, 0)


@pytest.mark.asyncio
async def test_list_automation_logs_combines_message_id_and_status_filters():
    repo = PostgresEmailRepository("postgresql://test")
    conn = _RecordingConn(rows=[_sample_log_row()])

    await repo.list_automation_logs(
        conn,
        "user@example.com",
        status="failed",
        message_id="msg-99",
    )

    count_sql, count_params = conn.queries[0]
    select_sql, select_params = conn.queries[1]
    assert "status = $2" in count_sql
    assert "zimbra_id = $3" in count_sql
    assert count_params == ("user@example.com", "failed", "msg-99")
    assert "r.status = $2" in select_sql
    assert "r.zimbra_id = $3" in select_sql
    assert select_params == ("user@example.com", "failed", "msg-99", 50, 0)


@pytest.mark.asyncio
async def test_list_automation_logs_all_mailboxes():
    repo = PostgresEmailRepository("postgresql://test")
    conn = _RecordingConn(rows=[_sample_log_row()])

    logs, total = await repo.list_automation_logs(conn, None)

    assert total == 1
    assert len(logs) == 1
    count_sql, count_params = conn.queries[0]
    assert "account =" not in count_sql
    assert count_params == ()


@pytest.mark.asyncio
async def test_list_automation_logs_ignores_blank_message_id():
    repo = PostgresEmailRepository("postgresql://test")
    conn = _RecordingConn()

    await repo.list_automation_logs(conn, "user@example.com", message_id="   ")

    count_sql, count_params = conn.queries[0]
    assert "zimbra_id" not in count_sql
    assert count_params == ("user@example.com",)


def test_finalize_trace_summaries():
    traces = {"m1": {"steps": []}, "m2": {"steps": []}}
    finalize_trace_summaries(traces, total_duration_ms=1200, llm_duration_ms=400)
    assert traces["m1"]["total_duration_ms"] == 1200
    assert traces["m2"]["llm_duration_ms"] == 400


def test_run_status_failed_with_record_error():
    status, error = _run_status(
        "msg-1",
        {"error": "move failed"},
        [],
    )
    assert status == "failed"
    assert error == "move failed"


def test_run_status_completed():
    status, error = _run_status("msg-1", {}, [])
    assert status == "completed"
    assert error is None


def test_result_from_db_without_action_row():
    runs = [
        {
            "id": 1,
            "thread_id": "manual:a:b:abc",
            "status": "failed",
            "dry_run": False,
            "classification": {"category": "support"},
            "actions": None,
            "draft_reply_text": None,
            "error": "pipeline error",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    result = _result_from_db("a@example.com", "b", None, runs)
    assert result.status == "failed"
    assert result.error == "pipeline error"
    assert result.automation_trace is None


@pytest.mark.asyncio
async def test_persist_message_automation_logs_inserts_rows():
    class FakeRepo:
        def __init__(self):
            self.calls: list[dict] = []

        async def save_message_automation_run(self, conn, account, zimbra_id, thread_id, status, **kwargs):
            self.calls.append(
                {
                    "account": account,
                    "zimbra_id": zimbra_id,
                    "thread_id": thread_id,
                    "status": status,
                    **kwargs,
                }
            )
            return len(self.calls)

    repo = FakeRepo()
    conn = object()
    state = {
        "user_email": "user@example.com",
        "automation_thread_id": "scheduled:user:abc",
        "report": {"dry_run": True},
        "actions_taken": [
            {
                "message_id": "100",
                "folder_moved": True,
                "folder_path": "Support",
                "forwarded_to": None,
                "draft_saved": False,
                "automation_trace": {"steps": [{"step": "classify_messages", "action": "classify", "success": True}]},
            }
        ],
        "action_errors": [],
        "automation_traces": {
            "100": {"steps": [{"step": "classify_messages", "action": "classify", "success": True}]}
        },
        "classifications": [{"message_id": "100", "category": "support"}],
        "enriched_messages": [
            {"id": "100", "subject": "Help", "from": "c@example.com"}
        ],
    }

    ids = await persist_message_automation_logs(
        repo,
        conn,
        state,
        total_duration_ms=500,
        llm_duration_ms=200,
    )
    assert ids == [1]
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call["zimbra_id"] == "100"
    assert call["status"] == "completed"
    assert call["duration_ms"] == 500
    assert call["llm_duration_ms"] == 200
    assert call["subject"] == "Help"
    assert call["from_address"] == "c@example.com"
    assert call["dry_run"] is True


def test_llm_duration_contextvar():
    reset_llm_duration()
    assert get_llm_duration_ms() == 0
