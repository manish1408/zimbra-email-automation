from __future__ import annotations

import json
from collections import Counter
from typing import Any

from typing_extensions import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.agents.state import AgentState, IntentCategory
from app.agents.tools import build_zimbra_tools, execute_tool_call
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.services.email_sync import EmailSyncService
from app.services.llm import create_chat_llm, llm_configured, ainvoke_structured

INTENT_TO_NODE: dict[IntentCategory, str] = {
    "urgent": "urgent_escalation",
    "compliance": "compliance_review",
    "sales": "sales_pipeline",
    "support": "support_agent",
    "newsletter": "newsletter_batch",
    "general": "general_briefing",
}

INTENT_PRIORITY: dict[IntentCategory, int] = {
    "urgent": 6,
    "compliance": 5,
    "support": 4,
    "sales": 3,
    "newsletter": 2,
    "general": 1,
}


class ClassificationItem(BaseModel):
    message_id: str
    subject: str | None = None
    intent: IntentCategory
    priority: int = Field(ge=1, le=5)
    reasoning: str
    compliance_risk: bool = False


class ClassificationBatch(BaseModel):
    classifications: list[ClassificationItem]


class LegacyMessageClassification(TypedDict):
    message_id: str
    subject: str | None
    intent: IntentCategory
    priority: int
    reasoning: str
    compliance_risk: bool


class NodeContext:
    def __init__(
        self,
        email_service: EmailSyncService,
        settings: Settings,
        email_repository: EmailRepository | None = None,
    ):
        self.email_service = email_service
        self.settings = settings
        self.email_repository = email_repository
        self.tools = build_zimbra_tools(email_service)
        self._llm = None
        self._llm_with_tools = None

    @property
    def llm(self):
        if self._llm is None:
            if not llm_configured(self.settings):
                raise ValueError("LLM is not configured")
            self._llm = create_chat_llm(self.settings, temperature=0.2)
        return self._llm

    @property
    def llm_with_tools(self):
        if self._llm_with_tools is None:
            self._llm_with_tools = self.llm.bind_tools(self.tools)
        return self._llm_with_tools


def _message_lines(messages: list[dict[str, Any]], include_body: bool = False) -> str:
    lines: list[str] = []
    for message in messages:
        line = (
            f"- id={message.get('id')} | from={message.get('from')} | "
            f"subject={message.get('subject')} | date={message.get('date')} | "
            f"preview={message.get('fragment', '')[:120]}"
        )
        if include_body and message.get("body"):
            line += f" | body={str(message.get('body'))[:300]}"
        lines.append(line)
    return "\n".join(lines) if lines else "(no messages)"


def _dominant_intent(classifications: list[LegacyMessageClassification]) -> IntentCategory:
    if not classifications:
        return "general"
    counts = Counter(item["intent"] for item in classifications)
    ranked = sorted(
        counts.items(),
        key=lambda item: (item[1], INTENT_PRIORITY.get(item[0], 0)),
        reverse=True,
    )
    return ranked[0][0]


