from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_FROM_EMAIL_RE = re.compile(r"<([^>]+)>")
_EMAIL_ONLY_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass
class AutomationRuleMatch:
    from_address: str | None = None
    from_address_regex: str | None = None
    to_address: str | None = None
    subject_regex: str | None = None
    header_contains: str | None = None


@dataclass
class AutomationRuleActions:
    move_to_folder: str | None = None
    no_action: bool = False
    skip_llm: bool = False
    mark_analyzed: bool = True
    set_category: str | None = None


@dataclass
class AutomationRule:
    id: str
    enabled: bool
    priority: int
    match: AutomationRuleMatch
    actions: AutomationRuleActions


@dataclass
class AutomationRules:
    rules: list[AutomationRule] = field(default_factory=list)

    def enabled_rules(self) -> list[AutomationRule]:
        return sorted(
            [r for r in self.rules if r.enabled],
            key=lambda r: r.priority,
        )


@dataclass
class RuleEvaluationResult:
    matched: bool = False
    rule_id: str | None = None
    no_action: bool = False
    skip_llm: bool = False
    mark_analyzed: bool = False
    move_to_folder: str | None = None
    set_category: str | None = None


def parse_email_address(raw: str | None) -> str | None:
    """Extract email from From header value."""
    if not raw:
        return None
    text = raw.strip()
    angle = _FROM_EMAIL_RE.search(text)
    if angle:
        return angle.group(1).strip().lower()
    if _EMAIL_ONLY_RE.match(text):
        return text.lower()
    return text.lower() if "@" in text else None


def load_automation_rules(path: Path | None = None) -> AutomationRules:
    config_path = path or Path(__file__).resolve().parents[2] / "config" / "automation_rules.yaml"
    if not config_path.is_file():
        return AutomationRules()
    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    rules: list[AutomationRule] = []
    for item in data.get("rules") or []:
        match_data = item.get("match") or {}
        actions_data = item.get("actions") or {}
        rules.append(
            AutomationRule(
                id=str(item["id"]),
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority") or 100),
                match=AutomationRuleMatch(
                    from_address=_norm(match_data.get("from_address")),
                    from_address_regex=match_data.get("from_address_regex"),
                    to_address=_norm(match_data.get("to_address")),
                    subject_regex=match_data.get("subject_regex"),
                    header_contains=match_data.get("header_contains"),
                ),
                actions=AutomationRuleActions(
                    move_to_folder=actions_data.get("move_to_folder"),
                    no_action=bool(actions_data.get("no_action", False)),
                    skip_llm=bool(actions_data.get("skip_llm", False)),
                    mark_analyzed=bool(actions_data.get("mark_analyzed", True)),
                    set_category=actions_data.get("set_category"),
                ),
            )
        )
    return AutomationRules(rules=rules)


def _norm(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def _matches_rule(message: dict[str, Any], rule: AutomationRule) -> bool:
    match = rule.match
    from_raw = message.get("from") or message.get("from_address")
    from_email = parse_email_address(str(from_raw) if from_raw else None)

    if match.from_address and from_email != match.from_address.lower():
        return False
    if match.from_address_regex and from_email:
        if not re.search(match.from_address_regex, from_email, re.IGNORECASE):
            return False
    elif match.from_address_regex and not from_email:
        return False

    if match.to_address:
        to_addrs = message.get("to") or message.get("to_addresses") or []
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]
        normalized = {parse_email_address(str(t)) for t in to_addrs}
        if match.to_address.lower() not in normalized:
            return False

    subject = str(message.get("subject") or "")
    if match.subject_regex and not re.search(match.subject_regex, subject, re.IGNORECASE):
        return False

    if match.header_contains:
        haystack = f"{from_raw or ''}\n{subject}\n{message.get('body') or message.get('fragment') or ''}"
        if match.header_contains.lower() not in haystack.lower():
            return False

    return bool(
        match.from_address
        or match.from_address_regex
        or match.to_address
        or match.subject_regex
        or match.header_contains
    )


def evaluate_message(
    message: dict[str, Any],
    rules: AutomationRules,
) -> RuleEvaluationResult:
    for rule in rules.enabled_rules():
        if not _matches_rule(message, rule):
            continue
        actions = rule.actions
        return RuleEvaluationResult(
            matched=True,
            rule_id=rule.id,
            no_action=actions.no_action,
            skip_llm=actions.skip_llm,
            mark_analyzed=actions.mark_analyzed,
            move_to_folder=actions.move_to_folder,
            set_category=actions.set_category,
        )
    return RuleEvaluationResult()
