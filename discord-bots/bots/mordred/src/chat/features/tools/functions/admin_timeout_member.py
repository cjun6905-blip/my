from datetime import timedelta
import re
from typing import Any, Dict

import discord
from pydantic import BaseModel, Field, ValidationError

from src.chat.features.tools.tool_metadata import tool_metadata
from src.chat.services.ai_moderation_service import (
    ai_moderation_service,
    env_bool,
    env_ids,
    env_int,
)


class AdminTimeoutMemberParams(BaseModel):
    target_user_id: str = Field(
        default="",
        max_length=100,
        description=(
            "目标成员的 @提及、数字 ID 或准确昵称。管理员只提及一名目标成员或回复其消息时可留空；"
            "不得猜测目标。"
        ),
    )
    duration_minutes: int = Field(
        default=5,
        ge=1,
        le=10,
        description="管理员通过 AI 发起的 Discord 禁言分钟数，范围 1-10。",
    )
    reason: str = Field(
        default="管理员指令",
        min_length=1,
        max_length=300,
        description="管理员给出的禁言原因；没有明确原因时概括为管理员指令。",
    )


def _parse_target_id(raw_value: str) -> int | None:
    value = raw_value.strip()
    if value.startswith("<@") and value.endswith(">"):
        value = value[2:-1].lstrip("!")
    return int(value) if value.isdigit() else None


async def _resolve_target_id(
    guild: discord.Guild, source_message: discord.Message, hint: str
) -> tuple[int | None, str | None]:
    """Resolve only a target grounded in the admin's current message or reply."""
    if source_message.guild is None or source_message.guild.id != guild.id:
        return None, "无法验证管理员的当前服务器消息。"

    caller_id = source_message.author.id
    mentioned = {
        user.id: user
        for user in source_message.mentions
        if user.id != caller_id and not user.bot
    }
    replied_id = None
    reference = source_message.reference
    if reference and reference.message_id:
        replied = reference.resolved
        if not isinstance(replied, discord.Message):
            try:
                replied = await source_message.channel.fetch_message(reference.message_id)
            except discord.HTTPException:
                replied = None
        if isinstance(replied, discord.Message) and replied.guild == guild:
            if replied.author.id != caller_id and not replied.author.bot:
                replied_id = replied.author.id

    hint = hint.strip()
    parsed_id = _parse_target_id(hint)
    if parsed_id is not None:
        in_admin_text = re.search(
            rf"(?<!\d){parsed_id}(?!\d)", source_message.content
        )
        if parsed_id in mentioned or parsed_id == replied_id or in_admin_text:
            return parsed_id, None
        return None, "目标 ID 必须出现在管理员当前消息的提及、文字或回复中。"

    if hint:
        candidates = list(mentioned.values())
        if replied_id is not None:
            replied_member = guild.get_member(replied_id)
            if replied_member is not None:
                candidates.append(replied_member)
        if hint.casefold() in source_message.content.casefold():
            candidates.extend(guild.members)
        matches = {
            member.id
            for member in candidates
            if member.id != caller_id
            and any(
                hint.casefold() == name.casefold()
                for name in (
                    member.display_name,
                    member.name,
                    member.global_name or "",
                )
                if name
            )
        }
        if len(matches) == 1:
            return matches.pop(), None
        if len(matches) > 1:
            return None, "多个成员使用这个名字，请 @ 提及目标或回复其消息。"

    if len(mentioned) == 1:
        return next(iter(mentioned)), None
    if len(mentioned) > 1:
        return None, "消息中提及了多名成员，请明确指定要禁言的一个人。"
    if replied_id is not None:
        return replied_id, None
    return None, "请 @ 提及目标、回复目标的消息，或写出唯一的准确昵称。"


