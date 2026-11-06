"""Private controls for Sasuke's verified owner; reusable moderation protections."""
import asyncio
import json
from datetime import timedelta

import discord
from src import config
from src.chat.services.owner_proxy import owner_proxy, OWNER
from src.chat.services.anger_service import anger_service
from src.chat.services.image_status import private_image_channel


async def require_owner(interaction, emergency=False):
    allowed=(interaction.guild_id in config.GUILD_IDS and interaction.user.id==OWNER)
    if emergency and interaction.guild_id in config.GUILD_IDS and getattr(interaction.user,'guild_permissions',discord.Permissions.none()).administrator:
        allowed=True
    if not allowed:
        await interaction.response.send_message('此控制仅限aireck本人使用；管理员可紧急关闭代答。',ephemeral=True)
    return allowed


async def audit(bot, guild, action):
    try:
        async with asyncio.timeout(10):
            channel=await private_image_channel(bot,guild)
            if channel:await channel.send('佐助代理管理记录 · '+action[:500],allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException,asyncio.TimeoutError,ValueError,OSError):pass


async def manual_timeout(interaction, member):
    if not await require_owner(interaction):return
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('你当前没有本服务器的禁言成员权限。',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    if member.guild.id!=interaction.guild_id:
        await interaction.followup.send('成员不在当前服务器。',ephemeral=True);return
    async with anger_service.lock:
        target=await interaction.guild.fetch_member(member.id)
        me=await interaction.guild.fetch_member(interaction.client.user.id)
        if target.bot or target.id==interaction.guild.owner_id or target.guild_permissions.administrator:
            result='服主、管理员和Bot受保护，未执行。'
        elif not me.guild_permissions.moderate_members or target.top_role>=me.top_role:
            result='Bot的权限或角色层级不足，未执行。'
        elif target.is_timed_out():result='对方已在禁言中，不延长。'
        else:
            now=discord.utils.utcnow()
            claimed=await asyncio.to_thread(anger_service._claim,interaction.guild_id,target.id,interaction.id,now.timestamp())
            if claimed!='reserved':result='处于冷却或频率上限，未执行。'
            else:
                try:
                    await target.timeout(now+timedelta(seconds=60),reason='Sasuke owner instruction; operator '+str(OWNER)+'; interaction '+str(interaction.id))
                    result='已禁言1分钟。';status='timed_out'
                except discord.HTTPException:result='Discord拒绝或请求失败，未确认成功。';status='api_error'
                await asyncio.to_thread(anger_service._finish,interaction.id,status)
    await interaction.followup.send(result,ephemeral=True)
    await audit(interaction.client,interaction.guild_id,'手动禁言 · 目标 '+str(member.id)+' · '+result)


async def proxy_state(interaction, enabled=None):
    if not await require_owner(interaction,emergency=enabled is False):return
    if enabled is not None:await owner_proxy.configure(enabled=enabled)
    c=owner_proxy.cfg
    await interaction.response.send_message('代答：'+('开启' if c['enabled'] else '关闭')+'；等待'+str(c['wait_seconds'])+'秒；频道冷却'+str(c['cooldown_seconds'])+'秒；白名单频道：'+', '.join(map(str,c['channels']))+'。正文不附额外标识，使用独立Bot账户。',ephemeral=True)


async def configure(interaction, channel=None, allowed=None, wait=None, cooldown=None):
    if not await require_owner(interaction):return
    changes={}
    if channel is not None:
        if channel.guild.id!=interaction.guild_id or not channel.permissions_for(interaction.user).view_channel:
            await interaction.response.send_message('无法管理这个频道。',ephemeral=True);return
        if allowed is not None:
            channels=list(owner_proxy.cfg['channels'])
            if allowed and channel.id not in channels:
                if len(channels)>=16:
                    await interaction.response.send_message('频道白名单最多16个。',ephemeral=True);return
                if (not channel.permissions_for(channel.guild.default_role).view_channel
                    or not channel.permissions_for(channel.guild.me).read_message_history):
                    await interaction.response.send_message('首版仅允许Bot可读取历史的公开文字频道。',ephemeral=True);return
                from src.chat.services.channel_policy import may_send_automatic_message
                if not may_send_automatic_message(channel):
                    await interaction.response.send_message('该频道受禁止主动发言规则保护，不能开启自动代答。',ephemeral=True);return
                channels.append(channel.id)
            elif not allowed and channel.id in channels:
                channels.remove(channel.id);owner_proxy.cancel(channel.id)
            changes['channels']=channels
    if wait is not None:changes['wait_seconds']=wait
    if cooldown is not None:changes['cooldown_seconds']=cooldown
    if changes:await owner_proxy.configure(**changes)
    c=owner_proxy.cfg
    await interaction.response.send_message('代理配置已保存。白名单频道：'+', '.join('<#'+str(cid)+'>' for cid in c['channels'])+'；等待'+str(c['wait_seconds'])+'秒；同频道冷却'+str(c['cooldown_seconds'])+'秒。',ephemeral=True)


async def learning(interaction, enabled=None):
    if not await require_owner(interaction):return
    if enabled is not None:await owner_proxy.configure(learning=enabled)
    stats=await owner_proxy.stats()
    await interaction.response.send_message('学习：'+('开启' if owner_proxy.cfg['learning'] else '关闭')+'；本人有效样本'+str(stats['samples'])+'条。仅白名单公开频道；最多400条/30天，每天最多两次低优先级总结。',ephemeral=True)


async def style(interaction, operation, version=None):
    if not await require_owner(interaction):return
    await interaction.response.defer(ephemeral=True)
    if operation=='update':text=await owner_proxy.maybe_learn(force=True)
    elif operation=='rollback':
        if version is None:text='请指定语料版本号。'
        else:
            try:await owner_proxy.rollback(version);text='已回滚风格语料。'
            except ValueError:text='没有这个版本。'
    elif operation=='clear':await owner_proxy.clear();text='本人样本和风格版本已清空。佐助基础人设保留。'
    else:
        stats=await owner_proxy.stats()
        labels={'sentence_length':'句子习惯','punctuation':'断句与标点','common_phrases':'常用表达','humor':'幽默方式','response_habits':'回应习惯','kaomoji':'颜文字'}
        text='当前风格语料（仅表达习惯）：\n'+('\n'.join(labels[k]+'：'+v for k,v in stats['style'].items() if v) or '还没有足够样本，当前使用佐助基础人设。')+'\n版本：'+(', '.join(str(v['id']) for v in stats['versions']) or '暂无')
    if operation == 'view':
        e = stats.get('expressions', {})
        visible = list(e.get('unicode', {}).items()) + list(e.get('kaomoji', {}).items())
        text += '\n本人常用符号（按消息计数）：' + ('、'.join(code+'×'+str(count) for code,count in visible[:8]) or '暂无')
        text += '；自定义表情种类：'+str(len(e.get('custom', {})))+'。只从当前确实可用的代码选择。'
    await interaction.followup.send(text[:1900],ephemeral=True)
