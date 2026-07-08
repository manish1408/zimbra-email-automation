from __future__ import annotations

from app.agents.state import MessageClassification
from app.services.classification_rules import CategoryRule, ClassificationRules
from app.services.email_sync import EmailSyncService


class RoutingResolver:
    """Map LLM classifications to folders, forwards, and ack/draft behavior."""

    DRAFT_REPLY_CATEGORIES = frozenset({"customer_support", "orders"})

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
        if classification.get("is_spam"):
            return None

        category_slug = classification["category"]
        rule = self.resolve_category_rule(category_slug)
        if not rule:
            return self.rules.config.default_forward

        if rule.skip_forward:
            return None

        if rule.route_by_person:
            person = (classification.get("requested_person") or "").strip()
            if person:
                email = self._lookup_employee(person)
                if email:
                    return email
                if self.email_service:
                    gal = await self.email_service.autocomplete_person(account, person)
                    if gal:
                        return gal[0]
            return self.rules.config.default_forward

        return rule.forward_to or self.rules.config.default_forward

    def folder_for_classification(self, classification: MessageClassification) -> str:
        if classification.get("is_spam"):
            return self.rules.config.spam_folder
        rule = self.resolve_category_rule(classification["category"])
        if rule:
            return rule.folder
        fallback = self.rules.fallback_category()
        return fallback.folder if fallback else self.rules.config.spam_folder

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
        if classification.get("is_spam"):
            return False
        if "needs_forwarding" in classification:
            return bool(classification.get("needs_forwarding"))
        rule = self.resolve_category_rule(classification.get("category", ""))
        if rule and rule.skip_forward:
            return False
        return not classification.get("is_spam")

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
