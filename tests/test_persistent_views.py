from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import core.persistent_views as registry_module
from core.persistent_views import PersistentViewRegistry
from modules.recruitment.views import RecruitmentPanelView, RecruitmentTicketView
from modules.roles.views import RolePanelView
from ui.views.ticket_view import TicketPanelButtonView, TicketView


class SessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


def _result(rows):
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


@pytest.mark.asyncio
async def test_registry_restores_views_from_all_modules(monkeypatch):
    order_panel = SimpleNamespace(
        id=11,
        panel_message_id=101,
        button_label="Создать заявку",
        button_emoji=None,
    )
    order_ticket = SimpleNamespace(id=22, guild_id=33, ticket_message_id=202)
    role_item = SimpleNamespace(
        id=44, label="Logistics", emoji=None, enabled=True, position=1
    )
    role_panel = SimpleNamespace(id=33, panel_message_id=303, items=[role_item])
    recruitment_settings = SimpleNamespace(
        id=55,
        panel_message_id=404,
        button_label="Подать заявку",
        button_emoji=None,
    )
    recruitment_application = SimpleNamespace(
        id=66,
        guild_id=77,
        ticket_message_id=505,
        status="ACCEPTED",
        closed_at=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[
            _result([order_panel]),
            _result([order_ticket]),
            _result([role_panel]),
            _result([recruitment_settings]),
            _result([recruitment_application]),
        ])
    )
    monkeypatch.setattr(
        registry_module,
        "async_session_maker",
        lambda: SessionContext(session),
    )
    bot = SimpleNamespace(add_view=Mock())

    stats = await PersistentViewRegistry.restore(bot)

    assert stats.total == 5
    assert bot.add_view.call_count == 5
    expected = [
        (TicketPanelButtonView, 101),
        (TicketView, 202),
        (RolePanelView, 303),
        (RecruitmentPanelView, 404),
        (RecruitmentTicketView, 505),
    ]
    for call, (view_type, message_id) in zip(bot.add_view.call_args_list, expected):
        assert isinstance(call.args[0], view_type)
        assert call.kwargs == {"message_id": message_id}

    recruitment_view = bot.add_view.call_args_list[-1].args[0]
    assert recruitment_view.accept.disabled is True
    assert recruitment_view.reject.disabled is True
    assert recruitment_view.close.disabled is False
