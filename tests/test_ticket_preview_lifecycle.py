from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ui.views.ticket_view as ticket_view_module
from ui.views.ticket_view import OrderPreviewView, TicketView


class PreviewServiceStub:
    catalog = []

    def format_order(self, order) -> str:
        return "Предпросмотр"

    def snapshots(self, order) -> list[dict]:
        return []


class SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_preview(*, panel_message_id: int = 101, preview_message_id: int = 303):
    preview_message = SimpleNamespace(
        id=preview_message_id,
        edit=AsyncMock(),
        delete=AsyncMock(),
        channel=SimpleNamespace(id=404),
    )
    view = OrderPreviewView(
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
        panel_message_id=panel_message_id,
    )
    view.attach_preview(preview_message)
    return view, preview_message


def make_interaction():
    return SimpleNamespace(
        message=SimpleNamespace(id=303),
        user=SimpleNamespace(id=1),
        response=SimpleNamespace(
            edit_message=AsyncMock(),
            send_message=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        delete_original_response=AsyncMock(),
        edit_original_response=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_successful_creation_deletes_preview(monkeypatch, caplog):
    caplog.set_level("INFO", logger="ui.views.ticket_view")
    preview, preview_message = make_preview()
    interaction = make_interaction()
    create_ticket = AsyncMock(return_value=True)
    monkeypatch.setattr(ticket_view_module, "_finish_ticket_creation", create_ticket)

    await preview.create_order.callback(interaction)

    preview_message.delete.assert_awaited_once_with()
    interaction.delete_original_response.assert_not_awaited()
    assert "Deleted message_id=303 message_type=ORDER_PREVIEW" in caplog.text
    interaction.edit_original_response.assert_not_awaited()
    assert preview.is_finished()


@pytest.mark.asyncio
async def test_failed_creation_keeps_retryable_preview(monkeypatch):
    preview, preview_message = make_preview()
    interaction = make_interaction()
    create_ticket = AsyncMock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(ticket_view_module, "_finish_ticket_creation", create_ticket)

    await preview.create_order.callback(interaction)

    interaction.delete_original_response.assert_not_awaited()
    preview_message.edit.assert_awaited_once()
    interaction.edit_original_response.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()
    assert not preview.is_finished()
    assert all(not child.disabled for child in preview.children)


@pytest.mark.asyncio
async def test_panel_message_is_never_deleted_as_preview(caplog):
    preview, panel_message = make_preview(panel_message_id=101, preview_message_id=101)

    await preview._delete_preview()

    panel_message.delete.assert_not_awaited()
    assert "Refusing to delete application panel as preview: message_id=101" in caplog.text


@pytest.mark.asyncio
async def test_preview_interaction_guard_rejects_application_panel():
    preview, _ = make_preview(panel_message_id=101, preview_message_id=303)
    interaction = make_interaction()
    interaction.message.id = 101

    allowed = await preview.interaction_check(interaction)

    assert allowed is False
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_show_preview_forces_separate_ephemeral_response(monkeypatch):
    order = SimpleNamespace(
        items=[SimpleNamespace(resolved=SimpleNamespace(requires_confirmation=False))],
        unresolved=[],
        requires_confirmation=False,
    )
    service = PreviewServiceStub()
    service.parse = Mock(return_value=order)
    preview_message = SimpleNamespace(
        id=303,
        channel=SimpleNamespace(id=404),
        edit=AsyncMock(),
        delete=AsyncMock(),
    )
    interaction = SimpleNamespace(
        guild_id=10,
        channel_id=20,
        user=SimpleNamespace(id=1),
        message=SimpleNamespace(id=101),
        response=SimpleNamespace(
            is_done=Mock(return_value=False),
            defer=AsyncMock(),
        ),
        edit_original_response=AsyncMock(return_value=preview_message),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    session = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(
        ticket_view_module,
        "async_session_maker",
        lambda: SessionContext(session),
    )
    monkeypatch.setattr(
        ticket_view_module.ItemCatalogService,
        "get_catalog",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        ticket_view_module.TicketService,
        "get_panel_by_id",
        AsyncMock(return_value=SimpleNamespace(
            panel_message_id=101,
            panel_channel_id=20,
        )),
    )
    monkeypatch.setattr(
        ticket_view_module,
        "OrderPreviewService",
        Mock(return_value=service),
    )

    await ticket_view_module._show_order_preview(
        interaction=interaction,
        panel_id=2,
        form_id=3,
        responses=[],
        category_id=4,
        ping_role_ids=[],
        viewer_role_ids=[],
        order_text="15 ящиков аргенти",
        panel_name="Заказ",
    )

    interaction.response.defer.assert_awaited_once_with(
        ephemeral=True,
        thinking=True,
    )
    interaction.edit_original_response.assert_awaited_once()
    interaction.followup.send.assert_not_awaited()
    view = interaction.edit_original_response.await_args.kwargs["view"]
    assert view.panel_message_id == 101
    assert view.preview_message_id == 303
    assert view.preview_message is preview_message


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
