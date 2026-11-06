from __future__ import annotations
from src.chat.services.channel_policy import may_send_automatic_message

import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import commands, tasks

from src.chat.config import chat_config
from src.chat.features.chat_settings.services.chat_settings_service import (
    chat_settings_service,
)
from src.chat.services.config_override_service import config_override_service
from src.chat.services.takeover_service import takeover_service
from src.chat.utils.database import chat_db_manager
from src.config import ADMIN_ROLE_IDS, BOT_NAME, DEVELOPER_USER_IDS

log = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value.strip())
    except ValueError:
        log.warning("%s 不是有效整数，使用默认值 %s", name, default)
        return default
    return max(minimum, min(maximum, value))


def _env_ids(name: str) -> frozenset[int]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return frozenset()

    parsed: set[int] = set()
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            parsed.add(int(item))
        except ValueError:
            log.warning("忽略 %s 中无效的 Discord ID", name)
    return frozenset(parsed)


@dataclass(frozen=True)
class IdleChatConfig:
    enabled: bool
    channel_ids: frozenset[int]
    excluded_role_ids: frozenset[int]
    min_idle_minutes: int
    max_idle_minutes: int
    recent_user_minutes: int
    user_cooldown_minutes: int
    global_cooldown_minutes: int
    quiet_start_hour: int
    quiet_end_hour: int
    timezone_name: str

    @classmethod
    def from_env(cls) -> "IdleChatConfig":
        min_idle = _env_int("IDLE_CHAT_MIN_IDLE_MINUTES", 45, 5, 1440)
        max_idle = _env_int("IDLE_CHAT_MAX_IDLE_MINUTES", 120, 5, 1440)
        if max_idle < min_idle:
            min_idle, max_idle = max_idle, min_idle

        return cls(
            enabled=_env_bool("IDLE_CHAT_ENABLED", False),
            channel_ids=_env_ids("IDLE_CHAT_CHANNEL_IDS"),
            excluded_role_ids=_env_ids("IDLE_CHAT_EXCLUDED_ROLE_IDS"),
            min_idle_minutes=min_idle,
            max_idle_minutes=max_idle,
            recent_user_minutes=_env_int(
                "IDLE_CHAT_RECENT_USER_MINUTES", 720, 30, 10080
            ),
            user_cooldown_minutes=_env_int(
                "IDLE_CHAT_USER_COOLDOWN_MINUTES", 720, 30, 43200
            ),
            global_cooldown_minutes=_env_int(
                "IDLE_CHAT_GLOBAL_COOLDOWN_MINUTES", 90, 5, 1440
            ),
            quiet_start_hour=_env_int("IDLE_CHAT_QUIET_START_HOUR", 1, 0, 23),
            quiet_end_hour=_env_int("IDLE_CHAT_QUIET_END_HOUR", 8, 0, 23),
            timezone_name=os.getenv("IDLE_CHAT_TIMEZONE", "Asia/Shanghai").strip()
            or "Asia/Shanghai",
        )


@dataclass
class ChannelActivity:
    last_human_message_at: datetime
    next_prompt_at: datetime
    recent_users: dict[int, datetime] = field(default_factory=dict)


PROMPTS = (
    "{mention}，这里突然安静得有点过分……来陪我聊两句？",
    "{mention}，随机点名！你今天过得怎么样？",
    "{mention}，我有点无聊，正好抓到你了。最近有什么想吐槽的吗？",
    "{mention}，路过的你被我选中了。来讲一件最近发生的小事吧？",
    "{mention}，别潜水啦，陪我说会儿话。你现在最想做什么？",
    "{mention}，我决定把今天的随机聊天名额交给你。最近有遇到什么开心事吗？",
)


def is_quiet_hour(hour: int, start_hour: int, end_hour: int) -> bool:
    """Return whether an hour falls inside a possibly overnight quiet window."""
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


