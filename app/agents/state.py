from __future__ import annotations

from typing import Any, Literal

from typing_extensions import TypedDict

EmailCategory = str


class MessageClassification(TypedDict, total=False):
    message_id: str
    subject: str | None
    category: str
    is_spam: bool
    confidence: float
    requested_person: str | None
    needs_live_agent: bool
    reasoning: str
    route_target: str | None
    is_invoice_question: bool
    is_order_status_question: bool
    needs_response_generation: bool
    needs_forwarding: bool
    automation_source: Literal["rule", "llm"]
    rule_id: str | None


class MessageActionRecord(TypedDict, total=False):
    message_id: str
    category: str
    is_spam: bool
    folder_path: str | None
    folder_moved: bool
    forwarded_to: str | None
    draft_saved: bool
    draft_reply_text: str | None
    error: str | None
    automation_trace: dict[str, Any] | None


class PipelineState(TypedDict, total=False):
    user_email: str
    limit: int
    use_local_db: bool
    message_ids: list[str] | None
    force_reprocess: bool
    automation_thread_id: str | None
    agent_training: str | None
    draft_reply_rules: str | None
    classification_rules: Any
    messages: list[dict[str, Any]]
    enriched_messages: list[dict[str, Any]]
    rule_results: dict[str, dict[str, Any]]
    classifications: list[MessageClassification]
    shopify_context: dict[str, dict[str, Any]]
    draft_replies: dict[str, str]
    automation_traces: dict[str, dict[str, Any]]
    action_records: dict[str, MessageActionRecord]
    actions_taken: list[MessageActionRecord]
    action_errors: list[str]
    report: dict[str, Any]
    current_node: str
    db_conn: Any
