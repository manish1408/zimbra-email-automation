from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.agents.state import EmailCategory, MessageClassification
from app.config import Settings
from app.services.email_sync import EmailSyncService


@dataclass
class CategoryRule:
    folder: str
    forward_to: str | None = None
    send_ack: bool = True
    needs_live_agent: bool = False


@dataclass
class RoutingRules:
    spam_folder: str = "Junk"
    default_forward: str = "info@gkhair.com"
    ack_template: str = ""
    categories: dict[str, CategoryRule] = field(default_factory=dict)


def load_routing_rules(path: str | Path) -> RoutingRules:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    categories: dict[str, CategoryRule] = {}
    for name, rule in (data.get("categories") or {}).items():
        if not isinstance(rule, dict):
            continue
        categories[name] = CategoryRule(
            folder=rule.get("folder", name.title()),
            forward_to=rule.get("forward_to"),
            send_ack=bool(rule.get("send_ack", True)),
            needs_live_agent=bool(rule.get("needs_live_agent", False)),
        )
    return RoutingRules(
        spam_folder=data.get("spam_folder", "Junk"),
        default_forward=data.get("default_forward", "info@gkhair.com"),
        ack_template=data.get("ack_template", "").strip(),
        categories=categories,
    )


def load_employees(path: str | Path) -> dict[str, str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    index: dict[str, str] = {}
    for _key, entry in (data.get("employees") or {}).items():
        if not isinstance(entry, dict):
            continue
        email = entry.get("email")
        if not email:
            continue
        names = [entry.get("name"), _key, *(entry.get("aliases") or [])]
        for name in names:
            if name:
                index[str(name).strip().lower()] = email
    return index


class RoutingResolver:
    def __init__(
        self,
        settings: Settings,
        email_service: EmailSyncService | None = None,
        rules: RoutingRules | None = None,
        employees: dict[str, str] | None = None,
    ):
        self.settings = settings
        self.email_service = email_service
        self.rules = rules or load_routing_rules(settings.routing_rules_path)
        self.employees = employees or load_employees(settings.employees_path)

    def resolve_category_rule(self, category: EmailCategory) -> CategoryRule:
        rule = self.rules.categories.get(category)
        if rule:
            return rule
        return CategoryRule(
            folder="General",
            forward_to=self.rules.default_forward,
            send_ack=True,
        )

    async def resolve_forward_target(
        self,
        classification: MessageClassification,
        account: str,
    ) -> str | None:
        if classification.get("is_spam"):
            return None

        category = classification["category"]
        rule = self.resolve_category_rule(category)

        if category == "person_request":
            person = (classification.get("requested_person") or "").strip()
            if person:
                email = self._lookup_employee(person)
                if email:
                    return email
                if self.email_service:
                    gal = await self.email_service.autocomplete_person(account, person)
                    if gal:
                        return gal[0]
            return self.rules.default_forward

        if category == "marketing":
            return None

        return rule.forward_to or self.rules.default_forward

    def folder_for_classification(self, classification: MessageClassification) -> str:
        if classification.get("is_spam"):
            return self.rules.spam_folder
        rule = self.resolve_category_rule(classification["category"])
        return rule.folder

    def should_send_ack(self, classification: MessageClassification) -> bool:
        if classification.get("is_spam"):
            return False
        rule = self.resolve_category_rule(classification["category"])
        return rule.send_ack

    def should_draft_reply(self, classification: MessageClassification) -> bool:
        if classification.get("is_spam"):
            return False
        if classification.get("needs_live_agent"):
            return True
        rule = self.resolve_category_rule(classification["category"])
        return rule.needs_live_agent

    def _lookup_employee(self, name: str) -> str | None:
        return self.employees.get(name.strip().lower())

    def apply_route_targets(
        self, classifications: list[MessageClassification]
    ) -> list[MessageClassification]:
        """Sync helper — sets route_target without GAL (person uses employee file only)."""
        updated: list[MessageClassification] = []
        for item in classifications:
            copy = dict(item)
            if copy.get("is_spam"):
                copy["route_target"] = None
            elif copy["category"] == "person_request":
                person = (copy.get("requested_person") or "").strip()
                copy["route_target"] = (
                    self._lookup_employee(person) if person else None
                ) or self.rules.default_forward
            elif copy["category"] == "marketing":
                copy["route_target"] = None
            else:
                rule = self.resolve_category_rule(copy["category"])
                copy["route_target"] = rule.forward_to or self.rules.default_forward
            updated.append(MessageClassification(**copy))
        return updated

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
