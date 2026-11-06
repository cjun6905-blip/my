import asyncio,time
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from . import config
from .conversation import ContextBuffer,parse_reply,messages_for
from .image_generation import image_generation,ImageGenerationError,image_candidate,model_request
from .media_replies import MediaRepliesMixin
from .store import store
from .ai import ai_service,ModelError
from src.chat.services.ai.providers.base import GenerationConfig
from src.chat.services.takeover_service import takeover_service

class PersonaMediaCog(MediaRepliesMixin,commands.Cog):
 def __init__(self,bot):
  self.bot=bot;self.context=ContextBuffer(channels=32,turns=8);self.image_jobs=set();self.background=set();self.seen={}
 async def _can_chat(self,m):
  if getattr(m.author,'bot',False) or getattr(m,'webhook_id',None) is not None or not m.guild or m.guild.id!=0:return False
  if m.channel.id==0 or await takeover_service.message_active(m):return False
  from src.chat.config.chat_config import CHAT_ENABLED
  from src.chat.features.chat_settings.services.chat_settings_service import chat_settings_service
  from src.chat.utils.database import chat_db_manager
  if not CHAT_ENABLED or not await chat_settings_service.is_chat_globally_enabled(m.guild.id):return False
  if await chat_db_manager.is_user_globally_blacklisted(m.author.id):return False
  return True
 async def reference(self,m):
  r=getattr(m,'reference',None)
  if not r:return None
  if isinstance(r.resolved,discord.Message):return r.resolved
  try:return await asyncio.wait_for(m.channel.fetch_message(r.message_id),3)
  except (discord.HTTPException,asyncio.TimeoutError):return None
 async def is_image_reply(self,m):
  if not image_candidate(m.content) and not self._recent_picture(m):return False
  r=await self.reference(m)
  return bool(r and r.author.id==self.bot.user.id and self._image_hint(m,r))
 async def handle(self,m):
     # Text is now owned by the original chat framework; no early image diversion.
     return False
 async def after_reply(self,m,text):
  # Called only after the existing framework successfully delivered its reply.
  if not text or len(self.background)>=4 or not await self._can_chat(m):return
  now=time.monotonic();self.seen={k:v for k,v in self.seen.items() if now-v<600}
  if m.id in self.seen:return
  if len(self.seen)>=512:self.seen.pop(next(iter(self.seen)))
  self.seen[m.id]=now
  task=asyncio.create_task(self._decide_after_reply(m,text))
  self.background.add(task);task.add_done_callback(self.background.discard)
 async def _decide_after_reply(self,m,text):
  try:
   from .image_decision import IMAGE_INSTRUCTIONS,decision_request
   import json,logging
   messages=messages_for(m,self.context.get(m.channel.id),[],{},'direct')
   messages[0]['content']+='\n'+IMAGE_INSTRUCTIONS+'\n文字回复已由主框架发出。只返回image决定，不再生成回复。'
   messages.append({'role':'assistant','content':text[:1500]})
   messages.append({'role':'user','content':'根据刚刚的真人消息和已发送回复，返回 {"image":null} 或结构化image决定。不要把本条控制提示当成索图。'})
   result=await asyncio.wait_for(ai_service.generate(messages=messages,config=GenerationConfig(temperature=.3,max_output_tokens=550)),35)
   reply=parse_reply(result.content,{}, {m.author.id},direct=True)
   request=decision_request(m,reply.image,self._recent_picture(m))
   if request and await self._can_chat(m):
    self.context.add(m.channel.id,m.id,m.author.id,m.author.display_name,m.content)
    self.context.add(m.channel.id,-m.id,self.bot.user.id,self.bot.user.display_name,text,True)
    await self._queue_picture(m,request,reply)
  except asyncio.CancelledError:raise
  except Exception as e:
   import logging
   logging.getLogger(__name__).warning('image_decision_failed type=%s',type(e).__name__)

 @app_commands.command(name='生图上游',description='管理员：查看或切换生图上游与模型')
 @app_commands.guild_only()
 @app_commands.checks.has_permissions(administrator=True)
 @app_commands.choices(上游=[app_commands.Choice(name='duck · gpt-6-luna',value='duck'),app_commands.Choice(name='CPA · gpt-image-2.5',value='cpa'),app_commands.Choice(name='CPA · gpt-image-2.5-sunburst',value='cpa_sunburst'),app_commands.Choice(name='OpenAI · gpt-image-2.6-sunburst',value='openai_2_6_sunburst'),app_commands.Choice(name='OpenAI · gpt-image-2.6-flare',value='openai_2_6_flare'),app_commands.Choice(name='OpenAI · gpt-image-2.5-sunburst',value='openai_2_5_sunburst'),app_commands.Choice(name='OpenAI · gpt-image-2.5-flare',value='openai_2_5_flare')])
 async def image_upstream(self,i:discord.Interaction,上游:Optional[str]=None):
  if not i.guild or not i.user.guild_permissions.administrator:
   await i.response.send_message('此操作需要服务器管理员权限。',ephemeral=True);return
  await i.response.defer(ephemeral=True)
  try:
   p=await image_generation.select_provider(上游) if 上游 else await image_generation.current_provider()
   await i.followup.send(config.BOT_NAME+'当前生图：'+p['name']+' · '+p['model']+'。选择已保存，下次生图生效。',ephemeral=True)
  except ImageGenerationError:await i.followup.send('生图配置不可用，未切换。',ephemeral=True)
 async def cog_app_command_error(self,i,e):
  sender=i.followup.send if i.response.is_done() else i.response.send_message
  await sender('此操作需要服务器管理员权限。' if isinstance(e,app_commands.MissingPermissions) else '操作未完成，请稍后再试。',ephemeral=True)
 async def cog_unload(self):
  for task in list(self.background):task.cancel()
  await asyncio.gather(*list(self.background),return_exceptions=True);await store.close()
