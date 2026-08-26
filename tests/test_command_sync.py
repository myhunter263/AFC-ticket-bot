from types import SimpleNamespace

import pytest

from core.command_sync import sync_commands_to_guild


class FakeTree:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def copy_global_to(self, *, guild) -> None:
        self.calls.append(("copy", guild.id))

    async def sync(self, *, guild):
        self.calls.append(("sync", guild.id))
        return ["calc", "train"]


@pytest.mark.asyncio
async def test_guild_sync_copies_global_commands_before_publish():
    bot = SimpleNamespace(tree=FakeTree())

    synced = await sync_commands_to_guild(bot, SimpleNamespace(id=222))

    assert synced == ["calc", "train"]
    assert bot.tree.calls == [("copy", 222), ("sync", 222)]
