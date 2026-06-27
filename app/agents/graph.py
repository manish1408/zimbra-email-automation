from __future__ import annotations

from typing import Any

from app.agents.email_agent import EmailAutomationOrchestrator
from app.agents.nodes import NodeContext, make_nodes
from app.agents.state import AgentState
from app.config import Settings
from app.services.email_sync import EmailSyncService


def build_graph(
    email_service: EmailSyncService,
    settings: Settings,
    checkpointer: Any | None = None,
) -> Any:
    ctx = NodeContext(email_service=email_service, settings=settings)
    nodes = make_nodes(ctx)
    builder = EmailAutomationOrchestrator(
        state_schema=AgentState,
        impl=[
            ("ingest_mailbox", nodes["ingest_mailbox"]),
            ("enrich_messages", nodes["enrich_messages"]),
            ("classify_intent", nodes["classify_intent"]),
            ("urgent_escalation", nodes["urgent_escalation"]),
            ("compliance_review", nodes["compliance_review"]),
            ("sales_pipeline", nodes["sales_pipeline"]),
            ("support_agent", nodes["support_agent"]),
            ("zimbra_tools", nodes["zimbra_tools"]),
            ("draft_support_reply", nodes["draft_support_reply"]),
            ("newsletter_batch", nodes["newsletter_batch"]),
            ("general_briefing", nodes["general_briefing"]),
            ("merge_insights", nodes["merge_insights"]),
            ("quality_review", nodes["quality_review"]),
            ("refine_output", nodes["refine_output"]),
            ("format_executive_report", nodes["format_executive_report"]),
            ("route_intent", nodes["route_intent"]),
            ("route_support_agent", nodes["route_support_agent"]),
            ("route_quality", nodes["route_quality"]),
        ],
    )
    return builder.compile(checkpointer=checkpointer)
