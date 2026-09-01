from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.models.schemas import User, UserListResponse
from app.services.scheduled_pipeline import (
    ScheduledPipeline,
    _is_active_mailbox,
    build_poll_queries,
    build_poll_query_specs,
    build_poll_query,
)

def _settings(**overrides) -> Settings:
    base = {
        "zimbra_host": "mail.example.com",
        "zimbra_admin_user": "admin@example.com",
        "zimbra_admin_password": "secret",
        "sync_target_email": "info@example.com",
        "sync_poll_all_mailboxes": False,
        "sync_mailboxes": "",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, True),
        ("", True),
        ("active", True),
        ("Active", True),
        ("closed", False),
        ("locked", False),
        ("maintenance", False),
    ],
)
def test_is_active_mailbox(status, expected):
    user = User(id="1", email="user@example.com", status=status)
    assert _is_active_mailbox(user) is expected


def test_build_poll_queries_includes_junk_by_default():
    settings = _settings()
    assert build_poll_queries(settings) == ["in:inbox is:unread", "in:junk is:unread"]
    assert build_poll_query(settings, None) == "in:inbox is:unread"


def test_build_poll_queries_can_disable_junk():
    settings = _settings(sync_include_junk=False)
    assert build_poll_queries(settings) == ["in:inbox is:unread"]


def test_build_poll_queries_skips_duplicate_junk_in_inbox_query():
    settings = _settings(sync_inbox_query="(in:inbox OR in:junk)")
    assert build_poll_queries(settings) == ["(in:inbox OR in:junk) is:unread"]


def test_build_poll_query_specs_prioritizes_recent_unread():
    settings = _settings(sync_recent_hours=24, sync_poll_fetch_limit=100)
    specs = build_poll_query_specs(settings)
    assert len(specs) >= 2
    assert all(limit == 100 for _, limit in specs)
    assert specs[0][0].startswith("in:inbox is:unread after:")
    assert any(query == "in:inbox is:unread" for query, _ in specs)
    assert any(query.startswith("in:junk is:unread after:") for query, _ in specs)


@pytest.mark.asyncio
async def test_list_poll_accounts_filters_and_sorts():
    settings = _settings(sync_poll_all_mailboxes=True)
    email_service = MagicMock()
    email_service.list_users = AsyncMock(
        return_value=UserListResponse(
            total=4,
            users=[
                User(id="2", email="zeta@example.com", status="active"),
                User(id="1", email="alpha@example.com", status="active"),
                User(id="3", email="closed@example.com", status="closed"),
                User(id="4", email="legacy@example.com", status=None),
            ],
        )
    )
    pipeline = ScheduledPipeline(settings, email_service=email_service)

    assert await pipeline.list_poll_accounts() == [
        "alpha@example.com",
        "legacy@example.com",
        "zeta@example.com",
    ]


@pytest.mark.asyncio
async def test_list_poll_accounts_respects_sync_mailboxes_allowlist():
    settings = _settings(
        sync_poll_all_mailboxes=True,
        sync_mailboxes="Zeta@example.com, missing@example.com, alpha@example.com",
    )
    email_service = MagicMock()
    email_service.list_users = AsyncMock(
        return_value=UserListResponse(
            total=4,
            users=[
                User(id="2", email="zeta@example.com", status="active"),
                User(id="1", email="alpha@example.com", status="active"),
                User(id="3", email="closed@example.com", status="closed"),
                User(id="4", email="legacy@example.com", status=None),
            ],
        )
    )
    pipeline = ScheduledPipeline(settings, email_service=email_service)

    assert await pipeline.list_poll_accounts() == [
        "zeta@example.com",
        "alpha@example.com",
    ]


@pytest.mark.asyncio
async def test_run_all_processes_each_active_account():
    settings = _settings(sync_poll_all_mailboxes=True)
    pipeline = ScheduledPipeline(settings, email_service=MagicMock(), repository=MagicMock())
    pipeline.list_poll_accounts = AsyncMock(
        return_value=["alpha@example.com", "beta@example.com"]
    )
    pipeline._run_for_account = AsyncMock(
        side_effect=[
            {"account": "alpha@example.com", "sync": {"fetched": 1}},
            {"account": "beta@example.com", "sync": {"fetched": 2}},
        ]
    )
    mock_conn = MagicMock()
    mock_conn.close = AsyncMock()
    pipeline.repository.connect = AsyncMock(return_value=mock_conn)

    result = await pipeline.run_all(skip_analysis=True)

    assert result["mode"] == "all"
    assert result["accounts_total"] == 2
    assert result["accounts_succeeded"] == 2
    assert result["accounts_failed"] == 0
    assert result["results"]["alpha@example.com"]["sync"]["fetched"] == 1
    assert result["results"]["beta@example.com"]["sync"]["fetched"] == 2
    assert pipeline._run_for_account.await_count == 2
    pipeline.repository.connect.assert_awaited_once()
    mock_conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_all_continues_after_account_failure():
    settings = _settings(sync_poll_all_mailboxes=True)
    pipeline = ScheduledPipeline(settings, email_service=MagicMock(), repository=MagicMock())
    pipeline.list_poll_accounts = AsyncMock(
        return_value=["bad@example.com", "good@example.com"]
    )
    pipeline._run_for_account = AsyncMock(
        side_effect=[
            RuntimeError("delegate auth failed"),
            {"account": "good@example.com", "sync": {"fetched": 1}},
        ]
    )
    mock_conn = MagicMock()
    mock_conn.close = AsyncMock()
    pipeline.repository.connect = AsyncMock(return_value=mock_conn)

    result = await pipeline.run_all(skip_analysis=True)

    assert result["accounts_total"] == 2
    assert result["accounts_succeeded"] == 1
    assert result["accounts_failed"] == 1
    assert "bad@example.com" in result["errors"]
    assert "good@example.com" in result["results"]


@pytest.mark.asyncio
async def test_run_all_returns_empty_when_no_accounts():
    settings = _settings(sync_poll_all_mailboxes=True)
    pipeline = ScheduledPipeline(settings, email_service=MagicMock(), repository=MagicMock())
    pipeline.list_poll_accounts = AsyncMock(return_value=[])

    result = await pipeline.run_all()

    assert result["accounts_total"] == 0
    assert result["accounts_succeeded"] == 0
    assert result["results"] == {}
    pipeline.repository.connect.assert_not_called()


@pytest.mark.asyncio
async def test_run_single_account_requires_target_email():
    settings = _settings(sync_target_email=None)
    pipeline = ScheduledPipeline(settings, email_service=MagicMock(), repository=MagicMock())

    with pytest.raises(ValueError, match="SYNC_TARGET_EMAIL"):
        await pipeline.run()


@pytest.mark.asyncio
@patch("app.services.scheduled_pipeline.llm_configured", return_value=False)
async def test_run_single_account_uses_target_email(mock_llm_configured):
    settings = _settings(sync_target_email="info@example.com", sync_poll_all_mailboxes=False)
    pipeline = ScheduledPipeline(settings, email_service=MagicMock(), repository=MagicMock())
    pipeline._run_for_account = AsyncMock(
        return_value={"account": "info@example.com", "sync": {"fetched": 3}}
    )
    mock_conn = MagicMock()
    mock_conn.close = AsyncMock()
    pipeline.repository.connect = AsyncMock(return_value=mock_conn)

    result = await pipeline.run(skip_analysis=True)

    pipeline._run_for_account.assert_awaited_once_with(
        mock_conn,
        "info@example.com",
        skip_analysis=True,
        process_all=False,
    )
    assert result["account"] == "info@example.com"
    mock_conn.close.assert_awaited_once()
