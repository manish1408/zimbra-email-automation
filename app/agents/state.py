from __future__ import annotations

from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

# Legacy demo graph intents
IntentCategory = Literal["urgent", "compliance", "sales", "support", "newsletter", "general"]

EmailCategory = Literal[
    "spam",
    "marketing",
    "logistics",
    "billing",
    "careers",
    "orders",
    "person_request",
    "customer_support",
    "enquiry",
    "general",
]


class MessageClassification(TypedDict):
    message_id: str
    subject: str | None
    category: EmailCategory
    is_spam: bool
    confidence: float
    requested_person: str | None
    needs_live_agent: bool
    reasoning: str
    route_target: str | None


class MessageActionRecord(TypedDict, total=False):
    message_id: str
    category: str
    is_spam: bool
    folder_path: str | None
    folder_moved: bool
    forwarded_to: str | None
    ack_sent: bool
    draft_saved: bool
    draft_reply_text: str | None
    ack_body_text: str | None
    thread_summary: dict[str, Any] | None
    error: str | None


class ThreadSummaryRecord(TypedDict, total=False):
    message_id: str
    history_points: list[str]
    current_points: list[str]
    focus: str


class AgentState(TypedDict, total=False):
    user_email: str
    limit: int
    instruction: str | None
    use_local_db: bool
    message_ids: list[str] | None
    force_reprocess: bool
    automation_thread_id: str | None
    messages: list[dict[str, Any]]
    enriched_messages: list[dict[str, Any]]
    classifications: list[MessageClassification]
    thread_summaries: list[ThreadSummaryRecord]
    draft_replies: dict[str, str]
    actions_taken: list[MessageActionRecord]
    action_errors: list[str]
    report: dict[str, Any]
    current_node: str

    # Legacy demo graph fields
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
