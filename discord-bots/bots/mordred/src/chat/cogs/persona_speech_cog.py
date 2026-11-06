import asyncio,time
from collections import OrderedDict,deque
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from src.chat.services.persona_speech.speech_replies import SpeechRepliesMixin
from src.chat.services.persona_speech.speech_generation import speech_generation
from src.chat.services.persona_speech.store import store
from src.chat.services.takeover_service import takeover_service

class PersonaSpeechCog(SpeechRepliesMixin,commands.Cog):
    def __init__(self,bot):
        self.bot=bot;self.speech_jobs=set();self.background=set();self.history=OrderedDict();self.seen=OrderedDict()
    async def _can_chat(self,m):
        if m.author.bot or getattr(m,'webhook_id',None) is not None:return False
        if m.guild and (m.guild.id!=0 or m.channel.id==0):return False
        if await takeover_service.message_active(m):return False
        from src.chat.config.chat_config import CHAT_ENABLED
        from src.chat.features.chat_settings.services.chat_settings_service import chat_settings_service
        from src.chat.utils.database import chat_db_manager
        scope=m.guild.id if m.guild else 0
        if not CHAT_ENABLED or not await chat_settings_service.is_chat_globally_enabled(scope):return False
        if await chat_db_manager.is_user_globally_blacklisted(m.author.id) or await chat_db_manager.is_user_blacklisted(m.author.id,scope):return False
        if m.guild:return True
        original=self.bot.get_cog('AIChatCog')
        # Preserve native inbox allowlist plus original quota-authorized DM replies.
        return bool(original and (original.private_inbox.allowed(m) or getattr(m,'_speech_original_dm_delivered',False)))
    async def after_reply(self,m,text):
        if not text or not await self._can_chat(m) or not await speech_generation.enabled():return
        now=time.monotonic()
        while self.seen and (len(self.seen)>=512 or now-next(iter(self.seen.values()))>600):self.seen.popitem(last=False)
        if m.id in self.seen:return
        self.seen[m.id]=now
        rows=self.history.setdefault((m.channel.id,m.author.id),deque(maxlen=6));self.history.move_to_end((m.channel.id,m.author.id))
        while len(self.history)>32:self.history.popitem(last=False)
        r=getattr(m,'reference',None);reference=None
        if r:
            if isinstance(r.resolved,discord.Message):reference=r.resolved
            elif r.message_id:
                try:reference=await asyncio.wait_for(m.channel.fetch_message(r.message_id),3)
                except (discord.HTTPException,asyncio.TimeoutError):pass
        # A validated false avoids a classifier for ordinary messages; an explicit
        # natural request or recent same-user continuation gets the one bounded review.
        await self._queue_speech_decision(m,'{"speech":{"generate":false,"source":"reply","text":""}}',text,reference,list(rows))
        rows.append({'user_id':m.author.id,'bot':False,'text':m.content[:800]})
        rows.append({'user_id':self.bot.user.id,'bot':True,'text':text[:800]})
    async def cog_unload(self):
        for t in list(self.background):t.cancel()
        await asyncio.gather(*list(self.background),return_exceptions=True)
        await store.close()

    @app_commands.command(name="语音设置", description="管理员：查看或切换日语音色上游、查看音色状态或开关语音")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(上游=[app_commands.Choice(name="Fish · 日语", value="fish")])
    async def speech_control(self, interaction: discord.Interaction, 开启: Optional[bool] = None, 上游: Optional[app_commands.Choice[str]] = None):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("此操作需要服务器管理员权限。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        from src.chat.services.persona_speech.speech_generation import speech_generation, SpeechError
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

    async def cog_app_command_error(self,interaction,error):
        sender=interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await sender("此操作需要服务器管理员权限。" if isinstance(error,app_commands.MissingPermissions) else "操作未完成，请稍后重试。",ephemeral=True)

async def setup(bot):
    await bot.add_cog(PersonaSpeechCog(bot))
