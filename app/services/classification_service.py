from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import MessageClassification
from app.config import Settings
from app.services.agent_training import augment_system_prompt
from app.services.classification_rules import ClassificationRules
from app.services.llm import ainvoke_structured, create_chat_llm, llm_configured
from app.services.routing import RoutingResolver

logger = logging.getLogger(__name__)


@dataclass
class ClassifyBatchResult:
    classifications: list[MessageClassification] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


class ClassificationItem(BaseModel):
    message_id: str
    subject: str | None = None
    category: str
    is_spam: bool = False
    is_invoice_question: bool = False
    is_order_status_question: bool = False
    needs_response_generation: bool = False
    needs_forwarding: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    requested_person: str | None = None
    needs_live_agent: bool = False
    reasoning: str = ""


class ClassificationBatch(BaseModel):
    analyses: list[ClassificationItem]


def _message_body(message: dict[str, Any]) -> str:
    return str(message.get("body") or message.get("fragment") or "").strip()


class ClassificationService:
    """Step 1: slim classify LLM — subject + body only."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            if not llm_configured(self.settings):
                raise ValueError("LLM is not configured")
            self._llm = create_chat_llm(self.settings, temperature=0.15)
        return self._llm

    async def classify_batch(
        self,
        messages: list[dict[str, Any]],
        classification_rules: ClassificationRules,
        agent_training: str | None = None,
    ) -> ClassifyBatchResult:
        if not messages:
            return ClassifyBatchResult()

        timeout = self.settings.vastai_timeout_seconds
        classifications: list[MessageClassification] = []
        errors: list[dict[str, str]] = []

        for message in messages:
            msg_id = str(message.get("id", ""))
            try:
                items = await asyncio.wait_for(
                    self._classify_messages_llm(
                        [message],
                        classification_rules=classification_rules,
                        agent_training=agent_training,
                    ),
                    timeout=timeout,
                )
                classifications.extend(items)
            except asyncio.TimeoutError:
                err = f"LLM classify timed out after {timeout:g}s"
                logger.warning("Message %s: %s", msg_id, err)
                errors.append({"message_id": msg_id, "error": err})
            except httpx.TimeoutException:
                err = f"LLM classify timed out after {timeout:g}s"
                logger.warning("Message %s: %s", msg_id, err)
                errors.append({"message_id": msg_id, "error": err})
            except Exception as exc:
                err = f"LLM classify failed: {exc}"
                logger.warning("Message %s: %s", msg_id, err)
                errors.append({"message_id": msg_id, "error": err})

        return ClassifyBatchResult(classifications=classifications, errors=errors)

    async def _classify_messages_llm(
        self,
        messages: list[dict[str, Any]],
        *,
        classification_rules: ClassificationRules,
        agent_training: str | None = None,
    ) -> list[MessageClassification]:
        resolver = RoutingResolver(rules=classification_rules)
        rules_prompt = classification_rules.build_classification_prompt()
        blocks: list[str] = []
        for message in messages:
            msg_id = str(message.get("id", ""))
            blocks.append(
                "\n".join(
                    [
                        f"### Message id={msg_id}",
                        f"Subject: {message.get('subject') or '(no subject)'}",
                        f"Body:\n{_message_body(message) or '(empty)'}",
                    ]
                )
            )

        prompt = (
            "Classify each email below. Return one analysis per message id.\n"
            "Set is_invoice_question / is_order_status_question when the customer asks "
            "about invoices or order status. Set needs_response_generation when a "
            "reply draft should be written. Set needs_forwarding when the email should "
            "be forwarded to the team.\n\n"
            f"{rules_prompt}\n\n"
            f"Emails:\n\n" + "\n\n".join(blocks)
        )

        system_prompt = augment_system_prompt(
            (
                "You are an email classifier. Use exact category slug values. "
                "Return compact JSON only."
            ),
            agent_training,
        )

        result: ClassificationBatch = await ainvoke_structured(
            self.llm,
            ClassificationBatch,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ],
        )

        by_id = {str(m.get("id")): m for m in messages}
        classifications: list[MessageClassification] = []

        for item in result.analyses:
            msg_id = item.message_id
            row = MessageClassification(
                message_id=msg_id,
                subject=item.subject or by_id.get(msg_id, {}).get("subject"),
                category=item.category,
                is_spam=item.is_spam,
                confidence=item.confidence,
                requested_person=item.requested_person,
                needs_live_agent=item.needs_live_agent,
                reasoning=item.reasoning,
                route_target=None,
                is_invoice_question=item.is_invoice_question,
                is_order_status_question=item.is_order_status_question,
                needs_response_generation=item.needs_response_generation,
                needs_forwarding=item.needs_forwarding,
                automation_source="llm",
                rule_id=None,
            )
            classifications.append(resolver.normalize_classification(row))

        if not classifications and messages:
            fallback = classification_rules.fallback_category()
            for message in messages:
                msg_id = str(message.get("id", ""))
                row = MessageClassification(
                    message_id=msg_id,
                    subject=message.get("subject"),
                    category=fallback.slug if fallback else "unknown",
                    is_spam=False,
                    confidence=0.5,
                    requested_person=None,
                    needs_live_agent=False,
                    reasoning="Default when model returned no items.",
                    route_target=None,
                    is_invoice_question=False,
                    is_order_status_question=False,
                    needs_response_generation=False,
                    needs_forwarding=False,
                    automation_source="llm",
                    rule_id=None,
                )
                classifications.append(resolver.normalize_classification(row))

        return classifications
