from types import SimpleNamespace

import discord
import pytest

from src.chat.services.ai_moderation_service import AiModerationService


@pytest.mark.asyncio
async def test_reservation_enforces_user_cooldown(tmp_path):
    service = AiModerationService(tmp_path / "moderation.db")
    first_id, first_error = await service.reserve_action(
        guild_id=1,
        user_id=2,
        action="timeout",
        reason="repeated abuse",
        duration_minutes=5,
        source="ai",
        guild_daily_limit=3,
        user_cooldown_minutes=60,
    )
    second_id, second_error = await service.reserve_action(
        guild_id=1,
        user_id=2,
        action="timeout",
        reason="repeated abuse",
        duration_minutes=5,
        source="ai",
        guild_daily_limit=3,
        user_cooldown_minutes=60,
    )

    assert first_id is not None
    assert first_error is None
    assert second_id is None
    assert second_error == "user_cooldown"


@pytest.mark.asyncio
async def test_reservation_enforces_guild_daily_limit(tmp_path):
    service = AiModerationService(tmp_path / "moderation.db")
    for user_id in (1, 2):
        action_id, error = await service.reserve_action(
            guild_id=10,
            user_id=user_id,
            action="ignore",
            reason="spam",
            duration_minutes=30,
            source="ai",
            guild_daily_limit=2,
            user_cooldown_minutes=60,
        )
        assert action_id is not None
        assert error is None

    action_id, error = await service.reserve_action(
        guild_id=10,
        user_id=3,
        action="ignore",
        reason="spam",
        duration_minutes=30,
        source="ai",
        guild_daily_limit=2,
        user_cooldown_minutes=60,
    )
    assert action_id is None
    assert error == "guild_daily_limit"


def test_protected_member_detects_moderators(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_MODERATION_PROTECTED_ROLE_IDS", "99")
    service = AiModerationService(tmp_path / "moderation.db")
    member = SimpleNamespace(
        bot=False,
        id=5,
        guild=SimpleNamespace(owner_id=1),
        roles=[SimpleNamespace(id=99)],
        guild_permissions=SimpleNamespace(
            administrator=False,
            manage_guild=False,
            manage_messages=False,
            moderate_members=False,
        ),
    )
    assert service.is_protected_member(member)


def test_controller_id_is_always_protected(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_MODERATION_CONTROLLER_IDS", "0")
    service = AiModerationService(tmp_path / "moderation.db")
    member = SimpleNamespace(
        bot=False,
        id=0,
        guild=SimpleNamespace(owner_id=1),
        roles=[],
        guild_permissions=SimpleNamespace(
            administrator=False,
            manage_guild=False,
            manage_messages=False,
            moderate_members=False,
        ),
    )
    assert service.is_protected_member(member)


def test_ordinary_member_is_not_protected(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_MODERATION_CONTROLLER_IDS", "0")
    monkeypatch.setenv("AI_MODERATION_PROTECTED_ROLE_IDS", "")
    service = AiModerationService(tmp_path / "moderation.db")
    member = SimpleNamespace(
        bot=False,
        id=0,
        guild=SimpleNamespace(owner_id=1),
        roles=[],
        guild_permissions=SimpleNamespace(
            administrator=False,
            manage_guild=False,
            manage_messages=False,
            moderate_members=False,
        ),
    )
    assert not service.is_protected_member(member)


@pytest.mark.asyncio
async def test_public_timeout_notice_is_sent_to_trigger_channel(monkeypatch, tmp_path):
    sent = []

    class FakeTextChannel:
        id = 123

        async def send(self, *args, **kwargs):
            sent.append((args, kwargs))

    class FakeThread:
        pass

    monkeypatch.setattr(discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(discord, "Thread", FakeThread)
    service = AiModerationService(tmp_path / "moderation.db")
    member = SimpleNamespace(mention="<@0>")

    result = await service.send_public_timeout_notice(
        channel=FakeTextChannel(),
        member=member,
        duration_minutes=5,
        reason="测试禁言公告",
        source="管理员指令",
    )

    assert result is True
    assert len(sent) == 1
    assert sent[0][1]["embed"].title == "🔇 禁言通知"
