import discord
from discord import app_commands
from discord.ext import commands
from src import config
from src.chat.services.store import store
from src.chat.services.channel_policy import may_send_automatic_message
from src.chat.services.image_generation import image_generation, ImageGenerationError
from typing import Optional


class SettingsCog(commands.Cog):
    control = app_commands.Group(name=config.COMMAND_GROUP, description=f"{config.BOT_NAME}的记忆与群聊设置")

    def __init__(self, bot):
        self.bot = bot

    @control.command(name="源码", description="获取当前版本源码与许可证，不含密钥和聊天数据")
    async def source(self, interaction: discord.Interaction):
        from pathlib import Path
        archive = Path("source.zip")
        if archive.exists():
            await interaction.response.send_message(f"这是{config.BOT_NAME}当前版本的源码。", file=discord.File(archive), ephemeral=True)
        else:
            await interaction.response.send_message("源码随部署目录提供，请联系管理员获取。", ephemeral=True)

    @control.command(name="状态", description="查看当前角色的基本状态，仅自己可见")
    async def status(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id or 0
        enabled = await store.get(f"chat:{guild_id}", True)
        channels = await store.get("proactive_channels", config.DEFAULT_PROACTIVE_CHANNELS)
        await interaction.response.send_message(
            f"{config.BOT_NAME}在线 · v{config.VERSION}\n聊天：{'开启' if enabled else '关闭'}\n"
            f"本频道主动互动：{'开启' if interaction.channel_id in channels else '关闭'}\n"
            "被 @ 或原生回复时优先回应；不额外等待30秒。", ephemeral=True)

    @control.command(name="记忆", description="查看当前角色记住的你的偏好，仅自己可见")
    async def memory(self, interaction: discord.Interaction):
        facts, enabled = await store.memory(interaction.guild_id or 0, interaction.user.id)
        body = "\n".join("• " + discord.utils.escape_mentions(f) for f in facts) or "还没有记住你的长期偏好。"
        await interaction.response.send_message(
            f"记忆：{'开启' if enabled else '关闭'}\n{body}", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    @control.command(name="记住", description="明确告诉当前角色一条你的偏好")
    async def remember(self, interaction: discord.Interaction, 内容: app_commands.Range[str, 1, 160]):
        await interaction.response.defer(ephemeral=True)
        _, enabled = await store.memory(interaction.guild_id or 0, interaction.user.id)
        if not enabled:
            await interaction.followup.send(f"你的记忆已关闭，先用 /{config.COMMAND_GROUP} 记忆开关 重新开启。", ephemeral=True)
            return
        await store.remember(interaction.guild_id or 0, interaction.user.id, 内容)
        await interaction.followup.send("记下你的这条偏好了。", ephemeral=True)

    @control.command(name="忘记我", description="清除本会话范围中你的长期偏好，并关闭自动记忆")
    async def forget(self, interaction: discord.Interaction):
        await store.forget(interaction.guild_id or 0, interaction.user.id, enabled=False)
        await interaction.response.send_message("已清除这里属于你的长期偏好，并关闭自动记忆。", ephemeral=True)

    @control.command(name="记忆开关", description="开启或关闭当前角色对你的长期记忆；关闭会清除旧偏好")
    async def toggle_memory(self, interaction: discord.Interaction, 开启: bool):
        if 开启:
            facts, _ = await store.memory(interaction.guild_id or 0, interaction.user.id)
            await store.forget(interaction.guild_id or 0, interaction.user.id, enabled=True)
            for fact in facts:
                await store.remember(interaction.guild_id or 0, interaction.user.id, fact)
        else:
            await store.forget(interaction.guild_id or 0, interaction.user.id, enabled=False)
        await interaction.response.send_message("已开启你的记忆。" if 开启 else "已关闭记忆并清除旧偏好。", ephemeral=True)

    @control.command(name="主动互动", description="管理员：设置本频道是否允许主动接话、表情与热评")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def proactive(self, interaction: discord.Interaction, 开启: bool):
        channels = set(await store.get("proactive_channels", config.DEFAULT_PROACTIVE_CHANNELS))
        if 开启:
            channels.add(interaction.channel_id)
        else:
            channels.discard(interaction.channel_id)
        channels.discard(config.CONTROL_CHANNEL_ID)
        await store.set("proactive_channels", sorted(channels))
        text = "已开启本频道主动互动。" if 开启 else f"已关闭本频道主动互动，仍可 @ {config.BOT_NAME}。"
        if 开启 and not may_send_automatic_message(interaction.channel):
            text = "已开启本频道表情互动。频道规则仍禁止主动接话和热评，可 @ 或原生回复与我交谈。"
        await interaction.response.send_message(text, ephemeral=True)

    @control.command(name="生图上游", description="管理员：查看或切换本 Bot 的生图上游，重启后保留")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(上游=[
        app_commands.Choice(name="duck · gpt-6-luna", value="duck"),
        app_commands.Choice(name="CPA · gpt-image-2.5", value="cpa"),
        app_commands.Choice(name="CPA · gpt-image-2.5-sunburst", value="cpa_sunburst"),app_commands.Choice(name='OpenAI · gpt-image-2.6-sunburst',value='openai_2_6_sunburst'),app_commands.Choice(name='OpenAI · gpt-image-2.6-flare',value='openai_2_6_flare'),app_commands.Choice(name='OpenAI · gpt-image-2.5-sunburst',value='openai_2_5_sunburst'),app_commands.Choice(name='OpenAI · gpt-image-2.5-flare',value='openai_2_5_flare'),
    ])
    async def image_upstream(self, interaction: discord.Interaction, 上游: Optional[str] = None):
        # Keep a runtime guard as well as Discord's command checks.
        if interaction.guild is None or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("此操作需要服务器管理员权限。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            provider = (await image_generation.select_provider(上游) if 上游
                else await image_generation.current_provider())
            text = (f"已将{config.BOT_NAME}的生图上游切换为" if 上游 else f"{config.BOT_NAME}当前生图上游：")
            text += f" {provider['name']} · {provider['model']}。"
            if 上游:
                text += "\n已保存，下次生图生效；正在生成的图片继续使用原上游。"
            await interaction.followup.send(text, ephemeral=True)
        except ImageGenerationError as exc:
            text = "当前角色尚未开启生图。" if exc.code == 'disabled' else "上游未配置完整，未切换。请联系维护者检查配置。"
            await interaction.followup.send(text, ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await sender("此操作需要服务器管理员权限。" if isinstance(error, app_commands.MissingPermissions)
                     else "操作未完成，请稍后重试。", ephemeral=True)
