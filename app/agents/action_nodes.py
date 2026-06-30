from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.state import AgentState, EmailCategory, MessageClassification
from app.config import Settings
from app.db.email_repository import EmailRepository
from app.services.action_executor import ActionExecutor
from app.services.email_sync import EmailSyncService
from app.services.routing import RoutingResolver


class EmailClassificationItem(BaseModel):
    message_id: str
    subject: str | None = None
    category: EmailCategory
    is_spam: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    requested_person: str | None = None
    needs_live_agent: bool = False
    reasoning: str


class EmailClassificationBatch(BaseModel):
    classifications: list[EmailClassificationItem]


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
        self.resolver = resolver or RoutingResolver(settings, email_service)
        self._llm: ChatOpenAI | None = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            if not self.settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not configured")
            self._llm = ChatOpenAI(
                model=self.settings.openai_model,
                api_key=self.settings.openai_api_key,
                temperature=0.1,
            )
        return self._llm

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


def _message_lines(messages: list[dict[str, Any]], include_body: bool = False) -> str:
    lines: list[str] = []
    for message in messages:
        line = (
            f"- id={message.get('id')} | from={message.get('from') or message.get('from_address')} | "
            f"subject={message.get('subject')} | date={message.get('date')} | "
            f"preview={str(message.get('fragment', ''))[:120]}"
        )
        if include_body and message.get("body"):
            line += f" | body={str(message.get('body'))[:400]}"
        lines.append(line)
    return "\n".join(lines) if lines else "(no messages)"


def make_action_nodes(ctx: ActionNodeContext) -> dict[str, Any]:
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
            messages = [m.model_dump(by_alias=True) for m in inbox.messages]

        return {"messages": messages, "limit": limit, "current_node": "ingest_mailbox"}

    async def enrich_messages(state: AgentState) -> dict:
        user_email = state["user_email"]
        messages = list(state.get("messages") or [])
        enriched: list[dict[str, Any]] = []

        for message in messages:
            if message.get("body"):
                enriched.append(message)
                continue
            try:
                if state.get("use_local_db") and ctx.email_repository:
                    conn = await ctx.email_repository.connect()
                    try:
                        detail = await ctx.email_repository.get_message(
                            conn, user_email, str(message.get("id"))
                        )
                        enriched.append(
                            EmailRepository.to_summary_dict(detail)
                            if detail
                            else message
                        )
                    finally:
                        await conn.close()
                else:
                    detail = await ctx.email_service.get_message(
                        user_email=user_email,
                        message_id=str(message.get("id")),
                    )
                    enriched.append(detail.model_dump(by_alias=True))
            except Exception:
                enriched.append(message)

        return {"enriched_messages": enriched, "current_node": "enrich_messages"}

    async def classify_emails(state: AgentState) -> dict:
        messages = state.get("enriched_messages") or state.get("messages") or []
        structured_llm = ctx.llm.with_structured_output(EmailClassificationBatch)
        prompt = (
            "Classify each email for GK Hair automation.\n"
            "Categories: spam, marketing, logistics, billing, careers, orders, "
            "person_request, customer_support, enquiry, general.\n\n"
            "CRITICAL spam rules — mark is_spam=true and category=spam for:\n"
            "- Phishing, fake invoices, payment scams\n"
            "- Promotional logistics/shipping offers disguised as real shipments\n"
            "- Unsolicited sales pitches for billing/finance services\n"
            "- Bulk newsletters and marketing blasts\n\n"
            "person_request: sender asks to reach a specific person by name.\n"
            "needs_live_agent: true when a human must respond (complex support, complaints).\n\n"
            f"Emails:\n{_message_lines(messages, include_body=True)}"
        )
        result: EmailClassificationBatch = await structured_llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are an email classifier for GK Hair. "
                        "Never route fake invoices or promotional spam as billing or logistics. "
                        "Extract requested_person name for person_request emails."
                    )
                ),
                HumanMessage(content=prompt),
            ]
        )
        classifications: list[MessageClassification] = []
        for item in result.classifications:
            row = MessageClassification(
                message_id=item.message_id,
                subject=item.subject,
                category=item.category,
                is_spam=item.is_spam,
                confidence=item.confidence,
                requested_person=item.requested_person,
                needs_live_agent=item.needs_live_agent,
                reasoning=item.reasoning,
                route_target=None,
            )
            classifications.append(row)

        if not classifications and messages:
            for message in messages:
                classifications.append(
                    MessageClassification(
                        message_id=str(message.get("id", "")),
                        subject=message.get("subject"),
                        category="general",
                        is_spam=False,
                        confidence=0.5,
                        requested_person=None,
                        needs_live_agent=False,
                        reasoning="Default when model returned no items.",
                        route_target=None,
                    )
                )

        return {"classifications": classifications, "current_node": "classify_emails"}

    async def resolve_routes(state: AgentState) -> dict:
        account = state["user_email"]
        classifications = state.get("classifications") or []
        resolved = await ctx.resolver.resolve_routes_async(classifications, account)
        return {"classifications": resolved, "current_node": "resolve_routes"}

    async def apply_actions(state: AgentState) -> dict:
        account = state["user_email"]
        messages = state.get("enriched_messages") or state.get("messages") or []
        classifications = state.get("classifications") or []

        if not ctx.email_repository:
            return {
                "actions_taken": [],
                "action_errors": ["email_repository not configured"],
                "current_node": "apply_actions",
            }

        conn = await ctx.email_repository.connect()
        try:
            actions, errors = await ctx.executor.apply_all(
                conn, account, messages, classifications
            )
            zimbra_ids = [c["message_id"] for c in classifications]
            await ctx.email_repository.mark_analyzed(conn, account, zimbra_ids)
        finally:
            await conn.close()

        return {
            "actions_taken": actions,
            "action_errors": errors,
            "current_node": "apply_actions",
        }

    async def format_run_report(state: AgentState) -> dict:
        classifications = state.get("classifications") or []
        actions = state.get("actions_taken") or []
        spam_count = sum(1 for c in classifications if c.get("is_spam"))
        forwarded = sum(1 for a in actions if a.get("forwarded_to"))
        acked = sum(1 for a in actions if a.get("ack_sent"))
        drafts = sum(1 for a in actions if a.get("draft_saved"))
        errors = state.get("action_errors") or []

        report = {
            "user_email": state.get("user_email"),
            "message_count": len(state.get("messages") or []),
            "classified": len(classifications),
            "spam": spam_count,
            "forwarded": forwarded,
            "acked": acked,
            "drafts": drafts,
            "errors": errors,
            "classifications": classifications,
            "actions": actions,
            "dry_run": ctx.settings.automation_dry_run,
        }
        return {"report": report, "current_node": "format_run_report"}

    return {
        "ingest_mailbox": ingest_mailbox,
        "enrich_messages": enrich_messages,
        "classify_emails": classify_emails,
        "resolve_routes": resolve_routes,
        "apply_actions": apply_actions,
        "format_run_report": format_run_report,
    }
