from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings
from app.services.zimbra.soap import (
    ZIMBRA_MAIL_NS,
    ZimbraSoapError,
    build_envelope,
    escape_xml,
    find_all,
    find_by_local_name,
    find_text,
    local_name,
    normalize_zimbra_date,
    parse_response,
)

# Zimbra default folder IDs (resolved dynamically when possible)
INBOX_FOLDER_ID = "2"
ROOT_FOLDER_ID = "1"

# Some Zimbra/Carbonio builds reject in:anywhere with HTTP 500; is:anywhere works.
QUERY_ALIASES = {
    "in:anywhere": "is:anywhere",
}

# sort: in search queries triggers HTTP 500 on some Zimbra/Carbonio builds.
_SORT_CLAUSE_RE = re.compile(r"\bsort:\s*\w+\b", re.IGNORECASE)


def normalize_search_query(query: str) -> str:
    q = query.strip()
    q = QUERY_ALIASES.get(q.lower(), q)
    q = _SORT_CLAUSE_RE.sub("", q).strip()
    return " ".join(q.split())


@dataclass
class ZimbraMessage:
    id: str
    subject: str | None
    from_address: str | None
    to_addresses: list[str]
    date: str | None
    fragment: str | None
    account: str
    cc_addresses: list[str] = field(default_factory=list)
    folder: str | None = None
    size: int | None = None
    is_read: bool | None = None
    body: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ZimbraFolder:
    id: str
    name: str
    path: str | None = None
    unread_count: int | None = None
    message_count: int | None = None


