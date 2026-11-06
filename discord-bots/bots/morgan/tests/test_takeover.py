import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord.ext import commands

from src.chat.services.takeover_service import TakeoverService, TakeoverError
from src.chat.cogs import takeover_cog as feature


def test_sessions_persist_expire_and_enforce_ownership(tmp_path):
    clock = [1000.0]
    store = TakeoverService(tmp_path / "sessions.db", clock=lambda: clock[0])

    async def run():
        await store.start("channel:10", 1, 2, 5)
        assert await store.channel_active(SimpleNamespace(id=10))
        assert await store.channel_active(SimpleNamespace(id=11, parent_id=10))
        assert not await store.channel_active(SimpleNamespace(id=12))
        restarted = TakeoverService(store.path, clock=lambda: clock[0])
        assert await restarted.get("channel:10")
        with pytest.raises(TakeoverError):
            await restarted.start("channel:10", 1, 3, 5)
        with pytest.raises(TakeoverError):
            await restarted.stop("channel:10", 9, 2)
        clock[0] += 301
        assert not await restarted.get("channel:10")
        await restarted.start("dm:30", 1, 2, 5)
        assert await restarted.message_active(SimpleNamespace(guild=None, author=SimpleNamespace(id=30)))
        assert await restarted.stop("dm:30", 1, 2)
        assert not await restarted.get("dm:30")

    asyncio.run(run())


def make_interaction(admin=True):
    guild = SimpleNamespace(id=1, me=SimpleNamespace(id=99))
    user = Mock(spec=discord.Member)
    user.id = 2
    user.guild = guild
    user.guild_permissions = discord.Permissions(administrator=admin)
    channel = Mock(spec=discord.TextChannel)
    channel.id = 10
    channel.guild = guild
    channel.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True, read_message_history=True)
    channel.send = AsyncMock(return_value=SimpleNamespace(id=123))
    interaction = SimpleNamespace(
        guild=guild, guild_id=1, user=user, channel=channel,
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: True),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    return interaction


def test_admin_runtime_check_rejects_regular_members():
    cog = feature.TakeoverCog(SimpleNamespace())
    regular = make_interaction(admin=False)
    assert not asyncio.run(cog.cog_app_command_check(regular))
    assert regular.response.send_message.call_args.kwargs["ephemeral"] is True
    assert asyncio.run(cog.cog_app_command_check(make_interaction()))


def test_send_uses_bot_exact_content_and_private_ack(monkeypatch, tmp_path):
    store = TakeoverService(tmp_path / "sessions.db")
    monkeypatch.setattr(feature, "takeover_service", store)
    cog = feature.TakeoverCog(SimpleNamespace())
    interaction = make_interaction()
    asyncio.run(cog._send(interaction, "测试内容"))
    interaction.channel.send.assert_awaited_once()
    args = interaction.channel.send.call_args
    assert args.args == ("测试内容",)
    assert args.kwargs["allowed_mentions"].everyone is False
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True


def test_dm_only_targets_local_human_members(monkeypatch, tmp_path):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))
    cog = feature.TakeoverCog(SimpleNamespace())
    interaction = make_interaction()
    target = Mock(spec=discord.Member)
    target.id, target.bot, target.guild = 30, False, interaction.guild
    target.send = AsyncMock(return_value=SimpleNamespace(id=124))
    asyncio.run(cog._send(interaction, "私信内容", user=target))
    target.send.assert_awaited_once()
    target.guild = SimpleNamespace(id=999)
    with pytest.raises(TakeoverError):
        asyncio.run(cog._send(interaction, "不能跨服务器", user=target))


def test_other_operator_cannot_send_or_view_owned_session(monkeypatch, tmp_path):
    store = TakeoverService(tmp_path / "sessions.db")
    monkeypatch.setattr(feature, "takeover_service", store)
    cog = feature.TakeoverCog(SimpleNamespace())
    interaction = make_interaction()

    async def run():
        await store.start("channel:10", 1, 3, 5)
        with pytest.raises(TakeoverError):
            await cog._send(interaction, "blocked")
        with pytest.raises(TakeoverError):
            await cog._check_owner(interaction, "channel:10", interaction.channel, required=True)
        interaction.channel.send.assert_not_awaited()

    asyncio.run(run())