def make_nodes(ctx: NodeContext) -> dict[str, Any]:
    async def ingest_mailbox(state: AgentState) -> dict:
        user_email = state["user_email"]
        limit = state.get("limit") or ctx.settings.agent_inbox_limit

        if state.get("use_local_db") and ctx.email_repository:
            conn = await ctx.email_repository.connect()
            try:
                stored = await ctx.email_repository.get_unanalyzed_messages(
                    conn, user_email, limit=limit
                )
                messages = [
                    EmailRepository.to_summary_dict(m) for m in stored
                ]
            finally:
                await conn.close()
        else:
            inbox = await ctx.email_service.get_inbox(user_email=user_email, limit=limit)
            messages = [message.model_dump(by_alias=True) for message in inbox.messages]

        return {"messages": messages, "limit": limit, "current_node": "ingest_mailbox"}

    async def enrich_messages(state: AgentState) -> dict:
        user_email = state["user_email"]
        messages = list(state.get("messages") or [])
        enriched: list[dict[str, Any]] = []

        if state.get("use_local_db") and ctx.email_repository:
            for message in messages[:3]:
                if message.get("body"):
                    enriched.append(message)
                    continue
                conn = await ctx.email_repository.connect()
                try:
                    detail = await ctx.email_repository.get_message(
                        conn, user_email, str(message.get("id"))
                    )
                    enriched.append(
                        EmailRepository.to_summary_dict(detail) if detail else message
                    )
                finally:
                    await conn.close()
        else:
            for message in messages[:3]:
                try:
                    detail = await ctx.email_service.get_message(
                        user_email=user_email,
                        message_id=str(message.get("id")),
                    )
                    enriched.append(detail.model_dump(by_alias=True))
                except Exception:
                    enriched.append(message)

        if not enriched:
            enriched = messages
        return {"enriched_messages": enriched, "current_node": "enrich_messages"}

    async def classify_intent(state: AgentState) -> dict:
        messages = state.get("enriched_messages") or state.get("messages") or []
        instruction = state.get("instruction") or ""
        prompt = (
            "Classify each email into exactly one intent: urgent, compliance, sales, "
            "support, newsletter, or general. Flag compliance_risk for legal/PII/finance topics.\n"
            f"User focus: {instruction or 'none'}\n\n"
            f"Emails:\n{_message_lines(messages, include_body=True)}"
        )
        result: ClassificationBatch = await ainvoke_structured(
            ctx.llm,
            ClassificationBatch,
            [
                SystemMessage(
                    content=(
                        "You are an enterprise email orchestration classifier. "
                        "urgent=time-critical; compliance=legal/regulatory/PII; "
                        "sales=leads/opportunities; support=customer issues; "
                        "newsletter=bulk mail; general=other."
                    )
                ),
                HumanMessage(content=prompt),
            ],
        )
        classifications: list[LegacyMessageClassification] = [
            LegacyMessageClassification(**item.model_dump()) for item in result.classifications
        ]
        if not classifications and messages:
            classifications = [
                LegacyMessageClassification(
                    message_id=str(message.get("id", "")),
                    subject=message.get("subject"),
                    intent="general",
                    priority=3,
                    reasoning="Default when model returned no items.",
                    compliance_risk=False,
                )
                for message in messages[:3]
            ]
        dominant = _dominant_intent(classifications)
        return {
            "classifications": classifications,
            "dominant_intent": dominant,
            "current_node": "classify_intent",
        }

    async def urgent_escalation(state: AgentState) -> dict:
        urgent = [c for c in state.get("classifications") or [] if c["intent"] == "urgent"]
        messages = state.get("enriched_messages") or state.get("messages") or []
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Create an urgent escalation brief with owners, deadlines, and recommended actions.\n"
                f"Urgent items: {json.dumps(urgent)}\n"
                f"Context:\n{_message_lines(messages, include_body=True)}"
            ))
        ])
        return {"branch_output": str(response.content), "current_node": "urgent_escalation"}

    async def compliance_review(state: AgentState) -> dict:
        risky = [c for c in state.get("classifications") or [] if c.get("compliance_risk")]
        messages = state.get("enriched_messages") or state.get("messages") or []
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Review emails for compliance risk. List flags and recommended handling.\n"
                f"Risky classifications: {json.dumps(risky)}\n"
                f"Context:\n{_message_lines(messages, include_body=True)}"
            ))
        ])
        flags = [f"{c.get('subject') or c.get('message_id')}: {c.get('reasoning')}" for c in risky]
        return {
            "branch_output": str(response.content),
            "compliance_flags": flags,
            "current_node": "compliance_review",
        }

    async def sales_pipeline(state: AgentState) -> dict:
        sales = [c for c in state.get("classifications") or [] if c["intent"] == "sales"]
        messages = state.get("enriched_messages") or state.get("messages") or []
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Extract sales opportunities, deal stage signals, and follow-up actions.\n"
                f"Sales items: {json.dumps(sales)}\n"
                f"Context:\n{_message_lines(messages, include_body=True)}"
            ))
        ])
        content = str(response.content)
        return {
            "branch_output": content,
            "sales_insights": content,
            "current_node": "sales_pipeline",
        }

    async def newsletter_batch(state: AgentState) -> dict:
        newsletters = [c for c in state.get("classifications") or [] if c["intent"] == "newsletter"]
        messages = state.get("messages") or []
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Cluster newsletter senders and suggest safe archive candidates. Suggestions only.\n"
                f"Newsletters: {json.dumps(newsletters)}\n"
                f"Context:\n{_message_lines(messages)}"
            ))
        ])
        content = str(response.content)
        return {
            "branch_output": content,
            "archive_suggestion": content,
            "current_node": "newsletter_batch",
        }

    async def general_briefing(state: AgentState) -> dict:
        messages = state.get("messages") or []
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Provide a concise executive briefing for general inbox items.\n"
                f"Context:\n{_message_lines(messages)}"
            ))
        ])
        return {"branch_output": str(response.content), "current_node": "general_briefing"}

    async def support_agent(state: AgentState) -> dict:
        user_email = state["user_email"]
        messages = state.get("enriched_messages") or state.get("messages") or []
        classifications = state.get("classifications") or []
        agent_messages = list(state.get("agent_messages") or [])
        if not agent_messages:
            agent_messages = [
                SystemMessage(
                    content=(
                        "You are a support triage agent with Zimbra tools. "
                        "Inspect support tickets deeply; call tools when needed. "
                        "Stop calling tools when you can recommend a resolution."
                    )
                ),
                HumanMessage(content=(
                    f"Mailbox: {user_email}\n"
                    f"Support items: {json.dumps([c for c in classifications if c['intent'] == 'support'])}\n"
                    f"Context:\n{_message_lines(messages, include_body=True)}"
                )),
            ]
        response: AIMessage = await ctx.llm_with_tools.ainvoke(agent_messages)
        agent_messages.append(response)
        pending_tool_calls = [
            {"id": call.get("id"), "name": call.get("name"), "args": call.get("args", {})}
            for call in (response.tool_calls or [])
        ]
        return {
            "agent_messages": agent_messages,
            "pending_tool_calls": pending_tool_calls,
            "needs_tools": bool(pending_tool_calls),
            "current_node": "support_agent",
        }

    async def zimbra_tools(state: AgentState) -> dict:
        agent_messages = list(state.get("agent_messages") or [])
        for call in state.get("pending_tool_calls") or []:
            result = await execute_tool_call(
                ctx.email_service, call["name"], call.get("args") or {}
            )
            agent_messages.append(ToolMessage(content=result, tool_call_id=call.get("id") or ""))
        return {
            "agent_messages": agent_messages,
            "pending_tool_calls": [],
            "needs_tools": False,
            "current_node": "zimbra_tools",
        }

    async def draft_support_reply(state: AgentState) -> dict:
        agent_messages = state.get("agent_messages") or []
        context = ""
        last_ai = next((m for m in reversed(agent_messages) if isinstance(m, AIMessage)), None)
        if last_ai and last_ai.content:
            context = str(last_ai.content)
        messages = state.get("enriched_messages") or state.get("messages") or []
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Draft a professional support reply. Output draft only; do not send.\n"
                f"Analysis:\n{context}\n\nContext:\n{_message_lines(messages, include_body=True)}"
            ))
        ])
        content = str(response.content)
        return {
            "branch_output": content,
            "draft_reply": content,
            "current_node": "draft_support_reply",
        }

    async def merge_insights(state: AgentState) -> dict:
        parts = [
            f"Intent route: {state.get('dominant_intent')}",
            state.get("branch_output") or "",
            state.get("sales_insights") or "",
            state.get("archive_suggestion") or "",
            state.get("draft_reply") or "",
        ]
        if state.get("compliance_flags"):
            parts.append("Compliance flags: " + "; ".join(state["compliance_flags"]))
        merged = "\n\n".join(part for part in parts if part)
        return {"merged_insights": merged, "current_node": "merge_insights"}

    async def quality_review(state: AgentState) -> dict:
        merged = state.get("merged_insights") or ""
        needs_refinement = len(merged) < 120 or merged.count("\n") < 2
        return {"needs_refinement": needs_refinement, "current_node": "quality_review"}

    async def refine_output(state: AgentState) -> dict:
        merged = state.get("merged_insights") or ""
        response = await ctx.llm.ainvoke([
            HumanMessage(content=(
                "Refine this email operations brief for an executive audience. "
                "Use clear sections: Situation, Risks, Actions, Drafts.\n\n"
                f"{merged}"
            ))
        ])
        return {"merged_insights": str(response.content), "current_node": "refine_output"}

    async def format_executive_report(state: AgentState) -> dict:
        report = {
            "user_email": state.get("user_email"),
            "dominant_intent": state.get("dominant_intent"),
            "dominant_category": state.get("dominant_intent"),
            "message_count": len(state.get("messages") or []),
            "classifications": state.get("classifications") or [],
            "compliance_flags": state.get("compliance_flags") or [],
            "sales_insights": state.get("sales_insights"),
            "summary": state.get("merged_insights") or state.get("branch_output"),
            "draft_reply": state.get("draft_reply"),
            "archive_suggestion": state.get("archive_suggestion"),
            "instruction": state.get("instruction"),
            "branch_output": state.get("branch_output"),
        }
        executive = state.get("merged_insights") or json.dumps(report, indent=2, default=str)
        report["executive_report"] = executive
        return {
            "executive_report": executive,
            "report": report,
            "current_node": "format_executive_report",
        }

    def route_intent(state: AgentState) -> str:
        intent = state.get("dominant_intent") or "general"
        return INTENT_TO_NODE.get(intent, "general_briefing")

    def route_support_agent(state: AgentState) -> str:
        return "zimbra_tools" if state.get("needs_tools") else "draft_support_reply"

    def route_quality(state: AgentState) -> str:
        return "refine_output" if state.get("needs_refinement") else "format_executive_report"

    return {
        "ingest_mailbox": ingest_mailbox,
        "enrich_messages": enrich_messages,
        "classify_intent": classify_intent,
        "urgent_escalation": urgent_escalation,
        "compliance_review": compliance_review,
        "sales_pipeline": sales_pipeline,
        "support_agent": support_agent,
        "zimbra_tools": zimbra_tools,
        "draft_support_reply": draft_support_reply,
        "newsletter_batch": newsletter_batch,
        "general_briefing": general_briefing,
        "merge_insights": merge_insights,
        "quality_review": quality_review,
        "refine_output": refine_output,
        "format_executive_report": format_executive_report,
        "route_intent": route_intent,
        "route_support_agent": route_support_agent,
        "route_quality": route_quality,
    }
