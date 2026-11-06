"""Authorized normal messages, native replies and private messages."""
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from src import config
from src.chat.utils.message_utils import user_mentions

log = logging.getLogger(__name__)
RELAY_USER_IDS = frozenset({0})
MESSAGE_LINK = re.compile(
    r"https://(?:(?:canary|ptb|www)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>@me|[0-9]{1,20})/(?P<channel>[0-9]{1,20})/(?P<message>[0-9]{1,20})/?"
)


def can_relay(user, guild_id: int | None) -> bool:
    if guild_id is None or not isinstance(user, discord.Member):
        return False
    if config.GUILD_ALLOWLIST_IDS and guild_id not in config.GUILD_ALLOWLIST_IDS:
        return False
    return (
        user.id in RELAY_USER_IDS
        or user.id in config.DEVELOPER_USER_IDS
        or user.guild_permissions.administrator
        or any(role.id in config.ADMIN_ROLE_IDS for role in user.roles)
    )


def parse_reference(value: str, guild_id: int | None, channel_id: int) -> int:
    """Accept an ID or a Discord link belonging to exactly this conversation."""
    value = value.strip()
    if re.fullmatch(r"[0-9]{1,20}", value):
        message_id = int(value)
    else:
        match = MESSAGE_LINK.fullmatch(value)
        if not match:
            raise ValueError("回复消息请填写 Discord 消息链接或消息 ID。")
        expected_guild = str(guild_id) if guild_id is not None else "@me"
        if match["guild"] != expected_guild or int(match["channel"]) != channel_id:
            raise ValueError("该消息不在目标对话中。请使用当前频道或所选用户与 Bot 的私信消息。")
        message_id = int(match["message"])
    if not 0 < message_id < 2**64:
        raise ValueError("无效的消息 ID。")
    return message_id


async def report(interaction: discord.Interaction, content: str):
    if interaction.response.is_done():
        await interaction.edit_original_response(content=content)
    else:
        await interaction.response.send_message(content, ephemeral=True)


async def validate_channel(interaction: discord.Interaction, replying: bool) -> bool:
    if not can_relay(interaction.user, interaction.guild_id):
        await report(interaction, "你没有代发权限。")
        return False
    channel = interaction.channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await report(interaction, "请在服务器文字频道或帖子中使用。")
        return False
    permissions = channel.permissions_for(interaction.user)
    send_allowed = permissions.send_messages_in_threads if isinstance(channel, discord.Thread) else permissions.send_messages
    if not permissions.view_channel or not send_allowed:
        await report(interaction, "你没有在当前频道发言的权限。")
        return False
    if replying and not permissions.read_message_history:
        await report(interaction, "回复消息需要读取当前频道历史消息的权限。")
        return False
    return True


