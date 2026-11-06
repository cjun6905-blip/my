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

    if config.PROFILE_KEY in ('yoshino', 'kazusa', 'setsuna', 'sasuke'):
        @control.command(name="自主禁言", description="管理员：查看或设置本角色的一分钟自主禁言")
        @app_commands.guild_only()
        @app_commands.checks.has_permissions(administrator=True)
        async def temper_control(self, interaction: discord.Interaction, 开启: Optional[bool] = None):
            if not interaction.guild or not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("此操作需要服务器管理员权限。", ephemeral=True)
                return
            if 开启 is not None:
                await store.set('temper_enabled', 开启)
            value = await store.get('temper_enabled', True)
            await interaction.response.send_message("自主禁言：" + ("开启" if value else "关闭")
                + "。只针对当前直接互动的真人，固定60秒，同人120秒冷却，10分钟最多3次；不延长已有禁言。", ephemeral=True)
    
    if config.PROFILE_KEY == 'sasuke':
        @control.command(name="代答", description="aireck：开启/关闭被提及时的代理回复；管理员可紧急关闭")
        @app_commands.guild_only()
        async def proxy_control(self, interaction: discord.Interaction, 开启: Optional[bool] = None):
            from src.chat.services.owner_controls import proxy_state
            await proxy_state(interaction, 开启)

        @control.command(name="代答设置", description="aireck：公开频道白名单、等待时间与冷却")
        @app_commands.guild_only()
        async def proxy_configure(self, interaction: discord.Interaction, 频道: Optional[discord.TextChannel] = None,
                允许: Optional[bool] = None, 等待秒数: Optional[app_commands.Range[int,3,60]] = None,
                冷却秒数: Optional[app_commands.Range[int,1,300]] = None):
            from src.chat.services.owner_controls import configure
            await configure(interaction, 频道, 允许, 等待秒数, 冷却秒数)

        @control.command(name="代发", description="aireck：原样发送文字，可填写消息链接进行原生回复")
        @app_commands.guild_only()
        async def proxy_speak(self, interaction: discord.Interaction, 内容: app_commands.Range[str,1,2000],
                频道: Optional[discord.TextChannel] = None, 回复消息: Optional[str] = None):
            from src.chat.services.owner_controls import require_owner
            from src.chat.services.owner_proxy import owner_proxy
            if not await require_owner(interaction): return
            owner_proxy.cancel((频道 or interaction.channel).id)
            cog = self.bot.get_cog('TakeoverCog')
            await cog.speak.callback(cog, interaction, 内容, 频道, 回复消息)

        @control.command(name="接管", description="aireck：暂停或恢复本频道的AI自动回复")
        @app_commands.guild_only()
        async def proxy_takeover(self, interaction: discord.Interaction, 开始: bool):
            from src.chat.services.owner_controls import require_owner
            from src.chat.services.owner_proxy import owner_proxy
            if not await require_owner(interaction): return
            owner_proxy.cancel(interaction.channel_id)
            cog = self.bot.get_cog('TakeoverCog')
            if 开始: await cog.start.callback(cog, interaction)
            else: await cog.stop.callback(cog, interaction)

        @control.command(name="学习", description="aireck：控制只学习本人公开消息的表达风格")
        @app_commands.guild_only()
        async def owner_learning(self, interaction: discord.Interaction, 开启: Optional[bool] = None):
            from src.chat.services.owner_controls import learning
            await learning(interaction, 开启)

        @control.command(name="风格", description="aireck私密：查看、总结、回滚或清空风格语料")
        @app_commands.guild_only()
        @app_commands.choices(操作=[app_commands.Choice(name="查看",value="view"),app_commands.Choice(name="立即总结",value="update"),app_commands.Choice(name="回滚",value="rollback"),app_commands.Choice(name="清空本人语料",value="clear")])
        async def owner_style(self, interaction: discord.Interaction, 操作: str = 'view', 版本: Optional[int] = None):
            from src.chat.services.owner_controls import style
            await style(interaction, 操作, 版本)

        @control.command(name="禁言强度", description="aireck：调整自主禁言触发强度，固定一分钟")
        @app_commands.guild_only()
        @app_commands.choices(强度=[app_commands.Choice(name="关闭",value="off"),app_commands.Choice(name="克制",value="restrained"),app_commands.Choice(name="标准",value="standard"),app_commands.Choice(name="敏感",value="sensitive")])
        async def owner_temper(self, interaction: discord.Interaction, 强度: Optional[str] = None):
            from src.chat.services.owner_controls import require_owner
            from src.chat.services.owner_proxy import owner_proxy
            if not await require_owner(interaction): return
            if 强度 is not None: await owner_proxy.configure(strength=强度)
            await interaction.response.send_message('当前强度：'+owner_proxy.cfg['strength']+'。固定60秒；正常纠错、不同意见、善意玩笑始终排除；管理员自主禁言总开关仍有效。',ephemeral=True)

        @control.command(name="禁言", description="aireck：手动禁言本服成员一分钟，保留权限、角色与冷却保护")
        @app_commands.guild_only()
        async def owner_manual_timeout(self, interaction: discord.Interaction, 对象: discord.Member):
            from src.chat.services.owner_controls import manual_timeout
            await manual_timeout(interaction, 对象)


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

    @control.command(name="语音设置", description="管理员：查看或切换日语音色上游、查看音色状态或开关语音")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(上游=[app_commands.Choice(name="Fish · 日语", value="fish")])
    async def speech_control(self, interaction: discord.Interaction, 开启: Optional[bool] = None, 上游: Optional[app_commands.Choice[str]] = None):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("此操作需要服务器管理员权限。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        from src.chat.services.speech_generation import speech_generation, SpeechError
        try:
            if 上游 is not None:
                await speech_generation.select_provider(上游.value)
            if 开启 is not None:
                await store.set('speech:enabled', 开启)
            provider = await speech_generation.current_provider()
            value = await speech_generation.enabled()
            last = await store.get('speech:last_result:'+provider['id'], {})
            decision = await store.get('speech:last_decision', {})
            state = "开启" if value else "关闭"
            label = "Fish · 日语" if provider['id']=='fish' else "MOSS · 日语"
            count = speech_generation.key_count(provider['id'])
            text = f"语音：{state}；{label} · {provider['model']}\n音色：{provider['voice_id']}\n{count}个Key按请求轮询；日语音频后跟中文释义，中文音频不附释义。正常文字发送后按AI决定生成；同机1个任务，单次最多500字。"
            if last:
                text += f"\n最近结果：{last.get('code', 'unknown')}；HTTP：{last.get('status')}。"
            if decision:
                text += f"\n最近语音判断：{decision.get('code', 'unknown')}；请求：{decision.get('request_id')}。"
            if 上游 is not None:
                text += "\n切换已保存，下次语音生效；正在生成的语音继续使用原上游。"
            await interaction.followup.send(text, ephemeral=True)
        except SpeechError:
            await interaction.followup.send("语音上游未配置完整，未切换。请联系维护者检查。", ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await sender("此操作需要服务器管理员权限。" if isinstance(error, app_commands.MissingPermissions)
                     else "操作未完成，请稍后重试。", ephemeral=True)
