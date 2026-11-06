from datetime import datetime, timezone

from src.chat.features.idle_chat.cogs.idle_chat_cog import (
    IdleChatConfig,
    is_quiet_hour,
)


def test_quiet_hour_handles_overnight_window():
    assert is_quiet_hour(23, 22, 8)
    assert is_quiet_hour(3, 22, 8)
    assert not is_quiet_hour(12, 22, 8)


def test_equal_quiet_hours_disable_window():
    assert not is_quiet_hour(3, 0, 0)


def test_config_swaps_reversed_idle_bounds(monkeypatch):
    monkeypatch.setenv("IDLE_CHAT_MIN_IDLE_MINUTES", "120")
    monkeypatch.setenv("IDLE_CHAT_MAX_IDLE_MINUTES", "45")

    config = IdleChatConfig.from_env()

    assert config.min_idle_minutes == 45
    assert config.max_idle_minutes == 120


def test_config_parses_scope_and_excluded_roles(monkeypatch):
    monkeypatch.setenv("IDLE_CHAT_CHANNEL_IDS", "123, 456,invalid")
    monkeypatch.setenv("IDLE_CHAT_EXCLUDED_ROLE_IDS", "789")

    config = IdleChatConfig.from_env()

    assert config.channel_ids == frozenset({123, 456})
    assert config.excluded_role_ids == frozenset({789})


def test_datetime_baseline_is_timezone_aware():
    baseline = datetime.min.replace(tzinfo=timezone.utc)
    assert baseline.tzinfo is timezone.utc