class IdleChatCog(commands.Cog):
    """Occasionally invites a recently active member to chat after a quiet period."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = IdleChatConfig.from_env()
        self.channel_activity: dict[int, ChannelActivity] = {}
        self.last_selected_at: dict[int, datetime] = {}
        self.last_global_prompt_at: datetime | None = None
        try:
            self.local_timezone = ZoneInfo(self.config.timezone_name)
        except ZoneInfoNotFoundError:
            log.warning(
                "未知时区 %s，随机聊天安静时段将使用 UTC",
                self.config.timezone_name,
            )
            self.local_timezone = timezone.utc

        if self.config.enabled:
            self.idle_chat_worker.start()
            log.info(
                "随机聊天已启用：空闲 %s-%s 分钟，全局冷却 %s 分钟",
                self.config.min_idle_minutes,
                self.config.max_idle_minutes,
                self.config.global_cooldown_minutes,
            )
        else:
            log.info("随机聊天未启用")

    def cog_unload(self):
        if self.idle_chat_worker.is_running():
            self.idle_chat_worker.cancel()

    def _channel_is_scoped(self, channel: discord.abc.Messageable) -> bool:
        if not may_send_automatic_message(channel):
            return False
        if not self.config.channel_ids:
            return True
        channel_id = getattr(channel, "id", None)
        parent_id = getattr(channel, "parent_id", None)
        return channel_id in self.config.channel_ids or parent_id in self.config.channel_ids

    def _schedule_next(self, now: datetime) -> datetime:
        delay_minutes = random.uniform(
            self.config.min_idle_minutes, self.config.max_idle_minutes
        )
        return now + timedelta(minutes=delay_minutes)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            not self.config.enabled
            or message.guild is None
            or message.author.bot
            or not isinstance(message.channel, (discord.TextChannel, discord.Thread))
            or not self._channel_is_scoped(message.channel)
        ):
            return

        now = discord.utils.utcnow()
        state = self.channel_activity.get(message.channel.id)
        if state is None:
            state = ChannelActivity(
                last_human_message_at=now,
                next_prompt_at=self._schedule_next(now),
            )
            self.channel_activity[message.channel.id] = state
        else:
            state.last_human_message_at = now
            state.next_prompt_at = self._schedule_next(now)

        state.recent_users[message.author.id] = now
        cutoff = now - timedelta(minutes=self.config.recent_user_minutes)
        state.recent_users = {
            user_id: seen_at
            for user_id, seen_at in state.recent_users.items()
            if seen_at >= cutoff
        }

    @tasks.loop(minutes=1)
    async def idle_chat_worker(self):
        now = discord.utils.utcnow()
        local_now = now.astimezone(self.local_timezone)
        if is_quiet_hour(
            local_now.hour,
            self.config.quiet_start_hour,
            self.config.quiet_end_hour,
        ):
            return

        if self.last_global_prompt_at is not None:
            global_ready_at = self.last_global_prompt_at + timedelta(
                minutes=self.config.global_cooldown_minutes
            )
            if now < global_ready_at:
                return

        due_states = list(self.channel_activity.items())
        random.shuffle(due_states)
        for channel_id, state in due_states:
            if now < state.next_prompt_at:
                continue

            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                self.channel_activity.pop(channel_id, None)
                continue

            try:
                sent = await self._try_send_prompt(channel, state, now)
            except Exception:
                log.exception("检查频道 %s 的随机聊天条件时发生错误", channel.id)
                sent = False
            state.next_prompt_at = self._schedule_next(now)
            if sent:
                self.last_global_prompt_at = now
                break

    @idle_chat_worker.before_loop
    async def before_idle_chat_worker(self):
        await self.bot.wait_until_ready()

    @idle_chat_worker.error
    async def idle_chat_worker_error(self, error: Exception):
        log.error("随机聊天后台任务发生错误: %s", error, exc_info=error)

    async def _try_send_prompt(
        self,
        channel: discord.TextChannel | discord.Thread,
        state: ChannelActivity,
        now: datetime,
    ) -> bool:
        if not may_send_automatic_message(channel) or await takeover_service.channel_active(channel):
            return False
        if not await self._channel_is_eligible(channel):
            return False

        member = await self._choose_member(channel, state, now)
        if member is None:
            return False

        content = random.choice(PROMPTS).format(mention=member.mention)
        allowed_mentions = discord.AllowedMentions(
            users=[member], roles=False, everyone=False, replied_user=False
        )
        try:
            if not may_send_automatic_message(channel) or await takeover_service.channel_active(channel):
                return False
            await channel.send(content, allowed_mentions=allowed_mentions)
        except (discord.Forbidden, discord.NotFound):
            log.warning("无法在频道 %s 发送随机聊天邀请", channel.id)
            return False
        except discord.HTTPException as error:
            log.warning("发送随机聊天邀请失败: %s", error)
            return False

        self.last_selected_at[member.id] = now
        log.info(
            "%s 在频道 %s 发起随机聊天，目标用户 %s",
            BOT_NAME,
            channel.id,
            member.id,
        )
        return True

    async def _channel_is_eligible(
        self, channel: discord.TextChannel | discord.Thread
    ) -> bool:
        if not self._channel_is_scoped(channel):
            return False
        if isinstance(channel, discord.Thread) and (channel.archived or channel.locked):
            return False

        guild = channel.guild
        bot_member = guild.me
        if bot_member is None:
            return False
        permissions = channel.permissions_for(bot_member)
        if not permissions.view_channel:
            return False
        if isinstance(channel, discord.Thread):
            if not permissions.send_messages_in_threads:
                return False
        elif not permissions.send_messages:
            return False

        if await chat_db_manager.is_channel_muted(channel.id):
            return False

        disabled_ids = await config_override_service.get_json(
            "channels.disabled_interaction_ids",
            chat_config.DISABLED_INTERACTION_CHANNEL_IDS,
        )
        parent_id = getattr(channel, "parent_id", None)
        if channel.id in disabled_ids or parent_id in disabled_ids:
            return False

        if not await chat_settings_service.is_chat_globally_enabled(guild.id):
            return False
        effective_config = await chat_settings_service.get_effective_channel_config(channel)
        return bool(effective_config.get("is_chat_enabled", True))

    async def _choose_member(
        self,
        channel: discord.TextChannel | discord.Thread,
        state: ChannelActivity,
        now: datetime,
    ) -> discord.Member | None:
        recent_cutoff = now - timedelta(minutes=self.config.recent_user_minutes)
        cooldown_cutoff = now - timedelta(minutes=self.config.user_cooldown_minutes)

        user_ids = [
            user_id
            for user_id, seen_at in state.recent_users.items()
            if seen_at >= recent_cutoff
            and self.last_selected_at.get(user_id, datetime.min.replace(tzinfo=timezone.utc))
            < cooldown_cutoff
        ]
        random.shuffle(user_ids)

        for user_id in user_ids[:20]:
            member = channel.guild.get_member(user_id)
            if member is None or self._member_is_protected(member):
                continue
            if not channel.permissions_for(member).view_channel:
                continue
            if await chat_db_manager.is_user_globally_blacklisted(member.id):
                continue
            if await chat_db_manager.is_user_blacklisted(member.id, channel.guild.id):
                continue
            return member
        return None

    def _member_is_protected(self, member: discord.Member) -> bool:
        if member.bot or member.id == member.guild.owner_id:
            return True
        if member.id in DEVELOPER_USER_IDS:
            return True
        if any(role.id in ADMIN_ROLE_IDS for role in member.roles):
            return True
        if any(role.id in self.config.excluded_role_ids for role in member.roles):
            return True

        permissions = member.guild_permissions
        return bool(
            permissions.administrator
            or permissions.manage_guild
            or permissions.manage_messages
            or permissions.moderate_members
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(IdleChatCog(bot))
