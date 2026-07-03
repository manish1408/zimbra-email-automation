from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import Settings
from app.services.agent_training import augment_system_prompt
from app.services.email_thread import build_thread_context
from app.services.llm import create_chat_llm, llm_configured, ainvoke_structured


class ThreadSummaryOutput(BaseModel):
    history_points: list[str] = Field(
        default_factory=list,
        description="Short bullet points summarizing prior conversation, oldest first",
    )
    current_points: list[str] = Field(
        default_factory=list,
        description="Short bullet points describing the current email only",
    )
    focus: str = Field(
        default="",
        description="One sentence on what the current email needs or asks for",
    )


class ThreadSummaryService:
    """Generate point-wise thread summaries with PII redacted."""

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

    async def summarize(
        self,
        message: dict[str, Any],
        related_messages: list[dict[str, Any]] | None = None,
        agent_training: str | None = None,
    ) -> dict[str, Any]:
        context = build_thread_context(message, related_messages)
        current_text = context["current_text"]
        history_text = context["history_text"]

        if not current_text and not history_text:
            return {
                "message_id": str(message.get("id", "")),
                "history_points": [],
                "current_points": ["No readable email content available."],
                "focus": "Review the original message manually.",
            }

        prompt = (
            f"Subject: {context['subject']}\n\n"
            f"CURRENT EMAIL (focus here):\n{current_text or '(empty)'}\n\n"
            f"PRIOR CONVERSATION HISTORY (summarize briefly, no PII):\n"
            f"{history_text or '(none — this appears to be the first message in the thread)'}"
        )

        system_prompt = augment_system_prompt(
            (
                "You summarize email threads for support agents. "
                "Personal details are already redacted as [EMAIL], [PHONE], [LINK], [REDACTED]. "
                "Never invent facts. Keep each bullet under 15 words. "
                "history_points should cover prior messages only. "
                "current_points should cover the latest email only. "
                "focus is one actionable sentence about the current email."
            ),
            agent_training,
        )

        result: ThreadSummaryOutput = await ainvoke_structured(
            self.llm,
            ThreadSummaryOutput,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ],
        )

        return {
            "message_id": str(message.get("id", "")),
            "history_points": [p.strip() for p in result.history_points if p.strip()],
            "current_points": [p.strip() for p in result.current_points if p.strip()],
            "focus": result.focus.strip(),
        }
