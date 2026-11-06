from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from src.chat.services.takeover_service import takeover_service, TakeoverError

log = logging.getLogger(__name__)
Channel = discord.TextChannel | discord.Thread


def parse_reply_target(value):
    """Return optional guild/channel constraints and a Discord message ID."""
    value = value.strip().strip("<>")
    if re.fullmatch(r"[0-9]{1,20}", value) and 0 < int(value) < 2**64:
        return None, None, int(value)
    try:
        url = urlsplit(value)
        match = re.fullmatch(r"/channels/(@me|[0-9]{1,20})/([0-9]{1,20})/([0-9]{1,20})/?", url.path)
        valid_host = url.netloc in {
            "discord.com", "www.discord.com", "ptb.discord.com", "canary.discord.com", "discordapp.com",
        }
        if url.scheme == "https" and valid_host and match:
            guild, channel, message = match.groups()
            if all(0 < int(v) < 2**64 for v in (channel, message)) and (guild == "@me" or 0 < int(guild) < 2**64):
                return guild, int(channel), int(message)
    except ValueError:
        pass
    raise TakeoverError("回复消息请填写 Discord 消息链接或消息 ID。")


class TakeoverCog(commands.Cog):
    control = app_commands.Group(
        name="接管", description="管理员私密控制 Bot 发言和私信",
        default_permissions=discord.Permissions(administrator=True), guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await takeover_service.initialize()

    async def cog_app_command_check(self, interaction):
        if __import__('src.config',fromlist=['PROFILE_KEY']).PROFILE_KEY == 'sasuke':
            from src.chat.services.owner_controls import require_owner
            return await require_owner(interaction)
        allowed = (
            interaction.guild is not None
            and isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )
        if not allowed:
            await interaction.response.send_message("此功能仅限服务器管理员在服务器内使用。", ephemeral=True)
        return bool(allowed)

    async def interaction_check(self, interaction):
        return await self.cog_app_command_check(interaction)

    async def _target(self, interaction, channel=None, user=None, require_send=False):
        if channel is not None and user is not None:
            raise TakeoverError("频道和私信对象只能选择一个。")
        if user is not None:
            if user.guild.id != interaction.guild_id or user.bot:
                raise TakeoverError("请选择本服务器的一名真人成员。")
            return f"dm:{user.id}", user
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.Thread)) or target.guild.id != interaction.guild_id:
            raise TakeoverError("请选择本服务器的文字频道或帖子。")
        if not target.permissions_for(interaction.user).view_channel:
            raise TakeoverError("你无权查看该频道。")
        perms = target.permissions_for(target.guild.me)
        send = perms.send_messages_in_threads if isinstance(target, discord.Thread) else perms.send_messages
        if require_send and not (perms.view_channel and send):
            raise TakeoverError("Bot 无法查看或发送消息到该频道。")
        if require_send and isinstance(target, discord.Thread) and (target.archived or target.locked):
            raise TakeoverError("帖子已归档或锁定，请先恢复帖子。")
        return f"channel:{target.id}", target

    async def _check_owner(self, interaction, scope, target, required=False):
        session = await takeover_service.require_owner(
            scope, interaction.guild_id, interaction.user.id, required=required,
        )
        parent_id = getattr(target, "parent_id", None)
        if isinstance(parent_id, int):
            await takeover_service.require_owner(
                f"channel:{parent_id}", interaction.guild_id, interaction.user.id,
            )
        return session

    @control.command(name="开始", description="暂停目标会话的自动聊天，默认30分钟后恢复")
    @app_commands.rename(channel="频道", user="私信对象", minutes="分钟")
    async def start(self, interaction: discord.Interaction, channel: Channel | None = None,
                    user: discord.Member | None = None, minutes: app_commands.Range[int, 5, 240] = 30):
        await interaction.response.defer(ephemeral=True)
        scope, target = await self._target(interaction, channel, user)
        await self._check_owner(interaction, scope, target)
        session = await takeover_service.start(scope, interaction.guild_id, interaction.user.id, minutes)
        await interaction.followup.send(
            f"接管已开始，<t:{int(session.expires_at)}:R> 自动恢复。使用 /接管 发言 或 /接管 私信 发送内容，/接管 查看 查看本次会话。",
            ephemeral=True,
        )

    @control.command(name="结束", description="结束指定会话的接管，恢复自动聊天")
    @app_commands.rename(channel="频道", user="私信对象")
    async def stop(self, interaction: discord.Interaction, channel: Channel | None = None,
                   user: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)
        scope, _ = await self._target(interaction, channel, user)
        stopped = await takeover_service.stop(scope, interaction.guild_id, interaction.user.id)
        await interaction.followup.send("已结束接管，自动聊天已恢复。" if stopped else "该会话当前没有接管。", ephemeral=True)

    async def _reply_reference(self, interaction, target, value):
        guild_id, channel_id, message_id = parse_reply_target(value)
        is_dm = isinstance(target, discord.Member)
        expected_guild = "@me" if is_dm else str(interaction.guild_id)
        if guild_id is not None and guild_id != expected_guild:
            raise TakeoverError("消息链接不属于所选服务器或私信会话。")
        if is_dm:
            target = target.dm_channel or await target.create_dm()
        else:
            for member in (interaction.user, target.guild.me):
                perms = target.permissions_for(member)
                if not (perms.view_channel and perms.read_message_history):
                    raise TakeoverError("引用回复需要你和 Bot 都有查看频道及读取消息历史的权限。")
        if channel_id is not None and channel_id != target.id:
            raise TakeoverError("消息链接不属于所选频道或私信对象；请先选择正确的目标。")
        try:
            message = await target.fetch_message(message_id)
        except discord.NotFound as exc:
            raise TakeoverError("找不到要回复的消息：请检查消息 ID、所选会话，或消息是否已删除。") from exc
        # A deleted reference must fail rather than silently become a standalone message.
        return target, message.to_reference(fail_if_not_exists=True)

    async def _send(self, interaction, content, channel=None, user=None, reply_to=None):
        content = content.strip()
        if not content or len(content) > 2000:
            raise TakeoverError("内容应为 1–2000 字。")
        scope, target = await self._target(interaction, channel, user, require_send=True)
        await self._check_owner(interaction, scope, target)
        kwargs = {}
        if reply_to is not None:
            target, reference = await self._reply_reference(interaction, target, reply_to)
            kwargs.update(reference=reference, mention_author=True)
        await takeover_service.audit("send_requested", interaction.guild_id, interaction.user.id, scope)
        sent = await target.send(
            content, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            **kwargs,
        )
        # Never report an accepted Discord send as failed if audit storage fails.
        try:
            await takeover_service.audit("sent", interaction.guild_id, interaction.user.id, scope, sent.id)
        except Exception:
            log.error("Manual message sent but audit update failed; message_id=%s", sent.id)
        await interaction.followup.send("已由 Bot 引用回复。" if reply_to is not None else "已由 Bot 发送。", ephemeral=True)

    @control.command(name="发言", description="让 Bot 在指定频道发言；省略频道则发到当前频道")
    @app_commands.rename(content="内容", channel="频道", reply_to="回复消息")
    @app_commands.describe(reply_to="可选：当前或所选频道中的消息链接/消息 ID；填写后原生回复并提醒作者")
    async def speak(self, interaction: discord.Interaction, content: app_commands.Range[str, 1, 2000],
                    channel: Channel | None = None, reply_to: str | None = None):
        await interaction.response.defer(ephemeral=True)
        await self._send(interaction, content, channel=channel, reply_to=reply_to)

    @control.command(name="私信", description="让 Bot 向一名服务器成员发送私信")
    @app_commands.rename(user="对象", content="内容", reply_to="回复消息")
    @app_commands.describe(reply_to="可选：Bot 与该对象私信中的消息链接/消息 ID，可通过 /接管 查看 获取 ID")
    async def dm(self, interaction: discord.Interaction, user: discord.Member,
                 content: app_commands.Range[str, 1, 2000], reply_to: str | None = None):
        await interaction.response.defer(ephemeral=True)
        await self._send(interaction, content, user=user, reply_to=reply_to)

    @control.command(name="查看", description="仅自己可见：查看本人本次接管开始后的最近消息")
    @app_commands.rename(channel="频道", user="私信对象")
    async def recent(self, interaction: discord.Interaction, channel: Channel | None = None,
                     user: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)
        scope, target = await self._target(interaction, channel, user)
        session = await self._check_owner(interaction, scope, target, required=True)
        if isinstance(target, discord.Member):
            target = target.dm_channel or await target.create_dm()
        from datetime import datetime, timezone
        rows = []
        async for msg in target.history(limit=5, after=datetime.fromtimestamp(session.started_at, timezone.utc), oldest_first=False):
            name = discord.utils.escape_markdown(msg.author.display_name[:40])
            body = discord.utils.escape_markdown(msg.content[:250]) or "[非文字消息]"
            rows.append(f"消息 ID：`{msg.id}`\n{name}: {body}")
        await takeover_service.audit("view", interaction.guild_id, interaction.user.id, scope)
        await interaction.followup.send(
            "\n\n".join(reversed(rows))[:1900] or "本次接管开始后暂无消息。",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @control.command(name="状态", description="仅自己可见：列出本服务器正在接管的会话")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = []
        for scope in list(takeover_service.sessions):
            session = await takeover_service.get(scope)
            if session and session.guild_id == interaction.guild_id:
                rows.append(f"{scope} · 管理员 {session.operator_id} · <t:{int(session.expires_at)}:R> 到期")
        await interaction.followup.send("\n".join(rows)[:1900] or "当前没有接管中的会话。", ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        original = getattr(error, "original", error)
        if isinstance(original, TakeoverError):
            message = str(original)
        elif isinstance(original, discord.Forbidden):
            message = "发送或读取被 Discord 拒绝：请检查频道权限，或对方是否关闭了私信。"
        elif isinstance(original, discord.NotFound):
            message = "目标会话已不存在。"
        else:
            log.error("Takeover command failed: %s", type(original).__name__)
            message = "操作未完成，请稍后重试。"
        sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await sender(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(TakeoverCog(bot))
