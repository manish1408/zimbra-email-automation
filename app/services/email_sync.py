from __future__ import annotations

from app.config import Settings
from app.models.schemas import (
    AccountMessages,
    Folder,
    FolderListResponse,
    InboxResponse,
    MessageDetail,
    MessageSearchResponse,
    MessageSummary,
    SyncResult,
    User,
    UserListResponse,
)
from app.services.zimbra.admin_client import ZimbraAdminClient
from app.services.zimbra.mail_client import ZimbraMailClient, ZimbraMessage


class EmailSyncService:
    """Orchestrates admin auth, account discovery, and mailbox operations."""

    INBOX_QUERY = "in:inbox"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.admin = ZimbraAdminClient(settings)
        self.mail = ZimbraMailClient(settings)

    async def test_connection(self) -> tuple[bool, int, str]:
        try:
            accounts = await self.admin.get_all_accounts()
            return True, len(accounts), "Connected to Zimbra successfully"
        except Exception as exc:
            return False, 0, str(exc)

    async def list_users(self) -> UserListResponse:
        accounts = await self.admin.get_all_accounts()
        users = [self._to_user(account) for account in accounts]
        return UserListResponse(total=len(users), users=users)

    async def get_user(self, user_email: str) -> User:
        for account in await self.admin.get_all_accounts():
            if account["name"] == user_email:
                return self._to_user(account)
        return User(id="", email=user_email)

    async def get_inbox(
        self,
        user_email: str,
        limit: int = 50,
        offset: int = 0,
    ) -> InboxResponse:
        return await self._search_mailbox(
            user_email=user_email,
            query=self.INBOX_QUERY,
            limit=limit,
            offset=offset,
            response_class=InboxResponse,
        )

    async def search_user_messages(
        self,
        user_email: str,
        query: str,
        limit: int = 50,
        offset: int = 0,
    ) -> MessageSearchResponse:
        return await self._search_mailbox(
            user_email=user_email,
            query=query,
            limit=limit,
            offset=offset,
            response_class=MessageSearchResponse,
        )

    async def list_folders(self, user_email: str) -> FolderListResponse:
        user = await self.get_user(user_email)
        token = await self.admin.delegate_auth(user_email)
        folders = await self.mail.list_folders(auth_token=token, account_name=user_email)
        return FolderListResponse(
            user=user,
            folders=[
                Folder(
                    id=f.id,
                    name=f.name,
                    path=f.path,
                    unread_count=f.unread_count,
                    message_count=f.message_count,
                )
                for f in folders
            ],
        )

    async def get_message(self, user_email: str, message_id: str) -> MessageDetail:
        token = await self.admin.delegate_auth(user_email)
        message = await self.mail.get_message(
            auth_token=token,
            account_name=user_email,
            message_id=message_id,
        )
        detail = MessageDetail(**self._to_summary(message).model_dump())
        detail.body = message.body
        return detail

    async def _delegate_token(self, user_email: str) -> str:
        return await self.admin.delegate_auth(user_email)

    async def move_message(
        self, user_email: str, message_id: str, folder_id: str
    ) -> None:
        token = await self._delegate_token(user_email)
        await self.mail.move_message(token, user_email, message_id, folder_id)

    async def get_or_create_folder(self, user_email: str, name: str) -> str:
        token = await self._delegate_token(user_email)
        return await self.mail.get_or_create_folder(token, user_email, name)

    async def forward_message(
        self, user_email: str, message_id: str, to_address: str
    ) -> None:
        token = await self._delegate_token(user_email)
        await self.mail.forward_message(
            token, user_email, message_id, to_address, from_address=user_email
        )

    async def send_reply(
        self, user_email: str, message_id: str, body_text: str
    ) -> None:
        token = await self._delegate_token(user_email)
        await self.mail.send_reply(
            token, user_email, message_id, body_text, from_address=user_email
        )

    async def save_draft(
        self,
        user_email: str,
        subject: str,
        body_text: str,
        to_address: str | None = None,
    ) -> str | None:
        token = await self._delegate_token(user_email)
        return await self.mail.save_draft(
            token, user_email, subject, body_text, to_address=to_address
        )

    async def autocomplete_person(self, user_email: str, name: str) -> list[str]:
        token = await self._delegate_token(user_email)
        return await self.mail.autocomplete_gal(token, user_email, name)

    async def poll_inbox(
        self,
        user_email: str,
        query: str,
        limit: int = 50,
    ) -> list[MessageSummary]:
        response = await self._search_mailbox(
            user_email=user_email,
            query=query,
            limit=limit,
            offset=0,
            response_class=MessageSearchResponse,
        )
        return response.messages

    async def sync_all_mailboxes(
        self,
        query: str | None = None,
        max_accounts: int | None = None,
    ) -> SyncResult:
        users = (await self.list_users()).users
        if max_accounts is not None:
            users = users[:max_accounts]

        exported: list[AccountMessages] = []
        total_messages = 0

        for user in users:
            account_messages = await self.sync_user_mailbox(user.email, query=query)
            exported.append(account_messages)
            total_messages += account_messages.message_count

        return SyncResult(
            accounts_processed=len(exported),
            total_messages=total_messages,
            accounts=exported,
        )

    async def sync_user_mailbox(
        self,
        user_email: str,
        query: str | None = None,
    ) -> AccountMessages:
        user = await self.get_user(user_email)
        token = await self.admin.delegate_auth(user_email)
        messages = await self.mail.fetch_all_messages(
            auth_token=token,
            account_name=user_email,
            query=query,
        )
        return AccountMessages(
            user=user,
            message_count=len(messages),
            messages=[self._to_summary(message) for message in messages],
        )

    async def _search_mailbox(
        self,
        user_email: str,
        query: str,
        limit: int,
        offset: int,
        response_class: type,
    ):
        user = await self.get_user(user_email)
        token = await self.admin.delegate_auth(user_email)
        messages, has_more, total = await self.mail.search_messages(
            auth_token=token,
            account_name=user_email,
            query=query,
            limit=limit,
            offset=offset,
        )
        payload = {
            "user": user,
            "query": query,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "messages": [self._to_summary(message) for message in messages],
        }
        return response_class(**payload)

    @staticmethod
    def _to_user(account: dict[str, str | None]) -> User:
        return User(
            id=account["id"],
            email=account["name"],
            display_name=account.get("display_name"),
            status=account.get("status"),
        )

    @staticmethod
    def _to_summary(message: ZimbraMessage) -> MessageSummary:
        return MessageSummary(
            id=message.id,
            account=message.account,
            subject=message.subject,
            from_address=message.from_address,
            to_addresses=message.to_addresses,
            date=message.date,
            fragment=message.fragment,
            folder=message.folder,
            size=message.size,
            is_read=message.is_read,
        )
