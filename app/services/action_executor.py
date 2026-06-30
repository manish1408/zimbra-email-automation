from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI

from app.agents.state import MessageActionRecord, MessageClassification
from app.config import Settings
from app.db.email_repository import DbConnection, EmailRepository
from app.services.acknowledgement import build_acknowledgement
from app.services.email_sync import EmailSyncService
from app.services.routing import RoutingResolver

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Apply Zimbra folder moves, forwards, acknowledgements, and drafts."""

    def __init__(
        self,
        settings: Settings,
        email_service: EmailSyncService,
        repository: EmailRepository,
        resolver: RoutingResolver,
    ):
        self.settings = settings
        self.email_service = email_service
        self.repository = repository
        self.resolver = resolver
        self._llm: ChatOpenAI | None = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            if not self.settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not configured")
            self._llm = ChatOpenAI(
                model=self.settings.openai_model,
                api_key=self.settings.openai_api_key,
                temperature=0.3,
            )
        return self._llm

    async def apply_all(
        self,
        conn: DbConnection,
        account: str,
        messages: list[dict[str, Any]],
        classifications: list[MessageClassification],
    ) -> tuple[list[MessageActionRecord], list[str]]:
        by_id = {str(m.get("id")): m for m in messages}
        actions: list[MessageActionRecord] = []
        errors: list[str] = []

        for classification in classifications:
            msg_id = classification["message_id"]
            if await self.repository.is_message_processed(conn, account, msg_id):
                logger.info("Skipping already-processed message %s", msg_id)
                continue

            message = by_id.get(msg_id)
            if not message:
                errors.append(f"Message {msg_id} not found in batch")
                continue

            record, error = await self._apply_one(conn, account, message, classification)
            actions.append(record)
            if error:
                errors.append(error)

        return actions, errors

    async def _apply_one(
        self,
        conn: DbConnection,
        account: str,
        message: dict[str, Any],
        classification: MessageClassification,
    ) -> tuple[MessageActionRecord, str | None]:
        msg_id = classification["message_id"]
        folder_name = self.resolver.folder_for_classification(classification)
        route_target = classification.get("route_target")
        dry_run = self.settings.automation_dry_run

        record: MessageActionRecord = {
            "message_id": msg_id,
            "category": classification["category"],
            "is_spam": classification.get("is_spam", False),
            "folder_path": folder_name,
            "forwarded_to": None,
            "ack_sent": False,
            "draft_saved": False,
            "error": None,
        }
        error: str | None = None

        try:
            if dry_run:
                logger.info(
                    "[DRY RUN] %s → folder=%s forward=%s spam=%s",
                    msg_id,
                    folder_name,
                    route_target,
                    classification.get("is_spam"),
                )
                record["forwarded_to"] = route_target
                if self.resolver.should_send_ack(classification):
                    record["ack_sent"] = True
                if self.resolver.should_draft_reply(classification):
                    record["draft_saved"] = True
            else:
                folder_id = await self.email_service.get_or_create_folder(
                    account, folder_name
                )
                await self.email_service.move_message(account, msg_id, folder_id)

                if route_target and not classification.get("is_spam"):
                    await self.email_service.forward_message(
                        account, msg_id, route_target
                    )
                    record["forwarded_to"] = route_target

                if self.settings.auto_send_ack and self.resolver.should_send_ack(
                    classification
                ):
                    ack_body = build_acknowledgement(
                        message, classification, self.resolver.rules
                    )
                    await self.email_service.send_reply(account, msg_id, ack_body)
                    record["ack_sent"] = True

                if self.resolver.should_draft_reply(classification):
                    draft_body = await self._generate_draft(message, classification)
                    subject = message.get("subject") or "Support request"
                    to_addr = message.get("from") or message.get("from_address")
                    await self.email_service.save_draft(
                        account,
                        subject=f"Re: {subject}",
                        body_text=draft_body,
                        to_address=to_addr,
                    )
                    record["draft_saved"] = True

            await self.repository.save_message_action(
                conn,
                account,
                msg_id,
                category=classification["category"],
                is_spam=classification.get("is_spam", False),
                folder_path=folder_name,
                forwarded_to=record.get("forwarded_to"),
                ack_sent_at=_utc_now() if record.get("ack_sent") else None,
                draft_saved=bool(record.get("draft_saved")),
                classification=dict(classification),
            )
        except Exception as exc:
            error = f"{msg_id}: {exc}"
            record["error"] = str(exc)
            logger.exception("Failed to process message %s", msg_id)
            await self.repository.save_message_action(
                conn,
                account,
                msg_id,
                category=classification.get("category"),
                is_spam=classification.get("is_spam", False),
                classification=dict(classification),
                error=str(exc),
            )

        return record, error

    async def _generate_draft(
        self, message: dict[str, Any], classification: MessageClassification
    ) -> str:
        subject = message.get("subject") or ""
        body_preview = (message.get("body") or message.get("fragment") or "")[:1500]
        response = await self.llm.ainvoke(
            f"Draft a professional customer support reply for GK Hair.\n"
            f"Category: {classification['category']}\n"
            f"Subject: {subject}\n"
            f"Email body:\n{body_preview}\n\n"
            "Output only the reply body text."
        )
        return str(response.content).strip()


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
