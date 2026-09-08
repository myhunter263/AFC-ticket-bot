from cogs.admin import AdminCog
from cogs.points import PointsCog
from cogs.setup import SetupCog
from cogs.tickets import TicketsCog
from modules.orders.commands import marker_aliases


def test_slash_commands_use_hec_prefix_and_hector_description():
    commands = [command for cog in (AdminCog, PointsCog, SetupCog, TicketsCog)
                for command in cog.__cog_app_commands__]
    assert len([c for c in commands if c.name.startswith("hec-")]) >= 25
    assert not any(c.name.startswith("afc-") or "AFC" in c.description for c in commands)
    assert {"hec-admin", "hec-setup", "hec-close", "hec-points"} <= {c.name for c in commands}


def test_existing_discord_markers_remain_recognizable():
    assert marker_aliases("Hector CRM panel 123") == {"Hector CRM panel 123", "AFC CRM panel 123"}
    assert marker_aliases("Hector CRM notification 12") == {"Hector CRM notification 12", "AFC CRM notification 12"}