class ZimbraMailClient:
    """Search and fetch messages from a delegated user mailbox."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def _post(
        self,
        body_xml: str,
        auth_token: str,
        target_account: str | None = None,
    ) -> str:
        envelope = build_envelope(
            body_xml,
            auth_token=auth_token,
            target_account=target_account,
        )
        async with httpx.AsyncClient(verify=self.settings.zimbra_verify_ssl) as client:
            response = await client.post(
                self.settings.mail_soap_url,
                content=envelope,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=120.0,
            )
            text = response.text
            if response.status_code >= 400:
                try:
                    parse_response(text)
                except ZimbraSoapError:
                    raise
                except ValueError:
                    pass
                response.raise_for_status()
            return text

    async def search_messages(
        self,
        auth_token: str,
        account_name: str,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ZimbraMessage], bool, int]:
        query = normalize_search_query(query or self.settings.zimbra_search_query)
        body = (
            f'<SearchRequest xmlns="{ZIMBRA_MAIL_NS}"'
            f' types="message" fetch="1" limit="{limit}" offset="{offset}">'
            f"<query>{escape_xml(query)}</query>"
            "</SearchRequest>"
        )
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)

        more = root.attrib.get("more", "0") == "1"
        total_text = root.attrib.get("total", "0")
        total = int(total_text) if total_text.isdigit() else 0

        messages: list[ZimbraMessage] = []
        for hit in find_all(root, ".//m"):
            msg_id = hit.attrib.get("id")
            if not msg_id:
                continue
            messages.append(self._parse_message_hit(hit, account_name=account_name))

        if total == 0:
            if more:
                total = -1
            else:
                total = offset + len(messages)
        return messages, more, total

    async def get_message(
        self,
        auth_token: str,
        account_name: str,
        message_id: str,
    ) -> ZimbraMessage:
        body = (
            f'<GetMsgRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f'<m id="{escape_xml(message_id)}" html="1" needExp="1" wantContent="full"/>'
            "</GetMsgRequest>"
        )
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)
        message_node = find_by_local_name(root, "m")
        if message_node is None:
            raise RuntimeError(f"GetMsg returned no message for id={message_id}")
        message = self._parse_message_hit(message_node, account_name=account_name)
        message.body = self._extract_body(message_node)
        return message

    async def list_folders(
        self,
        auth_token: str,
        account_name: str,
    ) -> list[ZimbraFolder]:
        body = f'<GetFolderRequest xmlns="{ZIMBRA_MAIL_NS}" visible="1"/>'
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)
        return self._parse_folders(root)

    def _parse_folders(self, root) -> list[ZimbraFolder]:
        """Walk folder tree iteratively (avoids recursion overflow on large trees)."""
        folders: list[ZimbraFolder] = []
        for node in root.iter():
            if local_name(node.tag) != "folder":
                continue
            folder_id = node.attrib.get("id")
            name = node.attrib.get("name") or node.attrib.get("abs")
            if not folder_id or not name:
                continue
            unread = node.attrib.get("u")
            count = node.attrib.get("n")
            folders.append(
                ZimbraFolder(
                    id=folder_id,
                    name=name,
                    path=node.attrib.get("abs"),
                    unread_count=int(unread) if unread and unread.isdigit() else None,
                    message_count=int(count) if count and count.isdigit() else None,
                )
            )
        return folders

    async def fetch_all_messages(
        self,
        auth_token: str,
        account_name: str,
        query: str | None = None,
        batch_size: int | None = None,
    ) -> list[ZimbraMessage]:
        batch_size = batch_size or self.settings.zimbra_search_batch_size
        all_messages: list[ZimbraMessage] = []
        offset = 0

        while True:
            batch, more, _ = await self.search_messages(
                auth_token=auth_token,
                account_name=account_name,
                query=query,
                limit=batch_size,
                offset=offset,
            )
            all_messages.extend(batch)
            if not more or not batch:
                break
            offset += len(batch)

        return all_messages

    def _parse_message_hit(self, node, account_name: str) -> ZimbraMessage:
        subject = find_text(node, "su")
        fragment = find_text(node, "fr")
        date = normalize_zimbra_date(find_text(node, "d") or node.attrib.get("d"))
        folder = node.attrib.get("l")
        size_text = node.attrib.get("s")
        size = int(size_text) if size_text and size_text.isdigit() else None
        read_flag = node.attrib.get("f")
        is_read = None
        if read_flag is not None:
            is_read = "u" not in read_flag

        from_address = None
        to_addresses: list[str] = []
        cc_addresses: list[str] = []
        for email in find_all(node, "e"):
            address = email.attrib.get("a")
            if not address:
                continue
            email_type = email.attrib.get("t", "")
            if email_type == "f":
                from_address = address
            elif email_type == "t":
                to_addresses.append(address)
            elif email_type == "c":
                cc_addresses.append(address)

        return ZimbraMessage(
            id=node.attrib.get("id", ""),
            subject=subject,
            from_address=from_address,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            date=date,
            fragment=fragment,
            account=account_name,
            folder=folder,
            size=size,
            is_read=is_read,
            raw={"attrs": dict(node.attrib)},
        )

    def _extract_body(self, node) -> str | None:
        plain_parts: list[str] = []
        html_parts: list[str] = []
        other_parts: list[str] = []

        for mp in find_all(node, ".//mp"):
            content_type = mp.attrib.get("ct", "")
            content_node = find_by_local_name(mp, "content")
            if content_node is None:
                continue
            text = self._content_text(content_node)
            if not text:
                continue
            if "text/plain" in content_type:
                plain_parts.append(text)
            elif "text/html" in content_type:
                html_parts.append(text)
            else:
                other_parts.append(text)

        if plain_parts:
            return "\n\n".join(plain_parts)
        if html_parts:
            return "\n\n".join(html_parts)
        if other_parts:
            return "\n\n".join(other_parts)

        for part in find_all(node, ".//content"):
            text = self._content_text(part)
            if text:
                return text
        return find_text(node, "fr")

    @staticmethod
    def _content_text(content_node) -> str:
        text = "".join(content_node.itertext()).strip()
        return html_module.unescape(text) if text else ""

    async def create_folder(
        self,
        auth_token: str,
        account_name: str,
        name: str,
        parent_id: str = INBOX_FOLDER_ID,
    ) -> str:
        body = (
            f'<CreateFolderRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f'<folder name="{escape_xml(name)}" l="{parent_id}"/>'
            "</CreateFolderRequest>"
        )
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)
        folder = find_all(root, "folder")
        if folder:
            folder_id = folder[0].attrib.get("id")
            if folder_id:
                return folder_id
        folder_id = root.attrib.get("id")
        if folder_id:
            return folder_id
        raise RuntimeError(f"CreateFolder did not return id for folder {name!r}")

    async def get_or_create_folder(
        self,
        auth_token: str,
        account_name: str,
        name: str,
        parent_id: str = INBOX_FOLDER_ID,
    ) -> str:
        return await self.ensure_folder(
            auth_token=auth_token,
            account_name=account_name,
            name=name,
            parent_id=parent_id,
        )

    async def ensure_folder(
        self,
        auth_token: str,
        account_name: str,
        name: str,
        parent_id: str = INBOX_FOLDER_ID,
        *,
        force_create: bool = False,
    ) -> str:
        """Return folder id, creating the folder when it does not exist."""
        folders = await self.list_folders(
            auth_token=auth_token, account_name=account_name
        )
        folder_id = self.find_folder_id(folders, name)
        if folder_id:
            return folder_id
        if not force_create:
            return folder_id or await self._create_folder_with_fallback(
                auth_token, account_name, name, parent_id
            )

        return await self._create_folder_with_fallback(
            auth_token, account_name, name, parent_id
        )

    async def _create_folder_with_fallback(
        self,
        auth_token: str,
        account_name: str,
        name: str,
        parent_id: str,
    ) -> str:
        last_exc: Exception | None = None
        for candidate_parent in (parent_id, ROOT_FOLDER_ID):
            if candidate_parent == parent_id and parent_id == ROOT_FOLDER_ID:
                continue
            try:
                return await self.create_folder(
                    auth_token=auth_token,
                    account_name=account_name,
                    name=name,
                    parent_id=candidate_parent,
                )
            except (ZimbraSoapError, RuntimeError) as exc:
                last_exc = exc
                if _is_folder_exists_error(exc):
                    folders = await self.list_folders(
                        auth_token=auth_token, account_name=account_name
                    )
                    folder_id = self.find_folder_id(folders, name)
                    if folder_id:
                        return folder_id
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to create folder {name!r}")

    @staticmethod
    def folder_matches(folder: ZimbraFolder, name: str) -> bool:
        target = name.strip().lower()
        if folder.name.lower() == target:
            return True
        raw_path = (folder.path or "").strip("/")
        if not raw_path:
            return False
        path_lower = raw_path.lower()
        if path_lower == target:
            return True
        return path_lower.endswith(f"/{target}")

    def find_folder_id(self, folders: list[ZimbraFolder], name: str) -> str | None:
        for folder in folders:
            if self.folder_matches(folder, name):
                return folder.id
        return None

    async def move_message(
        self,
        auth_token: str,
        account_name: str,
        message_id: str,
        folder_id: str,
    ) -> None:
        body = (
            f'<MsgActionRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f'<action op="move" id="{escape_xml(message_id)}" l="{escape_xml(folder_id)}"/>'
            "</MsgActionRequest>"
        )
        await self._post(body, auth_token=auth_token, target_account=account_name)

    async def forward_message(
        self,
        auth_token: str,
        account_name: str,
        message_id: str,
        to_address: str,
        from_address: str | None = None,
    ) -> None:
        from_xml = ""
        if from_address:
            from_xml = f'<e t="f" a="{escape_xml(from_address)}"/>'
        body = (
            f'<SendMsgRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f'<m origid="{escape_xml(message_id)}" rt="w">'
            f'<e t="t" a="{escape_xml(to_address)}"/>'
            f"{from_xml}"
            "</m>"
            "</SendMsgRequest>"
        )
        await self._post(body, auth_token=auth_token, target_account=account_name)

    async def send_reply(
        self,
        auth_token: str,
        account_name: str,
        message_id: str,
        body_text: str,
        from_address: str | None = None,
    ) -> None:
        from_xml = ""
        if from_address:
            from_xml = f'<e t="f" a="{escape_xml(from_address)}"/>'
        body = (
            f'<SendMsgRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f'<m origid="{escape_xml(message_id)}" rt="r">'
            f"{from_xml}"
            f'<mp ct="text/plain"><content>{escape_xml(body_text)}</content></mp>'
            "</m>"
            "</SendMsgRequest>"
        )
        await self._post(body, auth_token=auth_token, target_account=account_name)

    async def save_draft(
        self,
        auth_token: str,
        account_name: str,
        subject: str,
        body_text: str,
        to_address: str | None = None,
        *,
        cc_addresses: list[str] | None = None,
        from_address: str | None = None,
        origid: str | None = None,
        reply_type: str | None = None,
    ) -> str | None:
        recipients: list[str] = []
        if from_address:
            recipients.append(f'<e t="f" a="{escape_xml(from_address)}"/>')
        if to_address:
            recipients.append(f'<e t="t" a="{escape_xml(to_address)}"/>')
        for cc in cc_addresses or []:
            recipients.append(f'<e t="c" a="{escape_xml(cc)}"/>')

        m_attrs = ""
        if origid:
            m_attrs += f' origid="{escape_xml(origid)}"'
        if reply_type:
            m_attrs += f' rt="{escape_xml(reply_type)}"'

        body = (
            f'<SaveDraftRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f"<m{m_attrs}>"
            f"{''.join(recipients)}"
            f"<su>{escape_xml(subject)}</su>"
            f'<mp ct="text/plain"><content>{escape_xml(body_text)}</content></mp>'
            f"</m>"
            "</SaveDraftRequest>"
        )
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)
        draft_id = root.attrib.get("id")
        if draft_id:
            return draft_id
        msg = find_all(root, "m")
        if msg:
            return msg[0].attrib.get("id")
        return None

    async def autocomplete_gal(
        self,
        auth_token: str,
        account_name: str,
        name: str,
    ) -> list[str]:
        body = (
            f'<AutoCompleteRequest xmlns="{ZIMBRA_MAIL_NS}"'
            f' type="account" name="{escape_xml(name)}"/>'
        )
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)
        matches: list[str] = []
        for match in find_all(root, "match"):
            email = match.attrib.get("email") or match.attrib.get("type")
            if email and "@" in email:
                matches.append(email)
            elif match.text and "@" in match.text:
                matches.append(match.text.strip())
        return matches


def _is_folder_exists_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in ("exist", "already", "duplicate", "name not unique")
    )


def _is_folder_lookup_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "no such folder",
            "unknown folder",
            "invalid folder",
            "folder not found",
            "mail_no_such_folder",
        )
    )
