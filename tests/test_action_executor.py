from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.state import MessageClassification
from app.config import Settings
from app.services.action_executor import ActionExecutor
from app.services.draft_service import build_shopify_context_payload
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
    repository = MagicMock()
    resolver = MagicMock()
    executor = ActionExecutor(settings, email_service, repository, resolver)

    message = {"id": "1", "subject": "Hi", "from": "c@example.com"}
    saved = await executor.apply_response_draft(
        "user@example.com", message, "Thanks for writing."
    )
    assert saved is True
    email_service.save_draft.assert_awaited_once()


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
