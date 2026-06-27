from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings
from app.services.zimbra.soap import (
    ZIMBRA_MAIL_NS,
    build_envelope,
    find_all,
    find_text,
    parse_response,
)


@dataclass
class ZimbraMessage:
    id: str
    subject: str | None
    from_address: str | None
    to_addresses: list[str]
    date: str | None
    fragment: str | None
    account: str
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
            response.raise_for_status()
            return response.text

    async def search_messages(
        self,
        auth_token: str,
        account_name: str,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ZimbraMessage], bool, int]:
        query = query or self.settings.zimbra_search_query
        body = (
            f'<SearchRequest xmlns="{ZIMBRA_MAIL_NS}"'
            f' types="message" fetch="1" limit="{limit}" offset="{offset}">'
            f"<query>{query}</query>"
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
        return messages, more, total

    async def get_message(
        self,
        auth_token: str,
        account_name: str,
        message_id: str,
    ) -> ZimbraMessage:
        body = (
            f'<GetMsgRequest xmlns="{ZIMBRA_MAIL_NS}">'
            f'<m id="{message_id}" wantContent="full"/>'
            "</GetMsgRequest>"
        )
        xml = await self._post(body, auth_token=auth_token, target_account=account_name)
        root = parse_response(xml)
        message_node = root.find("m")
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
        return self._parse_folders(find_all(root, ".//folder"))

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

    def _parse_folders(self, folder_nodes) -> list[ZimbraFolder]:
        folders: list[ZimbraFolder] = []
        for node in folder_nodes:
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
            folders.extend(self._parse_folders(find_all(node, "folder")))
        return folders

    def _parse_message_hit(self, node, account_name: str) -> ZimbraMessage:
        subject = find_text(node, "su")
        fragment = find_text(node, "fr")
        date = find_text(node, "d") or node.attrib.get("d")
        folder = node.attrib.get("l")
        size_text = node.attrib.get("s")
        size = int(size_text) if size_text and size_text.isdigit() else None
        read_flag = node.attrib.get("f")
        is_read = None
        if read_flag is not None:
            is_read = "u" not in read_flag

        from_address = None
        to_addresses: list[str] = []
        for email in find_all(node, "e"):
            address = email.attrib.get("a")
            if not address:
                continue
            email_type = email.attrib.get("t", "")
            if email_type == "f":
                from_address = address
            elif email_type == "t":
                to_addresses.append(address)

        return ZimbraMessage(
            id=node.attrib.get("id", ""),
            subject=subject,
            from_address=from_address,
            to_addresses=to_addresses,
            date=date,
            fragment=fragment,
            account=account_name,
            folder=folder,
            size=size,
            is_read=is_read,
            raw={"attrs": dict(node.attrib)},
        )

    def _extract_body(self, node) -> str | None:
        for part in find_all(node, ".//content"):
            text = (part.text or "").strip()
            if text:
                return text
        for part in find_all(node, ".//mp"):
            text = (part.text or "").strip()
            if text:
                return text
        return find_text(node, "fr")
