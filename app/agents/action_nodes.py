from __future__ import annotations

from typing import Any

from app.agents.state import PipelineState
from app.config import Settings
from app.db.email_repository import DbConnection, EmailRepository
from app.services.action_executor import ActionExecutor
from app.services.email_sync import EmailSyncService
from app.services.email_thread import message_needs_full_body
from app.services.llm import llm_configured
from app.services.message_analysis import MessageAnalysisService
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


def make_action_nodes(ctx: ActionNodeContext) -> dict[str, Any]:
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

    async def _load_cached_summaries(
        account: str,
        message_ids: list[str],
        conn: DbConnection | None,
    ) -> dict[str, dict[str, Any]]:
        if not ctx.email_repository or not message_ids or conn is None:
            return {}
        cached: dict[str, dict[str, Any]] = {}
        for msg_id in message_ids:
            action = await ctx.email_repository.get_message_action(conn, account, msg_id)
            summary = action.get("thread_summary") if action else None
            if summary and isinstance(summary, dict):
                cached[msg_id] = summary
        return cached

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

        for message in messages:
            try:
                enriched.append(
                    await _ensure_readable_content(user_email, message, conn)
                )
            except Exception:
                enriched.append(message)

        return {"enriched_messages": enriched, "current_node": "enrich_messages"}

    async def analyze_messages(state: PipelineState) -> dict:
        user_email = state["user_email"]
        messages = state.get("enriched_messages") or state.get("messages") or []
        if not messages or not llm_configured(ctx.settings):
            return {
                "classifications": [],
                "thread_summaries": [],
                "draft_replies": {},
                "current_node": "analyze_messages",
            }

        rules = state.get("classification_rules")
        if not rules:
            raise ValueError("Classification rules are not loaded")

        msg_ids = [str(m.get("id", "")) for m in messages]
        cached_summaries = await _load_cached_summaries(
            user_email, msg_ids, _pipeline_conn(state)
        )

        related_by_id: dict[str, list[dict[str, Any]]] = {}
        for message in messages:
            msg_id = str(message.get("id", ""))
            if cached_summaries.get(msg_id):
                related_by_id[msg_id] = []
                continue
            try:
                thread_messages = await ctx.email_service.search_thread_messages(
                    user_email,
                    message.get("subject"),
                    exclude_id=msg_id,
                    limit=4,
                )
                related_by_id[msg_id] = [
                    item.model_dump(by_alias=True) for item in thread_messages
                ]
            except Exception:
                related_by_id[msg_id] = []

        try:
            classifications, summaries, drafts = await MessageAnalysisService(
                ctx.settings
            ).analyze_batch(
                messages,
                classification_rules=state["classification_rules"],
                related_by_id=related_by_id,
                cached_summaries=cached_summaries,
                agent_training=state.get("agent_training"),
                draft_reply_rules=state.get("draft_reply_rules"),
            )
        except Exception as exc:
            classifications = []
            summaries = []
            drafts = {}
            for message in messages:
                msg_id = str(message.get("id", ""))
                summaries.append(
                    {
                        "message_id": msg_id,
                        "history_points": [],
                        "current_points": [f"Analysis failed: {exc}"],
                        "focus": "",
                    }
                )

        return {
            "classifications": classifications,
            "thread_summaries": summaries,
            "draft_replies": drafts,
            "current_node": "analyze_messages",
        }

    async def resolve_routes(state: PipelineState) -> dict:
        account = state["user_email"]
        classifications = state.get("classifications") or []
        resolved = await ctx.resolver.resolve_routes_async(classifications, account)
        return {"classifications": resolved, "current_node": "resolve_routes"}

    async def apply_actions(state: PipelineState) -> dict:
        account = state["user_email"]
        messages = state.get("enriched_messages") or state.get("messages") or []
        classifications = state.get("classifications") or []
        conn = _pipeline_conn(state)

        if not ctx.email_repository or conn is None:
            return {
                "actions_taken": [],
                "action_errors": ["email_repository not configured"],
                "current_node": "apply_actions",
            }

        summaries_by_id = {
            str(item.get("message_id")): item
            for item in (state.get("thread_summaries") or [])
        }
        actions, errors = await ctx.executor.apply_all(
            conn,
            account,
            messages,
            classifications,
            force_reprocess=bool(state.get("force_reprocess")),
            automation_thread_id=state.get("automation_thread_id"),
            report=state.get("report"),
            thread_summaries=summaries_by_id,
            draft_replies=state.get("draft_replies") or {},
        )
        zimbra_ids = [c["message_id"] for c in classifications]
        await ctx.email_repository.mark_analyzed(conn, account, zimbra_ids)
        if hasattr(conn, "commit"):
            await conn.commit()

        return {
            "actions_taken": actions,
            "action_errors": errors,
            "current_node": "apply_actions",
        }

    async def format_run_report(state: PipelineState) -> dict:
        classifications = state.get("classifications") or []
        actions = state.get("actions_taken") or []
        spam_count = sum(1 for c in classifications if c.get("is_spam"))
        forwarded = sum(1 for a in actions if a.get("forwarded_to"))
        moved = sum(1 for a in actions if a.get("folder_moved"))
        acked = sum(1 for a in actions if a.get("ack_sent"))
        ack_drafts = sum(1 for a in actions if a.get("ack_draft_saved"))
        drafts = sum(1 for a in actions if a.get("draft_saved"))
        errors = state.get("action_errors") or []

        report = {
            "user_email": state.get("user_email"),
            "message_count": len(state.get("messages") or []),
            "classified": len(classifications),
            "spam": spam_count,
            "moved": moved,
            "forwarded": forwarded,
            "acked": acked,
            "ack_drafts": ack_drafts,
            "drafts": drafts,
            "errors": errors,
            "classifications": classifications,
            "actions": actions,
            "thread_summaries": state.get("thread_summaries") or [],
            "dry_run": ctx.settings.automation_dry_run,
            "move_to_folders": ctx.settings.automation_move_to_folders,
        }
        return {"report": report, "current_node": "format_run_report"}

    return {
        "ingest_mailbox": ingest_mailbox,
        "enrich_messages": enrich_messages,
        "analyze_messages": analyze_messages,
        "resolve_routes": resolve_routes,
        "apply_actions": apply_actions,
        "format_run_report": format_run_report,
    }
