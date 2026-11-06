# -*- coding: utf-8 -*-

import json
import re

import discord

DISCORD_MESSAGE_LIMIT = 2000
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024


def user_mentions() -> discord.AllowedMentions:
    """Permit individual pings without enabling mass or role mentions."""
    return discord.AllowedMentions(users=True, roles=False, everyone=False, replied_user=False)


def with_mention_context(message: discord.Message, text: str) -> str:
    members = {message.author.id: message.author}
    members.update({user.id: user for user in message.mentions})
    reference = getattr(message, "reference", None)
    resolved = getattr(reference, "resolved", None)
    if isinstance(resolved, discord.Message):
        members[resolved.author.id] = resolved.author
    identities = [
        {"name": user.display_name, "mention": f"<@{user.id}>"}
        for user in members.values() if not user.bot
    ]
    return (
        text + "\n\n[Discord 提及格式提示：仅在确有必要时 @ 用户，使用真实的 <@数字ID>，"
        "不要使用 @昵称、反引号或转义符，不要猜测 ID。以下是本条消息已确认的用户数据："
        + json.dumps(identities, ensure_ascii=False) + "]"
    )


def split_message(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = None
        for sep in ["\n\n", "\n", " "]:
            idx = remaining.rfind(sep, 0, limit)
            if idx > limit * 0.25:
                split_at = idx
                break

        if split_at is None:
            split_at = limit

        # A hard split must not cut a Discord mention/custom emoji in half.
        for match in re.finditer(r"<(?:@!?|@&|#)\d+>|<a?:\w+:\d+>", remaining):
            if match.start() < split_at < match.end() and match.start() > 0:
                split_at = match.start()
                break

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n ")

    return chunks


def truncate_text(text: str, limit: int, suffix: str = "...") -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(suffix)] + suffix


async def safe_send(
    sendable, text: str, embed=None, view=None, **kwargs
) -> list[discord.Message]:
    chunks = split_message(text)
    kwargs.setdefault("allowed_mentions", user_mentions())
    messages = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            if embed is not None:
                kwargs["embed"] = embed
            if view is not None:
                kwargs["view"] = view
            msg = await sendable.send(chunk, **kwargs)
        else:
            msg = await sendable.send(chunk, allowed_mentions=kwargs["allowed_mentions"])
        messages.append(msg)
    return messages


async def safe_reply(
    message: discord.Message, text: str, embed=None, view=None, **kwargs
) -> list[discord.Message]:
    chunks = split_message(text)
    kwargs.setdefault("allowed_mentions", user_mentions())
    messages = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            if embed is not None:
                kwargs["embed"] = embed
            if view is not None:
                kwargs["view"] = view
            msg = await message.reply(chunk, **kwargs)
        else:
            msg = await message.channel.send(chunk, allowed_mentions=kwargs["allowed_mentions"])
        messages.append(msg)
    return messages
