import asyncio
import itertools
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from src.chat.cogs import bot_dialogue_cog as feature
from src.chat.services.bot_dialogue_service import BotDialogue, BotDialogueService


class TypingProbe:
    def __init__(self):
        self.active = False
        self.entered = self.exited = 0

    async def __aenter__(self):
        self.active = True
        self.entered += 1

    async def __aexit__(self, *args):
        self.active = False
        self.exited += 1


def private_channel(guild, bots, id=12):
    channel = Mock(spec=discord.TextChannel)
    channel.id, channel.guild = id, guild
    default = Mock(spec=discord.Role)
    default.id = guild.id
    guild.default_role = default
    channel.overwrites = {default: discord.PermissionOverwrite(view_channel=False)}
    channel.overwrites.update({discord.Object(id=bot): discord.PermissionOverwrite(view_channel=True) for bot in bots})
    channel.overwrites_for = lambda role: channel.overwrites.get(role, discord.PermissionOverwrite())
    channel.send = AsyncMock()
    return channel


def configure(monkeypatch):
    monkeypatch.setattr(feature, "CHAT_ENABLED", True)
    monkeypatch.setattr(feature.takeover_service, "message_active", AsyncMock(return_value=False))
    monkeypatch.setattr(feature.takeover_service, "channel_active", AsyncMock(return_value=False))
    monkeypatch.setattr(feature.chat_settings_service, "is_chat_globally_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(feature.chat_settings_service, "get_current_ai_model", AsyncMock(return_value="model"))
    generate = AsyncMock(return_value=SimpleNamespace(content="你好，我们聊聊吧。"))
    monkeypatch.setattr(feature.ai_service, "generate", generate)
    return generate


def test_migration_reservations_survive_restart_and_replay(tmp_path):
    path = tmp_path / "dialogue.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE bot_dialogues (channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER,target_id INTEGER,operator_id INTEGER,topic TEXT,turn_limit INTEGER,
            sent INTEGER,last_our_id INTEGER,last_target_id INTEGER,expires_at REAL)""")

    async def run():
        store = BotDialogueService(path, clock=lambda: 1000)
        s = BotDialogue(11, 1, 3, 5, "话题", 2, 1, 100, 0, 1600, "invite")
        assert await store.start(s)
        reserved = await store.reserve(s, 200)
        assert reserved.sent == 2
        assert await store.reserve(s, 200) is None
        restarted = BotDialogueService(path, clock=lambda: 1000)
        assert (await restarted.get(11)).sent == 2
        assert not (await restarted.get(11)).active(1000)
        assert await restarted.complete(reserved, 300)
        await restarted.stop(11)
        assert not await restarted.start(s)  # even after completion/stop

    asyncio.run(run())


def test_two_bots_reach_cap_without_reopening(monkeypatch, tmp_path):
    generate = configure(monkeypatch)

    async def run():
        ids = itertools.count(1000)
        guild = SimpleNamespace(id=1)
        users = {i: SimpleNamespace(id=i, bot=True, display_name=f"Bot{i}") for i in (20, 30)}
        stores = {i: BotDialogueService(tmp_path / f"bot{i}.db") for i in users}
        cogs = {i: feature.BotDialogueCog(SimpleNamespace(user=user)) for i, user in users.items()}
        for cog in cogs.values():
            cog.trusted_peers, cog.allowed_guilds = {20, 30}, {1}
        messages = {}
        queue = []
        typing = TypingProbe()
        channel = Mock(spec=discord.TextChannel)
        channel.id, channel.guild = 11, guild
        channel.fetch_message = AsyncMock(side_effect=lambda id: messages[id])
        channel.typing = lambda: typing
        control = private_channel(guild, users)
        for cog in cogs.values():
            cog.control_channel_id = control.id
            cog.bot.get_channel = lambda id: {11: channel, 12: control}.get(id)

        def message(author, target, content, reference=None, embeds=()):
            m = SimpleNamespace(id=next(ids), author=users[author], guild=guild, channel=channel,
                                content=content, mentions=[users[target]], webhook_id=None,
                                reference=SimpleNamespace(message_id=reference) if reference else None,
                                embeds=list(embeds))

            async def reply(text, **kwargs):
                result = message(target, author, text, reference=m.id)
                queue.append((author, result))
                return result

            m.reply = AsyncMock(side_effect=reply)
            messages[m.id] = m
            return m

        session_id = "a" * 32
        expires = int(time.time()) + 600
        opener = message(20, 30, "<@30> 聊聊")
        embed = discord.Embed(title="限轮 Bot 对话（管理员控制）")
        embed.set_footer(text=f"互聊控制 {session_id} / 30 / 1 / 11 / {opener.id} / 4 / {expires}")
        invitation = SimpleNamespace(id=next(ids), author=users[20], guild=guild, channel=control,
                                     content="", mentions=[], reference=None, embeds=[embed], webhook_id=None)
        await stores[20].start(BotDialogue(11, 1, 30, 99, "聊聊", 4, 1, opener.id, 0,
                                           expires, session_id))
        queue.append((30, opener))
        queue.append((30, invitation))
        delivered = 0
        while queue and delivered < 30:
            recipient, msg = queue.pop(0)
            monkeypatch.setattr(feature, "bot_dialogue_service", stores[recipient])
            await cogs[recipient].on_message(msg)
            delivered += 1
        assert not queue
        assert len(messages) == 8
        assert generate.await_count == 7
        assert typing.entered == typing.exited == 7 and not typing.active
        assert all(not msg.embeds for msg in messages.values())
        for store in stores.values():
            assert (await store.get(11)).sent == 4
        # Replaying the invitation after the cap, including after store recreation,
        # must not create another chat session.
        monkeypatch.setattr(feature, "bot_dialogue_service", BotDialogueService(stores[30].path))
        await cogs[30].on_message(invitation)
        assert len(messages) == 8 and generate.await_count == 7
        assert all(call.kwargs["tools"] is None for call in generate.await_args_list)

    asyncio.run(run())


def test_untrusted_invites_and_unrelated_human_replies_are_ignored(monkeypatch, tmp_path):
    generate = configure(monkeypatch)

    async def run():
        store = BotDialogueService(tmp_path / "state.db")
        monkeypatch.setattr(feature, "bot_dialogue_service", store)
        cog = feature.BotDialogueCog(SimpleNamespace(user=SimpleNamespace(id=99)))
        cog.trusted_peers, cog.allowed_guilds = {3}, {1}
        expires = int(time.time()) + 600
        embed = discord.Embed()
        embed.set_footer(text=f"互聊控制 {'a' * 32} / 99 / 1 / 11 / 200 / 4 / {expires}")
        m = SimpleNamespace(id=200, author=SimpleNamespace(id=4, bot=True),
                            guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=11),
                            mentions=[SimpleNamespace(id=99)], content="你好", reference=None,
                            embeds=[embed], webhook_id=None, reply=AsyncMock())
        await cog.on_message(m)
        assert await store.get(11) is None
        await store.start(BotDialogue(11, 1, 3, 5, "话题", 4, 1, 100, 0, expires, "b" * 32))
        m.author.id = 3
        m.reference = SimpleNamespace(message_id=150)  # replying to a human, even if mentioning us
        await cog.on_message(m)
        assert generate.await_count == 0

    asyncio.run(run())


def test_stop_during_generation_prevents_send(monkeypatch, tmp_path):
    configure(monkeypatch)

    async def run():
        store = BotDialogueService(tmp_path / "state.db")
        monkeypatch.setattr(feature, "bot_dialogue_service", store)
        await store.start(BotDialogue(11, 1, 3, 5, "话题", 4, 1, 100, 0, time.time() + 600, "c" * 32))
        entered, release = asyncio.Event(), asyncio.Event()

        async def generate(**kwargs):
            assert typing.active
            entered.set()
            await release.wait()
            return SimpleNamespace(content="不应发送")

        monkeypatch.setattr(feature.ai_service, "generate", generate)
        cog = feature.BotDialogueCog(SimpleNamespace(user=SimpleNamespace(id=99)))
        typing = TypingProbe()
        m = SimpleNamespace(id=200, author=SimpleNamespace(id=3, bot=True, display_name="peer"),
                            guild=SimpleNamespace(id=1), content="你好", mentions=[], embeds=[],
                            webhook_id=None, reference=SimpleNamespace(message_id=100), reply=AsyncMock(),
                            channel=SimpleNamespace(id=11, typing=lambda: typing,
                                fetch_message=AsyncMock(return_value=SimpleNamespace(content="hi"))))
        task = asyncio.create_task(cog.on_message(m))
        await entered.wait()
        await store.stop(11)
        release.set()
        await task
        m.reply.assert_not_awaited()
        assert not typing.active and typing.exited == 1

    asyncio.run(run())


def test_start_keeps_metadata_private_and_uses_native_typing(monkeypatch, tmp_path):
    configure(monkeypatch)

    async def run():
        store = BotDialogueService(tmp_path / "state.db")
        monkeypatch.setattr(feature, "bot_dialogue_service", store)
        target_id = 0
        target = SimpleNamespace(id=target_id, bot=True, mention=f"<@{target_id}>")
        guild = SimpleNamespace(id=1, fetch_member=AsyncMock(return_value=target))
        channel = Mock(spec=discord.TextChannel)
        channel.id, channel.guild, channel.mention = 11, guild, "<#11>"
        channel.send = AsyncMock(return_value=SimpleNamespace(id=100))
        typing = TypingProbe()
        channel.typing = lambda: typing
        control = private_channel(guild, [target_id, 99])
        cog = feature.BotDialogueCog(SimpleNamespace(user=SimpleNamespace(id=99), get_channel=lambda _: control))
        cog.trusted_peers, cog.allowed_guilds, cog.control_channel_id = {target_id, 99}, {1}, 12
        interaction = SimpleNamespace(guild=guild, guild_id=1, channel=channel, user=SimpleNamespace(id=5),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await cog.start.callback(cog, interaction, str(target_id), "你好", 4)
        public = channel.send.call_args
        assert public.args[0] == f"<@{target_id}> 你好"
        assert "embed" not in public.kwargs and "embeds" not in public.kwargs
        assert "限轮" not in public.args[0]
        assert control.send.await_count == 1
        assert feature.CONTROL_RE.fullmatch(control.send.call_args.kwargs["embed"].footer.text)
        assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
        assert typing.entered == typing.exited == 1

    asyncio.run(run())


def test_control_channel_must_be_private_and_allow_only_bots_or_admins():
    guild = SimpleNamespace(id=1)
    channel = private_channel(guild, [20, 30])
    cog = feature.BotDialogueCog(SimpleNamespace(user=SimpleNamespace(id=20)))
    cog.allowed_guilds, cog.trusted_peers, cog.control_channel_id = {1}, {20, 30}, channel.id
    assert cog._is_private_control(channel)
    role = Mock(spec=discord.Role)
    role.id, role.permissions = 300, discord.Permissions.none()
    channel.overwrites[role] = discord.PermissionOverwrite(view_channel=True)
    assert not cog._is_private_control(channel)
    channel.overwrites.pop(role)
    channel.overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True)
    assert not cog._is_private_control(channel)


def test_search_fetches_uncached_bots(monkeypatch):
    async def run():
        async def members(**kwargs):
            yield SimpleNamespace(id=3, display_name="Other AI", bot=True)
            yield SimpleNamespace(id=99, display_name="self", bot=True)
        cog = feature.BotDialogueCog(SimpleNamespace(user=SimpleNamespace(id=99)))
        monkeypatch.setattr(cog, "_admin", lambda _: True)
        guild = SimpleNamespace(id=1, member_count=2, members=[], fetch_members=members)
        choices = await cog.target_autocomplete(SimpleNamespace(guild=guild), "other")
        assert [choice.value for choice in choices] == ["3"]
    asyncio.run(run())


def test_named_user_is_authorized_only_for_dialogue():
    from src.chat.cogs.takeover_cog import TakeoverCog
    user_id = 0

    def interaction(id, admin=False, guild_id=1):
        member = Mock(spec=discord.Member)
        member.id, member.guild_permissions = id, discord.Permissions(administrator=admin)
        return SimpleNamespace(guild=SimpleNamespace(id=guild_id), user=member,
            response=SimpleNamespace(send_message=AsyncMock()))

    async def run():
        cog = feature.BotDialogueCog(SimpleNamespace())
        cog.allowed_guilds, cog.dialogue_operators = {1}, {user_id}
        target = interaction(user_id)
        assert await cog.cog_app_command_check(target)
        assert not await cog.cog_app_command_check(interaction(user_id + 1))
        assert not await cog.cog_app_command_check(interaction(user_id, guild_id=2))
        assert await cog.cog_app_command_check(interaction(50, admin=True))
        assert not await TakeoverCog(SimpleNamespace()).cog_app_command_check(target)
        assert cog.control.default_permissions is None
        assert TakeoverCog.control.default_permissions.administrator

    asyncio.run(run())


def test_allowlisted_user_can_manage_only_own_dialogue(monkeypatch, tmp_path):
    user_id = 0

    async def run():
        store = BotDialogueService(tmp_path / "state.db")
        monkeypatch.setattr(feature, "bot_dialogue_service", store)
        cog = feature.BotDialogueCog(SimpleNamespace())
        member = Mock(spec=discord.Member)
        member.id, member.guild_permissions = user_id, discord.Permissions.none()
        interaction = SimpleNamespace(guild=SimpleNamespace(id=1), user=member, channel_id=11,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        session = BotDialogue(11, 1, 3, 5, "admin topic", 4, 1, 100, 0, time.time() + 600, "owner-test")
        await store.start(session)
        await cog.stop.callback(cog, interaction)
        assert (await store.get(11)).active(time.time())
        assert "本人" in interaction.followup.send.call_args.args[0]
        await cog.status.callback(cog, interaction)
        assert "<@3>" not in interaction.followup.send.call_args.args[0]
        own = BotDialogue(11, 1, 3, user_id, "own topic", 4, 1, 100, 0, time.time() + 600, "own-test")
        await store.start(own)
        await cog.status.callback(cog, interaction)
        assert "<@3>" in interaction.followup.send.call_args.args[0]
        await cog.stop.callback(cog, interaction)
        assert not (await store.get(11)).active(time.time())

    asyncio.run(run())


def test_registered_commands_enforce_the_operator_gate(monkeypatch):
    from discord.ext import commands

    async def run():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            cog = feature.BotDialogueCog(bot)
            cog.allowed_guilds, cog.dialogue_operators = {1}, {0}
            monkeypatch.setattr(cog, "cog_load", AsyncMock())
            await bot.add_cog(cog)
            group = bot.tree.get_command("机器人对话")
            for name in ("开始", "停止", "状态"):
                command = group.get_command(name)
                for user_id, expected in ((0, True), (0, False)):
                    member = Mock(spec=discord.Member)
                    member.id, member.guild_permissions = user_id, discord.Permissions.none()
                    interaction = SimpleNamespace(client=bot, guild=SimpleNamespace(id=1), user=member,
                        response=SimpleNamespace(send_message=AsyncMock()))
                    assert await command._check_can_run(interaction) is expected
    asyncio.run(run())
