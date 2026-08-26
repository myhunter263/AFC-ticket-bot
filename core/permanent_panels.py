from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MessageKind(StrEnum):
    """A common vocabulary for permanent panels and temporary messages."""

    ORDER_PANEL = "ORDER_PANEL"
    ROLE_PANEL = "ROLE_PANEL"
    RECRUITMENT_PANEL = "RECRUITMENT_PANEL"
    ORDER_TICKET = "ORDER_TICKET"
    RECRUITMENT_TICKET = "RECRUITMENT_TICKET"
    TEMPORARY_ADMIN = "TEMPORARY_ADMIN"


class PanelType(StrEnum):
    ORDER = "ORDER"
    ROLE = "ROLE"
    RECRUITMENT = "RECRUITMENT"


PERMANENT_KINDS = {
    MessageKind.ORDER_PANEL,
    MessageKind.ROLE_PANEL,
    MessageKind.RECRUITMENT_PANEL,
}


@dataclass(frozen=True, slots=True)
class PermanentMessageRef:
    kind: MessageKind
    channel_id: int
    message_id: int

    @property
    def is_permanent(self) -> bool:
        return self.kind in PERMANENT_KINDS


@dataclass(frozen=True, slots=True)
class PermanentPanel:
    """Module-neutral identity of an administrator-managed panel message."""

    panel_id: int
    guild_id: int
    channel_id: int
    message_id: int | None
    panel_type: PanelType
    enabled: bool = True
