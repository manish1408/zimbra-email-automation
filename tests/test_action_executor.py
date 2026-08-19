from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.state import MessageClassification
from app.config import Settings
from app.services.action_executor import ActionExecutor
from app.services.draft_service import (
    build_shopify_context_payload,
    mailbox_is_direct_to_recipient,
)
from app.services.zimbra.mail_client import ZimbraMessage
from app.services.shopify.order_reference import ReferenceExtractionResult


@pytest.mark.asyncio
async def test_apply_response_draft_calls_save_draft():
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        automation_dry_run=False,
    )
    email_service = AsyncMock()
    email_service.get_raw_message.return_value = None
    email_service.save_draft.return_value = "draft-1"
    email_service.ensure_folder.return_value = "folder-1"
    repository = MagicMock()
    resolver = MagicMock()
    executor = ActionExecutor(settings, email_service, repository, resolver)

    message = {"id": "1", "subject": "Hi", "from": "c@example.com"}
    saved = await executor.apply_response_draft(
        "user@example.com", message, "Thanks for writing."
    )
    assert saved is True
    email_service.save_draft.assert_awaited_once()
    _, kwargs = email_service.save_draft.await_args
    assert kwargs["reply_type"] == "w"
    email_service.ensure_folder.assert_not_awaited()
    email_service.move_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_response_draft_uses_reply_all_recipients():
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        automation_dry_run=False,
    )
    email_service = AsyncMock()
    email_service.save_draft.return_value = "draft-1"
    email_service.ensure_folder.return_value = "folder-1"
    email_service.get_raw_message.return_value = ZimbraMessage(
        id="1",
        subject="Need help",
        from_address="customer@example.com",
        to_addresses=["agent@example.com", "team@example.com"],
        cc_addresses=["manager@example.com"],
        date="2026-07-09T10:00:00Z",
        fragment=None,
        account="agent@example.com",
        body="Original message body",
    )
    repository = MagicMock()
    resolver = MagicMock()
    executor = ActionExecutor(settings, email_service, repository, resolver)

    message = {"id": "1", "subject": "Need help", "from": "customer@example.com"}
    saved = await executor.apply_response_draft(
        "agent@example.com", message, "Thanks for writing."
    )
    assert saved is True
    _, kwargs = email_service.save_draft.await_args
    assert kwargs["to_address"] == "customer@example.com"
    assert kwargs["cc_addresses"] == ["team@example.com", "manager@example.com"]
    assert kwargs["reply_type"] == "w"
    email_service.ensure_folder.assert_not_awaited()
    email_service.move_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_response_draft_skips_move_when_save_draft_has_no_id():
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        automation_dry_run=False,
    )
    email_service = AsyncMock()
    email_service.get_raw_message.return_value = None
    email_service.save_draft.return_value = None
    repository = MagicMock()
    resolver = MagicMock()
    executor = ActionExecutor(settings, email_service, repository, resolver)

    message = {"id": "1", "subject": "Hi", "from": "c@example.com"}
    saved = await executor.apply_response_draft(
        "user@example.com", message, "Thanks for writing."
    )
    assert saved is True
    email_service.ensure_folder.assert_not_awaited()
    email_service.move_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_forward_respects_needs_forwarding_false():
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        automation_dry_run=False,
    )
    email_service = AsyncMock()
    repository = MagicMock()
    resolver = MagicMock()
    resolver.should_forward.return_value = False
    executor = ActionExecutor(settings, email_service, repository, resolver)

    classification = MessageClassification(
        message_id="1",
        category="customer_support",
        is_spam=False,
        confidence=1.0,
        requested_person=None,
        needs_live_agent=False,
        reasoning="",
        route_target="orders@gkhair.com",
        needs_forwarding=False,
    )
    result = await executor.apply_forward(
        "user@example.com",
        "1",
        "orders@gkhair.com",
        classification=classification,
    )
    assert result is None
    email_service.forward_message.assert_not_awaited()


def test_shopify_context_reference_required():
    classification = MessageClassification(
        message_id="1",
        category="orders",
        is_spam=False,
        confidence=1.0,
        requested_person=None,
        needs_live_agent=False,
        reasoning="",
        route_target=None,
        is_order_status_question=True,
        is_invoice_question=False,
        needs_response_generation=True,
        needs_forwarding=False,
    )
    ref = ReferenceExtractionResult()
    payload = build_shopify_context_payload(classification, ref)
    assert payload["outcome"] == "reference_required"


def test_mailbox_is_direct_to_recipient_requires_to_header():
    account = "gk07@gkhair.com"
    assert mailbox_is_direct_to_recipient(
        account,
        {"to": ["gk07@gkhair.com", "orders@gkhair.com"]},
    )
    assert mailbox_is_direct_to_recipient(
        account,
        {"to_addresses": ['"GK Hair" <gk07@gkhair.com>']},
    )
    assert not mailbox_is_direct_to_recipient(
        account,
        {"to": ["orders@gkhair.com"], "cc": ["gk07@gkhair.com"]},
    )
    assert not mailbox_is_direct_to_recipient(
        account,
        {"to": ["meghan.mchugh@gkhair.com"]},
    )
    assert not mailbox_is_direct_to_recipient(account, {"to": []})


def _executor(*, dry_run: bool = False):
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        automation_dry_run=dry_run,
        automation_move_to_folders=True,
    )
    email_service = AsyncMock()
    email_service.ensure_folder.return_value = "junk-id"
    repository = AsyncMock()
    resolver = MagicMock()
    resolver.rules.config.spam_folder = "Junk"
    return (
        ActionExecutor(settings, email_service, repository, resolver),
        email_service,
        repository,
        resolver,
    )


@pytest.mark.asyncio
async def test_rule_folder_move_skips_non_junk():
    executor, email_service, repository, _resolver = _executor()
    moved = await executor.apply_rule_folder_move(
        MagicMock(),
        "user@example.com",
        {"id": "1", "folder": "2"},
        "Billing",
    )
    assert moved is False
    email_service.ensure_folder.assert_not_awaited()
    email_service.move_message.assert_not_awaited()
    repository.update_message_folder.assert_not_awaited()


@pytest.mark.asyncio
async def test_rule_folder_move_junk_creates_and_moves():
    executor, email_service, repository, _resolver = _executor()
    moved = await executor.apply_rule_folder_move(
        MagicMock(),
        "user@example.com",
        {"id": "1", "folder": "2"},
        "Junk",
    )
    assert moved is True
    email_service.ensure_folder.assert_awaited_once_with("user@example.com", "Junk")
    email_service.move_message.assert_awaited_once_with(
        "user@example.com", "1", "junk-id"
    )
    repository.update_message_folder.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_folder_move_skips_non_spam_classification():
    executor, email_service, _repository, resolver = _executor()
    resolver.folder_for_classification.return_value = None
    classification = MessageClassification(
        message_id="1",
        category="billing",
        is_spam=False,
        confidence=1.0,
        requested_person=None,
        needs_live_agent=False,
        reasoning="",
    )
    folder_name, moved = await executor.apply_folder_move(
        MagicMock(),
        "user@example.com",
        {"id": "1"},
        classification,
    )
    assert folder_name is None
    assert moved is False
    email_service.ensure_folder.assert_not_awaited()
