import asyncio
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from src.chat.features.engagement.cogs import engagement_cog as feature


def _user(user_id, bot=False):
    return SimpleNamespace(id=user_id, bot=bot)


class FakeReaction:
    def __init__(self, emoji, users, me=False):
        self.emoji = emoji
        self._users = users
        self.me = me
        self.count = len(users)

    async def users(self, limit=None):
        for user in self._users[:limit]:
            yield user


def test_human_counts_exclude_bots_and_author_and_choose_safe_emoji():
    author = _user(1)
    message = SimpleNamespace(
        author=author,
        reactions=[
            FakeReaction("👍", [author, _user(2), _user(3), _user(4, bot=True)]),
            FakeReaction("👎", [_user(5), _user(6)]),
        ],
    )
    counts = asyncio.run(feature.human_reaction_counts(message))
    assert counts == Counter({"👍": 2, "👎": 2})
    assert feature.select_reaction(message, counts) == "👍"
    message.reactions[0].me = True
    assert feature.select_reaction(message, counts) is None


class FakeGuildEmoji:
    def __init__(self, emoji_id, name, usable=True):
        self.id = emoji_id
        self.name = name
        self._usable = usable

    def is_usable(self):
        return self._usable

    def __str__(self):
        return f"<:{self.name}:{self.id}>"


def test_guild_and_default_reactions_are_candidates():
    custom = FakeGuildEmoji(123, "community")
    message = SimpleNamespace(
        id=42,
        guild=SimpleNamespace(emojis=[custom]),
        reactions=[FakeReaction(custom, [_user(2), _user(3)])],
    )
    assert feature.select_reaction(message, Counter({str(custom): 2})) is custom
    message.reactions = [FakeReaction("🐷", [_user(2), _user(3)])]
    assert feature.select_reaction(message, Counter({"🐷": 2})) == "🐷"
    message.reactions = [FakeReaction("😂", [_user(2), _user(3)])]
    assert feature.select_reaction(message, Counter({"😂": 2})) == "😂"
    message.reactions.append(FakeReaction("👍", [_user(99, bot=True)], me=True))
    assert feature.select_reaction(message, Counter({"😂": 2})) is None


def test_usable_guild_pool_is_available_as_fallback():
    custom = FakeGuildEmoji(123, "community")
    unavailable = FakeGuildEmoji(124, "retired", usable=False)
    message = SimpleNamespace(
        id=0,
        guild=SimpleNamespace(emojis=[unavailable, custom]),
        reactions=[FakeReaction("👎", [_user(2), _user(3)])],
    )
    assert feature.select_reaction(message, Counter({"👎": 2})) is custom
    message.guild.emojis = [unavailable]
    assert feature.select_reaction(message, Counter({str(unavailable): 2})) == "😂"


def test_four_human_reactions_trigger_one_reaction_and_one_comment(monkeypatch, tmp_path):
    bot = SimpleNamespace(user=_user(99), get_channel=lambda _: channel)
    channel = Mock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock()
    cog = feature.EngagementCog(bot)
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    cog._eligible = AsyncMock(return_value=True)
    cog._react = AsyncMock()
    cog._comment = AsyncMock()
    message = SimpleNamespace(
        id=44,
        guild=SimpleNamespace(id=1),
        channel=channel,
        author=_user(10),
        mentions=[],
        created_at=datetime.now(timezone.utc),
        reactions=[FakeReaction("👍", [_user(2), _user(3), _user(4), _user(5)])],
        content="这是一条可以得到简短评价的消息。",
    )
    channel.fetch_message.return_value = message
    monkeypatch.setattr(feature, "human_reaction_counts", AsyncMock(return_value=Counter({"👍": 4})))
    payload = SimpleNamespace(channel_id=2, message_id=44)
    asyncio.run(cog._process(payload))
    cog._react.assert_awaited_once_with(message, "👍")
    cog._comment.assert_awaited_once_with(message)


def test_own_reaction_does_not_make_four_human_reactions(monkeypatch, tmp_path):
    bot = SimpleNamespace(user=_user(99), get_channel=lambda _: channel)
    channel = Mock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock()
    cog = feature.EngagementCog(bot)
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    cog._eligible = AsyncMock(return_value=True)
    cog._react = AsyncMock()
    cog._comment = AsyncMock()
    message = SimpleNamespace(
        id=44,
        author=_user(10),
        mentions=[],
        created_at=datetime.now(timezone.utc),
        reactions=[FakeReaction("👍", [_user(2), _user(3), _user(4), _user(99, bot=True)], me=True)],
        content="这是一条可以得到简短评价的消息。",
    )
    channel.fetch_message.return_value = message
    monkeypatch.setattr(feature, "human_reaction_counts", AsyncMock(return_value=Counter({"👍": 3})))
    asyncio.run(cog._process(SimpleNamespace(channel_id=2, message_id=44)))
    cog._comment.assert_not_awaited()


