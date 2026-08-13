from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ui.views.ticket_view as ticket_view_module
from ui.views.ticket_view import OrderPreviewView, TicketView


class PreviewServiceStub:
    catalog = []

    def format_order(self, order) -> str:
        return "Предпросмотр"

    def snapshots(self, order) -> list[dict]:
        return []


def make_preview() -> OrderPreviewView:
    return OrderPreviewView(
        author_id=1,
        panel_id=2,
        form_id=3,
        responses=[],
        category_id=4,
        ping_role_ids=[],
        viewer_role_ids=[],
        panel_name="Заказ",
        service=PreviewServiceStub(),
        order=SimpleNamespace(items=[], unresolved=[], requires_confirmation=False),
    )


def make_interaction():
    return SimpleNamespace(
        response=SimpleNamespace(
            edit_message=AsyncMock(),
            send_message=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        delete_original_response=AsyncMock(),
        edit_original_response=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_successful_creation_deletes_preview(monkeypatch):
    preview = make_preview()
    interaction = make_interaction()
    create_ticket = AsyncMock(return_value=True)
    monkeypatch.setattr(ticket_view_module, "_finish_ticket_creation", create_ticket)

    await preview.create_order.callback(interaction)

    interaction.delete_original_response.assert_awaited_once_with()
    interaction.edit_original_response.assert_not_awaited()
    assert preview.is_finished()


@pytest.mark.asyncio
async def test_failed_creation_keeps_retryable_preview(monkeypatch):
    preview = make_preview()
    interaction = make_interaction()
    create_ticket = AsyncMock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(ticket_view_module, "_finish_ticket_creation", create_ticket)

    await preview.create_order.callback(interaction)

    interaction.delete_original_response.assert_not_awaited()
    interaction.edit_original_response.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()
    assert not preview.is_finished()
    assert all(not child.disabled for child in preview.children)


@pytest.mark.asyncio
async def test_final_ticket_view_remains_persistent():
    view = TicketView(ticket_id=10, guild_id=20)

    assert view.timeout is None
    assert view.is_persistent()
    assert all(child.custom_id for child in view.children)
    assert {child.custom_id for child in view.children} == {
        "tv:claim",
        "tv:status",
        "tv:transfer",
        "tv:close",
        "tv:reopen",
        "tv:export",
        "tv:report",
        "tv:award",
        "tv:delete",
    }
