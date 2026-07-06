from __future__ import annotations

import time
from typing import Any

from app.agents.action_nodes import ActionNodeContext
from app.agents.modular_nodes import make_modular_action_nodes
from app.agents.state import PipelineState
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.services.agent_training import load_training_texts
from app.services.automation_console import AutomationConsoleReporter
from app.services.automation_run_logs import persist_message_automation_logs
from app.services.classification_rules import load_classification_rules
from app.services.email_sync import EmailSyncService
from app.services.llm import get_llm_duration_ms, reset_llm_duration
from app.services.routing import RoutingResolver

MODULAR_PIPELINE_STEPS = (
    "ingest_mailbox",
    "enrich_messages",
    "apply_automation_rules",
    "persist_rule_matched",
    "classify_messages",
    "apply_routing_actions",
    "fetch_shopify_context",
    "generate_drafts",
    "apply_draft_actions",
    "persist_message_actions",
    "format_run_report",
)


async def run_action_pipeline(
    initial_state: PipelineState,
    *,
    email_service: EmailSyncService,
    settings: Settings,
    email_repository: EmailRepository | None = None,
    resolver: RoutingResolver | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    """Run the production email automation pipeline sequentially."""
    state: dict[str, Any] = dict(initial_state)
    owns_conn = conn is None and email_repository is not None
    if owns_conn:
        conn = await email_repository.connect()
    if conn is not None:
        state["db_conn"] = conn

    reset_llm_duration()
    run_started = time.perf_counter()
    reporter = AutomationConsoleReporter()
    reporter.start_run(
        account=state.get("user_email", ""),
        thread_id=state.get("automation_thread_id") or "",
        message_count=len(state.get("message_ids") or []),
        dry_run=settings.automation_dry_run,
    )

    try:
        if email_repository:
            if state.get("agent_training") is None or state.get("draft_reply_rules") is None:
                general_rules, draft_reply_rules = await load_training_texts(
                    email_repository, conn
                )
                state.setdefault("agent_training", general_rules)
                state.setdefault("draft_reply_rules", draft_reply_rules)
            if state.get("classification_rules") is None:
                state["classification_rules"] = await load_classification_rules(
                    email_repository, conn
                )

        rules = state.get("classification_rules")
        if resolver is None:
            if not rules:
                raise ValueError("Classification rules are required to run the pipeline")
            resolver = RoutingResolver(email_service=email_service, rules=rules)

        ctx = ActionNodeContext(
            email_service=email_service,
            settings=settings,
            email_repository=email_repository,
            resolver=resolver,
        )
        nodes = make_modular_action_nodes(ctx)

        for step in MODULAR_PIPELINE_STEPS:
            step_started = reporter.start_step(step)
            try:
                patch = await nodes[step](state)
                state.update(patch)
                reporter.end_step(step, step_started)
            except Exception as exc:
                reporter.end_step(step, step_started, error=str(exc))
                raise

        total_duration_ms = int((time.perf_counter() - run_started) * 1000)
        llm_duration_ms = get_llm_duration_ms()
        actions_taken = state.get("actions_taken") or []
        failed = sum(1 for a in actions_taken if a.get("error"))
        completed = len(actions_taken) - failed
        reporter.finish_run(
            total_duration_ms=total_duration_ms,
            llm_duration_ms=llm_duration_ms,
            completed=completed,
            failed=failed,
        )

        if email_repository and conn is not None and actions_taken:
            logged_ids = set(state.get("automation_logged_ids") or [])
            remaining = [
                a for a in actions_taken if str(a.get("message_id")) not in logged_ids
            ]
            if remaining:
                await persist_message_automation_logs(
                    email_repository,
                    conn,
                    {**state, "actions_taken": remaining},
                    total_duration_ms=total_duration_ms,
                    llm_duration_ms=llm_duration_ms,
                )

        state["pipeline_duration_ms"] = total_duration_ms
        state["pipeline_llm_duration_ms"] = llm_duration_ms
        return state
    finally:
        if owns_conn and conn is not None:
            await conn.close()
