from __future__ import annotations

import logging
from typing import Any

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

    async def apply_all(
        self,
        conn: DbConnection,
        account: str,
        messages: list[dict[str, Any]],
        classifications: list[MessageClassification],
        *,
        force_reprocess: bool = False,
        automation_thread_id: str | None = None,
        report: dict[str, Any] | None = None,
        draft_replies: dict[str, str] | None = None,
    ) -> tuple[list[MessageActionRecord], list[str]]:
        by_id = {str(m.get("id")): m for m in messages}
        actions: list[MessageActionRecord] = []
        errors: list[str] = []
        drafts = draft_replies or {}

        for classification in classifications:
            msg_id = classification["message_id"]
            if not force_reprocess and await self.repository.is_message_processed(
                conn, account, msg_id
            ):
                logger.info("Skipping already-processed message %s", msg_id)
                continue

            message = by_id.get(msg_id)
            if not message:
                errors.append(f"Message {msg_id} not found in batch")
                continue

            record, error = await self._apply_one(
                conn,
                account,
                message,
                classification,
                automation_thread_id=automation_thread_id,
                report=report,
                draft_reply_text=drafts.get(msg_id),
            )
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
        *,
        automation_thread_id: str | None = None,
        report: dict[str, Any] | None = None,
        draft_reply_text: str | None = None,
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
            "folder_moved": False,
            "forwarded_to": None,
            "ack_sent": False,
            "ack_draft_saved": False,
            "draft_saved": False,
            "draft_reply_text": None,
            "ack_body_text": None,
            "error": None,
        }
        error: str | None = None
        draft_body: str | None = None
        ack_body: str | None = None

        try:
            if self.resolver.should_send_ack(classification):
                ack_body = build_acknowledgement(
                    message, classification, self.resolver.rules
                )
                record["ack_body_text"] = ack_body

            if self.resolver.should_draft_reply(classification):
                draft_body = draft_reply_text
                if draft_body:
                    record["draft_reply_text"] = draft_body
                else:
                    logger.warning(
                        "Draft reply expected for %s but none was provided by analysis",
                        msg_id,
                    )

            if dry_run:
                logger.info(
                    "[DRY RUN] %s → folder=%s forward=%s spam=%s",
                    msg_id,
                    folder_name,
                    route_target,
                    classification.get("is_spam"),
                )
                record["forwarded_to"] = route_target
                if ack_body:
                    if self.settings.save_ack_as_draft:
                        record["ack_draft_saved"] = True
                    elif self.settings.auto_send_ack:
                        record["ack_sent"] = True
                if draft_body:
                    record["draft_saved"] = True
            else:
                folder_moved = await self._move_to_folder(
                    conn, account, message, msg_id, folder_name
                )
                record["folder_moved"] = folder_moved

                if route_target and not classification.get("is_spam"):
                    await self.email_service.forward_message(
                        account, msg_id, route_target
                    )
                    record["forwarded_to"] = route_target

                if ack_body:
                    if self.settings.save_ack_as_draft:
                        await self._save_draft(
                            account, message, ack_body, label="acknowledgement"
                        )
                        record["ack_draft_saved"] = True
                    elif self.settings.auto_send_ack:
                        await self.email_service.send_reply(account, msg_id, ack_body)
                        record["ack_sent"] = True

                if draft_body:
                    await self._save_draft(
                        account, message, draft_body, label="response"
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
                draft_reply_text=draft_body,
                ack_body_text=ack_body,
                automation_thread_id=automation_thread_id,
                report_json=report,
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
                draft_reply_text=draft_body,
                ack_body_text=ack_body,
                automation_thread_id=automation_thread_id,
                report_json=report,
                error=str(exc),
            )

        return record, error

    async def _save_draft(
        self,
        account: str,
        message: dict[str, Any],
        body_text: str,
        *,
        label: str,
    ) -> None:
        subject = message.get("subject") or "Support request"
        to_addr = message.get("from") or message.get("from_address")
        draft_subject = f"Re: {subject}"
        if label == "acknowledgement":
            draft_subject = f"Re: {subject} (acknowledgement)"
        await self.email_service.save_draft(
            account,
            subject=draft_subject,
            body_text=body_text,
            to_address=to_addr,
        )
        logger.info("Saved %s draft for message %s", label, message.get("id"))

    async def _move_to_folder(
        self,
        conn: DbConnection,
        account: str,
        message: dict[str, Any],
        msg_id: str,
        folder_name: str,
    ) -> bool:
        """Classify-driven folder move on Zimbra. Returns True when message was moved."""
        if not self.settings.automation_move_to_folders:
            logger.info("Folder moves disabled; skipping move for %s", msg_id)
            return False

        folder_id = await self.email_service.get_or_create_folder(account, folder_name)
        current_folder_id = str(message.get("folder") or "")
        if current_folder_id and current_folder_id == folder_id:
            logger.info("Message %s already in folder %s", msg_id, folder_name)
            await self.repository.update_message_folder(conn, account, msg_id, folder_name)
            return False

        await self.email_service.move_message(account, msg_id, folder_id)
        await self.repository.update_message_folder(conn, account, msg_id, folder_name)
        logger.info("Moved message %s to folder %s", msg_id, folder_name)
        return True


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
