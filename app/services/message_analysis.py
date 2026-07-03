from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import EmailCategory, MessageClassification
from app.config import Settings
from app.services.agent_training import augment_system_prompt
from app.services.email_thread import build_thread_context
from app.services.llm import create_chat_llm, llm_configured, ainvoke_structured


class MessageAnalysisItem(BaseModel):
    message_id: str
    subject: str | None = None
    category: EmailCategory
    is_spam: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    requested_person: str | None = None
    needs_live_agent: bool = False
    reasoning: str
    history_points: list[str] = Field(
        default_factory=list,
        description="Short bullet points for prior conversation, oldest first",
    )
    current_points: list[str] = Field(
        default_factory=list,
        description="Short bullet points for the current email only",
    )
    focus: str = Field(
        default="",
        description="One sentence on what the current email needs or asks for",
    )
    draft_reply_text: str | None = Field(
        default=None,
        description=(
            "Professional GK Hair support reply body when needs_live_agent is true; "
            "otherwise null"
        ),
    )


class MessageAnalysisBatch(BaseModel):
    analyses: list[MessageAnalysisItem]


def _message_prompt_block(
    message: dict[str, Any],
    related: list[dict[str, Any]] | None,
    *,
    cached_summary: dict[str, Any] | None = None,
) -> str:
    msg_id = str(message.get("id", ""))
    context = build_thread_context(message, related)
    lines = [
        f"### Message id={msg_id}",
        f"From: {message.get('from') or message.get('from_address')}",
        f"Subject: {context['subject']}",
        f"Date: {message.get('date')}",
        f"CURRENT EMAIL:\n{context['current_text'] or '(empty)'}",
        f"PRIOR CONVERSATION:\n{context['history_text'] or '(none)'}",
    ]
    if cached_summary:
        lines.append(
            "CACHED SUMMARY (reuse these summary fields unless content clearly changed):\n"
            f"history_points: {cached_summary.get('history_points')}\n"
            f"current_points: {cached_summary.get('current_points')}\n"
            f"focus: {cached_summary.get('focus')}"
        )
    return "\n".join(lines)


class MessageAnalysisService:
    """Summarize, classify, and draft replies in a single LLM call per batch."""

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

    async def analyze_batch(
        self,
        messages: list[dict[str, Any]],
        related_by_id: dict[str, list[dict[str, Any]]] | None = None,
        cached_summaries: dict[str, dict[str, Any]] | None = None,
        agent_training: str | None = None,
    ) -> tuple[list[MessageClassification], list[dict[str, Any]], dict[str, str]]:
        if not messages:
            return [], [], {}

        related_by_id = related_by_id or {}
        cached_summaries = cached_summaries or {}

        blocks = [
            _message_prompt_block(
                message,
                related_by_id.get(str(message.get("id", "")), []),
                cached_summary=cached_summaries.get(str(message.get("id", ""))),
            )
            for message in messages
        ]
        prompt = (
            "Analyze each email below for GK Hair automation. For every message return:\n"
            "- Thread summary (history_points, current_points, focus). "
            "Personal details are redacted as [EMAIL], [PHONE], [LINK], [REDACTED]. "
            "Never invent facts. Keep bullets under 15 words.\n"
            "- Classification with category, is_spam, confidence, requested_person, "
            "needs_live_agent, reasoning.\n"
            "- draft_reply_text: professional support reply body when needs_live_agent "
            "is true; otherwise null.\n\n"
            "Categories: spam, marketing, logistics, billing, careers, orders, "
            "person_request, customer_support, enquiry, general.\n\n"
            "CRITICAL spam rules — mark is_spam=true and category=spam for:\n"
            "- Phishing, fake invoices, payment scams\n"
            "- Promotional logistics/shipping offers disguised as real shipments\n"
            "- Unsolicited sales pitches for billing/finance services\n"
            "- Bulk newsletters and marketing blasts\n\n"
            "person_request: sender asks to reach a specific person by name.\n"
            "needs_live_agent: true when a human must respond (complex support, complaints).\n\n"
            f"Emails:\n\n" + "\n\n".join(blocks)
        )

        system_prompt = augment_system_prompt(
            (
                "You are an email analyst for GK Hair. "
                "Never route fake invoices or promotional spam as billing or logistics. "
                "Extract requested_person for person_request emails. "
                "Return one analysis object per message id."
            ),
            agent_training,
        )

        result: MessageAnalysisBatch = await ainvoke_structured(
            self.llm,
            MessageAnalysisBatch,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ],
        )

        by_id = {str(m.get("id")): m for m in messages}
        classifications: list[MessageClassification] = []
        summaries: list[dict[str, Any]] = []
        drafts: dict[str, str] = {}

        for item in result.analyses:
            msg_id = item.message_id
            classifications.append(
                MessageClassification(
                    message_id=msg_id,
                    subject=item.subject or by_id.get(msg_id, {}).get("subject"),
                    category=item.category,
                    is_spam=item.is_spam,
                    confidence=item.confidence,
                    requested_person=item.requested_person,
                    needs_live_agent=item.needs_live_agent,
                    reasoning=item.reasoning,
                    route_target=None,
                )
            )
            summaries.append(
                {
                    "message_id": msg_id,
                    "history_points": [p.strip() for p in item.history_points if p.strip()],
                    "current_points": [p.strip() for p in item.current_points if p.strip()],
                    "focus": item.focus.strip(),
                }
            )
            if item.draft_reply_text and item.draft_reply_text.strip():
                drafts[msg_id] = item.draft_reply_text.strip()

        if not classifications and messages:
            for message in messages:
                msg_id = str(message.get("id", ""))
                classifications.append(
                    MessageClassification(
                        message_id=msg_id,
                        subject=message.get("subject"),
                        category="general",
                        is_spam=False,
                        confidence=0.5,
                        requested_person=None,
                        needs_live_agent=False,
                        reasoning="Default when model returned no items.",
                        route_target=None,
                    )
                )
                summaries.append(
                    {
                        "message_id": msg_id,
                        "history_points": [],
                        "current_points": ["Analysis unavailable."],
                        "focus": "Review manually.",
                    }
                )

        return classifications, summaries, drafts
