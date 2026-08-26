from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.models import (
    RecruitmentApplication,
    RecruitmentSettings,
    RolePanel,
    Ticket,
    TicketPanel,
)
from database.session import async_session_maker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RestoreStats:
    order_panels: int = 0
    order_tickets: int = 0
    role_panels: int = 0
    recruitment_panels: int = 0
    recruitment_tickets: int = 0

    @property
    def total(self) -> int:
        return sum((
            self.order_panels,
            self.order_tickets,
            self.role_panels,
            self.recruitment_panels,
            self.recruitment_tickets,
        ))


class PersistentViewRegistry:
    """Restores every module's persistent Discord components in one place."""

    @classmethod
    async def restore(cls, bot: discord.Client) -> RestoreStats:
        # Imports stay local so models and extensions can finish loading first.
        from modules.recruitment.views import RecruitmentPanelView, RecruitmentTicketView
        from modules.roles.views import RolePanelView
        from ui.views.ticket_view import TicketPanelButtonView, TicketView

        stats = RestoreStats()
        async with async_session_maker() as session:
            order_panels = (await session.execute(
                select(TicketPanel).where(
                    TicketPanel.is_active.is_(True),
                    TicketPanel.panel_message_id.is_not(None),
                )
            )).scalars().all()
            for panel in order_panels:
                bot.add_view(
                    TicketPanelButtonView(panel.id, panel.button_label, panel.button_emoji),
                    message_id=panel.panel_message_id,
                )
            stats.order_panels = len(order_panels)

            order_tickets = (await session.execute(
                select(Ticket).where(Ticket.ticket_message_id.is_not(None))
            )).scalars().all()
            for ticket in order_tickets:
                bot.add_view(
                    TicketView(ticket_id=ticket.id, guild_id=ticket.guild_id),
                    message_id=ticket.ticket_message_id,
                )
            stats.order_tickets = len(order_tickets)

            role_panels = (await session.execute(
                select(RolePanel)
                .options(selectinload(RolePanel.items))
                .where(
                    RolePanel.enabled.is_(True),
                    RolePanel.panel_message_id.is_not(None),
                )
            )).scalars().all()
            for panel in role_panels:
                bot.add_view(
                    RolePanelView(panel.id, list(panel.items)),
                    message_id=panel.panel_message_id,
                )
            stats.role_panels = len(role_panels)

            recruitment_panels = (await session.execute(
                select(RecruitmentSettings).where(
                    RecruitmentSettings.enabled.is_(True),
                    RecruitmentSettings.panel_message_id.is_not(None),
                )
            )).scalars().all()
            for settings in recruitment_panels:
                bot.add_view(
                    RecruitmentPanelView(
                        settings.id,
                        settings.button_label,
                        settings.button_emoji,
                    ),
                    message_id=settings.panel_message_id,
                )
            stats.recruitment_panels = len(recruitment_panels)

            applications = (await session.execute(
                select(RecruitmentApplication).where(
                    RecruitmentApplication.ticket_message_id.is_not(None)
                )
            )).scalars().all()
            for application in applications:
                bot.add_view(
                    RecruitmentTicketView(
                        application.id,
                        application.guild_id,
                        status=application.status,
                        closed=application.closed_at is not None,
                    ),
                    message_id=application.ticket_message_id,
                )
            stats.recruitment_tickets = len(applications)

        logger.info(
            "Restored %d persistent views (orders=%d/%d, roles=%d, recruitment=%d/%d).",
            stats.total,
            stats.order_panels,
            stats.order_tickets,
            stats.role_panels,
            stats.recruitment_panels,
            stats.recruitment_tickets,
        )
        return stats
