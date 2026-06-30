from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.action_nodes import ActionNodeContext, make_action_nodes
from app.agents.state import AgentState
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.services.email_sync import EmailSyncService
from app.services.routing import RoutingResolver


def build_action_graph(
    email_service: EmailSyncService,
    settings: Settings,
    checkpointer: Any | None = None,
    email_repository: EmailRepository | None = None,
    resolver: RoutingResolver | None = None,
) -> Any:
    ctx = ActionNodeContext(
        email_service=email_service,
        settings=settings,
        email_repository=email_repository,
        resolver=resolver,
    )
    nodes = make_action_nodes(ctx)

    graph = StateGraph(AgentState)
    graph.add_node("ingest_mailbox", nodes["ingest_mailbox"])
    graph.add_node("enrich_messages", nodes["enrich_messages"])
    graph.add_node("classify_emails", nodes["classify_emails"])
    graph.add_node("resolve_routes", nodes["resolve_routes"])
    graph.add_node("apply_actions", nodes["apply_actions"])
    graph.add_node("format_run_report", nodes["format_run_report"])

    graph.add_edge(START, "ingest_mailbox")
    graph.add_edge("ingest_mailbox", "enrich_messages")
    graph.add_edge("enrich_messages", "classify_emails")
    graph.add_edge("classify_emails", "resolve_routes")
    graph.add_edge("resolve_routes", "apply_actions")
    graph.add_edge("apply_actions", "format_run_report")
    graph.add_edge("format_run_report", END)

    return graph.compile(checkpointer=checkpointer)
