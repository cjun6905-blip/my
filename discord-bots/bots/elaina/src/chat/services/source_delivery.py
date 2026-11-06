"""Keep research citations out of conversation messages; deliver only to owner DM."""
import asyncio
import logging
import re
import discord
from .web_research import append_sources

SOURCE_VIEWER_ID = 0
log = logging.getLogger(__name__)


def public_answer(text):
    # A model may still include citations despite the output instruction.
    text = re.sub(r'(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:来源|参考来源|参考资料|资料来源|参考链接|Sources?|References?)\s*(?:\*\*)?\s*[:：].*$', '', text)
    text = re.sub(r'!?\[([^\]\n]*)\]\(\s*<?https?://[^\s>]+>?\s*\)', r'\1', text, flags=re.I)
    text = re.sub(r'[（(]\s*<?https?://[^\s<>）)]+>?\s*[）)]', '', text, flags=re.I)
    text = re.sub(r'<?(?:https?://|www\.)[^\s<>\u3000，。；！？）)]+>?', '', text, flags=re.I)
    text = re.sub(r'\[\d+(?:[,，\s-]+\d+)*\]|【\d+(?:[,，\s-]+\d+)*】', '', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


async def send_private_sources(bot, sent, sources):
    if not sources:
        return False
    citations = append_sources('', sources).strip()
    if not citations:
        return False
    try:
        async with asyncio.timeout(8):
            viewer = bot.get_user(SOURCE_VIEWER_ID) or await bot.fetch_user(SOURCE_VIEWER_ID)
            await viewer.send('【联网来源 · 仅发送给你】\n对应回复：' + sent.jump_url + '\n' + citations,
                              allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        return True
    except (discord.HTTPException, asyncio.TimeoutError):
        # Never fall back to a channel, another administrator, or the requester.
        log.warning('research_sources_private_delivery_failed')
        return False
