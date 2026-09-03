from __future__ import annotations

from app.services.spam_policy import (
    SALES_MARKETING_SPAM_POLICY,
    apply_spam_confidence_policy,
)


def test_policy_text_covers_sales_and_marketing():
    text = SALES_MARKETING_SPAM_POLICY.lower()
    assert "sell" in text
    assert "marketing" in text
    assert "newsletter" in text
    assert "is_spam=true" in text
    assert "category=spam" in text


def test_high_confidence_marketing_becomes_spam():
    result = apply_spam_confidence_policy(
        {
            "message_id": "1",
            "category": "marketing",
            "is_spam": False,
            "confidence": 0.92,
            "needs_response_generation": True,
            "needs_forwarding": True,
            "reasoning": "Promo newsletter",
        },
        threshold=0.75,
    )
    assert result["is_spam"] is True
    assert result["category"] == "spam"
    assert result["needs_response_generation"] is False
    assert result["needs_forwarding"] is False
    assert "sales/marketing spam policy" in result["reasoning"].lower()


def test_high_confidence_explicit_spam_stays_spam():
    result = apply_spam_confidence_policy(
        {
            "message_id": "1",
            "category": "spam",
            "is_spam": True,
            "confidence": 0.88,
            "reasoning": "Cold pitch",
        },
        threshold=0.75,
    )
    assert result["is_spam"] is True
    assert result["category"] == "spam"


def test_low_confidence_spam_is_not_applied():
    result = apply_spam_confidence_policy(
        {
            "message_id": "1",
            "category": "spam",
            "is_spam": True,
            "confidence": 0.4,
            "reasoning": "Maybe promo",
        },
        threshold=0.75,
    )
    assert result["is_spam"] is False
    assert result["category"] == "general"
    assert "below threshold" in result["reasoning"].lower()


def test_non_spam_categories_unaffected():
    result = apply_spam_confidence_policy(
        {
            "message_id": "1",
            "category": "orders",
            "is_spam": False,
            "confidence": 0.95,
            "needs_response_generation": True,
            "reasoning": "Customer order question",
        },
        threshold=0.75,
    )
    assert result["is_spam"] is False
    assert result["category"] == "orders"
    assert result["needs_response_generation"] is True


def test_informational_newsletter_labeled_general_becomes_spam():
    result = apply_spam_confidence_policy(
        {
            "message_id": "204051",
            "subject": "Liberation Travel Hacks 09/2026 (EN)",
            "category": "general",
            "is_spam": False,
            "confidence": 0.95,
            "reasoning": "The content is a monthly newsletter from Liberation Travel.",
        },
        threshold=0.75,
    )
    assert result["is_spam"] is True
    assert result["category"] == "spam"
    assert "informational newsletter policy" in result["reasoning"].lower()


def test_prompt_includes_sales_marketing_policy():
    from app.services.classification_rules import (
        CategoryRule,
        ClassificationConfig,
        ClassificationRules,
    )

    rules = ClassificationRules(
        config=ClassificationConfig(classification_instructions="Extra note."),
        categories=[
            CategoryRule(
                slug="spam",
                display_name="Spam",
                classification_hints="Junk",
                folder="Junk",
                is_spam=True,
            )
        ],
    )
    prompt = rules.build_classification_prompt()
    assert "Sales / promotion / marketing" in prompt
    assert "Extra note." in prompt
    assert "**spam**" in prompt
