"""Sales / promotion / marketing spam detection policy.

The LLM is instructed to treat unsolicited selling and marketing as spam.
Code then enforces a confidence threshold before moving mail to Junk.
"""

from __future__ import annotations

from typing import Any, Mapping

# Always injected into the classify prompt (not only DB instructions).
SALES_MARKETING_SPAM_POLICY = """
## Sales / promotion / marketing → spam
Analyze the sender, subject, and body together. Use judgment — do not rely on a single keyword.

Mark is_spam=true and category=spam when you are confident the email is primarily:
- trying to sell a product or service to the recipient
- promoting the sender's products, services, agency, SaaS, tools, ads platform, or offerings
- cold outreach / "partnership" / "collaboration" pitches that are really sales
- marketing newsletters, promo blasts, catalogs, demos, webinars, or "book a call" pitches
- vendor/brand promotional content (sales, discounts, new features, ad products)

Set confidence to reflect how sure you are (typically ≥ 0.75 for clear sales/marketing).
Do NOT use category=marketing for these — use spam so they go to Junk.
Do NOT generate a reply draft for spam.

Do NOT mark as spam when:
- a customer or prospect is asking about GK Hair products, orders, invoices, or support
- the message is transactional (shipping, invoices, password resets, account alerts for tools we use)
- it is genuine personal/business correspondence that is not a sales pitch
""".strip()

# Categories that mean "this is promotional / should be Junk" when confidence is high.
SPAM_LIKE_CATEGORIES = frozenset({"spam", "marketing"})


def apply_spam_confidence_policy(
    classification: Mapping[str, Any],
    *,
    threshold: float,
    spam_slug: str = "spam",
) -> dict[str, Any]:
    """Apply confidence-gated spam marking for sales/marketing-like classifications."""
    copy = dict(classification)
    try:
        confidence = float(copy.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    copy["confidence"] = confidence

    slug = str(copy.get("category") or "").strip().lower()
    model_flags_spam = bool(copy.get("is_spam")) or slug in SPAM_LIKE_CATEGORIES

    if model_flags_spam and confidence >= threshold:
        copy["is_spam"] = True
        copy["category"] = spam_slug
        copy["needs_response_generation"] = False
        copy["needs_forwarding"] = False
        copy["needs_live_agent"] = False
        reasoning = str(copy.get("reasoning") or "").strip()
        marker = "sales/marketing spam policy"
        if marker not in reasoning.lower():
            note = (
                f"Marked spam by {marker} "
                f"(confidence={confidence:.2f} ≥ {threshold:.2f})."
            )
            copy["reasoning"] = f"{reasoning} {note}".strip() if reasoning else note
        return copy

    if bool(copy.get("is_spam")) and confidence < threshold:
        copy["is_spam"] = False
        if slug == spam_slug.lower() or slug == "marketing":
            copy["category"] = "general"
        reasoning = str(copy.get("reasoning") or "").strip()
        note = (
            f"Spam not applied; confidence={confidence:.2f} "
            f"below threshold {threshold:.2f}."
        )
        copy["reasoning"] = f"{reasoning} {note}".strip() if reasoning else note

    return copy
