from __future__ import annotations

from typing import Any

from app.agents.state import PipelineState
from app.config import Settings
from app.db.email_repository import DbConnection, EmailRepository
from app.services.action_executor import ActionExecutor
from app.services.email_sync import EmailSyncService
from app.services.email_thread import message_needs_full_body
from app.services.automation_rules import evaluate_message, load_automation_rules
from app.services.routing import RoutingResolver


class ActionNodeContext:
    def __init__(
        self,
        email_service: EmailSyncService,
        settings: Settings,
        email_repository: EmailRepository | None = None,
        resolver: RoutingResolver | None = None,
    ):
        self.email_service = email_service
        self.settings = settings
        self.email_repository = email_repository
        self.resolver = resolver
        if resolver is None:
            raise ValueError("RoutingResolver with classification rules is required")

    @property
    def executor(self) -> ActionExecutor:
        if not self.email_repository:
            raise ValueError("email_repository is required for action pipeline")
        return ActionExecutor(
            self.settings,
            self.email_service,
            self.email_repository,
            self.resolver,
        )


def _pipeline_conn(state: PipelineState) -> DbConnection | None:
    return state.get("db_conn")


def make_base_action_nodes(ctx: ActionNodeContext) -> dict[str, Any]:
    async def _fetch_full_message(
        user_email: str,
        message_id: str,
        message: dict[str, Any],
        conn: DbConnection | None,
    ) -> dict[str, Any]:
        detail = await ctx.email_service.get_message(
            user_email=user_email,
            message_id=message_id,
        )
        merged = {**message, **detail.model_dump(by_alias=True)}
        if ctx.email_repository and conn is not None:
            await ctx.email_repository.upsert_message(conn, detail)
        return merged

    async def _ensure_readable_content(
        user_email: str,
        message: dict[str, Any],
        conn: DbConnection | None,
    ) -> dict[str, Any]:
        if not message_needs_full_body(message):
            return message
        message_id = str(message.get("id") or "")
        if not message_id:
            return message
        try:
            return await _fetch_full_message(user_email, message_id, message, conn)
        except Exception:
            return message

    async def _load_message(
        user_email: str,
        message_id: str,
        conn: DbConnection | None,
    ) -> dict[str, Any] | None:
        message: dict[str, Any] | None = None
        if ctx.email_repository and conn is not None:
            detail = await ctx.email_repository.get_message(conn, user_email, message_id)
            if detail:
                message = EmailRepository.to_summary_dict(detail)
        if message is None:
            try:
                detail = await ctx.email_service.get_message(
                    user_email=user_email,
                    message_id=message_id,
                )
                message = detail.model_dump(by_alias=True)
            except Exception:
                return None
        return await _ensure_readable_content(user_email, message, conn)

    async def ingest_mailbox(state: PipelineState) -> dict:
        user_email = state["user_email"]
        limit = state.get("limit") or ctx.settings.agent_inbox_limit
        message_ids = state.get("message_ids")
        conn = _pipeline_conn(state)

        if message_ids:
            messages: list[dict[str, Any]] = []
            for message_id in message_ids:
                loaded = await _load_message(user_email, str(message_id), conn)
                if loaded:
                    messages.append(loaded)
            return {
                "messages": messages,
                "limit": len(messages) or limit,
                "current_node": "ingest_mailbox",
            }

        if state.get("use_local_db") and ctx.email_repository and conn is not None:
            stored = await ctx.email_repository.get_unanalyzed_messages(
                conn, user_email, limit=limit
            )
            messages = [EmailRepository.to_summary_dict(m) for m in stored]
        else:
            inbox = await ctx.email_service.get_inbox(user_email=user_email, limit=limit)
            messages = [m.model_dump(by_alias=True) for m in inbox.messages]

        return {"messages": messages, "limit": limit, "current_node": "ingest_mailbox"}

    async def enrich_messages(state: PipelineState) -> dict:
        user_email = state["user_email"]
        messages = list(state.get("messages") or [])
        enriched: list[dict[str, Any]] = []
        conn = _pipeline_conn(state)
        automation_rules = load_automation_rules()

        for message in messages:
            rule = evaluate_message(message, automation_rules)
            if rule.matched and rule.skip_llm:
                enriched.append(message)
                continue
            try:
                enriched.append(
                    await _ensure_readable_content(user_email, message, conn)
                )
            except Exception:
                enriched.append(message)

        return {"enriched_messages": enriched, "current_node": "enrich_messages"}

    async def format_run_report(state: PipelineState) -> dict:
        classifications = state.get("classifications") or []
        actions = state.get("actions_taken") or []
        spam_count = sum(1 for c in classifications if c.get("is_spam"))
        forwarded = sum(1 for a in actions if a.get("forwarded_to"))
        moved = sum(1 for a in actions if a.get("folder_moved"))
        drafts = sum(1 for a in actions if a.get("draft_saved"))
        errors = state.get("action_errors") or []

        report = {
            "user_email": state.get("user_email"),
            "message_count": len(state.get("messages") or []),
            "classified": len(classifications),
            "spam": spam_count,
            "moved": moved,
            "forwarded": forwarded,
            "drafts": drafts,
            "errors": errors,
            "classifications": classifications,
            "actions": actions,
            "dry_run": ctx.settings.automation_dry_run,
            "move_to_folders": ctx.settings.automation_move_to_folders,
        }
        return {"report": report, "current_node": "format_run_report"}

    return {
        "ingest_mailbox": ingest_mailbox,
        "enrich_messages": enrich_messages,
        "format_run_report": format_run_report,
    }
