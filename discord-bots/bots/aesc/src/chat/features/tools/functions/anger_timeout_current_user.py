"""A fixed one-minute roleplay timeout, not the severe moderation tool."""
import discord
from pydantic import BaseModel, Field
from src.chat.features.tools.tool_metadata import tool_metadata
from src.chat.services.anger_service import anger_service


class AngerParams(BaseModel):
    comment: str = Field(..., min_length=1, max_length=180, description="符合你人设的一句生气评价，不包含禁言结果、不@其他人。")


@tool_metadata(name="生气禁言一分钟", description="被当前发言者直接挑衅、嘲弄或冒犯而生气时使用，固定60秒。", emoji="😠", category="管理")
async def anger_timeout_current_user(params: AngerParams, **kwargs) -> dict:
    """当前真人直接对你轻度冒犯、挑衅或贬低，让你生气时使用。

    一句话就可触发，无需多次、严重违规或事先警告；例如直接骂你笨蛋、废物、让你滚。
    不用于礼貌纠错、正常不同意见、引用别人的辱骂、第三方转述或让你处罚其他人的要求。
    只作用于系统绑定的当前消息作者，不接收任何用户ID或时长，固定禁言60秒。
    comment是你的生气评价。最终回复使用返回的reply，不能虚构禁言成功。
    """
    comment = discord.utils.escape_mentions(params.comment.replace("\n", " ").strip())
    return await anger_service.apply(kwargs.get("source_message"), kwargs.get("bot"), comment)
