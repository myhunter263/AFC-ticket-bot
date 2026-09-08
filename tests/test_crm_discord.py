from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from integrations.backend.client import BackendError
from modules.orders.views import CartView, DeliveryModal, OrderActionView, OrderPanelView


def interaction(user_id=1):
    return SimpleNamespace(user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
        edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))


@pytest.mark.asyncio
async def test_confirm_creates_once_and_preserves_panel():
    client = SimpleNamespace(request=AsyncMock(return_value={"public_number": 12}))
    cart = CartView(client, 1)
    cart.items = [{"name": "Delivery", "category": "delivery", "quantity": 1, "unit": "request"}]
    cart.delivery = "Westgate"
    inter = interaction()
    await cart.confirm.callback(inter)
    await cart.confirm.callback(inter)
    assert client.request.await_count == 1
    assert cart.confirmed
    assert inter.edit_original_response.call_args.kwargs["view"] is None


@pytest.mark.asyncio
async def test_retry_uses_same_confirmation_key():
    client = SimpleNamespace(request=AsyncMock(side_effect=[BackendError("offline"), {"public_number": 1}]))
    cart = CartView(client, 1)
    cart.items = [{"name": "Delivery", "category": "delivery", "quantity": 1, "unit": "request"}]
    cart.delivery = "Westgate"
    with pytest.raises(BackendError):
        await cart.confirm.callback(interaction())
    assert not cart.creating
    await cart.confirm.callback(interaction())
    calls = client.request.call_args_list
    assert calls[0].kwargs["data"]["idempotency_key"] == calls[1].kwargs["data"]["idempotency_key"]


@pytest.mark.asyncio
async def test_crm_persistent_views_and_modals():
    client = SimpleNamespace()
    assert OrderPanelView(client, 1).is_persistent()
    view = OrderActionView(client, 123)
    assert view.is_persistent()
    assert {c.custom_id for c in view.children} == {"crm:accept:123", "crm:open:123", "crm:reject:123"}
    cart = CartView(client, 1)
    cart.delivery = "Westgate"
    assert DeliveryModal(cart).location.default == "Westgate"
    assert not await cart.interaction_check(interaction(2))
