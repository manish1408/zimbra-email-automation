from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.services.shopify.bot_client import OrderNotFoundError, ShopifyBotClient


@pytest.mark.asyncio
async def test_get_order_success():
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        shopify_bot_api_key="secret",
        shopify_bot_base_url="https://bot.example.com",
    )
    client = ShopifyBotClient(settings)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "order": {
            "name": "GKUS77914",
            "fulfillment_status": "fulfilled",
            "financial_status": "paid",
            "line_items": [{"id": 1}],
        }
    }
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        instance.__aenter__.return_value = instance
        instance.get.return_value = mock_response
        client_cls.return_value = instance

        order = await client.get_order("GKUS77914")
        assert order.order_id == "GKUS77914"
        assert order.fulfillment_status == "fulfilled"


@pytest.mark.asyncio
async def test_get_order_404():
    settings = Settings(
        zimbra_host="x",
        zimbra_admin_user="a",
        zimbra_admin_password="b",
        shopify_bot_api_key="secret",
    )
    client = ShopifyBotClient(settings)

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        instance.__aenter__.return_value = instance
        instance.get.return_value = mock_response
        client_cls.return_value = instance

        with pytest.raises(OrderNotFoundError):
            await client.get_order("GKUS99999")
