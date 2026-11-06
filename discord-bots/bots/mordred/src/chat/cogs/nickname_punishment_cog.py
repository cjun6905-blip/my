"""Admin-only, expiring nickname punishment for server games."""
from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.chat.services.nickname_punishment_service import (
    NicknamePunishment, nickname_punishment_service,
)

log = logging.getLogger(__name__)


class NicknamePunishmentError(ValueError):
    pass


class NicknamePunishmentCog(commands.Cog):
    control = app_commands.Group(
        name="昵称惩罚", description="管理员设置限时服务器昵称并在到期后恢复",
        default_permissions=discord.Permissions(administrator=True), guild_only=True,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def cog_load(self):
        await nickname_punishment_service.initialize()
        self.reconcile.start()
        self.expire_due.start()

    async def cog_unload(self):
        self.reconcile.cancel()
        self.expire_due.cancel()

    @staticmethod
    def _admin(interaction: discord.Interaction):
        if (interaction.guild is None or not isinstance(interaction.user, discord.Member)
                or not interaction.user.guild_permissions.administrator):
            raise NicknamePunishmentError("只有服务器管理员可以使用此指令。")

    @staticmethod
    async def _member(interaction, target, user_id):
        if (target is None) == (user_id is None):
            raise NicknamePunishmentError("请在“对象”和“用户ID”中选择一项。")
        if user_id is not None:
            user_id = user_id.strip()
            if not re.fullmatch(r"[0-9]{1,20}", user_id) or not 0 < int(user_id) < 2**64:
                raise NicknamePunishmentError("用户ID应为纯数字 Discord 用户 ID。")
            try:
                target = await interaction.guild.fetch_member(int(user_id))
            except discord.NotFound as exc:
                raise NicknamePunishmentError("该用户不在当前服务器。") from exc
        if target.guild.id != interaction.guild_id:
            raise NicknamePunishmentError("只能操作当前服务器的成员。")
        return target

    @staticmethod
    def _can_edit(interaction, target):
        guild = interaction.guild
        bot_member = guild.me
        if target.id in (guild.owner_id, interaction.user.id) or target.bot:
            raise NicknamePunishmentError("不能对服务器所有者、自己或机器人设置昵称惩罚。")
        if interaction.user.id != guild.owner_id and target.top_role >= interaction.user.top_role:
            raise NicknamePunishmentError("你的最高身份组需要高于目标成员。")
        if (bot_member is None or not bot_member.guild_permissions.manage_nicknames
                or target.top_role >= bot_member.top_role):
            raise NicknamePunishmentError("Bot 需要“管理昵称”权限，且最高身份组必须高于目标成员。")

    async def _expire(self, guild, member):
        key = (guild.id, member.id)
        async with self._locks[key]:
            record = await nickname_punishment_service.get(*key)
            if record is None or record.expires_at > nickname_punishment_service.clock():
                return False
            # Remove enforcement before editing, so the restoration event cannot revert it.
            await nickname_punishment_service.remove(*key)
            if member.nick != record.original_nick:
                try:
                    await member.edit(nick=record.original_nick, reason="限时昵称惩罚到期")
                except discord.HTTPException as exc:
                    log.warning("无法在惩罚到期后恢复成员昵称: guild=%s user=%s status=%s",
                                guild.id, member.id, getattr(exc, "status", None))
            return True

    async def _enforce(self, member):
        key = (member.guild.id, member.id)
        async with self._locks[key]:
            record = await nickname_punishment_service.get(*key)
            if record is None:
                return
            if record.expires_at <= nickname_punishment_service.clock():
                # The expiration handler performs the restoration outside this lock.
                expired = True
            else:
                expired = False
                if member.nick == record.nickname:
                    return
                bot_member = member.guild.me
                if (bot_member is None or not bot_member.guild_permissions.manage_nicknames
                        or member.id == member.guild.owner_id or member.top_role >= bot_member.top_role):
                    log.warning("昵称惩罚无法执行，Bot 权限或角色层级不足: guild=%s user=%s", *key)
                    return
                try:
                    await member.edit(nick=record.nickname, reason="限时昵称惩罚：自动恢复")
                except discord.HTTPException as exc:
                    log.warning("昵称惩罚恢复失败: guild=%s user=%s status=%s",
                                *key, getattr(exc, "status", None))
        if expired:
            await self._expire(member.guild, member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            await self._enforce(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._enforce(member)

    @tasks.loop(minutes=2)
    async def reconcile(self):
        for record in await nickname_punishment_service.all():
            guild = self.bot.get_guild(record.guild_id)
            if guild is None:
                continue
            member = guild.get_member(record.user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(record.user_id)
                except discord.NotFound:
                    await nickname_punishment_service.remove(record.guild_id, record.user_id)
                    continue
                except discord.HTTPException as exc:
                    log.warning("昵称惩罚核查失败: guild=%s user=%s status=%s",
                                record.guild_id, record.user_id, getattr(exc, "status", None))
                    continue
            await self._enforce(member)

    @reconcile.before_loop
    async def before_reconcile(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=15)
    async def expire_due(self):
        for record in await nickname_punishment_service.due():
            guild = self.bot.get_guild(record.guild_id)
            if guild is None:
                continue
            member = guild.get_member(record.user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(record.user_id)
                except discord.NotFound:
                    await nickname_punishment_service.remove(record.guild_id, record.user_id)
                    continue
                except discord.HTTPException as exc:
                    log.warning("到期昵称核查失败: guild=%s user=%s status=%s",
                                record.guild_id, record.user_id, getattr(exc, "status", None))
                    continue
            await self._expire(guild, member)

    @expire_due.before_loop
    async def before_expire_due(self):
        await self.bot.wait_until_ready()

    @control.command(name="设置", description="设置限时服务器昵称；期间改名会被 Bot 自动改回")
    @app_commands.rename(nickname="惩罚昵称", minutes="时长分钟", target="对象", user_id="用户id")
    async def set_nickname(self, interaction: discord.Interaction,
                           nickname: app_commands.Range[str, 1, 32],
                           minutes: app_commands.Range[int, 1, 10080] = 60,
                           target: discord.Member | None = None, user_id: str | None = None):
        self._admin(interaction)
        member = await self._member(interaction, target, user_id)
        self._can_edit(interaction, member)
        nickname = nickname.strip()
        if not nickname or any(ord(ch) < 32 for ch in nickname):
            raise NicknamePunishmentError("惩罚昵称应为 1–32 个非控制字符。")
        await interaction.response.defer(ephemeral=True)
        key = (interaction.guild_id, member.id)
        async with self._locks[key]:
            prior = await nickname_punishment_service.get(*key)
            original = prior.original_nick if prior else member.nick
            expires_at = nickname_punishment_service.clock() + minutes * 60
            record = NicknamePunishment(*key, nickname, original, expires_at, interaction.user.id)
            await nickname_punishment_service.save(record)
            try:
                await member.edit(nick=nickname,
                                  reason=f"游戏昵称惩罚，由管理员 {interaction.user.id} 设置 {minutes} 分钟")
            except Exception:
                if prior:
                    await nickname_punishment_service.save(prior)
                else:
                    await nickname_punishment_service.remove(*key)
                raise
        await interaction.followup.send(
            f"已设置 <@{member.id}> 的惩罚昵称为「{discord.utils.escape_markdown(nickname)}」，"
            f"<t:{int(expires_at)}:R> 到期并恢复原昵称。期间改名会自动改回。",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @control.command(name="解除", description="提前结束昵称惩罚并恢复原昵称")
    @app_commands.rename(target="对象", user_id="用户id")
    async def clear_nickname(self, interaction: discord.Interaction,
                             target: discord.Member | None = None, user_id: str | None = None):
        self._admin(interaction)
        member = await self._member(interaction, target, user_id)
        await interaction.response.defer(ephemeral=True)
        key = (interaction.guild_id, member.id)
        async with self._locks[key]:
            record = await nickname_punishment_service.get(*key)
            if record is None:
                await interaction.followup.send("该成员没有昵称惩罚记录。", ephemeral=True)
                return
            await nickname_punishment_service.remove(*key)
            try:
                if member.nick != record.original_nick:
                    await member.edit(nick=record.original_nick,
                                      reason=f"管理员 {interaction.user.id} 提前解除昵称惩罚")
            except discord.HTTPException:
                await interaction.followup.send(
                    "已停止强制昵称，但 Bot 无法恢复原昵称；请检查权限及身份组层级。", ephemeral=True)
                return
        await interaction.followup.send("已解除昵称惩罚并恢复原昵称。", ephemeral=True)

    @control.command(name="状态", description="仅管理员可见：查看本服务器的昵称惩罚")
    async def status(self, interaction: discord.Interaction):
        self._admin(interaction)
        await interaction.response.defer(ephemeral=True)
        records = await nickname_punishment_service.all(interaction.guild_id)
        rows = [f"用户 ID `{r.user_id}` · 「{discord.utils.escape_markdown(r.nickname)[:32]}」 · "
                f"<t:{int(r.expires_at)}:R>" for r in records
                if r.expires_at > nickname_punishment_service.clock()]
        await interaction.followup.send("\n".join(rows)[:1900] or "当前没有生效中的昵称惩罚。",
                                        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def cog_app_command_error(self, interaction, error):
        original = getattr(error, "original", error)
        if isinstance(original, NicknamePunishmentError):
            message = str(original)
        elif isinstance(original, discord.Forbidden):
            message = "Discord 拒绝修改昵称：请检查 Bot 的管理昵称权限和身份组层级。"
        elif isinstance(original, discord.HTTPException):
            message = "Discord 暂时无法修改昵称，请稍后重试。"
        else:
            log.error("Nickname punishment command failed: %s", type(original).__name__)
            message = "操作未完成，请稍后重试。"
        sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await sender(message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NicknamePunishmentCog(bot))