def test_command_registration_is_admin_only_and_guild_only(monkeypatch, tmp_path):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))

    async def run():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        await bot.add_cog(feature.TakeoverCog(bot))
        command = bot.tree.get_command("接管")
        assert command.default_permissions.administrator
        assert command.guild_only
        assert {cmd.name for cmd in command.commands} == {"开始", "结束", "发言", "私信", "查看", "状态"}
        payload = command.to_dict(bot.tree)
        assert payload["name"] == "接管"
        for name in ("发言", "私信"):
            options = next(item for item in payload["options"] if item["name"] == name)["options"]
            reply = next(item for item in options if item["name"] == "回复消息")
            assert reply["type"] == 3 and not reply["required"]
        await bot.close()

    asyncio.run(run())


def test_ai_chat_stops_before_processing_during_takeover(monkeypatch, tmp_path):
    from src.chat.cogs import ai_chat_cog as chat
    store = TakeoverService(tmp_path / "sessions.db")
    monkeypatch.setattr(chat, "takeover_service", store)
    monkeypatch.setattr(chat, "CHAT_ENABLED", True)
    processor = AsyncMock()
    monkeypatch.setattr(chat.message_processor, "process_message", processor)
    message = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(bot=False), channel=SimpleNamespace(id=10))

    async def run():
        await store.start("channel:10", 1, 2, 5)
        await chat.AIChatCog(SimpleNamespace()).on_message(message)
        processor.assert_not_awaited()

    asyncio.run(run())


def test_comment_generated_before_takeover_is_not_sent(monkeypatch, tmp_path):
    import importlib.util
    if importlib.util.find_spec("src.chat.features.engagement") is None:
        pytest.skip("This bot does not include automatic engagement comments")
    from src.chat.features.engagement.cogs import engagement_cog as engagement
    store = TakeoverService(tmp_path / "takeover.db")
    monkeypatch.setattr(engagement, "takeover_service", store)
    cog = engagement.EngagementCog(SimpleNamespace(user=SimpleNamespace(id=99)))
    cog.store = engagement.EngagementStore(tmp_path / "engagement.db")
    channel = SimpleNamespace(id=10)

    async def history(limit):
        if False:
            yield None

    async def generate(_):
        await store.start("channel:10", 1, 2, 30)
        return "不应发出的自动点评"

    channel.history = history
    message = SimpleNamespace(
        id=20, guild=SimpleNamespace(id=1), channel=channel,
        author=SimpleNamespace(id=3), content="模拟消息", reply=AsyncMock(),
    )
    cog._generate_comment = generate
    asyncio.run(cog._comment(message))
    message.reply.assert_not_awaited()


def test_dm_error_response_is_private():
    cog = feature.TakeoverCog(SimpleNamespace())
    interaction = make_interaction()
    error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "closed DM")
    asyncio.run(cog.cog_app_command_error(interaction, error))
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True


def test_no_channel_send_permission_blocks_send_but_not_end(monkeypatch, tmp_path):
    store = TakeoverService(tmp_path / "sessions.db")
    monkeypatch.setattr(feature, "takeover_service", store)
    interaction = make_interaction()
    interaction.channel.permissions_for.return_value = discord.Permissions(view_channel=True)
    cog = feature.TakeoverCog(SimpleNamespace())
    with pytest.raises(TakeoverError):
        asyncio.run(cog._send(interaction, "不能发出"))
    interaction.channel.send.assert_not_awaited()
    scope, _ = asyncio.run(cog._target(interaction))
    assert scope == "channel:10"


@pytest.mark.parametrize("value,expected", [
    (" 123 ", (None, None, 123)),
    ("https://discord.com/channels/1/10/123", ("1", 10, 123)),
    ("<https://canary.discord.com/channels/@me/20/123>", ("@me", 20, 123)),
    ("https://discordapp.com/channels/1/10/123?foo=bar", ("1", 10, 123)),
])
def test_reply_target_parser(value, expected):
    assert feature.parse_reply_target(value) == expected


@pytest.mark.parametrize("value", ["", "0", "-1", "0", "abc", "https://evil.example/channels/1/10/123", "https://discord.com@evil.example/channels/1/10/123"])
def test_reply_target_parser_rejects_bad_input(value):
    with pytest.raises(TakeoverError):
        feature.parse_reply_target(value)


def prepare_reference(channel):
    reference = discord.MessageReference(message_id=456, channel_id=channel.id, fail_if_not_exists=True)
    message = Mock()
    message.to_reference.return_value = reference
    channel.fetch_message = AsyncMock(return_value=message)
    return message, reference


