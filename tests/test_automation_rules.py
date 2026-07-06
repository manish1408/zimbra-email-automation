from __future__ import annotations

import pytest

from app.services.automation_rules import (
    evaluate_message,
    load_automation_rules,
    parse_email_address,
)
from app.services.shopify.order_reference import extract_order_reference


@pytest.fixture
def rules():
    return load_automation_rules()


def test_parse_email_address_from_display():
    assert (
        parse_email_address('"GK Hair ." <no-reply@gkhair.com>')
        == "no-reply@gkhair.com"
    )


def test_mailer_daemon_moves_to_undelivered(rules):
    message = {
        "from": "MAILER-DAEMON@mail-tibolli.vantibolli.com",
        "subject": "Undelivered",
    }
    result = evaluate_message(message, rules)
    assert result.matched
    assert result.rule_id == "mailer_daemon_undelivered"
    assert result.move_to_folder == "Undelivered"
    assert result.skip_llm


def test_gk_noreply_no_action(rules):
    message = {"from": '"GK Hair ." <no-reply@gkhair.com>', "subject": "Receipt"}
    result = evaluate_message(message, rules)
    assert result.matched
    assert result.no_action
    assert result.skip_llm
    assert result.move_to_folder is None


def test_facebook_platform_notifications(rules):
    message = {
        "from": '"Inspired Hair on Facebook" <notification@facebookmail.com>',
        "subject": "New comment",
    }
    result = evaluate_message(message, rules)
    assert result.matched
    assert result.move_to_folder == "Platform Notifications"


def test_shopify_audiences_platform(rules):
    message = {
        "from": '"Shopify Audiences" <no-reply-audiences@shopify.com>',
        "subject": "Audience update",
    }
    result = evaluate_message(message, rules)
    assert result.matched
    assert result.move_to_folder == "Platform Notifications"


def test_postscript_platform(rules):
    message = {
        "from": (
            '"conversations+651824709=mg postscriptapp com" '
            "<conversations+651824709=mg.postscriptapp.com@postscript.io>"
        ),
        "subject": "SMS",
    }
    result = evaluate_message(message, rules)
    assert result.matched
    assert result.move_to_folder == "Platform Notifications"


def test_didww_platform(rules):
    message = {"from": "sms-forwarding@didww.com", "subject": "SMS forward"}
    result = evaluate_message(message, rules)
    assert result.matched
    assert result.move_to_folder == "Platform Notifications"


def test_no_match_customer_email(rules):
    message = {"from": "customer@example.com", "subject": "Help"}
    result = evaluate_message(message, rules)
    assert not result.matched


def test_extract_reference_from_current():
    result = extract_order_reference(
        "Where is order GKUS77914?",
        "",
    )
    assert result.reference == "GKUS77914"
    assert result.source == "current"
    assert not result.ambiguous


def test_extract_reference_missing():
    result = extract_order_reference("Where is my order?", "")
    assert result.reference is None
    assert result.confidence == "none"


def test_extract_reference_ambiguous():
    result = extract_order_reference(
        "Status for GKUS111 and GKUS222?",
        "",
    )
    assert result.ambiguous
    assert result.reference is None


def test_extract_reference_from_history():
    result = extract_order_reference(
        "Any update?",
        "My order is GKUS55555",
    )
    assert result.reference == "GKUS55555"
    assert result.source == "history"
