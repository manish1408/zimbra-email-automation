from __future__ import annotations

from typing import Any

from app.agents.action_nodes import ActionNodeContext, make_action_nodes
from app.agents.state import PipelineState
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.services.agent_training import load_training
from app.services.email_sync import EmailSyncService
from app.services.routing import RoutingResolver

PIPELINE_STEPS = (
    "ingest_mailbox",
    "enrich_messages",
    "analyze_messages",
    "resolve_routes",
    "apply_actions",
    "format_run_report",
)


async def run_action_pipeline(
    initial_state: PipelineState,
    *,
    email_service: EmailSyncService,
    settings: Settings,
    email_repository: EmailRepository | None = None,
    resolver: RoutingResolver | None = None,
) -> dict[str, Any]:
    """Run the production email automation pipeline sequentially."""
    ctx = ActionNodeContext(
        email_service=email_service,
        settings=settings,
        email_repository=email_repository,
        resolver=resolver,
    )
    nodes = make_action_nodes(ctx)
    state: dict[str, Any] = dict(initial_state)
    if email_repository and state.get("agent_training") is None:
        state["agent_training"] = await load_training(email_repository)
    for step in PIPELINE_STEPS:
        patch = await nodes[step](state)
        state.update(patch)
    return state