def test_channel_native_reply(monkeypatch, tmp_path):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))
    cog, interaction = feature.TakeoverCog(SimpleNamespace()), make_interaction()
    message, reference = prepare_reference(interaction.channel)
    asyncio.run(cog.speak.callback(cog, interaction, "引用回复", reply_to="https://discord.com/channels/1/10/456"))
    interaction.channel.fetch_message.assert_awaited_once_with(456)
    message.to_reference.assert_called_once_with(fail_if_not_exists=True)
    kwargs = interaction.channel.send.call_args.kwargs
    assert kwargs["reference"] is reference
    assert kwargs["mention_author"] is True
    assert kwargs["allowed_mentions"].roles is False
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True


def test_dm_native_reply(monkeypatch, tmp_path):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))
    cog, interaction = feature.TakeoverCog(SimpleNamespace()), make_interaction()
    target = Mock(spec=discord.Member)
    target.id, target.bot, target.guild, target.dm_channel = 30, False, interaction.guild, None
    dm = SimpleNamespace(id=20, send=AsyncMock(return_value=SimpleNamespace(id=789)))
    _, reference = prepare_reference(dm)
    target.create_dm = AsyncMock(return_value=dm)
    asyncio.run(cog.dm.callback(cog, interaction, target, "私信回复", reply_to="https://discord.com/channels/@me/20/456"))
    target.create_dm.assert_awaited_once()
    dm.fetch_message.assert_awaited_once_with(456)
    assert dm.send.call_args.kwargs["reference"] is reference


@pytest.mark.parametrize("link", ["https://discord.com/channels/2/10/456", "https://discord.com/channels/1/11/456", "https://discord.com/channels/@me/10/456"])
def test_wrong_reply_scope_never_fetches_or_sends(monkeypatch, tmp_path, link):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))
    cog, interaction = feature.TakeoverCog(SimpleNamespace()), make_interaction()
    prepare_reference(interaction.channel)
    with pytest.raises(TakeoverError):
        asyncio.run(cog._send(interaction, "不能发送", reply_to=link))
    interaction.channel.fetch_message.assert_not_awaited()
    interaction.channel.send.assert_not_awaited()


@pytest.mark.parametrize("who", ["operator", "bot"])
def test_reply_requires_history_for_both_parties(monkeypatch, tmp_path, who):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))
    cog, interaction = feature.TakeoverCog(SimpleNamespace()), make_interaction()
    prepare_reference(interaction.channel)
    blocked = interaction.user if who == "operator" else interaction.guild.me
    interaction.channel.permissions_for.side_effect = lambda member: discord.Permissions(
        view_channel=True, send_messages=True, read_message_history=member is not blocked)
    with pytest.raises(TakeoverError):
        asyncio.run(cog._send(interaction, "不能发送", reply_to="456"))
    interaction.channel.fetch_message.assert_not_awaited()
    interaction.channel.send.assert_not_awaited()


@pytest.mark.parametrize("status,error_type,expected", [(404, discord.NotFound, TakeoverError), (403, discord.Forbidden, discord.Forbidden)])
def test_missing_or_forbidden_reply_never_sends_standalone(monkeypatch, tmp_path, status, error_type, expected):
    monkeypatch.setattr(feature, "takeover_service", TakeoverService(tmp_path / "sessions.db"))
    cog, interaction = feature.TakeoverCog(SimpleNamespace()), make_interaction()
    prepare_reference(interaction.channel)
    interaction.channel.fetch_message.side_effect = error_type(SimpleNamespace(status=status, reason="test"), "test")
    with pytest.raises(expected):
        asyncio.run(cog._send(interaction, "不能发送", reply_to="456"))
    interaction.channel.send.assert_not_awaited()


def test_recent_includes_message_id_privately(monkeypatch, tmp_path):
    store = TakeoverService(tmp_path / "sessions.db")
    monkeypatch.setattr(feature, "takeover_service", store)
    cog, interaction = feature.TakeoverCog(SimpleNamespace()), make_interaction()

    async def history(**kwargs):
        assert kwargs["after"] is not None
        yield SimpleNamespace(id=456, author=SimpleNamespace(display_name="测试用户"), content="测试消息")

    interaction.channel.history = history

    async def run():
        await store.start("channel:10", 1, 2, 30)
        await cog.recent.callback(cog, interaction)

    asyncio.run(run())
    call = interaction.followup.send.call_args
    assert "`456`" in call.args[0]
    assert call.kwargs["ephemeral"] is True
