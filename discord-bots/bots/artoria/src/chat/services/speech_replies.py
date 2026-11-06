"""Optional explicit-human TTS, leaving character-specific chat/DM cores intact."""
import asyncio
import io
import logging
import discord
from src import config
from src.chat.services.speech_generation import speech_generation,SpeechError
from src.chat.services.speech_decision import read_decision, fallback_decision, record_decision, needs_review
from src.chat.services.ai.service import ModelError

log=logging.getLogger(__name__)


class SpeechRepliesMixin:
    async def _queue_speech_decision(self,message,raw,reply,reference=None,history=()):
        if (message.author.bot or getattr(message,'webhook_id',None) is not None
                or not await self._can_chat(message) or not await speech_generation.enabled()):return False
        # Reuse the one-audio-task reservation, including rare missing-field
        # recovery, so there cannot be an unbounded classifier task fan-out.
        key=(message.channel.id,message.id)
        if key in self.speech_jobs:return False
        decision=read_decision(raw,message,reply,reference,self.bot.user.id)
        if decision is False and needs_review(message,history,reference,self.bot.user.id):
            decision=None
        if decision is False:
            await record_decision(message,'not_requested')
            return False
        if self.speech_jobs:
            await record_decision(message,'busy')
            if decision is not None or needs_review(message,history,reference,self.bot.user.id):
                await message.reply('上一段语音还在准备，稍等一下再叫我吧。',mention_author=False,allowed_mentions=discord.AllowedMentions.none())
            return False
        self.speech_jobs.add(key)
        task=asyncio.create_task(self._speech_after_reply(message,raw,reply,reference,history,key,decision))
        self.background.add(task);task.add_done_callback(self.background.discard)
        return True

    async def _speech_after_reply(self,message,raw,reply,reference,history,key,decision):
        try:
            if not await self._can_chat(message) or not await speech_generation.enabled():return
            if decision is None:
                decision=await fallback_decision(message,reply,reference,history,self.bot.user.id)
            if decision is False:
                await record_decision(message,'not_requested');return
            if decision is None:
                raise SpeechError('decision')
            await record_decision(message,'requested')
            log.info('speech_intent_confirmed profile=%s request=%s route=ai_after_reply',config.PROFILE_KEY,message.id)
            # _speech rechecks authorization/enabled and owns final cleanup.
            await self._speech(message,decision,key)
        except (SpeechError,ModelError,asyncio.TimeoutError):
            await record_decision(message,'decision_failed')
            log.warning('speech_decision_failed profile=%s request=%s',config.PROFILE_KEY,message.id)
            if await self._can_chat(message):await message.reply('文字已发出，但这次语音判断没有完成，请再试一次。',mention_author=False,allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            log.error('speech_decision_failed type=%s',type(exc).__name__)
        finally:self.speech_jobs.discard(key)

    async def _queue_speech(self,message,text):
        if message.author.bot or getattr(message,'webhook_id',None) is not None or not await self._can_chat(message):return False
        if not await speech_generation.enabled():return False
        key=(message.channel.id,message.id)
        if key in self.speech_jobs:return False
        if self.speech_jobs:
            await message.reply('上一段语音还在准备，稍等一下再叫我吧。',mention_author=False,allowed_mentions=discord.AllowedMentions.none());return False
        self.speech_jobs.add(key)
        task=asyncio.create_task(self._speech(message,text,key));self.background.add(task);task.add_done_callback(self.background.discard);return True

    async def _speech(self,message,text,key):
        try:
            if not await self._can_chat(message):return
            async with message.channel.typing():
                audio=await speech_generation.generate(text,message.author.id)
                if not await self._can_chat(message) or not await speech_generation.enabled():return
                if audio.language=='Japanese' and not audio.gloss:raise SpeechError('translation')
                attachment=discord.File(io.BytesIO(audio.data),filename=config.PROFILE_KEY+'_speech.wav')
                try:
                    await message.reply(file=attachment,mention_author=False,allowed_mentions=discord.AllowedMentions.none())
                    if audio.language=='Japanese' and audio.gloss and await self._can_chat(message):
                        await message.channel.send(audio.gloss,allowed_mentions=discord.AllowedMentions.none())
                finally:attachment.close()
        except SpeechError as exc:
            texts={'translation':'这次没有转换出所选上游需要的语言，因此没有生成语音，请稍后再试。','configuration':'语音配置暂不可用，请管理员检查。','busy':'语音任务正在忙，稍后再叫我吧。','memory':'服务器内存暂时不足，这次语音没有生成，文字聊天仍可继续。',
                   'credit':'语音接口余额不足，请管理员检查。','authentication':'语音接口授权暂时不可用，请管理员检查。',
                   'voice_unavailable':'本角色的音色暂不可用，请管理员检查音色ID及使用权限。','rate_limit':'语音接口暂时限流，稍后再试。',
                   'cooldown':'刚刚说过一段啦，稍等几秒再叫我。','too_long':'请把朗读内容缩短到500字以内。',
                   'timeout':'语音生成等待超时，这次没有拿到音频。','disabled':'当前语音功能已关闭。'}
            log.warning('speech_failed profile=%s code=%s status=%s',config.PROFILE_KEY,exc.code,exc.status)
            if await self._can_chat(message):await message.reply(texts.get(exc.code,'这次语音没有生成成功，稍后再试吧。'),mention_author=False,allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:log.warning('speech_delivery_failed status=%s',exc.status)
        except Exception as exc:log.error('speech_failed type=%s',type(exc).__name__)
        finally:self.speech_jobs.discard(key)
