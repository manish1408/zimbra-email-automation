from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.models.schemas import MessageSearchResponse
from app.services.email_sync import EmailSyncService
from app.services.zimbra.mail_client import ZimbraMessage


@pytest.mark.asyncio
async def test_search_mailbox_uses_direct_lookup_for_message_id():
    service = EmailSyncService(Settings())
    message = ZimbraMessage(
        id="203684",
        subject="picking this back up",
        from_address="sender@example.com",
        to_addresses=["gk07@gkhair.com"],
        date="2026-08-31T13:52:04+00:00",
        fragment="Hello",
        account="gk07@gkhair.com",
    )

    service.admin = AsyncMock()
    service.admin.delegate_auth = AsyncMock(return_value="token")
    service.mail = AsyncMock()
    service.mail.get_message = AsyncMock(return_value=message)
    service.mail.search_messages = AsyncMock()

    result = await service.search_user_messages(
        user_email="gk07@gkhair.com",
        query="203684",
        limit=50,
        offset=0,
    )

    assert isinstance(result, MessageSearchResponse)
    assert result.total == 1
    assert len(result.messages) == 1
    assert result.messages[0].id == "203684"
    service.mail.get_message.assert_awaited_once_with(
        auth_token="token",
        account_name="gk07@gkhair.com",
        message_id="203684",
    )
    service.mail.search_messages.assert_not_called()


@pytest.mark.asyncio
async def test_search_mailbox_falls_back_to_zimbra_search_for_text_query():
    service = EmailSyncService(Settings())

    service.admin = AsyncMock()
    service.admin.delegate_auth = AsyncMock(return_value="token")
    service.mail = AsyncMock()
    service.mail.search_messages = AsyncMock(return_value=([], False, 0))

    await service.search_user_messages(
        user_email="gk07@gkhair.com",
        query="subject:invoice",
        limit=50,
        offset=0,
    )

    service.mail.get_message.assert_not_called()
    service.mail.search_messages.assert_awaited_once()
