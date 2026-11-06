import asyncio
import logging
import random
import re
import time
from collections import OrderedDict
from contextlib import nullcontext
import discord
from discord.ext import commands
from src import config
from src.chat.services.ai.service import ai_service, ModelError
from src.chat.services.ai.providers.base import GenerationConfig
from src.chat.services.store import store
from src.chat.services.channel_policy import may_send_automatic_message
from src.chat.services.takeover_service import takeover_service
from src.chat.services.bot_dialogue_service import bot_dialogue_service
from src.chat.services.fleet_budget import fleet_budget, BudgetError
from src.chat.services.vision import vision_service, image_sources, IMAGE_QUESTION
from src.chat.services.conversation import (
    ContextBuffer, Participation, MEMORY_CUE, emoji_candidates,
    parse_reply, messages_for,
)

log = logging.getLogger(__name__)


class SocialCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.context = ContextBuffer()
        self.participation = Participation()
        self.busy = set()
        self.reaction_checks = OrderedDict()
        self.reaction_tasks = {}
        self.pending = {}
        self.background = set()
        self.image_messages = OrderedDict()
        self.metrics = {"direct_replies": 0, "proactive_replies": 0, "reactions": 0}

    async def _reference(self, message):
        ref = message.reference
        if ref is None:
            return None
        if isinstance(ref.resolved, discord.Message):
            return ref.resolved
        if ref.message_id:
            try:
                return await asyncio.wait_for(message.channel.fetch_message(ref.message_id), timeout=3)
            except (discord.HTTPException, asyncio.TimeoutError):
                return None

    async def _can_chat(self, message):
        if message.guild and message.guild.id not in config.GUILD_IDS:
            return False
        if message.guild and message.channel.id == config.CONTROL_CHANNEL_ID:
            return False
        if await takeover_service.message_active(message):
            return False
        guild_id = message.guild.id if message.guild else 0
        if not await store.get(f"chat:{guild_id}", True):
            return False
        if message.guild:
            session = await bot_dialogue_service.get(message.channel.id)
            if session and session.active(time.time()):
                return False
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        if self.bot.user is None or message.webhook_id is not None:
            return
        if message.guild and message.guild.id not in config.GUILD_IDS:
            return
        if message.guild and message.channel.id == config.CONTROL_CHANNEL_ID:
            return
        self.context.add(message.channel.id, message.id, message.author.id,
            message.author.display_name, message.content or "[非文字消息]", message.author.bot)
        # Only the separately bounded dialogue cog accepts other bots.
        has_image = bool(image_sources(message))
        if message.author.bot or (not message.content and not has_image) or not await self._can_chat(message):
            return
        if not message.guild:
            # Mutual guild membership is required for automatic DMs.
            member = None
            for guild in self.bot.guilds:
                if guild.id not in config.GUILD_IDS:
                    continue
                try:
                    member = await guild.fetch_member(message.author.id)
                    break
                except discord.HTTPException:
                    pass
            if member is None:
                return
        reference = await self._reference(message) if message.reference else None
        if has_image:
            self.image_messages[message.channel.id] = (time.monotonic(), message)
            self.image_messages.move_to_end(message.channel.id)
            while len(self.image_messages) > 64:
                self.image_messages.popitem(last=False)
        direct = (message.guild is None or any(u.id == self.bot.user.id for u in message.mentions)
                  or (reference is not None and reference.author.id == self.bot.user.id))
        if not direct and (any(getattr(u, 'bot', False) for u in message.mentions)
                or (reference is not None and reference.author.bot)):
            # A message addressed to another bot is not an invitation to pile on.
            return
        if message.channel.id in self.busy:
            if direct:
                self.pending[message.channel.id] = (message, reference)
            return
        if direct:
            if not self.participation.direct(message.channel.id, message.author.id):
                return
        else:
            channels = await store.get("proactive_channels", config.DEFAULT_PROACTIVE_CHANNELS)
            if not self.participation.proactive(message.channel.id, message.content, message.channel.id in channels):
                return
        await self._respond(message, "direct" if direct else "proactive", reference)

    async def _respond(self, message, mode, reference=None):
        if message.channel.id in self.busy or not await self._can_chat(message):
            return
        if mode != 'direct' and fleet_budget.path:
            await asyncio.sleep(random.uniform(0.1, 1.0))
            try:
                if not await fleet_budget.allow_background(message.channel.id, message.id):
                    return
            except BudgetError:
                log.warning('fleet_background_budget_unavailable')
                return
            if message.channel.id in self.busy or not await self._can_chat(message):
                return
        self.busy.add(message.channel.id)
        started = time.monotonic()
        try:
            guild_id = message.guild.id if message.guild else 0
            facts, enabled = await store.memory(guild_id, message.author.id)
            rows = self.context.get(message.channel.id, exclude=message.id)
            users = {message.author.id} | {row["user_id"] for row in rows if not row["bot"]}
            candidates = emoji_candidates(message.guild, message.content, message.id,
                personal=getattr(self.bot, "personal_reactions", {}))
            quote = ""
            if reference:
                quote = f"引用作者ID={reference.author.id}：{reference.content}"
            image_reference = reference
            if not image_sources(message) and not image_sources(reference) and IMAGE_QUESTION.search(message.content or ''):
                previous = self.image_messages.get(message.channel.id)
                if previous and time.monotonic() - previous[0] < 600:
                    image_reference = previous[1]
            may_speak = mode == 'direct' or may_send_automatic_message(message.channel)
            async with (message.channel.typing() if may_speak else nullcontext()), vision_service.processing(
                    bool(image_sources(message) or image_sources(image_reference))) as admitted:
                vision = (await vision_service.load(message, image_reference) if admitted else
                          {'images': [], 'unavailable': ['图片处理正忙'], 'omitted': 0})
                if vision['unavailable'] and not vision['images']:
                    if mode == 'direct' and await self._can_chat(message):
                        text = ('图片处理正忙，稍后再叫我看看。' if '正忙' in vision['unavailable'][0] else
                                '图片这次读取超时了，请重新发送或稍后重试。' if '超时' in vision['unavailable'][0] else
                                '这次图片没读到。请重新上传 PNG、JPG、WebP 或 GIF，单张不超过8 MB；分辨率很大的图片可以先截图。')
                        await message.reply(text,
                            mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    log.info('vision_unavailable channel=%s', message.channel.id)
                    return
                result = await ai_service.generate(
                    messages=messages_for(message, rows, facts if enabled else [], candidates, mode, quote, vision),
                    config=GenerationConfig(temperature=0.85, max_output_tokens=1800 if vision['images'] else 1200),
                    traffic="interactive" if mode == "direct" else "background")
            if vision['images'] or vision['unavailable']:
                log.info('vision_input channel=%s images=%s unavailable=%s', message.channel.id, len(vision['images']), len(vision['unavailable']))
            reply = parse_reply(result.content, candidates, users, direct=mode == "direct")
            if mode != "direct" or not re.search(r"表情|贴纸|sticker|emote", message.content, re.I):
                reply.sticker = ""
            if not await self._can_chat(message):
                return
            if reply.reaction:
                try:
                    await message.add_reaction(reply.reaction)
                    self.metrics["reactions"] += 1
                except discord.HTTPException:
                    log.info("reaction_unavailable channel=%s", message.channel.id)
            sent = None
            sticker_path = config.PERSONAL_EMOTE_DIR / f"{reply.sticker}.webp" if reply.sticker else None
            # The parser only accepts names of our actually loaded application emojis.
            attachment = discord.File(sticker_path) if sticker_path and sticker_path.is_file() else None
            if (reply.reply or attachment) and (mode == 'direct' or may_send_automatic_message(message.channel)):
                try:
                    sent = await message.reply(reply.reply or None, mention_author=mode == "direct",
                        **({"file": attachment} if attachment else {}),
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False, roles=False, users=[discord.Object(id=u) for u in sorted(users)[:25]],
                            replied_user=mode == "direct"))
                finally:
                    if attachment:
                        attachment.close()
                self.context.add(message.channel.id, sent.id, self.bot.user.id,
                    self.bot.user.display_name, reply.reply or f"[自己的表情包：{reply.sticker}]", True)
                self.participation.sent(message.channel.id, proactive=mode != "direct")
                self.metrics["direct_replies" if mode == "direct" else "proactive_replies"] += 1
                if mode != 'direct' and fleet_budget.path:
                    try:
                        await fleet_budget.background_delivered(message.channel.id, message.id)
                    except BudgetError:
                        log.warning('fleet_background_delivery_record_failed channel=%s', message.channel.id)
            if enabled and reply.remember and MEMORY_CUE.search(message.content):
                await store.remember(guild_id, message.author.id, reply.remember)
            log.info("social_reply mode=%s channel=%s sent=%s elapsed=%.2f", mode, message.channel.id, bool(sent), time.monotonic() - started)
        except ModelError as exc:
            log.warning("social_model_failed mode=%s channel=%s code=%s status=%s", mode, message.channel.id, exc.code, exc.status)
            if mode == "direct" and await self._can_chat(message):
                text = "现在有点忙，稍后再叫我一下。" if exc.code == "busy" else config.MODEL_ERROR_REPLY
                await message.reply(text, mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("social_discord_failed channel=%s status=%s", message.channel.id, exc.status)
        except Exception as exc:
            log.error("social_failed channel=%s type=%s", message.channel.id, type(exc).__name__)
        finally:
            self.busy.discard(message.channel.id)
            pending = self.pending.pop(message.channel.id, None)
            if pending:
                task = asyncio.create_task(self._respond(pending[0], "direct", pending[1]))
                self.background.add(task)
                task.add_done_callback(self.background.discard)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if (not payload.guild_id or payload.guild_id not in config.GUILD_IDS
                or self.bot.user is None or payload.user_id == self.bot.user.id
                or payload.channel_id == config.CONTROL_CHANNEL_ID):
            return
        if payload.message_id in self.reaction_tasks or len(self.reaction_tasks) >= 32:
            return
        async def check_after_burst():
            try:
                await asyncio.sleep(1)
                await self._check_popular(payload)
            finally:
                self.reaction_tasks.pop(payload.message_id, None)
        self.reaction_tasks[payload.message_id] = asyncio.create_task(check_after_burst())

    async def cog_unload(self):
        tasks = list(self.reaction_tasks.values()) + list(self.background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_popular(self, payload):
        now = time.monotonic()
        key = payload.message_id
        self.reaction_checks[key] = now
        self.reaction_checks.move_to_end(key)
        while len(self.reaction_checks) > 512:
            self.reaction_checks.popitem(last=False)
        channels = await store.get("proactive_channels", config.DEFAULT_PROACTIVE_CHANNELS)
        if payload.channel_id not in channels or payload.channel_id in self.busy:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            if (message.author.bot or (not message.content and not image_sources(message))
                    or (discord.utils.utcnow() - message.created_at).total_seconds() > 86400
                    or sum(r.count - int(r.me) for r in message.reactions) < 4
                    or not await self._can_chat(message)):
                return
            if not self.participation.proactive(channel.id, message.content, True, popular=True):
                return
            if not await store.claim(f"popular:{message.id}"):
                return
            await self._respond(message, "popular")
        except discord.HTTPException:
            return
