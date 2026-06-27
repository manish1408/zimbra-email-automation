from __future__ import annotations

from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

IntentCategory = Literal["urgent", "compliance", "sales", "support", "newsletter", "general"]


class MessageClassification(TypedDict):
    message_id: str
    subject: str | None
    intent: IntentCategory
    priority: int
    reasoning: str
    compliance_risk: bool


class AgentState(TypedDict, total=False):
    user_email: str
    limit: int
    instruction: str | None
    messages: list[dict[str, Any]]
    enriched_messages: list[dict[str, Any]]
    classifications: list[MessageClassification]
    dominant_intent: IntentCategory
    agent_messages: Annotated[list, add_messages]
    pending_tool_calls: list[dict[str, Any]]
    needs_tools: bool
    branch_output: str
    compliance_flags: list[str]
    sales_insights: str
    draft_reply: str
    archive_suggestion: str
    merged_insights: str
    needs_refinement: bool
    executive_report: str
    report: dict[str, Any]
    current_node: str
