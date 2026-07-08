from __future__ import annotations

import pytest

from app.services.automation_run_logs import (
    _run_status,
    finalize_trace_summaries,
    persist_message_automation_logs,
)
from app.services.llm import get_llm_duration_ms, reset_llm_duration
from app.services.message_automation import _result_from_db


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
