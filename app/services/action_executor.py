from __future__ import annotations

import logging
from typing import Any

from app.agents.state import MessageActionRecord, MessageClassification
from app.config import Settings
from app.db.email_repository import DbConnection, EmailRepository
from app.services.acknowledgement import build_acknowledgement
from app.services.email_sync import EmailSyncService
from app.services.routing import RoutingResolver
from app.services.zimbra.mail_client import _is_folder_lookup_error

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

    async def apply_rule_folder_move(
        self,
        conn: DbConnection,
        account: str,
        message: dict[str, Any],
        folder_name: str,
    ) -> bool:
        msg_id = str(message.get("id", ""))
        return await self._move_to_folder(conn, account, message, msg_id, folder_name)

    async def apply_folder_move(
        self,
        conn: DbConnection,
        account: str,
        message: dict[str, Any],
        classification: MessageClassification,
    ) -> tuple[str, bool]:
        folder_name = self.resolver.folder_for_classification(classification)
        msg_id = classification["message_id"]
        moved = await self._move_to_folder(conn, account, message, msg_id, folder_name)
        return folder_name, moved

    async def apply_forward(
        self,
        account: str,
        msg_id: str,
        route_target: str | None,
        *,
        classification: MessageClassification | None = None,
    ) -> str | None:
        if not route_target:
            return None
        if classification and classification.get("is_spam"):
            return None
        if classification and not self.resolver.should_forward(classification):
            return None
        dry_run = self.settings.automation_dry_run
        if dry_run:
            logger.info("[DRY RUN] forward %s → %s", msg_id, route_target)
            return route_target
        await self.email_service.forward_message(account, msg_id, route_target)
        logger.info("Forwarded message %s to %s", msg_id, route_target)
        return route_target

    async def apply_ack(
        self,
        account: str,
        message: dict[str, Any],
        classification: MessageClassification,
    ) -> tuple[str | None, bool, bool]:
        if not self.resolver.should_send_ack(classification):
            return None, False, False
        ack_body = build_acknowledgement(message, classification, self.resolver.rules)
        dry_run = self.settings.automation_dry_run
        ack_sent = False
        ack_draft_saved = False
        if dry_run:
            if self.settings.save_ack_as_draft:
                ack_draft_saved = True
            elif self.settings.auto_send_ack:
                ack_sent = True
            return ack_body, ack_sent, ack_draft_saved

        msg_id = str(message.get("id", ""))
        if self.settings.save_ack_as_draft:
            await self._save_draft(account, message, ack_body, label="acknowledgement")
            ack_draft_saved = True
        elif self.settings.auto_send_ack:
            await self.email_service.send_reply(account, msg_id, ack_body)
            ack_sent = True
        return ack_body, ack_sent, ack_draft_saved

    async def apply_response_draft(
        self,
        account: str,
        message: dict[str, Any],
        draft_reply_text: str,
    ) -> bool:
        dry_run = self.settings.automation_dry_run
        if dry_run:
            logger.info(
                "[DRY RUN] save response draft for message %s",
                message.get("id"),
            )
            return True
        await self._save_draft(
            account, message, draft_reply_text, label="response"
        )
        return True

    async def persist_action(
        self,
        conn: DbConnection,
        account: str,
        msg_id: str,
        record: MessageActionRecord,
        classification: MessageClassification | None = None,
        *,
        automation_thread_id: str | None = None,
        report: dict[str, Any] | None = None,
    ) -> None:
        await self.repository.save_message_action(
            conn,
            account,
            msg_id,
            category=record.get("category"),
            is_spam=bool(record.get("is_spam")),
            folder_path=record.get("folder_path"),
            forwarded_to=record.get("forwarded_to"),
            ack_sent_at=_utc_now() if record.get("ack_sent") else None,
            draft_saved=bool(record.get("draft_saved")),
            classification=dict(classification) if classification else None,
            draft_reply_text=record.get("draft_reply_text"),
            ack_body_text=record.get("ack_body_text"),
            automation_thread_id=automation_thread_id,
            report_json=report,
            error=record.get("error"),
            automation_trace=record.get("automation_trace"),
        )

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
        if not self.settings.automation_move_to_folders:
            logger.info("Folder moves disabled; skipping move for %s", msg_id)
            return False

        dry_run = self.settings.automation_dry_run
        if dry_run:
            logger.info("[DRY RUN] move %s → %s", msg_id, folder_name)
            return True

        folder_id = await self.email_service.ensure_folder(account, folder_name)
        current_folder_id = str(message.get("folder") or "")
        if current_folder_id and current_folder_id == folder_id:
            logger.info("Message %s already in folder %s", msg_id, folder_name)
            await self.repository.update_message_folder(conn, account, msg_id, folder_name)
            return False

        try:
            await self.email_service.move_message(account, msg_id, folder_id)
        except Exception as exc:
            if not _is_folder_lookup_error(exc):
                raise
            logger.warning(
                "Move failed for %s → %s (%s); ensuring folder exists and retrying",
                msg_id,
                folder_name,
                exc,
            )
            folder_id = await self.email_service.ensure_folder(
                account, folder_name, force_create=True
            )
            await self.email_service.move_message(account, msg_id, folder_id)

        await self.repository.update_message_folder(conn, account, msg_id, folder_name)
        logger.info("Moved message %s to folder %s", msg_id, folder_name)
        return True


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
