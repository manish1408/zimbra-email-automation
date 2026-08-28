from __future__ import annotations

from app.agents.state import MessageClassification
from app.services.classification_rules import CategoryRule, ClassificationRules
from app.services.email_sync import EmailSyncService


class RoutingResolver:
    """Map LLM classifications to folders, forwards, and ack/draft behavior."""

    DRAFT_REPLY_CATEGORIES = frozenset({"customer_support", "orders", "careers"})

    def __init__(
        self,
        email_service: EmailSyncService | None = None,
        rules: ClassificationRules | None = None,
    ):
        if not rules:
            raise ValueError("Classification rules are required")
        self.email_service = email_service
        self.rules = rules

    def resolve_category_rule(self, category_slug: str) -> CategoryRule | None:
        return self.rules.get_category(category_slug)

    async def resolve_forward_target(
        self,
        classification: MessageClassification,
        account: str,
    ) -> str | None:
        # Email forwarding/routing is disabled for all categories.
        return None

    def folder_for_classification(self, classification: MessageClassification) -> str | None:
        if classification.get("is_spam"):
            return self.rules.config.spam_folder or "Junk"
        rule = self.resolve_category_rule(classification.get("category", ""))
        if rule and rule.is_spam:
            return self.rules.config.spam_folder or "Junk"
        return None

    def should_draft_reply(self, classification: MessageClassification) -> bool:
        if classification.get("is_spam"):
            return False
        if classification.get("needs_response_generation"):
            return True
        slug = str(classification.get("category") or "")
        if slug in self.DRAFT_REPLY_CATEGORIES:
            return True
        if classification.get("needs_live_agent"):
            return True
        rule = self.resolve_category_rule(slug)
        return rule.needs_live_agent if rule else False

    def should_forward(self, classification: MessageClassification) -> bool:
        # Email forwarding/routing is disabled.
        return False

    def _lookup_employee(self, name: str) -> str | None:
        return self.rules.employee_index().get(name.strip().lower())

    async def resolve_routes_async(
        self,
        classifications: list[MessageClassification],
        account: str,
    ) -> list[MessageClassification]:
        updated: list[MessageClassification] = []
        for item in classifications:
            copy = dict(item)
            copy["route_target"] = await self.resolve_forward_target(copy, account)
            updated.append(MessageClassification(**copy))
        return updated

    def normalize_classification(
        self, classification: MessageClassification
    ) -> MessageClassification:
        copy = dict(classification)
        slug = str(copy.get("category") or "").strip()
        rule = self.resolve_category_rule(slug)
        if not rule:
            fallback = self.rules.fallback_category()
            if fallback:
                copy["category"] = fallback.slug
                rule = fallback
        if rule and rule.is_spam:
            copy["is_spam"] = True
        return MessageClassification(**copy)
