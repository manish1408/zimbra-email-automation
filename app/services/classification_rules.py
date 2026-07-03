from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.email_repository import EmailRepository


@dataclass
class CategoryRule:
    slug: str
    display_name: str
    classification_hints: str
    folder: str
    forward_to: str | None = None
    send_ack: bool = True
    needs_live_agent: bool = False
    is_spam: bool = False
    route_by_person: bool = False
    skip_forward: bool = False
    sort_order: int = 0
    enabled: bool = True


@dataclass
class ClassificationConfig:
    spam_folder: str = "Junk"
    default_forward: str | None = None
    ack_template: str = ""
    classification_instructions: str = ""


@dataclass
class ClassificationEmployee:
    id: int | None
    name: str
    email: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class ClassificationRules:
    config: ClassificationConfig
    categories: list[CategoryRule] = field(default_factory=list)
    employees: list[ClassificationEmployee] = field(default_factory=list)
    updated_at: str | None = None

    def enabled_categories(self) -> list[CategoryRule]:
        return sorted(
            [c for c in self.categories if c.enabled],
            key=lambda c: c.sort_order,
        )

    def get_category(self, slug: str) -> CategoryRule | None:
        for category in self.categories:
            if category.slug == slug and category.enabled:
                return category
        return None

    def fallback_category(self) -> CategoryRule | None:
        return self.get_category("general") or (
            self.enabled_categories()[0] if self.enabled_categories() else None
        )

    def employee_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for employee in self.employees:
            names = [employee.name, *employee.aliases]
            for name in names:
                if name:
                    index[str(name).strip().lower()] = employee.email
        return index

    def build_classification_prompt(self) -> str:
        lines = [
            "Classify each email using exactly one category slug from the list below.",
            "For every message return: category (slug), is_spam, confidence, "
            "requested_person, needs_live_agent, reasoning, thread summary fields, "
            "and draft_reply_text when needs_live_agent is true (otherwise null).",
            "",
        ]
        instructions = (self.config.classification_instructions or "").strip()
        if instructions:
            lines.extend([instructions, ""])

        lines.append("Categories:")
        for category in self.enabled_categories():
            lines.append(f"- **{category.slug}** ({category.display_name}): {category.classification_hints}")
            actions: list[str] = [f"folder={category.folder}"]
            if category.is_spam:
                actions.append("is_spam=true")
            if category.skip_forward or category.is_spam:
                actions.append("no forward")
            elif category.forward_to:
                actions.append(f"forward={category.forward_to}")
            elif self.config.default_forward:
                actions.append(f"forward default={self.config.default_forward}")
            if category.route_by_person:
                actions.append("resolve person from requested_person")
            if category.needs_live_agent:
                actions.append("needs_live_agent=true")
            if not category.send_ack:
                actions.append("no acknowledgement")
            lines.append(f"  Actions when matched: {', '.join(actions)}.")

        return "\n".join(lines)

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> ClassificationRules:
        config_data = data.get("config") or {}
        config = ClassificationConfig(
            spam_folder=config_data.get("spam_folder") or "Junk",
            default_forward=config_data.get("default_forward"),
            ack_template=config_data.get("ack_template") or "",
            classification_instructions=config_data.get("classification_instructions") or "",
        )
        categories = [
            CategoryRule(
                slug=item["slug"],
                display_name=item["display_name"],
                classification_hints=item.get("classification_hints") or "",
                folder=item["folder"],
                forward_to=item.get("forward_to"),
                send_ack=bool(item.get("send_ack", True)),
                needs_live_agent=bool(item.get("needs_live_agent", False)),
                is_spam=bool(item.get("is_spam", False)),
                route_by_person=bool(item.get("route_by_person", False)),
                skip_forward=bool(item.get("skip_forward", False)),
                sort_order=int(item.get("sort_order") or 0),
                enabled=bool(item.get("enabled", True)),
            )
            for item in data.get("categories") or []
        ]
        employees = [
            ClassificationEmployee(
                id=item.get("id"),
                name=item["name"],
                email=item["email"],
                aliases=list(item.get("aliases") or []),
            )
            for item in data.get("employees") or []
        ]
        return cls(
            config=config,
            categories=categories,
            employees=employees,
            updated_at=data.get("updated_at"),
        )

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "config": {
                "spam_folder": self.config.spam_folder,
                "default_forward": self.config.default_forward,
                "ack_template": self.config.ack_template,
                "classification_instructions": self.config.classification_instructions,
            },
            "categories": [
                {
                    "slug": c.slug,
                    "display_name": c.display_name,
                    "classification_hints": c.classification_hints,
                    "folder": c.folder,
                    "forward_to": c.forward_to,
                    "send_ack": c.send_ack,
                    "needs_live_agent": c.needs_live_agent,
                    "is_spam": c.is_spam,
                    "route_by_person": c.route_by_person,
                    "skip_forward": c.skip_forward,
                    "sort_order": c.sort_order,
                    "enabled": c.enabled,
                }
                for c in sorted(self.categories, key=lambda x: x.sort_order)
            ],
            "employees": [
                {
                    "id": e.id,
                    "name": e.name,
                    "email": e.email,
                    "aliases": e.aliases,
                }
                for e in self.employees
            ],
            "updated_at": self.updated_at,
        }


async def load_classification_rules(
    repository: EmailRepository, conn: Any | None = None
) -> ClassificationRules:
    data = await repository.get_classification_rules(conn)
    return ClassificationRules.from_api_dict(data)


async def save_classification_rules(
    repository: EmailRepository,
    rules: ClassificationRules,
    conn: Any | None = None,
) -> ClassificationRules:
    data = await repository.save_classification_rules(rules.to_api_dict(), conn)
    return ClassificationRules.from_api_dict(data)