def test_store_prevents_duplicate_comment_after_restart(tmp_path):
    path = tmp_path / "engagement.db"

    async def run():
        first = feature.EngagementStore(path)
        args = dict(
            guild_id=1,
            channel_id=2,
            message_id=3,
            author_id=4,
            action="comment",
            daily_limit=3,
            channel_cooldown_minutes=120,
        )
        assert await first.reserve(**args)
        await first.finish(1, 3, "comment", "success")
        restarted = feature.EngagementStore(path)
        assert not await restarted.reserve(**args)
        assert not await restarted.reserve(**{**args, "message_id": 5})

    asyncio.run(run())


def test_text_filter_skips_noncommentable_messages():
    assert feature.suitable_text("这是一条完整的正常消息。")
    assert feature.suitable_text("真不错啊")
    assert not feature.suitable_text("hi")
    assert not feature.suitable_text("https://example.com/example")


def test_generated_comment_removes_mentions(monkeypatch, tmp_path):
    cog = feature.EngagementCog(SimpleNamespace())
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    monkeypatch.setattr(
        feature.chat_settings_service,
        "get_current_ai_model",
        AsyncMock(return_value="test-model"),
    )
    monkeypatch.setattr(
        feature.chat_settings_service,
        "is_two_stage_enabled",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        feature.ai_service,
        "generate",
        AsyncMock(return_value=SimpleNamespace(content="<@0> @everyone 真不错")),
    )
    result = asyncio.run(cog._generate_comment("今天终于把房间整理干净了。"))
    assert result == "@用户 @用户 真不错"


def test_chat_reply_reacts_once_and_uses_separate_limit(monkeypatch, tmp_path):
    bot = SimpleNamespace(user=_user(99))
    cog = feature.EngagementCog(bot)
    cog.config = feature.EngagementConfig(
        enabled=True,
        react_threshold=2,
        comment_threshold=4,
        max_message_age_hours=24,
        channel_ids=frozenset(),
        excluded_channel_ids=frozenset(),
        react_daily_limit=20,
        chat_react_daily_limit=40,
        comment_daily_limit=10,
        react_channel_cooldown_minutes=20,
        comment_channel_cooldown_minutes=20,
    )
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    cog._eligible = AsyncMock(return_value=True)
    channel = Mock(spec=discord.TextChannel)
    channel.id = 2
    guild = SimpleNamespace(id=1, emojis=[])
    message = SimpleNamespace(
        id=10,
        guild=guild,
        channel=channel,
        author=_user(2),
        reactions=[],
        add_reaction=AsyncMock(),
    )
    asyncio.run(cog.on_ai_chat_replied(message))
    message.add_reaction.assert_awaited_once()
    asyncio.run(cog.on_ai_chat_replied(message))
    message.add_reaction.assert_awaited_once()
    assert asyncio.run(cog.store.reserve(
        guild_id=1,
        channel_id=channel.id,
        message_id=11,
        author_id=2,
        action="react",
        daily_limit=20,
        channel_cooldown_minutes=0,
    ))


def test_chat_reply_does_not_react_when_ineligible(tmp_path):
    cog = feature.EngagementCog(SimpleNamespace(user=_user(99)))
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    cog._eligible = AsyncMock(return_value=False)
    message = SimpleNamespace(
        id=10,
        guild=SimpleNamespace(id=1, emojis=[]),
        channel=Mock(spec=discord.TextChannel),
        author=_user(2),
        reactions=[],
        add_reaction=AsyncMock(),
    )
    asyncio.run(cog.on_ai_chat_replied(message))
    message.add_reaction.assert_not_awaited()



def test_hot_message_sends_comment_and_persists_success(tmp_path):
    cog = feature.EngagementCog(SimpleNamespace(user=_user(99)))
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    cog._generate_comment = AsyncMock(return_value="这句说得很有趣。")
    channel = Mock(spec=discord.TextChannel)
    channel.id = 2

    async def empty_history():
        if False:
            yield None

    channel.history = Mock(side_effect=lambda limit: empty_history())
    message = SimpleNamespace(
        id=10,
        guild=SimpleNamespace(id=1),
        channel=channel,
        author=_user(2),
        content="这是一条热度很高的消息。",
        reply=AsyncMock(),
    )
    asyncio.run(cog._comment(message))
    message.reply.assert_awaited_once()
    assert asyncio.run(cog.store.reserve(
        guild_id=1,
        channel_id=2,
        message_id=10,
        author_id=2,
        action="comment",
        daily_limit=10,
        channel_cooldown_minutes=0,
    )) is False


