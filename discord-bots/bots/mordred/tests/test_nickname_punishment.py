import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord.ext import commands

from src.chat.cogs import nickname_punishment_cog as feature
from src.chat.services.nickname_punishment_service import NicknamePunishmentService


def fixture(monkeypatch, tmp_path):
    now = [1000.0]
    store = NicknamePunishmentService(tmp_path / "nicknames.db", clock=lambda: now[0])
    monkeypatch.setattr(feature, "nickname_punishment_service", store)
    guild = Mock(spec=discord.Guild)
    guild.id, guild.owner_id = 1, 900
    owner = Mock(spec=discord.Member)
    owner.id, owner.guild = 2, guild
    owner.guild_permissions = discord.Permissions(administrator=True)
    owner.top_role = 50
    bot_member = Mock(spec=discord.Member)
    bot_member.id, bot_member.guild = 99, guild
    bot_member.guild_permissions = discord.Permissions(manage_nicknames=True)
    bot_member.top_role = 100
    guild.me = bot_member
    member = Mock(spec=discord.Member)
    member.id, member.guild, member.nick, member.bot, member.top_role = 3, guild, "原昵称", False, 10
    member.edit = AsyncMock()
    guild.fetch_member = AsyncMock(return_value=member)
    guild.get_member.return_value = member
    bot = SimpleNamespace(get_guild=lambda id: guild, wait_until_ready=AsyncMock())
    interaction = SimpleNamespace(
        guild=guild, guild_id=1, user=owner,
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: True),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    cog = feature.NicknamePunishmentCog(bot)
    return now, store, guild, member, interaction, cog


def test_persist_revert_and_restore_after_expiry(monkeypatch, tmp_path):
    now, store, guild, member, interaction, cog = fixture(monkeypatch, tmp_path)

    async def run():
        await cog.set_nickname.callback(cog, interaction, "惩罚昵称", 5, member)
        assert member.edit.call_args.kwargs["nick"] == "惩罚昵称"
        record = await NicknamePunishmentService(store.path, clock=lambda: now[0]).get(1, 3)
        assert record.original_nick == "原昵称"
        assert record.expires_at == 1300
        before = SimpleNamespace(nick="惩罚昵称")
        member.nick = "自己改名"
        await cog.on_member_update(before, member)
        assert member.edit.call_args.kwargs["nick"] == "惩罚昵称"
        now[0] = 1301
        assert [(r.guild_id, r.user_id) for r in await store.due()] == [(1, 3)]
        member.nick = "惩罚昵称"
        await cog._expire(guild, member)
        assert member.edit.call_args.kwargs["nick"] == "原昵称"
        assert await store.get(1, 3) is None
        assert interaction.followup.send.call_args.kwargs["ephemeral"] is True

    asyncio.run(run())


def test_extension_keeps_original_and_cancel_restores(monkeypatch, tmp_path):
    now, store, _, member, interaction, cog = fixture(monkeypatch, tmp_path)

    async def run():
        await cog.set_nickname.callback(cog, interaction, "第一昵称", 5, member)
        member.nick = "第一昵称"
        now[0] += 20
        await cog.set_nickname.callback(cog, interaction, "第二昵称", 10, member)
        record = await store.get(1, 3)
        assert record.original_nick == "原昵称" and record.expires_at == 1620
        member.nick = "第二昵称"
        await cog.clear_nickname.callback(cog, interaction, member)
        assert member.edit.call_args.kwargs["nick"] == "原昵称"
        assert await store.get(1, 3) is None

    asyncio.run(run())


def test_numeric_id_and_invalid_targets(monkeypatch, tmp_path):
    _, store, guild, member, interaction, cog = fixture(monkeypatch, tmp_path)

    async def run():
        await cog.set_nickname.callback(cog, interaction, "惩罚", 60, None, "3")
        guild.fetch_member.assert_awaited_once_with(3)
        for bad in ("abc", "0", "3 4"):
            with pytest.raises(feature.NicknamePunishmentError):
                await cog._member(interaction, None, bad)
        with pytest.raises(feature.NicknamePunishmentError):
            await cog._member(interaction, member, "3")
        with pytest.raises(feature.NicknamePunishmentError):
            await cog._member(interaction, None, None)
        assert (await store.get(1, 3)).nickname == "惩罚"

    asyncio.run(run())


def test_admin_and_role_boundaries(monkeypatch, tmp_path):
    _, _, guild, member, interaction, cog = fixture(monkeypatch, tmp_path)
    interaction.user.guild_permissions = discord.Permissions(manage_nicknames=True)
    with pytest.raises(feature.NicknamePunishmentError):
        cog._admin(interaction)
    interaction.user.guild_permissions = discord.Permissions(administrator=True)
    interaction.user.top_role = 50
    member.top_role = 50
    with pytest.raises(feature.NicknamePunishmentError):
        cog._can_edit(interaction, member)
    member.top_role = 60
    interaction.user.id = guild.owner_id
    guild.me.top_role = 60
    with pytest.raises(feature.NicknamePunishmentError):
        cog._can_edit(interaction, member)
    member.id = guild.owner_id
    with pytest.raises(feature.NicknamePunishmentError):
        cog._can_edit(interaction, member)


def test_failed_edit_rolls_back_persistent_record(monkeypatch, tmp_path):
    _, store, _, member, interaction, cog = fixture(monkeypatch, tmp_path)
    member.edit.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied")

    async def run():
        with pytest.raises(discord.Forbidden):
            await cog.set_nickname.callback(cog, interaction, "惩罚", 5, member)
        assert await store.get(1, 3) is None

    asyncio.run(run())


def test_command_registration(monkeypatch, tmp_path):
    monkeypatch.setattr(feature, "nickname_punishment_service", NicknamePunishmentService(tmp_path / "nicks.db"))

    async def run():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        await bot.add_cog(feature.NicknamePunishmentCog(bot))
        group = bot.tree.get_command("昵称惩罚")
        assert group.default_permissions.administrator and group.guild_only
        payload = group.to_dict(bot.tree)
        assert {option["name"] for option in payload["options"]} == {"设置", "解除", "状态"}
        setting = next(option for option in payload["options"] if option["name"] == "设置")
        assert {option["name"] for option in setting["options"]} == {"惩罚昵称", "时长分钟", "对象", "用户id"}
        await bot.close()

    asyncio.run(run())
