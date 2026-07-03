from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import MessageClassification
from app.config import Settings
from app.services.agent_training import augment_system_prompt
from app.services.classification_rules import ClassificationRules
from app.services.email_thread import build_thread_context
from app.services.llm import create_chat_llm, llm_configured, ainvoke_structured
from app.services.routing import RoutingResolver


class MessageAnalysisItem(BaseModel):
    message_id: str
    subject: str | None = None
    category: str
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
            "Professional reply draft for customer_support and orders using thread "
            "context; also when needs_live_agent is true; otherwise null"
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
        classification_rules: ClassificationRules,
        related_by_id: dict[str, list[dict[str, Any]]] | None = None,
        cached_summaries: dict[str, dict[str, Any]] | None = None,
        agent_training: str | None = None,
        draft_reply_rules: str | None = None,
    ) -> tuple[list[MessageClassification], list[dict[str, Any]], dict[str, str]]:
        if not messages:
            return [], [], {}

        related_by_id = related_by_id or {}
        cached_summaries = cached_summaries or {}
        resolver = RoutingResolver(rules=classification_rules)

        blocks = [
            _message_prompt_block(
                message,
                related_by_id.get(str(message.get("id", "")), []),
                cached_summary=cached_summaries.get(str(message.get("id", ""))),
            )
            for message in messages
        ]
        rules_prompt = classification_rules.build_classification_prompt()
        draft_section = ""
        if (draft_reply_rules or "").strip():
            draft_section = (
                "\n\nDraft reply instructions:\n"
                f"{draft_reply_rules.strip()}\n"
            )
        prompt = (
            "Analyze each email below. For every message return thread summary fields, "
            "classification fields, and draft_reply_text.\n"
            "For category customer_support or orders, always write draft_reply_text as a "
            "complete reply draft grounded in the thread (prior messages + current email). "
            "For other categories, set draft_reply_text only when needs_live_agent is true.\n"
            "Personal details are redacted as [EMAIL], [PHONE], [LINK], [REDACTED]. "
            "Never invent facts. Keep summary bullets under 15 words.\n\n"
            f"{rules_prompt}"
            f"{draft_section}\n\n"
            f"Emails:\n\n" + "\n\n".join(blocks)
        )

        system_prompt = augment_system_prompt(
            (
                "You are an email analyst. Use exact category slug values from the rules. "
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
            )
            classifications.append(resolver.normalize_classification(row))
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
                )
                classifications.append(resolver.normalize_classification(row))
                summaries.append(
                    {
                        "message_id": msg_id,
                        "history_points": [],
                        "current_points": ["Analysis unavailable."],
                        "focus": "Review manually.",
                    }
                )

        return classifications, summaries, drafts