class ReplyModal(discord.ui.Modal, title="让 Bot 回复这条消息"):
    content = discord.ui.TextInput(label="回复内容", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, cog, actor_id: int, guild_id: int, channel_id: int, message_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.actor_id = actor_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.actor_id or interaction.guild_id != self.guild_id or interaction.channel_id != self.channel_id:
            await report(interaction, "此回复窗口不能用于其他用户或频道。")
            return
        # Recheck current permissions and refetch the message; modals can be old.
        await self.cog.publish(interaction, str(self.content), reply_to=str(self.message_id))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Reply modal failed actor=%s error=%s", interaction.user.id, type(error).__name__)
        await report(interaction, "回复未能确认成功，请检查对话后再试。")


class RelayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reply_command = app_commands.ContextMenu(name="让Bot回复", callback=self.reply_menu)

    async def cog_load(self):
        self.bot.tree.add_command(self.reply_command)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.reply_command.name, type=self.reply_command.type)

    @app_commands.guild_only()
    async def reply_menu(self, interaction: discord.Interaction, message: discord.Message):
        if not await validate_channel(interaction, replying=True):
            return
        if message.guild is None or message.guild.id != interaction.guild_id or message.channel.id != interaction.channel_id:
            await report(interaction, "请在消息所在频道使用此功能。")
            return
        await interaction.response.send_modal(ReplyModal(self, interaction.user.id, interaction.guild_id, message.channel.id, message.id))

    async def publish(self, interaction, content, mention=None, reply_to=None, ping_reply=False):
        if not await validate_channel(interaction, replying=reply_to is not None):
            return
        text = content.strip()
        if not text:
            await report(interaction, "内容不能为空。")
            return
        if mention is not None:
            text = f"{mention.mention} {text}"
        if len(text) > 2000:
            await report(interaction, "加上提及后超过 2000 字符，请缩短内容。")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = interaction.channel
        try:
            if reply_to is not None:
                message_id = parse_reference(reply_to, interaction.guild_id, channel.id)
                original = await channel.fetch_message(message_id)
                sent = await channel.send(text, reference=original.to_reference(fail_if_not_exists=True), mention_author=ping_reply, allowed_mentions=user_mentions())
            else:
                sent = await channel.send(text, allowed_mentions=user_mentions())
        except ValueError as exc:
            await report(interaction, str(exc))
            return
        except discord.NotFound:
            await report(interaction, "回复目标不存在或已被删除，没有发送消息。")
            return
        except discord.Forbidden:
            await report(interaction, "Bot 没有读取目标消息或在此频道发送消息的权限。")
            return
        except discord.HTTPException:
            log.warning("Relay send failed actor=%s channel=%s", interaction.user.id, channel.id)
            await report(interaction, "Discord 未确认发送成功，请检查频道后再重试。")
            return
        log.info("Relay sent actor=%s guild=%s channel=%s message=%s reply=%s", interaction.user.id, interaction.guild_id, channel.id, sent.id, reply_to is not None)
        await report(interaction, "已发送。")

    @app_commands.command(name="代发", description="授权用户让 Bot 发送消息或回复当前频道的某条消息")
    @app_commands.guild_only()
    @app_commands.rename(content="内容", mention="提及用户", reply_to="回复消息", ping_reply="通知原作者")
    @app_commands.describe(content="要发送的文字", mention="可选：在消息开头提及用户", reply_to="可选：当前频道的消息链接或 ID，发送原生回复", ping_reply="回复时是否通知原作者，默认不通知")
    async def relay(self, interaction: discord.Interaction, content: app_commands.Range[str, 1, 2000], mention: discord.Member | None = None, reply_to: str | None = None, ping_reply: bool = False):
        await self.publish(interaction, content, mention, reply_to, ping_reply)

    @app_commands.command(name="私信代发", description="授权用户让 Bot 向所选服务器成员发送私信")
    @app_commands.guild_only()
    @app_commands.rename(recipient="收件人", content="内容", reply_to="回复消息")
    @app_commands.describe(recipient="接收 Bot 私信的服务器成员", content="要发送的私信文字", reply_to="可选：该成员与 Bot 私信中的消息链接或 ID")
    async def direct(self, interaction: discord.Interaction, recipient: discord.Member, content: app_commands.Range[str, 1, 2000], reply_to: str | None = None):
        if not can_relay(interaction.user, interaction.guild_id):
            await report(interaction, "你没有代发权限。")
            return
        if recipient.guild.id != interaction.guild_id or recipient.bot:
            await report(interaction, "请选择当前服务器中的非 Bot 成员。")
            return
        text = content.strip()
        if not text or len(text) > 2000:
            await report(interaction, "私信内容应为 1–2000 字符。")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await recipient.create_dm()
            if reply_to is not None:
                message_id = parse_reference(reply_to, None, channel.id)
                original = await channel.fetch_message(message_id)
                sent = await channel.send(text, reference=original.to_reference(fail_if_not_exists=True), mention_author=False, allowed_mentions=user_mentions())
            else:
                sent = await channel.send(text, allowed_mentions=user_mentions())
        except ValueError as exc:
            await report(interaction, str(exc))
            return
        except discord.NotFound:
            await report(interaction, "该私信消息不存在或已被删除，没有发送消息。")
            return
        except discord.Forbidden:
            await report(interaction, "无法私信对方：对方可能关闭了服务器私信、屏蔽了 Bot，或 Discord 限制了发送。")
            return
        except discord.HTTPException:
            log.warning("Relay DM failed actor=%s recipient=%s", interaction.user.id, recipient.id)
            await report(interaction, "Discord 未确认私信发送成功，请检查后再试。")
            return
        log.info("Relay DM sent actor=%s guild=%s recipient=%s message=%s reply=%s", interaction.user.id, interaction.guild_id, recipient.id, sent.id, reply_to is not None)
        await report(interaction, "私信已发送。")


async def setup(bot: commands.Bot):
    await bot.add_cog(RelayCog(bot))
