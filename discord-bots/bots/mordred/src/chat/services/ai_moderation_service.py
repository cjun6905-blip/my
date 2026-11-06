from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord

from src.config import ADMIN_ROLE_IDS

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ai_moderation.db"


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def env_ids(name: str) -> set[int]:
    values: set[int] = set()
    for raw_value in os.getenv(name, "").split(","):
        raw_value = raw_value.strip()
        if not raw_value:
            continue
        try:
            values.add(int(raw_value))
        except ValueError:
            log.warning("忽略 %s 中无效的 Discord ID", name)
    return values


class AiModerationService:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def _secure_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.db_path}{suffix}")
            if path.exists():
                path.chmod(0o600)

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS moderation_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        action TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        duration_minutes INTEGER,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_moderation_actions_limits
                    ON moderation_actions(guild_id, action, user_id, created_at)
                    """
                )
                await db.commit()
            self._secure_database_files()
            self._initialized = True

    async def reserve_action(
        self,
        *,
        guild_id: int,
        user_id: int,
        action: str,
        reason: str,
        duration_minutes: int,
        source: str,
        guild_daily_limit: int,
        user_cooldown_minutes: int,
    ) -> tuple[int | None, str | None]:
        """Atomically reserve a rate-limited action before calling Discord."""
        await self.initialize()
        now = datetime.now(timezone.utc)
        day_cutoff = (now - timedelta(hours=24)).isoformat()
        user_cutoff = (now - timedelta(minutes=user_cooldown_minutes)).isoformat()
        expires_at = (now + timedelta(minutes=duration_minutes)).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM moderation_actions
                WHERE guild_id = ? AND action = ?
                  AND status IN ('pending', 'success') AND created_at >= ?
                """,
                (guild_id, action, day_cutoff),
            )
            guild_count = int((await cursor.fetchone())[0])
            if guild_count >= guild_daily_limit:
                await db.rollback()
                return None, "guild_daily_limit"

            cursor = await db.execute(
                """
                SELECT 1 FROM moderation_actions
                WHERE guild_id = ? AND user_id = ? AND action = ?
                  AND status IN ('pending', 'success') AND created_at >= ?
                LIMIT 1
                """,
                (guild_id, user_id, action, user_cutoff),
            )
            if await cursor.fetchone():
                await db.rollback()
                return None, "user_cooldown"

            cursor = await db.execute(
                """
                INSERT INTO moderation_actions(
                    guild_id, user_id, action, reason, duration_minutes,
                    source, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    guild_id,
                    user_id,
                    action,
                    reason[:500],
                    duration_minutes,
                    source,
                    now.isoformat(),
                    expires_at,
                ),
            )
            action_id = int(cursor.lastrowid)
            await db.commit()
            self._secure_database_files()
            return action_id, None

    async def finish_action(self, action_id: int, success: bool) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE moderation_actions SET status = ? WHERE id = ?",
                ("success" if success else "failed", action_id),
            )
            await db.commit()
        self._secure_database_files()

    async def record_manual_action(
        self,
        *,
        guild_id: int,
        user_id: int,
        action: str,
        reason: str,
        duration_minutes: int | None,
        source: str,
    ) -> None:
        await self.initialize()
        now = datetime.now(timezone.utc)
        expires_at = (
            (now + timedelta(minutes=duration_minutes)).isoformat()
            if duration_minutes
            else None
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO moderation_actions(
                    guild_id, user_id, action, reason, duration_minutes,
                    source, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'success', ?, ?)
                """,
                (
                    guild_id,
                    user_id,
                    action,
                    reason[:500],
                    duration_minutes,
                    source,
                    now.isoformat(),
                    expires_at,
                ),
            )
            await db.commit()
        self._secure_database_files()

    def is_protected_member(self, member: discord.Member) -> bool:
        if member.bot or member.id == member.guild.owner_id:
            return True
        if member.id in env_ids("AI_MODERATION_CONTROLLER_IDS"):
            return True

        protected_roles = ADMIN_ROLE_IDS | env_ids("AI_MODERATION_PROTECTED_ROLE_IDS")
        if any(role.id in protected_roles for role in member.roles):
            return True

        permissions = member.guild_permissions
        return bool(
            permissions.administrator
            or permissions.manage_guild
            or permissions.manage_messages
            or permissions.moderate_members
        )

    async def send_audit(
        self,
        *,
        bot: discord.Client,
        guild: discord.Guild,
        member: discord.Member,
        action: str,
        reason: str,
        duration_minutes: int | None,
        source: str,
    ) -> None:
        log.info(
            "AI管理审计 guild=%s user=%s action=%s duration=%s source=%s reason=%s",
            guild.id,
            member.id,
            action,
            duration_minutes,
            source,
            reason,
        )

        audit_channel_id = env_int(
            "AI_MODERATION_AUDIT_CHANNEL_ID", 0, 0, 2**63 - 1
        )
        if not audit_channel_id:
            return
        channel = bot.get_channel(audit_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning("AI 管理审计频道 %s 不可用", audit_channel_id)
            return

        embed = discord.Embed(
            title="AI 管理操作",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="操作", value=action, inline=True)
        embed.add_field(name="用户", value=f"{member} (`{member.id}`)", inline=True)
        if duration_minutes:
            embed.add_field(name="时长", value=f"{duration_minutes} 分钟", inline=True)
        embed.add_field(name="来源", value=source, inline=True)
        embed.add_field(name="原因", value=reason[:1000], inline=False)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("发送 AI 管理审计消息失败")

    async def send_public_timeout_notice(
        self,
        *,
        channel: discord.abc.Messageable,
        member: discord.Member,
        duration_minutes: int,
        reason: str,
        source: str,
    ) -> bool:
        """禁言成功后在触发频道公开发送结果，但不额外 ping 用户。"""
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning("AI 禁言公告频道不可用: %r", channel)
            return False

        embed = discord.Embed(
            title="🔇 禁言通知",
            description=f"{member.mention} 已被禁言。",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="时长", value=f"{duration_minutes} 分钟", inline=True)
        embed.add_field(name="来源", value=source, inline=True)
        embed.add_field(name="原因", value=reason[:1000], inline=False)
        embed.set_footer(text="请遵守服务器规则，保持友善交流。")
        allowed_mentions = discord.AllowedMentions.none()
        try:
            await channel.send(embed=embed, allowed_mentions=allowed_mentions)
            return True
        except discord.Forbidden:
            log.warning("Bot 无法在频道 %s 发送禁言 Embed，尝试纯文本", channel.id)
            try:
                await channel.send(
                    f"🔇 禁言通知：{member.mention} 已被禁言 "
                    f"{duration_minutes} 分钟。原因：{reason[:500]}",
                    allowed_mentions=allowed_mentions,
                )
                return True
            except discord.HTTPException:
                log.exception("发送 AI 禁言纯文本公告失败")
        except discord.HTTPException:
            log.exception("发送 AI 禁言公告失败")
        return False


ai_moderation_service = AiModerationService()
