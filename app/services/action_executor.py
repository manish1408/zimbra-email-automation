from __future__ import annotations

import logging
from typing import Any

from app.agents.state import MessageActionRecord, MessageClassification
from app.config import Settings
from app.db.email_repository import DbConnection, EmailRepository
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
        await self._save_draft(account, message, draft_reply_text)
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
            draft_saved=bool(record.get("draft_saved")),
            classification=dict(classification) if classification else None,
            draft_reply_text=record.get("draft_reply_text"),
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
    ) -> None:
        msg_id = str(message.get("id") or "")

        original = None
        if msg_id:
            try:
                original = await self.email_service.get_raw_message(account, msg_id)
            except Exception as exc:
                logger.warning(
                    "Could not fetch original message %s for reply-all draft: %s",
                    msg_id,
                    exc,
                )

        subject = (
            (original.subject if original else None)
            or message.get("subject")
            or "Support request"
        )
        draft_subject = _ensure_reply_subject(subject)

        to_addr = (
            (original.from_address if original else None)
            or message.get("from")
            or message.get("from_address")
        )

        if original:
            cc_source = [*original.to_addresses, *original.cc_addresses]
        else:
            cc_source = list(message.get("to") or message.get("to_addresses") or [])
        exclude = [account, to_addr] if to_addr else [account]
        cc_addresses = _dedupe_addresses(cc_source, exclude=exclude)

        reply_body = _build_reply_body(body_text, original)

        await self.email_service.save_draft(
            account,
            subject=draft_subject,
            body_text=reply_body,
            to_address=to_addr,
            cc_addresses=cc_addresses,
            from_address=account,
            origid=msg_id or None,
            reply_type="r",
        )
        logger.info(
            "Saved reply-all draft for message %s (to=%s, cc=%d)",
            msg_id,
            to_addr,
            len(cc_addresses),
        )

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


def _ensure_reply_subject(subject: str) -> str:
    text = (subject or "").strip()
    if not text:
        return "Re:"
    if text.lower().startswith("re:"):
        return text
    return f"Re: {text}"


def _dedupe_addresses(
    addresses: list[str], *, exclude: list[str | None]
) -> list[str]:
    exclude_lower = {a.lower() for a in exclude if a}
    seen: set[str] = set()
    result: list[str] = []
    for addr in addresses:
        if not addr:
            continue
        key = addr.lower()
        if key in exclude_lower or key in seen:
            continue
        seen.add(key)
        result.append(addr)
    return result


def _build_reply_body(reply_text: str, original: Any | None) -> str:
    """Prepend the reply and quote the original message so the thread stays visible."""
    if original is None:
        return reply_text
    header_lines = ["", "----- Original Message -----"]
    if getattr(original, "from_address", None):
        header_lines.append(f"From: {original.from_address}")
    if getattr(original, "date", None):
        header_lines.append(f"Sent: {original.date}")
    if getattr(original, "to_addresses", None):
        header_lines.append(f"To: {', '.join(original.to_addresses)}")
    if getattr(original, "cc_addresses", None):
        header_lines.append(f"Cc: {', '.join(original.cc_addresses)}")
    if getattr(original, "subject", None):
        header_lines.append(f"Subject: {original.subject}")

    quoted = "\n".join(header_lines)
    original_body = (getattr(original, "body", None) or "").strip()
    if original_body:
        quoted += "\n\n" + original_body
    return f"{reply_text.rstrip()}\n{quoted}\n"
