from types import SimpleNamespace

import discord
import pytest

from core.permanent_panels import (
    MessageKind,
    PanelType,
    PermanentMessageRef,
    PermanentPanel,
)
from modules.recruitment.service import RecruitmentService
from modules.recruitment.views import (
    RecruitmentFormState,
    RecruitmentPageModal,
    RecruitmentTicketView,
)
from modules.roles.service import RoleAssignmentError, RolePanelService


class FakeRole:
    def __init__(
        self,
        *,
        role_id: int = 10,
        position: int = 2,
        managed: bool = False,
        default: bool = False,
        **permissions: bool,
    ) -> None:
        self.id = role_id
        self.position = position
        self.managed = managed
        self._default = default
        self.guild = SimpleNamespace(id=1)
        self.permissions = SimpleNamespace(**permissions)

    def is_default(self) -> bool:
        return self._default

    def __ge__(self, other) -> bool:
        return self.position >= other.position


def fake_guild(role: FakeRole, *, bot_position: int = 10, manage_roles: bool = True):
    bot_member = SimpleNamespace(
        top_role=FakeRole(role_id=999, position=bot_position),
        guild_permissions=SimpleNamespace(manage_roles=manage_roles),
    )
    return SimpleNamespace(
        id=1,
        me=bot_member,
        get_role=lambda role_id: role if role_id == role.id else None,
    )


def test_safe_self_role_passes_validation():
    role = FakeRole(send_messages=True)
    RolePanelService.validate_assignable(fake_guild(role), role)


@pytest.mark.parametrize("permission", RolePanelService.DANGEROUS_PERMISSIONS)
def test_dangerous_self_roles_are_rejected(permission):
    role = FakeRole(**{permission: True})
    with pytest.raises(RoleAssignmentError):
        RolePanelService.validate_assignable(fake_guild(role), role)


def test_role_above_bot_is_rejected():
    role = FakeRole(position=10)
    with pytest.raises(RoleAssignmentError):
        RolePanelService.validate_assignable(fake_guild(role, bot_position=10), role)


def test_recruitment_form_is_split_into_five_field_pages():
    questions = [
        {
            "id": index,
            "label": f"Question {index}",
            "placeholder": None,
            "input_style": "short",
            "required": True,
            "min_length": 0,
            "max_length": 100,
        }
        for index in range(7)
    ]
    state = RecruitmentFormState(settings_id=1, author_id=2, questions=questions)

    assert len(RecruitmentPageModal(state, 0).children) == 5
    assert len(RecruitmentPageModal(state, 5).children) == 2


def test_recruitment_review_buttons_follow_application_state():
    pending = RecruitmentTicketView(1, 1)
    accepted = RecruitmentTicketView(1, 1, status="ACCEPTED")
    closed = RecruitmentTicketView(1, 1, status="REJECTED", closed=True)

    assert [button.disabled for button in pending.children] == [False, False, True]
    assert [button.disabled for button in accepted.children] == [True, True, False]
    assert all(button.disabled for button in closed.children)


def test_recruitment_channel_names_are_sanitized():
    user = SimpleNamespace(name="User Name!", id=42)
    name = RecruitmentService.sanitize_channel_name(
        "recruit-{username}-{application_id}", user, 17
    )
    assert name == "recruit-user-name-17"


def test_permanent_message_classification():
    panel = PermanentMessageRef(MessageKind.ROLE_PANEL, 10, 20)
    temporary = PermanentMessageRef(MessageKind.TEMPORARY_ADMIN, 10, 21)

    assert panel.is_permanent is True
    assert temporary.is_permanent is False

    common_panel = PermanentPanel(1, 2, 3, 4, PanelType.RECRUITMENT)
    assert common_panel.panel_type is PanelType.RECRUITMENT
