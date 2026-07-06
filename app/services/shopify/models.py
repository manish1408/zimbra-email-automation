from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ShopifyOrderSummary(BaseModel):
    order_id: str
    status: str | None = None
    financial_status: str | None = None
    fulfillment_status: str | None = None
    created_at: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    line_items_count: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ShopifyInvoiceSummary(BaseModel):
    order_id: str
    invoice_url: str | None = None
    invoice_number: str | None = None
    status: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
