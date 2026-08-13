from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import cogs.tickets as tickets_module
from cogs.tickets import TicketsCog
from ui.views.ticket_view import TicketPanelButtonView, TicketView


class SessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


@pytest.mark.asyncio
async def test_startup_restores_panel_and_ticket_views(monkeypatch):
    panel = SimpleNamespace(
        id=11,
        panel_message_id=101,
        button_label="Создать заявку",
        button_emoji=None,
    )
    ticket = SimpleNamespace(id=22, guild_id=33, ticket_message_id=202)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [panel])),
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [ticket])),
            ]
        )
    )
    monkeypatch.setattr(
        tickets_module,
        "async_session_maker",
        lambda: SessionContext(session),
    )
    bot = SimpleNamespace(add_view=Mock())

    await TicketsCog(bot)._restore_persistent_views()

    assert bot.add_view.call_count == 2
    panel_view = bot.add_view.call_args_list[0].args[0]
    ticket_view = bot.add_view.call_args_list[1].args[0]
    assert isinstance(panel_view, TicketPanelButtonView)
    assert isinstance(ticket_view, TicketView)
    assert bot.add_view.call_args_list[0].kwargs == {"message_id": 101}
    assert bot.add_view.call_args_list[1].kwargs == {"message_id": 202}
