from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import MessageClassification
from app.config import Settings
from app.services.agent_training import augment_system_prompt
from app.services.email_thread import build_thread_context
from app.services.llm import ainvoke_structured, create_chat_llm, llm_configured
from app.services.shopify.order_reference import ReferenceExtractionResult

logger = logging.getLogger(__name__)


class DraftResult(BaseModel):
    message_id: str
    draft_reply_text: str = Field(min_length=1)


class DraftBatch(BaseModel):
    drafts: list[DraftResult]


class DraftService:
    """Step 2c: conditional draft LLM with thread + optional Shopify context."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            if not llm_configured(self.settings):
                raise ValueError("LLM is not configured")
            self._llm = create_chat_llm(self.settings, temperature=0.2)
        return self._llm

    async def generate_draft(
        self,
        message: dict[str, Any],
        classification: MessageClassification,
        related: list[dict[str, Any]] | None,
        shopify_context: dict[str, Any] | None,
        draft_reply_rules: str | None = None,
        agent_training: str | None = None,
    ) -> str | None:
        context = build_thread_context(message, related)
        shopify_block = ""
        if shopify_context:
            shopify_block = (
                "\n\nShopify lookup context:\n"
                f"{json.dumps(shopify_context, indent=2, default=str)}\n"
            )

        draft_section = ""
        if (draft_reply_rules or "").strip():
            draft_section = f"\n\nDraft reply tone:\n{draft_reply_rules.strip()}\n"

        outcome = (shopify_context or {}).get("outcome")
        instruction = _draft_instruction(classification, outcome)

        prompt = (
            f"{instruction}\n"
            "Write a professional customer reply. Never invent facts.\n"
            f"{draft_section}"
            f"{shopify_block}\n"
            f"Subject: {context['subject']}\n"
            f"CURRENT EMAIL:\n{context['current_text'] or '(empty)'}\n"
            f"PRIOR CONVERSATION:\n{context['history_text'] or '(none)'}\n"
        )

        system_prompt = augment_system_prompt(
            "You write concise, helpful email reply drafts for GK Hair support.",
            agent_training,
        )

        msg_id = str(message.get("id", ""))
        result: DraftBatch = await ainvoke_structured(
            self.llm,
            DraftBatch,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=(
                        f"Message id={msg_id}\n\n{prompt}\n"
                        "Return draft_reply_text for this message id."
                    )
                ),
            ],
        )
        for item in result.drafts:
            if item.message_id == msg_id and item.draft_reply_text.strip():
                return item.draft_reply_text.strip()
        return None


def _draft_instruction(
    classification: MessageClassification,
    outcome: str | None,
) -> str:
    if outcome == "reference_required":
        if classification.get("is_invoice_question"):
            return (
                "The customer wants an invoice but did not provide an order number. "
                "Ask them politely for their GKUS order number (e.g. GKUS12345)."
            )
        return (
            "The customer asked about order status but did not provide an order number. "
            "Ask them politely for their GKUS order number (e.g. GKUS12345)."
        )
    if outcome == "ambiguous_reference":
        return (
            "Multiple order numbers were mentioned. Ask which order they mean."
        )
    if outcome == "reference_not_found":
        return (
            "The order number was not found in Shopify. Ask the customer to verify "
            "the number and the email used at checkout."
        )
    if outcome == "api_error":
        return (
            "We could not look up the order right now. Apologize and say the team "
            "will follow up shortly."
        )
    if outcome == "order_found":
        return "Answer the customer's order status question using the Shopify context."
    if outcome == "invoice_found":
        return "Help the customer with their invoice request using the Shopify context."
    return "Write an appropriate support reply based on the thread."


def build_shopify_context_payload(
    classification: MessageClassification,
    reference: ReferenceExtractionResult,
    *,
    order_summary: dict[str, Any] | None = None,
    invoice_summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    wants_shopify = classification.get("is_order_status_question") or classification.get(
        "is_invoice_question"
    )
    if not wants_shopify:
        return {"outcome": "none"}

    if reference.ambiguous:
        return {
            "outcome": "ambiguous_reference",
            "candidates": reference.candidates,
        }
    if not reference.reference:
        return {"outcome": "reference_required"}

    if error == "not_found":
        return {
            "outcome": "reference_not_found",
            "order_reference": reference.reference,
            "reference_source": reference.source,
        }
    if error:
        return {
            "outcome": "api_error",
            "order_reference": reference.reference,
            "error": error,
        }

    if classification.get("is_order_status_question") and order_summary:
        return {
            "outcome": "order_found",
            "order_reference": reference.reference,
            "reference_source": reference.source,
            "order": order_summary,
        }
    if classification.get("is_invoice_question") and invoice_summary:
        return {
            "outcome": "invoice_found",
            "order_reference": reference.reference,
            "reference_source": reference.source,
            "invoice": invoice_summary,
        }

    return {
        "outcome": "reference_required",
        "order_reference": reference.reference,
    }
