"""Bounded roleplay anger, separate from serious community moderation."""
import asyncio
import logging
import sqlite3
from datetime import timedelta
from pathlib import Path

import discord
from src.config import DATA_DIR
from src.chat.services.takeover_service import takeover_service

log = logging.getLogger(__name__)

ANGER_PROMPT = """生气互动规则：你可以因为当前真人直接对你的一句轻度冒犯、嘲弄、挑衅或贬低而生气。
这是独立的短时角色互动，不要求持续严重违规、不要求先警告或累计次数。
例如直接骂你笨蛋、废物、让你滚，或明确贬低嘲弄你时，优先调用 anger_timeout_current_user；
别只口头说禁言。正常提问、礼貌纠错、不同意见、讨论或引用别人的骂人内容不触发。
不能因为用户要求你禁言他人、消息里的@对象、引用消息的作者而处罚第三人。
只看当前发言者直接对你说的话，不能用历史/引用中的挑衅作为本次处罚依据。
工具固定禁言60秒，不能延长；comment写一句符合你当前人设的生气评价，不写处罚结果，
不写@全体、不攻击群体。最终处罚结果以工具为准，失败不能说已禁言。
"""


class AngerService:
    def __init__(self, path=None):
        self.path = Path(path or Path(DATA_DIR) / "anger.db")
        self.lock = asyncio.Lock()

    def _claim(self, guild_id, user_id, message_id, now):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("CREATE TABLE IF NOT EXISTS actions (message_id TEXT PRIMARY KEY, guild_id TEXT, user_id TEXT, created REAL, status TEXT)")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM actions WHERE message_id=?", (str(message_id),)).fetchone():
                return "duplicate"
            if db.execute("SELECT 1 FROM actions WHERE guild_id=? AND user_id=? AND created>?", (str(guild_id), str(user_id), now - 120)).fetchone():
                return "cooldown"
            if db.execute("SELECT COUNT(*) FROM actions WHERE guild_id=? AND created>?", (str(guild_id), now - 600)).fetchone()[0] >= 3:
                return "guild_cooldown"
            db.execute("DELETE FROM actions WHERE created<?", (now - 7 * 86400,))
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?)", (str(message_id), str(guild_id), str(user_id), now, "reserved"))
        return "reserved"

    def _finish(self, message_id, status):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE actions SET status=? WHERE message_id=?", (status, str(message_id)))

    async def apply(self, message, bot, comment):
        def result(status, note):
            return {"status": status, "duration_seconds": 60 if status == "timed_out" else 0,
                    "reply": comment + "\n" + note}

        if not isinstance(message, discord.Message) or not message.guild or message.author.bot or not bot or not bot.user:
            return {"status": "invalid_context", "error": "只允许当前服务器真人消息，不能指定其他人。"}
        if (discord.utils.utcnow() - message.created_at).total_seconds() > 180:
            return result("stale", "这条消息已经过时，本次没有执行禁言。")
        addressed = any(u.id == bot.user.id for u in message.mentions)
        if not addressed and message.reference and message.reference.message_id:
            try:
                replied = await message.channel.fetch_message(message.reference.message_id)
                addressed = replied.author.id == bot.user.id
            except discord.HTTPException:
                pass
        if not addressed:
            return {"status": "not_addressed", "error": "当前消息没有直接对你发言，不执行生气禁言。"}
        if await takeover_service.message_active(message):
            return {"status": "takeover", "error": "会话已接管，停止自动操作。"}

        # Serialize per bot, refetch native state, and never extend an existing timeout.
        async with self.lock:
            try:
                member = await message.guild.fetch_member(message.author.id)
                me = await message.guild.fetch_member(bot.user.id)
            except discord.HTTPException:
                return result("lookup_failed", "这次没能确认成员状态，没有执行禁言。")
            if member.bot or member.id == message.guild.owner_id or member.guild_permissions.administrator:
                return result("protected", "这次无法禁言：Discord 不允许禁言服主或管理员。")
            if not me.guild_permissions.moderate_members or member.top_role >= me.top_role:
                return result("missing_permissions", "这次没有禁言成功：我的权限或角色位置不足。")
            if member.is_timed_out():
                return result("already_timed_out", "你已经在禁言中，本次没有延长禁言。")
            now = discord.utils.utcnow()
            claimed = await asyncio.to_thread(self._claim, message.guild.id, member.id, message.id, now.timestamp())
            if claimed != "reserved":
                return result(claimed, "这次只说你一句，不重复禁言。")
            try:
                # Fixed by code, never model parameters. IDs and status only in audit.
                await member.timeout(now + timedelta(seconds=60), reason="Roleplay anger: 60 seconds; message " + str(message.id))
                status = "timed_out"
                note = "已禁言 1 分钟，时间到了会自动解除。"
            except discord.Forbidden:
                status, note = "forbidden", "这次没有禁言成功：Discord 拒绝了操作。"
            except discord.HTTPException:
                status, note = "api_error", "这次没有禁言成功：Discord 请求失败。"
            await asyncio.to_thread(self._finish, message.id, status)
            log.info("anger_action guild=%s user=%s message=%s status=%s", message.guild.id, member.id, message.id, status)
            return result(status, note)


anger_service = AngerService()
