from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.services.shopify.models import ShopifyInvoiceSummary, ShopifyOrderSummary

logger = logging.getLogger(__name__)


class OrderNotFoundError(Exception):
    pass


class ShopifyBotError(Exception):
    pass


class ShopifyBotClient:
    def __init__(self, settings: Settings):
        self.base_url = (settings.shopify_bot_base_url or "https://bot.gkhair.com").rstrip("/")
        self.api_key = settings.shopify_bot_api_key
        self.timeout = settings.shopify_bot_timeout_seconds

    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key}

    async def get_order(self, order_id: str) -> ShopifyOrderSummary:
        data = await self._get(f"/api/shopify/order/{order_id}")
        return _parse_order(order_id, data)

    async def get_invoice(self, order_id: str) -> ShopifyInvoiceSummary:
        data = await self._get(f"/api/shopify/invoice/{order_id}")
        return _parse_invoice(order_id, data)

    async def _get(self, path: str) -> dict[str, Any]:
        if not self.api_key:
            raise ShopifyBotError("SHOPIFY_BOT_API_KEY is not configured")
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, headers=self._headers())
                    if response.status_code == 404:
                        raise OrderNotFoundError(f"Order not found: {path}")
                    if response.status_code == 401:
                        raise ShopifyBotError("Shopify Bot API unauthorized")
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
                    return {"data": payload}
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last_exc = exc
                if attempt == 0:
                    continue
                raise ShopifyBotError(str(exc)) from exc
        raise ShopifyBotError(str(last_exc or "request failed"))


def _parse_order(order_id: str, data: dict[str, Any]) -> ShopifyOrderSummary:
    order = data.get("order") if isinstance(data.get("order"), dict) else data
    fulfillments = order.get("fulfillments") or []
    tracking_number = None
    tracking_url = None
    if fulfillments and isinstance(fulfillments[0], dict):
        tracking_number = fulfillments[0].get("tracking_number")
        tracking_url = fulfillments[0].get("tracking_url")
    line_items = order.get("line_items") or []
    return ShopifyOrderSummary(
        order_id=str(order.get("name") or order.get("id") or order_id),
        status=order.get("status") or order.get("order_status"),
        financial_status=order.get("financial_status"),
        fulfillment_status=order.get("fulfillment_status"),
        created_at=order.get("created_at"),
        tracking_number=tracking_number,
        tracking_url=tracking_url,
        line_items_count=len(line_items) if isinstance(line_items, list) else 0,
        raw=order if isinstance(order, dict) else data,
    )


def _parse_invoice(order_id: str, data: dict[str, Any]) -> ShopifyInvoiceSummary:
    invoice = data.get("invoice") if isinstance(data.get("invoice"), dict) else data
    return ShopifyInvoiceSummary(
        order_id=str(invoice.get("order_id") or invoice.get("name") or order_id),
        invoice_url=invoice.get("invoice_url") or invoice.get("url"),
        invoice_number=str(invoice.get("invoice_number") or invoice.get("number") or "") or None,
        status=invoice.get("status"),
        raw=invoice if isinstance(invoice, dict) else data,
    )
