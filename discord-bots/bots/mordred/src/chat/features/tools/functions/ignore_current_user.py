from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import discord
from pydantic import BaseModel, Field

from src.chat.features.tools.tool_metadata import tool_metadata
from src.chat.services.ai_moderation_service import (
    ai_moderation_service,
    env_bool,
    env_int,
)
from src.chat.utils.database import chat_db_manager


class IgnoreCurrentUserParams(BaseModel):
    duration_minutes: int = Field(
        default=30,
        ge=5,
        le=180,
        description="暂时不回复当前用户的分钟数，范围 5-180。",
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=300,
        description="不回复的明确原因；应引用当前对话行为，不得捏造。",
    )


@tool_metadata(
    name="暂时不理当前用户",
    description="在当前服务器暂时停止回复当前发言者；不会限制对方正常聊天",
    emoji="🙈",
    category="管理",
)
async def ignore_current_user(
    params: IgnoreCurrentUserParams,
    **kwargs,
) -> Dict[str, Any]:
    """
    暂时不回复当前发言者。只能用于持续纠缠、反复挑衅、刷屏或明确要求停止互动后仍继续的情况。
    不得因普通意见不同、一次玩笑、正常亲昵、礼貌批评或模型心情而调用。
    工具只允许作用于系统注入的当前发言者，不能选择其他成员。
    """
    if not env_bool("AI_IGNORE_ENABLED", True):
        return {"error": "管理员已关闭 AI 不理人功能。"}

    guild = kwargs.get("guild")
    bot = kwargs.get("bot")
    user_id = str(kwargs.get("user_id") or "")
    if not isinstance(guild, discord.Guild) or not user_id.isdigit():
        return {"error": "该功能只能在服务器频道中对当前发言者使用。"}

    member = guild.get_member(int(user_id))
    if member is None:
        return {"error": "无法在当前服务器找到该成员。"}
    if ai_moderation_service.is_protected_member(member):
        return {"error": "该成员受保护，不能由 AI 设置为不回复。"}
    if await chat_db_manager.is_user_globally_blacklisted(member.id):
        return {"status": "already_ignored", "message": "该用户已在全局黑名单中。"}
    if await chat_db_manager.is_user_blacklisted(member.id, guild.id):
        return {"status": "already_ignored", "message": "该用户已处于不回复状态。"}

    min_duration = env_int("AI_IGNORE_MIN_MINUTES", 5, 5, 180)
    max_duration = env_int("AI_IGNORE_MAX_MINUTES", 180, min_duration, 1440)
    duration = max(min_duration, min(max_duration, params.duration_minutes))
    reason = params.reason.strip()

    action_id, limit_error = await ai_moderation_service.reserve_action(
        guild_id=guild.id,
        user_id=member.id,
        action="ignore",
        reason=reason,
        duration_minutes=duration,
        source="ai",
        guild_daily_limit=env_int("AI_IGNORE_GUILD_DAILY_LIMIT", 8, 1, 100),
        user_cooldown_minutes=env_int(
            "AI_IGNORE_USER_COOLDOWN_MINUTES", 120, 5, 10080
        ),
    )
    if action_id is None:
        return {
            "error": (
                "今天的 AI 不理人次数已达到服务器上限。"
                if limit_error == "guild_daily_limit"
                else "近期已经对该用户执行过不理人操作，请勿重复。"
            )
        }

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration)
    try:
        await chat_db_manager.add_to_blacklist(member.id, guild.id, expires_at)
        await ai_moderation_service.finish_action(action_id, True)
    except Exception:
        await ai_moderation_service.finish_action(action_id, False)
        raise

    if isinstance(bot, discord.Client):
        await ai_moderation_service.send_audit(
            bot=bot,
            guild=guild,
            member=member,
            action="暂时不回复",
            reason=reason,
            duration_minutes=duration,
            source="AI",
        )
    return {
        "status": "ignored",
        "duration_minutes": duration,
        "message": "之后的消息将被静默忽略，当前回复可以简短说明决定。",
    }
