from datetime import timedelta
from typing import Any, Dict

import discord
from pydantic import BaseModel, Field

from src.chat.features.tools.tool_metadata import tool_metadata
from src.chat.services.ai_moderation_service import (
    ai_moderation_service,
    env_bool,
    env_int,
)


class TimeoutCurrentUserParams(BaseModel):
    duration_minutes: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Discord 原生禁言分钟数，范围 1-10。",
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=300,
        description="禁言的明确严重原因；必须基于当前对话证据，不得捏造。",
    )


@tool_metadata(
    name="禁言当前用户",
    description="对当前发言者执行短时 Discord Timeout；仅限明确、持续且严重的违规",
    emoji="🔇",
    category="管理",
)
async def timeout_current_user(
    params: TimeoutCurrentUserParams,
    **kwargs,
) -> Dict[str, Any]:
    """
    对当前发言者执行短时 Discord Timeout。这是最后手段。
    只有在持续刷屏、明确人身攻击、威胁或反复严重骚扰，且温和提醒无效时才能调用。
    普通争论、单次玩笑、正常亲昵、轻微冒犯、模型不高兴或意见不同绝不能触发。
    工具只允许作用于系统注入的当前发言者，不能选择其他成员。
    如果授权管理员要求禁言被提及的其他成员，应改用 admin_timeout_member。
    """
    if not env_bool("AI_TIMEOUT_ENABLED", True):
        return {"error": "管理员已关闭 AI Discord 禁言功能。"}

    guild = kwargs.get("guild")
    bot = kwargs.get("bot")
    channel = kwargs.get("channel")
    user_id = str(kwargs.get("user_id") or "")
    if not isinstance(guild, discord.Guild) or not user_id.isdigit():
        return {"error": "该功能只能在服务器频道中对当前发言者使用。"}

    member = guild.get_member(int(user_id))
    if member is None:
        return {"error": "无法在当前服务器找到该成员。"}
    if ai_moderation_service.is_protected_member(member):
        return {"error": "该成员受保护，不能由 AI 禁言。"}
    if member.is_timed_out():
        return {"status": "already_timed_out", "message": "该成员已经处于禁言状态。"}

    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.moderate_members:
        return {"error": "机器人缺少 Moderate Members（禁言成员）权限。"}
    if member.top_role >= bot_member.top_role:
        return {"error": "机器人角色层级不足，无法禁言该成员。"}

    min_duration = env_int("AI_TIMEOUT_MIN_MINUTES", 1, 1, 10)
    max_duration = env_int("AI_TIMEOUT_MAX_MINUTES", 10, min_duration, 60)
    duration = max(min_duration, min(max_duration, params.duration_minutes))
    reason = params.reason.strip()

    action_id, limit_error = await ai_moderation_service.reserve_action(
        guild_id=guild.id,
        user_id=member.id,
        action="timeout",
        reason=reason,
        duration_minutes=duration,
        source="ai",
        guild_daily_limit=env_int("AI_TIMEOUT_GUILD_DAILY_LIMIT", 3, 1, 30),
        user_cooldown_minutes=env_int(
            "AI_TIMEOUT_USER_COOLDOWN_MINUTES", 1440, 30, 43200
        ),
    )
    if action_id is None:
        return {
            "error": (
                "今天的 AI 禁言次数已达到服务器上限。"
                if limit_error == "guild_daily_limit"
                else "近期已经对该用户执行过 AI 禁言，请交由人工管理员处理。"
            )
        }

    try:
        await member.timeout(
            timedelta(minutes=duration),
            reason=f"AI moderation: {reason[:400]}",
        )
        await ai_moderation_service.finish_action(action_id, True)
    except Exception:
        await ai_moderation_service.finish_action(action_id, False)
        raise

    if isinstance(bot, discord.Client):
        await ai_moderation_service.send_audit(
            bot=bot,
            guild=guild,
            member=member,
            action="Discord Timeout",
            reason=reason,
            duration_minutes=duration,
            source="AI",
        )
    public_notice_sent = await ai_moderation_service.send_public_timeout_notice(
        channel=channel,
        member=member,
        duration_minutes=duration,
        reason=reason,
        source="AI 自动判断",
    )
    return {
        "status": "timed_out",
        "duration_minutes": duration,
        "public_notice_sent": public_notice_sent,
        "message": "用户已被短时禁言；请勿嘲讽，并简短说明社区边界。",
    }
