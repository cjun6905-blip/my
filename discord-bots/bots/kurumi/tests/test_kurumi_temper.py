import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

import discord
import pytest
from src.chat.services import anger_service as feature


def context():
    member = SimpleNamespace(id=2, bot=False, top_role=1,
        guild_permissions=discord.Permissions.none(), is_timed_out=lambda: False,
        timeout=AsyncMock())
    me = SimpleNamespace(id=99, top_role=5,
        guild_permissions=discord.Permissions(moderate_members=True))
    guild = SimpleNamespace(id=1, owner_id=100,
        fetch_member=AsyncMock(side_effect=lambda uid: member if uid == 2 else me))
    message = Mock(spec=discord.Message)
    message.id = 123
    message.guild = guild
    message.author = member
    message.created_at = discord.utils.utcnow()
    message.mentions = [me]
    message.reference = None
    message.channel = Mock()
    message.channel.fetch_message = AsyncMock(return_value=SimpleNamespace(author=me))
    return message, SimpleNamespace(user=me), member, me


@pytest.mark.parametrize("scenario,expected", [
    ("normal", "timed_out"), ("reply", "timed_out"),
    ("admin", "protected"), ("owner", "protected"),
    ("higher_role", "missing_permissions"), ("no_permission", "missing_permissions"),
    ("existing", "already_timed_out"), ("not_addressed", "not_addressed"),
    ("bot", "invalid_context"), ("dm", "invalid_context"),
    ("stale", "stale"), ("takeover", "takeover"), ("forbidden", "forbidden"),
])
def test_native_boundaries(tmp_path, monkeypatch, scenario, expected):
    async def run():
        message, bot, member, me = context()
        monkeypatch.setattr(feature.takeover_service, "message_active", AsyncMock(return_value=scenario == "takeover"))
        if scenario == "admin": member.guild_permissions.administrator = True
        if scenario == "owner": message.guild.owner_id = member.id
        if scenario == "higher_role": member.top_role = 5
        if scenario == "no_permission": me.guild_permissions.moderate_members = False
        if scenario == "existing": member.is_timed_out = lambda: True
        if scenario in ("not_addressed", "reply"): message.mentions = []
        if scenario == "reply": message.reference = SimpleNamespace(message_id=456)
        if scenario == "bot": member.bot = True
        if scenario == "dm": message.guild = None
        if scenario == "stale": message.created_at -= timedelta(minutes=4)
        if scenario == "forbidden":
            member.timeout.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "no")
        store = feature.AngerService(tmp_path / "anger.db")
        before = discord.utils.utcnow()
        result = await store.apply(message, bot, "哼，你惹我生气了！")
        after = discord.utils.utcnow()
        assert result["status"] == expected
        if expected == "timed_out":
            until = member.timeout.call_args.args[0]
            assert before + timedelta(seconds=60) <= until <= after + timedelta(seconds=60)
            assert result["duration_seconds"] == 60
            assert "已禁言 1 分钟" in result["reply"]
            # A second call / process restart cannot reapply or extend this action.
            result2 = await feature.AngerService(store.path).apply(message, bot, "哼！")
            assert result2["status"] == "duplicate"
            message.id += 1
            assert (await store.apply(message, bot, "哼！"))["status"] == "cooldown"
            assert member.timeout.await_count == 1
        else:
            assert result.get("duration_seconds", 0) == 0
            assert "已禁言 1 分钟" not in result.get("reply", "")
            if scenario != "forbidden": member.timeout.assert_not_awaited()
    asyncio.run(run())



def test_model_action_is_current_author_only():
    from src.chat.services.temper import action_for
    message,bot,member,me=context();message.content='你太没用了';message.webhook_id=None
    action={'timeout':True,'quote':message.content,'reason':'当前作者直接恶意羞辱角色'}
    reply=SimpleNamespace(moderation=action)
    assert action_for(message,reply,'direct')
    assert action_for(message,reply,'proactive') is None
    reply.moderation=dict(action,quote='历史中另一人的话');assert action_for(message,reply,'direct') is None
    reply.moderation=dict(action,target_id='666');assert action_for(message,reply,'direct') is None
    reply.moderation=dict(action,duration=999);assert action_for(message,reply,'direct') is None
    reply.moderation=action;message.author.bot=True;assert action_for(message,reply,'direct') is None

def test_persistent_guild_cap(tmp_path):
    service=feature.AngerService(tmp_path/'anger.db')
    for n in range(3):assert service._claim(1,n+2,n+100,10000.)=='reserved'
    assert service._claim(1,77,777,10000.)=='guild_cooldown'
    assert feature.AngerService(service.path)._claim(1,77,778,10001.)=='guild_cooldown'
    assert service._claim(1,77,779,10601.)=='reserved'