@tool_metadata(
    name="执行管理员禁言指令",
    description="当授权管理员明确要求时，对其提及的其他成员执行短时 Discord Timeout",
    emoji="🛡️",
    category="管理",
)
async def admin_timeout_member(
    params: AdminTimeoutMemberParams,
    **kwargs,
) -> Dict[str, Any]:
    """
    执行授权管理员的明确禁言指令。
    只有系统配置的管理员 ID 才能指定其他成员；普通用户请求必须拒绝。
    管理员明确说“禁言/timeout”并提及、回复或准确命名目标时应调用。
    不得从模糊昵称猜测用户 ID，不得把管理员本人或消息中未指定的人作为目标。
    """
    if isinstance(params, dict):
        try:
            params = AdminTimeoutMemberParams.model_validate(params)
        except ValidationError:
            return {"error": "禁言参数无效，请重新指定目标、时长和原因。"}
    if not env_bool("AI_TIMEOUT_ENABLED", True):
        return {"error": "管理员已关闭 AI Discord 禁言功能。"}

    caller_id_raw = str(kwargs.get("user_id") or "")
    controller_ids = env_ids("AI_MODERATION_CONTROLLER_IDS")
    if not caller_id_raw.isdigit() or int(caller_id_raw) not in controller_ids:
        return {"error": "只有授权管理员可以要求 AI 禁言其他成员。"}

    guild = kwargs.get("guild")
    bot = kwargs.get("bot")
    channel = kwargs.get("channel")
    source_message = kwargs.get("source_message")
    if not isinstance(guild, discord.Guild):
        return {"error": "该功能只能在服务器频道中使用。"}
    if not isinstance(source_message, discord.Message):
        return {"error": "无法验证管理员的当前消息，请改用 /禁言用户。"}
    if source_message.author.id != int(caller_id_raw):
        return {"error": "管理员身份与当前消息不一致。"}

    target_id, target_error = await _resolve_target_id(
        guild, source_message, params.target_user_id
    )
    if target_id is None:
        return {"error": target_error}
    member = guild.get_member(target_id)
    if member is None:
        try:
            member = await guild.fetch_member(target_id)
        except discord.HTTPException:
            return {"error": "无法在当前服务器找到目标成员。"}
    if ai_moderation_service.is_protected_member(member):
        return {"error": "目标是机器人、服主或受保护的管理成员，不能由 AI 禁言。"}
    if member.is_timed_out():
        return {"status": "already_timed_out", "message": "该成员已经处于禁言状态。"}

    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.moderate_members:
        return {"error": "机器人缺少 Moderate Members（禁言成员）权限。"}
    if member.top_role >= bot_member.top_role:
        return {"error": "目标角色不低于机器人最高角色；请由服主调整角色顺序。"}

    min_duration = env_int("AI_TIMEOUT_MIN_MINUTES", 1, 1, 10)
    max_duration = env_int("AI_TIMEOUT_MAX_MINUTES", 10, min_duration, 60)
    duration = max(min_duration, min(max_duration, params.duration_minutes))
    reason = params.reason.strip() or "管理员指令"

    action_id, limit_error = await ai_moderation_service.reserve_action(
        guild_id=guild.id,
        user_id=member.id,
        action="timeout",
        reason=reason,
        duration_minutes=duration,
        source=f"admin_ai:{caller_id_raw}",
        guild_daily_limit=env_int("AI_TIMEOUT_GUILD_DAILY_LIMIT", 10, 1, 100),
        user_cooldown_minutes=env_int(
            "AI_ADMIN_TIMEOUT_USER_COOLDOWN_MINUTES", 5, 1, 1440
        ),
    )
    if action_id is None:
        return {
            "error": (
                "今天的 AI 禁言次数已达到服务器上限。"
                if limit_error == "guild_daily_limit"
                else "近期已经对该成员执行过禁言，请稍后再试。"
            )
        }

    try:
        await member.timeout(
            timedelta(minutes=duration),
            reason=f"Authorized admin via AI: {reason[:380]}",
        )
        await ai_moderation_service.finish_action(action_id, True)
    except discord.Forbidden:
        await ai_moderation_service.finish_action(action_id, False)
        return {"error": "Discord 拒绝禁言：目标可能拥有管理员权限或角色层级不低于机器人。"}
    except Exception:
        await ai_moderation_service.finish_action(action_id, False)
        raise

    if isinstance(bot, discord.Client):
        await ai_moderation_service.send_audit(
            bot=bot,
            guild=guild,
            member=member,
            action="管理员指令 Discord Timeout",
            reason=reason,
            duration_minutes=duration,
            source=f"管理员经 AI：{caller_id_raw}",
        )
    public_notice_sent = await ai_moderation_service.send_public_timeout_notice(
        channel=channel,
        member=member,
        duration_minutes=duration,
        reason=reason,
        source="管理员指令",
    )
    return {
        "status": "timed_out",
        "target_user_id": str(member.id),
        "duration_minutes": duration,
        "public_notice_sent": public_notice_sent,
        "message": "已执行授权管理员的禁言指令。",
    }