def test_ai_chat_dispatches_reaction_event_only_after_reply(monkeypatch):
    from src.chat.cogs import ai_chat_cog as chat_feature

    class Typing:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot = SimpleNamespace(user=_user(99), dispatch=Mock())
    cog = chat_feature.AIChatCog(bot)
    channel = Mock(spec=discord.TextChannel)
    channel.id = 2
    channel.typing = Mock(return_value=Typing())
    message = SimpleNamespace(
        author=SimpleNamespace(id=2, bot=False),
        guild=SimpleNamespace(id=1, name="guild"),
        channel=channel,
        mentions=[bot.user],
    )
    monkeypatch.setattr(chat_feature, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        chat_feature.message_processor, "process_message",
        AsyncMock(return_value={"user_content": "你好"}),
    )
    monkeypatch.setattr(chat_feature, "get_all_keywords", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_feature, "check_content", lambda *_: (False, None))
    monkeypatch.setattr(
        chat_feature.chat_db_manager, "is_user_globally_blacklisted",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        chat_feature.chat_service, "should_process_message",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        chat_feature.chat_settings_service, "get_reply_delay",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        chat_feature.config_override_service, "get_json",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        chat_feature.config_override_service, "get",
        AsyncMock(return_value=2000),
    )
    monkeypatch.setattr(
        cog, "handle_chat_message",
        AsyncMock(return_value=SimpleNamespace(
            content="你好呀", ab_arm=None, tools_called=[],
        )),
    )
    sent = AsyncMock(return_value=[SimpleNamespace(id=77)])
    monkeypatch.setattr(chat_feature, "safe_reply", sent)
    asyncio.run(cog.on_message(message))
    bot.dispatch.assert_called_once_with("ai_chat_replied", message)
    bot.dispatch.reset_mock()
    sent.return_value = []
    asyncio.run(cog.on_message(message))
    bot.dispatch.assert_not_called()

    dm_channel = Mock(spec=discord.DMChannel)
    dm_channel.id = 3
    dm_channel.typing = Mock(return_value=Typing())
    message.guild = None
    message.channel = dm_channel
    message.mentions = []
    monkeypatch.setattr(
        chat_feature.dm_service, "get_config",
        AsyncMock(return_value={"enabled": True}),
    )
    monkeypatch.setattr(
        chat_feature.dm_service, "reserve",
        AsyncMock(return_value=(True, 9, 10, "today")),
    )
    monkeypatch.setattr(
        chat_feature, "safe_send",
        AsyncMock(return_value=[SimpleNamespace(id=78)]),
    )
    asyncio.run(cog.on_message(message))
    bot.dispatch.assert_called_once_with("ai_chat_replied", message)



def test_comment_has_no_channel_cooldown_but_keeps_daily_limit(tmp_path):
    store = feature.EngagementStore(tmp_path / "engagement.db")

    async def run():
        for message_id in (1, 2):
            assert await store.reserve(
                guild_id=1, channel_id=2, message_id=message_id,
                author_id=3, action="comment", daily_limit=2,
                channel_cooldown_minutes=0,
            )
            await store.finish(1, message_id, "comment", "success")
        assert not await store.reserve(
            guild_id=1, channel_id=2, message_id=3,
            author_id=3, action="comment", daily_limit=2,
            channel_cooldown_minutes=0,
        )

    asyncio.run(run())



def test_successful_dm_chat_can_react_without_guild(tmp_path):
    cog = feature.EngagementCog(SimpleNamespace(user=_user(99)))
    cog.config = SimpleNamespace(
        enabled=True,
        chat_react_daily_limit=40,
        react_daily_limit=20,
        react_channel_cooldown_minutes=20,
    )
    cog.store = feature.EngagementStore(tmp_path / "engagement.db")
    cog._eligible = AsyncMock(return_value=False)
    channel = Mock(spec=discord.DMChannel)
    channel.id = 3
    message = SimpleNamespace(
        id=10,
        guild=None,
        channel=channel,
        author=_user(2),
        reactions=[],
        add_reaction=AsyncMock(),
    )
    asyncio.run(cog.on_ai_chat_replied(message))
    message.add_reaction.assert_awaited_once()
    cog._eligible.assert_not_awaited()
