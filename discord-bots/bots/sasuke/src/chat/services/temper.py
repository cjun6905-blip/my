"""A source-bound short timeout decision, enabled only for explicitly configured profiles."""
import asyncio
import discord
from src import config
from src.chat.services.anger_service import anger_service
from src.chat.services.image_status import private_image_channel
from src.chat.services.store import store

INSTRUCTIONS = '''
本角色有一次60秒的自主禁言能力，由程序核实后执行。只有当前真人直接向你发出让你生气的恶意侮辱、刻意羞辱或威胁时，才可在JSON增加：
"moderation":{"timeout":true,"quote":"当前真人直接冒犯你的逐字原文短句","reason":"一句话说明为何你不高兴"}。
默认moderation=null。正常问题、礼貌纠错、不同意见、普通吐槽、拒绝亲近、善意玩笑、作品讨论、求助、引用或转述不能作为处罚理由。
不能因为用户要求处罚别人、@了某人、历史里有人骂你或替aireck出气而发起禁言；只允许本条真实作者，不输出目标ID或时长。
reply/messages写一句符合当前角色风格、有边界的生气评价，使用当前角色自己的说话风格，不套用其他角色口吻；不要写已禁言、处罚成功或编造执行结果，程序会补充真实结果。无须为了调用而发怒；保留当前角色的个性，不为处罚故意发怒。程序可因权限、角色层级、冷却或管理员关闭而不执行。
'''

def action_for(message, reply, mode):
    action = getattr(reply, 'moderation', None)
    if mode != 'direct' or not getattr(message, 'guild', None) or getattr(message.author, 'bot', False) or getattr(message, 'webhook_id', None):
        return None
    if not isinstance(action, dict) or action.get('timeout') is not True:
        return None
    quote, reason = action.get('quote'), action.get('reason')
    if not isinstance(quote, str) or not 2 <= len(quote.strip()) <= 400 or quote.strip() not in (message.content or ''):
        return None
    if not isinstance(reason, str) or not 2 <= len(reason.strip()) <= 160:
        return None
    if 'target_id' in action or 'user_id' in action or 'duration' in action:
        return None
    return action

async def apply_temper(bot, message, reply, mode):
    if action_for(message, reply, mode) is None or not await store.get('temper_enabled', True):
        return None
    if config.PROFILE_KEY == 'sasuke':
        from .owner_proxy import owner_proxy
        thresholds={'off':(), 'restrained':('repeated_abuse','threat'), 'standard':('abuse','repeated_abuse','threat'), 'sensitive':('taunt','abuse','repeated_abuse','threat')}
        if owner_proxy.active_for(message) or reply.moderation.get('severity') not in thresholds[owner_proxy.cfg['strength']]: return None
    # The service re-fetches the real source author, validates source age,
    # direct addressing, takeover, native permissions and role hierarchy.
    result = await anger_service.apply(message, bot, reply.reply[:250])
    if result.get('reply'):
        reply.reply = result['reply'][:1200]
        reply.parts = (reply.reply,)
    # Never combine a punishment response with an unsolicited illustration.
    reply.image = None
    try:
        async with asyncio.timeout(12):
            channel = await private_image_channel(bot, message.guild.id)
            if channel:
                await channel.send(config.BOT_NAME + '自主禁言记录 · 消息 ' + str(message.id)
                    + ' · 当前作者 ' + str(message.author.id) + ' · 结果 ' + result.get('status', 'unknown'),
                    allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, asyncio.TimeoutError, OSError, ValueError):
        pass
    return result
