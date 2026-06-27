from __future__ import annotations

import httpx

from app.config import Settings
from app.services.zimbra.soap import (
    ZIMBRA_ADMIN_NS,
    build_envelope,
    find_all,
    find_text,
    parse_response,
)


class ZimbraAdminClient:
    """Authenticate as Zimbra admin and enumerate accounts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._admin_token: str | None = None

    async def _post(self, body_xml: str, auth_token: str | None = None) -> str:
        envelope = build_envelope(body_xml, auth_token=auth_token)
        async with httpx.AsyncClient(verify=self.settings.zimbra_verify_ssl) as client:
            response = await client.post(
                self.settings.admin_soap_url,
                content=envelope,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=60.0,
            )
            response.raise_for_status()
            return response.text

    async def authenticate(self) -> str:
        body = (
            f'<AuthRequest xmlns="{ZIMBRA_ADMIN_NS}">'
            f"<name>{self.settings.zimbra_admin_user}</name>"
            f"<password>{self.settings.zimbra_admin_password}</password>"
            "</AuthRequest>"
        )
        xml = await self._post(body)
        root = parse_response(xml)
        token = find_text(root, "authToken")
        if not token:
            raise RuntimeError("Admin authentication succeeded but no authToken returned")
        self._admin_token = token
        return token

    async def ensure_authenticated(self) -> str:
        if not self._admin_token:
            return await self.authenticate()
        return self._admin_token

    async def get_all_accounts(self) -> list[dict[str, str | None]]:
        token = await self.ensure_authenticated()
        domain_filter = self.settings.zimbra_domain_filter
        domain_xml = ""
        if domain_filter:
            domain_xml = f'<domain by="name">{domain_filter}</domain>'

        body = (
            f'<GetAllAccountsRequest xmlns="{ZIMBRA_ADMIN_NS}">'
            f"{domain_xml}"
            "</GetAllAccountsRequest>"
        )
        xml = await self._post(body, auth_token=token)
        root = parse_response(xml)

        accounts: list[dict[str, str | None]] = []
        for account in find_all(root, "account"):
            name = account.attrib.get("name")
            account_id = account.attrib.get("id")
            if not name or not account_id:
                continue

            attrs: dict[str, str] = {}
            for attr in find_all(account, "a"):
                key = attr.attrib.get("n")
                if key:
                    attrs[key] = (attr.text or "").strip()

            accounts.append(
                {
                    "id": account_id,
                    "name": name,
                    "display_name": attrs.get("displayName") or attrs.get("cn"),
                    "status": attrs.get("zimbraAccountStatus"),
                }
            )
        return accounts

    async def delegate_auth(self, account_name: str) -> str:
        """Return a user-scoped auth token for the given mailbox."""
        token = await self.ensure_authenticated()
        body = (
            f'<DelegateAuthRequest xmlns="{ZIMBRA_ADMIN_NS}">'
            f'<account by="name">{account_name}</account>'
            "</DelegateAuthRequest>"
        )
        xml = await self._post(body, auth_token=token)
        root = parse_response(xml)
        delegated = find_text(root, "authToken")
        if not delegated:
            raise RuntimeError(f"DelegateAuth failed for {account_name}")
        return delegated
