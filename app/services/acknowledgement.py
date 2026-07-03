from __future__ import annotations

import re

from app.agents.state import MessageClassification
from app.services.classification_rules import ClassificationRules


def _extract_name(from_address: str | None) -> str:
    if not from_address:
        return "Customer"
    local = from_address.split("@")[0]
    local = re.sub(r"[._+-]+", " ", local).strip()
    if not local:
        return "Customer"
    return local.split()[0].title()


def build_acknowledgement(
    message: dict,
    classification: MessageClassification,
    rules: ClassificationRules,
) -> str:
    template = rules.config.ack_template.strip()
    if not template:
        return ""

    from_addr = message.get("from") or message.get("from_address")
    customer_name = _extract_name(from_addr)
    subject = message.get("subject") or "(no subject)"
    category = classification.get("category", "general")

    body = template
    replacements = {
        "{customer_name}": customer_name,
        "{category}": str(category).replace("_", " "),
        "{reference_subject}": subject,
    }
    for key, value in replacements.items():
        body = body.replace(key, value)
    return body.strip()
