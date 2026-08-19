from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.classification_rules import (
    CategoryRule,
    ClassificationConfig,
    ClassificationRules,
    load_classification_rules,
    mailbox_payload_to_rules,
    merge_classification_rules,
    resolve_rule_folder,
    save_mailbox_classification_rules,
)


def _category(**overrides) -> dict:
    data = {
        "slug": "billing",
        "display_name": "Billing",
        "classification_hints": "Invoices",
        "folder": "Billing",
        "forward_to": "billing@example.com",
        "send_ack": True,
        "needs_live_agent": False,
        "is_spam": False,
        "route_by_person": False,
        "skip_forward": False,
        "sort_order": 40,
        "enabled": True,
    }
    data.update(overrides)
    return data


def _global_payload(**overrides) -> dict:
    data = {
        "config": {
            "spam_folder": "Junk",
            "default_forward": "info@example.com",
            "ack_template": "",
            "classification_instructions": "Mark phishing as spam.",
        },
        "categories": [
            _category(
                slug="spam",
                display_name="Spam",
                classification_hints="Phishing",
                folder="Junk",
                forward_to=None,
                is_spam=True,
                skip_forward=True,
                sort_order=10,
            )
        ],
        "employees": [],
        "updated_at": None,
    }
    data.update(overrides)
    return data


def test_merge_combines_global_spam_with_inbox_categories():
    global_rules = ClassificationRules.from_api_dict(_global_payload())
    mailbox_rules = mailbox_payload_to_rules(
        {
            "extra_instructions": "Prefer Orders for SKUs.",
            "default_forward": "orders@example.com",
            "categories": [_category(slug="orders", display_name="Orders", folder="Orders")],
        }
    )
    merged = merge_classification_rules(global_rules, mailbox_rules)
    assert [c.slug for c in merged.categories] == ["spam", "orders"]
    assert merged.config.spam_folder == "Junk"
    assert merged.config.default_forward == "orders@example.com"
    assert "Mark phishing as spam." in merged.config.classification_instructions
    assert "Prefer Orders for SKUs." in merged.config.classification_instructions
    prompt = merged.build_classification_prompt()
    assert "**spam**" in prompt
    assert "**orders**" in prompt


def test_merge_drops_mailbox_spam_categories():
    global_rules = ClassificationRules.from_api_dict(_global_payload())
    mailbox_rules = mailbox_payload_to_rules(
        {
            "categories": [
                _category(slug="junk", is_spam=True, folder="Junk"),
                _category(slug="billing"),
            ]
        }
    )
    merged = merge_classification_rules(global_rules, mailbox_rules)
    assert [c.slug for c in merged.categories] == ["spam", "billing"]


def test_fallback_skips_spam_when_general_missing():
    rules = ClassificationRules(
        config=ClassificationConfig(),
        categories=[
            CategoryRule(
                slug="spam",
                display_name="Spam",
                classification_hints="",
                folder="Junk",
                is_spam=True,
                sort_order=10,
            ),
            CategoryRule(
                slug="billing",
                display_name="Billing",
                classification_hints="",
                folder="Billing",
                sort_order=20,
            ),
        ],
    )
    fallback = rules.fallback_category()
    assert fallback is not None
    assert fallback.slug == "billing"


def test_resolve_rule_folder_uses_global_spam_folder():
    rules = ClassificationRules.from_api_dict(_global_payload())
    assert resolve_rule_folder(rules, "spam") == "Junk"


def test_resolve_rule_folder_ignores_non_spam_categories():
    rules = merge_classification_rules(
        ClassificationRules.from_api_dict(_global_payload()),
        mailbox_payload_to_rules(
            {
                "categories": [
                    _category(slug="platform_notification", folder="Platform Notifications")
                ]
            }
        ),
    )
    assert resolve_rule_folder(rules, "platform_notification") is None


def test_resolve_rule_folder_skips_missing_inbox_category():
    rules = ClassificationRules.from_api_dict(_global_payload())
    assert resolve_rule_folder(rules, "undelivered") is None
    assert resolve_rule_folder(None, "spam") is None
    assert resolve_rule_folder(rules, None) is None


@pytest.mark.asyncio
async def test_load_classification_rules_seeds_empty_mailbox():
    repository = AsyncMock()
    repository.get_global_classification_rules.return_value = _global_payload()
    repository.get_mailbox_classification_rules.return_value = {
        "account": "info@example.com",
        "extra_instructions": "",
        "default_forward": None,
        "categories": [],
        "updated_at": None,
    }
    repository.seed_mailbox_classification_rules.return_value = {
        "account": "info@example.com",
        "extra_instructions": "",
        "default_forward": "info@example.com",
        "categories": [_category()],
        "updated_at": None,
    }

    rules = await load_classification_rules(repository, account="info@example.com")

    repository.seed_mailbox_classification_rules.assert_awaited_once()
    assert {c.slug for c in rules.categories} == {"spam", "billing"}
    repository.save_global_classification_rules.assert_not_called()


@pytest.mark.asyncio
async def test_load_classification_rules_does_not_seed_configured_mailbox():
    repository = AsyncMock()
    repository.get_global_classification_rules.return_value = _global_payload()
    repository.get_mailbox_classification_rules.return_value = {
        "account": "hr@example.com",
        "extra_instructions": "Jobs go to HR.",
        "default_forward": "hr@example.com",
        "categories": [_category(slug="careers", folder="Human Resources")],
        "updated_at": None,
    }

    rules = await load_classification_rules(repository, account="hr@example.com")

    repository.seed_mailbox_classification_rules.assert_not_called()
    assert {c.slug for c in rules.categories} == {"spam", "careers"}
    assert rules.config.default_forward == "hr@example.com"


@pytest.mark.asyncio
async def test_load_without_account_returns_global_only():
    repository = AsyncMock()
    repository.get_global_classification_rules.return_value = _global_payload()

    rules = await load_classification_rules(repository)

    repository.get_mailbox_classification_rules.assert_not_called()
    assert [c.slug for c in rules.categories] == ["spam"]


@pytest.mark.asyncio
async def test_save_mailbox_does_not_touch_global():
    repository = AsyncMock()
    repository.save_mailbox_classification_rules.return_value = {
        "account": "info@example.com",
        "extra_instructions": "",
        "default_forward": None,
        "categories": [_category()],
        "updated_at": None,
    }

    saved = await save_mailbox_classification_rules(
        repository,
        "info@example.com",
        {"categories": [_category()], "extra_instructions": ""},
    )

    repository.save_mailbox_classification_rules.assert_awaited_once()
    repository.save_global_classification_rules.assert_not_called()
    assert saved["account"] == "info@example.com"


def test_action_pipeline_loads_rules_by_account():
    from app.services import action_pipeline as pipeline_mod

    source = pipeline_mod.run_action_pipeline.__code__.co_names
    assert "load_classification_rules" in source
    text = open(pipeline_mod.__file__, encoding="utf-8").read()
    assert 'account=state.get("user_email")' in text
