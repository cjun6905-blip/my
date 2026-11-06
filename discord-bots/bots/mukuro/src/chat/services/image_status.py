"""Image job metadata only in a freshly verified administrator control channel."""
import asyncio
import json
import logging
import os
from collections import OrderedDict
from pathlib import Path

import discord
from src import config

log = logging.getLogger(__name__)
VIEW = 1 << 10
ADMIN = 1 << 3
_verified_bots = OrderedDict()


def remember_bot(user_id):
    # An account ID's bot identity cannot change. Cache identity only: role and
    # channel permissions must still be fetched fresh on every update.
    _verified_bots[user_id] = True
    _verified_bots.move_to_end(user_id)
    while len(_verified_bots) > 64:
        _verified_bots.popitem(last=False)


async def private_image_channel(bot, guild_id):
    path = Path(os.getenv('BOT_DIALOGUE_PEERS_PATH', 'config/bot_dialogue_peers.json'))
    if path.stat().st_size > 16384:
        return None
    cfg = json.loads(path.read_text(encoding='utf-8'))
    if guild_id not in {int(x) for x in cfg.get('allowed_guild_ids', [])}:
        return None
    channel_id = int(cfg.get('control_channel_id', 0))
    if not channel_id:
        return None
    # Fetch current overwrites AND role permissions. Never trust an old cache
    # when deciding whether operational metadata can be published.
    raw = await bot.http.get_channel(channel_id)
    if raw.get('type') != 0 or int(raw.get('guild_id', 0)) != guild_id:
        return None
    overwrites = raw.get('permission_overwrites', [])
    if not any(int(o['id']) == guild_id and int(o['type']) == 0
               and int(o.get('deny', 0)) & VIEW and not int(o.get('allow', 0)) & VIEW
               for o in overwrites):
        return None
    roles = {int(r['id']): int(r['permissions']) for r in await bot.http.get_roles(guild_id)}
    trusted = {int(x) for x in cfg.get('trusted_bot_ids', [])} | {bot.user.id}
    for overwrite in overwrites:
        if not int(overwrite.get('allow', 0)) & VIEW:
            continue
        target = int(overwrite['id'])
        if int(overwrite['type']) == 0:
            if not roles.get(target, 0) & ADMIN:
                return None
        else:
            cached = bot.get_user(target) if callable(getattr(bot, 'get_user', None)) else None
            if target in trusted and (target in _verified_bots or getattr(cached, 'bot', False)):
                remember_bot(target)
                continue
            member = await bot.http.get_member(guild_id, target)
            # A dialogue-only operator must not become an image administrator.
            if member.get('user', {}).get('bot') and target in trusted:
                remember_bot(target)
                continue
            if not any(roles.get(int(r), 0) & ADMIN for r in member.get('roles', [])):
                guild = await bot.http.get_guild(guild_id)
                if int(guild.get('owner_id', 0)) != target:
                    return None
    return await bot.fetch_channel(channel_id)


class ImageStatus:
    def __init__(self, bot, request_message):
        self.bot, self.request = bot, request_message
        self.sent = None

    async def update(self, stage, code=''):
        if config.PROFILE_KEY == 'mukuro':
            from src.chat.services.store import store
            await store.set('imagegen:last_status', {'stage':stage,'code':code[:40],'request_id':str(self.request.id)})
            return
        labels = {'confirmed': '已确认生图请求', 'optimizing': 'AI 正在优化画面提示词',
                  'generating': '提示词已优化，正在生图', 'sent': '图片已发送',
                  'failed': '本次未完成', 'cancelled': '任务已取消'}
        try:
            async with asyncio.timeout(12):
                guild = getattr(self.request, 'guild', None)
                channel = await private_image_channel(self.bot, guild.id) if guild else None
                if channel is None:
                    # Best effort removal if an administrator changed channel
                    # privacy while this job was running. No public fallback.
                    if self.sent:
                        await self.sent.delete()
                        self.sent = None
                    log.info('imagegen_private_status_unavailable profile=%s', config.PROFILE_KEY)
                    return
                body = (f'【{config.BOT_NAME} 生图】{labels[stage]}\n'
                        f'请求者：{self.request.author.id}；请求：{self.request.id}\n'
                        f'{self.request.jump_url}')
                if code:
                    body += '\n状态码：' + code[:40]
                if self.sent:
                    self.sent = await self.sent.edit(content=body, allowed_mentions=discord.AllowedMentions.none())
                else:
                    self.sent = await channel.send(body, suppress_embeds=True,
                        allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            log.info('imagegen_private_status_failed profile=%s type=%s', config.PROFILE_KEY, type(exc).__name__)
