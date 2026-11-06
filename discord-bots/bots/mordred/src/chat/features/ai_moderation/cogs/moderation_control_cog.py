from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from src.chat.services.ai_moderation_service import ai_moderation_service
from src.chat.utils.database import chat_db_manager


def _can_moderate(member: discord.Member) -> bool:
    permissions = member.guild_permissions
    return bool(permissions.administrator or permissions.moderate_members)


class ModerationControlCog(commands.Cog):
    """Manual recovery and moderation controls for administrators."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _check_admin(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not _can_moderate(interaction.user)
        ):
            await interaction.response.send_message(
                "只有拥有禁言成员权限的管理员可以使用此命令。",
                ephemeral=True,
            )
            return False
        return True

    @app_commands.command(name="不理用户", description="让机器人暂时不回复指定用户")
    @app_commands.default_permissions(moderate_members=True)
    async def ignore_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration_minutes: app_commands.Range[int, 5, 1440] = 30,
        reason: str = "管理员操作",
    ):
        if not await self._check_admin(interaction):
            return
        if ai_moderation_service.is_protected_member(user):
            await interaction.response.send_message("该成员受保护。", ephemeral=True)
            return

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        await chat_db_manager.add_to_blacklist(user.id, interaction.guild_id, expires_at)
        await ai_moderation_service.record_manual_action(
            guild_id=interaction.guild_id,
            user_id=user.id,
            action="ignore",
            reason=reason,
            duration_minutes=duration_minutes,
            source=f"admin:{interaction.user.id}",
        )
        await interaction.response.send_message(
            f"已让机器人暂时不回复 {user.mention}，持续 {duration_minutes} 分钟。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="解除不理", description="恢复机器人对指定用户的回复")
    @app_commands.default_permissions(moderate_members=True)
    async def unignore_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if not await self._check_admin(interaction):
            return
        await chat_db_manager.remove_from_blacklist(user.id, interaction.guild_id)
        await ai_moderation_service.record_manual_action(
            guild_id=interaction.guild_id,
            user_id=user.id,
            action="unignore",
            reason="管理员解除不回复",
            duration_minutes=None,
            source=f"admin:{interaction.user.id}",
        )
        await interaction.response.send_message(
            f"已恢复对 {user.mention} 的回复。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="禁言用户", description="对指定用户执行 Discord Timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration_minutes: app_commands.Range[int, 1, 1440] = 10,
        reason: str = "管理员操作",
    ):
        if not await self._check_admin(interaction):
            return
        if ai_moderation_service.is_protected_member(user):
            await interaction.response.send_message("该成员受保护。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if (
            bot_member is None
            or not bot_member.guild_permissions.moderate_members
            or user.top_role >= bot_member.top_role
        ):
            await interaction.response.send_message(
                "机器人权限或角色层级不足，无法禁言该成员。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await user.timeout(
            timedelta(minutes=duration_minutes),
            reason=f"Admin moderation: {reason[:400]}",
        )
        await ai_moderation_service.record_manual_action(
            guild_id=interaction.guild_id,
            user_id=user.id,
            action="timeout",
            reason=reason,
            duration_minutes=duration_minutes,
            source=f"admin:{interaction.user.id}",
        )
        await interaction.followup.send(
            f"已禁言 {user.mention} {duration_minutes} 分钟。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="解除禁言", description="解除指定用户的 Discord Timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def untimeout_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if not await self._check_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await user.timeout(None, reason=f"Admin untimeout by {interaction.user.id}")
        await ai_moderation_service.record_manual_action(
            guild_id=interaction.guild_id,
            user_id=user.id,
            action="untimeout",
            reason="管理员解除 Discord Timeout",
            duration_minutes=None,
            source=f"admin:{interaction.user.id}",
        )
        await interaction.followup.send(
            f"已解除 {user.mention} 的禁言。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationControlCog(bot))
