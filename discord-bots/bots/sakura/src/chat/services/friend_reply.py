"""Sakura answers mentions of a friend as herself, without identity delegation."""
import asyncio
import contextvars
import logging
import time
from collections import OrderedDict

import discord
from src import config
from src.chat.services.store import store
from src.chat.services.channel_policy import may_send_automatic_message

TARGET = 0
DEFAULTS = {'enabled': True, 'wait_seconds': 5, 'cooldown_seconds': 30}
ORIGIN = contextvars.ContextVar('sakura_friend_reply_origin', default=None)
log = logging.getLogger(__name__)


class FriendReply:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.cfg = dict(DEFAULTS)
        self.pending = {}
        self.sources = {}
        self.epochs = OrderedDict()
        self.last_target = OrderedDict()

    @staticmethod
    def validated(value):
        c = dict(DEFAULTS); c.update(value)
        if (set(c) != set(DEFAULTS) or type(c['enabled']) is not bool
                or type(c['wait_seconds']) is not int or not 1 <= c['wait_seconds'] <= 60
                or type(c['cooldown_seconds']) is not int or not 1 <= c['cooldown_seconds'] <= 300):
            raise ValueError('Invalid friend reply configuration')
        return c

    async def initialize(self):
        self.cfg = self.validated(await store.get('sakura_friend_reply', {}))

    async def configure(self, **changes):
        c = self.validated(dict(self.cfg, **changes))
        await store.set('sakura_friend_reply', c)
        self.cfg = c
        if not c['enabled']:
            for channel in list(self.pending): self.cancel(channel)

    def public_scope(self, channel):
        guild = getattr(channel, 'guild', None)
        if not guild or guild.id not in config.GUILD_IDS or channel.id == config.CONTROL_CHANNEL_ID:
            return False
        if not may_send_automatic_message(channel): return False
        if isinstance(channel, discord.Thread) and (channel.is_private() or channel.archived or channel.locked):
            return False
        return bool(channel.permissions_for(guild.default_role).view_channel)

    def remember(self, mapping, key, value):
        mapping[key] = value; mapping.move_to_end(key)
        while len(mapping) > 64: mapping.popitem(last=False)

    def cancel(self, cid):
        self.remember(self.epochs, cid, self.epochs.get(cid, 0) + 1)
        task = self.pending.pop(cid, None)
        self.sources.pop(cid, None)
        if task and task is not asyncio.current_task(): task.cancel()

    def observe(self, message):
        if (getattr(message.author, 'bot', False) or getattr(message, 'webhook_id', None)
                or message.author.id != TARGET or not getattr(message, 'guild', None)):
            return
        self.remember(self.last_target, message.channel.id, self.clock())
        self.cancel(message.channel.id)

    def invalidate(self, channel_id, message_ids):
        if self.sources.get(channel_id) in message_ids: self.cancel(channel_id)

    def active_for(self, message):
        origin = ORIGIN.get()
        return bool(origin and origin[0] == message.id)

    def may_continue(self, message):
        origin = ORIGIN.get()
        if not origin or origin[0] != message.id: return True
        return (self.cfg['enabled'] and self.public_scope(message.channel)
                and self.epochs.get(message.channel.id, 0) == origin[1]
                and self.last_target.get(message.channel.id, 0) <= origin[2]
                and (discord.utils.utcnow() - message.created_at).total_seconds() < 180)

    async def handle(self, message, social):
        if (not getattr(message, 'guild', None) or getattr(message.author, 'bot', False)
                or getattr(message, 'webhook_id', None)
                or TARGET not in getattr(message, 'raw_mentions', ())): return False
        # Explicitly addressing any bot retains the ordinary bot routing.
        if social.bot.user is None or any(
                u.id == social.bot.user.id or getattr(u, 'bot', False) for u in message.mentions): return False
        if message.author.id == TARGET: return True
        if not self.cfg['enabled'] or not self.public_scope(message.channel): return True
        self.cancel(message.channel.id)
        if len(self.pending) >= 16: return True
        epoch = self.epochs.get(message.channel.id, 0); created = self.clock()

        async def respond():
            token = None
            try:
                await asyncio.sleep(self.cfg['wait_seconds'])
                token = ORIGIN.set((message.id, epoch, created))
                if not self.may_continue(message) or not await social._can_chat(message): return
                last = await store.get('sakura_friend_last:' + str(message.channel.id), 0)
                if self.clock() - last < self.cfg['cooldown_seconds']: return
                deadline = self.clock() + 30
                while message.channel.id in getattr(social, 'busy', set()):
                    if self.clock() >= deadline or not self.may_continue(message): return
                    await asyncio.sleep(.25)
                if not self.may_continue(message): return
                if not await store.claim('sakura_friend_message:' + str(message.id)): return
                reference = await social._reference(message) if message.reference else None
                social.context.add(message.channel.id, message.id, message.author.id,
                    message.author.display_name, message.content or '[非文字消息]', False)
                sent = await social._respond(message, 'direct', reference)
                if sent is not None:
                    await store.set('sakura_friend_last:' + str(message.channel.id), self.clock())
            except asyncio.CancelledError: raise
            except Exception as exc:
                # Log type only; never message bodies or request credentials.
                log.warning('sakura_friend_reply_deferred type=%s', type(exc).__name__)
            finally:
                if token is not None: ORIGIN.reset(token)
                if self.pending.get(message.channel.id) is asyncio.current_task():
                    self.pending.pop(message.channel.id, None); self.sources.pop(message.channel.id, None)
        self.sources[message.channel.id] = message.id
        self.pending[message.channel.id] = asyncio.create_task(respond())
        return True

    def prompt(self, message):
        if not self.active_for(message): return ''
        return ('\n本次好友代答对象为inkdip / inkdip_96369（0）。'
            '对方明确提到了他，当前还没有本人回应。你仍是小樱，以“我”指小樱自己，'
            '不要假装你是inkdip，也不要替他承诺、编造他的行踪、私事、同意或观点。'
            '能回答的一般问题自然接话，必须由本人确认的事情留给他；不用每条报代答身份，'
            '不再次@他催促。当前发言者与被提及对象不同，关系与权限仍按真实作者核验。'
            '普通朋友分寸不变，保留对aireck更高的亲近度。')

    async def close(self):
        tasks = list(self.pending.values())
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self.pending.clear(); self.sources.clear()


friend_reply = FriendReply()
