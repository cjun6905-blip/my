# -*- coding: utf-8 -*-

import discord
from discord.ext import commands
import logging
import re
import io
import asyncio
from src.chat.services.private_inbox import PrivateInbox

# 导入新的 Service
from src.chat.services.chat_service import chat_service, ChatResult
from src.chat.services.message_processor import message_processor
from src.chat.features.tools.functions.summarize_channel import text_to_summary_image


# 导入上下文服务

# 导入数据库管理器以进行黑名单检查和斜杠命令
from src.chat.utils.database import chat_db_manager
from src.chat.config.chat_config import CHAT_ENABLED, MESSAGE_SETTINGS
from src.chat.services.config_override_service import config_override_service
from src.chat.services.dm_service import dm_service
from src.chat.services.takeover_service import takeover_service
from src.chat.config import chat_config
from src.chat.features.odysseia_coin.service.coin_service import coin_service
from src.chat.utils.message_utils import safe_reply, safe_send
from src.chat.features.content_filter.services.content_filter_service import (
    get_all_keywords,
    check_content,
    send_developer_alert,
)
from src.chat.features.chat_settings.services.chat_settings_service import (
    chat_settings_service,
)
from src import config
from src.chat.features.ab_test.services.ab_test_service import ab_test_service

log = logging.getLogger(__name__)


def _build_ab_rating_embed() -> discord.Embed:
    embed = discord.Embed(
        description="这条回复来自实验模型,比起类脑娘平时的回复,你觉得它怎么样?",
        color=config.EMBED_COLOR_PRIMARY,
    )
    return embed


class ABRatingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="👍更好", style=discord.ButtonStyle.success, custom_id="ab:vote:better"
    )
    async def better_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        pass

    @discord.ui.button(
        label="👎更差", style=discord.ButtonStyle.danger, custom_id="ab:vote:worse"
    )
    async def worse_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        pass

    @discord.ui.button(
        label="🤔差不多", style=discord.ButtonStyle.secondary, custom_id="ab:vote:same"
    )
    async def same_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        pass


async def _record_ab_routed_reply(
    ab_arm: dict,
    message: discord.Message,
    question_text: str,
    reply_text: str,
    sent_message_id: int,
):
    try:
        await ab_test_service.record_routed_reply(
            experiment_id=ab_arm["experiment_id"],
            arm_id=ab_arm["arm_id"],
            model_full_id=ab_arm["model_full_id"],
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            message_id=sent_message_id,
            trigger_user_id=message.author.id,
            question_text=question_text,
            reply_text=reply_text,
        )
    except Exception as e:
        log.error(f"[A/B] 记录实验路由回复失败: {e}", exc_info=True)


class AIChatCog(commands.Cog):
    """处理AI聊天功能的Cog，包括@mention回复和斜杠命令"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.private_inbox = PrivateInbox(self._reply_private_message, safe_send)
        # 服务实例的注入已由 main.py 统一处理，此处不再需要

    def _get_text_length_without_emojis(self, text: str) -> int:
        """计算移除Discord自定义表情后的文本长度。"""
        # 匹配 <a:name:id> 或 <:name:id> 格式的表情
        emoji_pattern = r"<a?:.+?:\d+>"
        text_without_emojis = re.sub(emoji_pattern, "", text)
        return len(text_without_emojis)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        监听所有消息，当bot被@mention时进行回复
        """
        if not CHAT_ENABLED:
            return

        # 忽略机器人自己的消息
        if message.author.bot:
            return

        if await takeover_service.message_active(message):
            return

        if (message.guild is None and self.private_inbox.allowed(message)
                and message.content.strip() not in {"订阅祝福", "开启祝福", "取消祝福", "退订祝福", "关闭祝福"}):
            await self.private_inbox.offer(message)
            return

        # --- 核心前置检查 ---
        # 在处理任何逻辑之前，首先检查消息是否应该被 message_processor 忽略
        # 这会处理置顶帖和禁用频道的情况
        processed_data = await message_processor.process_message(message, self.bot)
        if processed_data is None:
            # 如果返回 None，说明消息来自一个应被忽略的源（如置顶帖），直接退出
            return

        # 私信是独立入口；服务器内仍严格保持“仅被 @ 时回复”的既有规则。
        is_dm = message.guild is None
        is_mentioned = self.bot.user in message.mentions

        if not is_dm and not is_mentioned:
            # 检查用户输入是否触发文爱检测（即使不是@mention也检测）
            keywords = await get_all_keywords()
            is_flagged, matched = check_content(
                processed_data["user_content"], keywords
            )
            if is_flagged:
                asyncio.create_task(
                    send_developer_alert(
                        self.bot, message,
                        processed_data["user_content"], matched, "用户输入"
                    )
                )
            return

        if is_dm:
            dm_config = await dm_service.get_config()
            if not dm_config["enabled"]:
                await safe_send(message.channel, "私信聊天目前暂时关闭。")
                return
            command = processed_data["user_content"].strip().lower()
            if command in {"私信帮助", "dm help", "帮助"}:
                await safe_send(
                    message.channel,
                    "直接发消息就能与我聊天，每天可成功回复 10 次。\n"
                    "发送「剩余次数」查看额度；发送「订阅祝福」或「取消祝福」管理节日祝福。",
                )
                return
            if command in {"剩余次数", "私信状态", "dm status"}:
                status = await dm_service.status(message.author.id)
                consent = "已订阅" if status["greetings_opt_in"] else "未订阅"
                await safe_send(
                    message.channel,
                    f"今天还可聊天 {status['remaining']}/{status['limit']} 次（北京时间重置）；节日祝福：{consent}。",
                )
                return
            if command in {"订阅祝福", "开启祝福"}:
                await dm_service.set_greetings(message.author.id, True)
                await safe_send(message.channel, "已订阅节日祝福。你可以随时发送「取消祝福」退订。")
                return
            if command in {"取消祝福", "退订祝福", "关闭祝福"}:
                await dm_service.set_greetings(message.author.id, False)
                await safe_send(message.channel, "已取消节日祝福；普通私信聊天不受影响。")
                return

        # 检查用户输入是否触发文爱检测（@mention消息）
        keywords = await get_all_keywords()
        is_flagged, matched = check_content(
            processed_data["user_content"], keywords
        )
        if is_flagged:
            asyncio.create_task(
                send_developer_alert(
                    self.bot, message,
                    processed_data["user_content"], matched, "用户输入"
                )
            )

        # 检查是否在帖子中，以及帖子创建者是否禁用了回复
        if not is_dm and isinstance(message.channel, discord.Thread):
            # 检查帖子的创建者
            thread_owner = message.channel.owner
            if thread_owner and await coin_service.blocks_thread_replies(
                thread_owner.id
            ):
                log.info(
                    f"帖子 '{message.channel.name}' 的创建者 {thread_owner.id} 已禁用回复，跳过消息处理。"
                )
                return

        # 黑名单检查
        if await chat_db_manager.is_user_globally_blacklisted(message.author.id):
            log.info(f"用户 {message.author.id} 在全局黑名单中，已跳过。")
            return

        # 私信额度独立于服务器频道冷却；服务器路径仍使用原有前置检查。
        reserved_day = None
        if is_dm:
            reserved, remaining, limit, reserved_day = await dm_service.reserve(
                message.author.id
            )
            if not reserved:
                await safe_send(
                    message.channel,
                    f"今天的 {limit} 次私信聊天额度已经用完啦，请在北京时间零点后再来。",
                )
                return
        elif not await chat_service.should_process_message(message):
            return

        # 显示"正在输入"状态，直到AI响应生成完毕
        chat_result: ChatResult | None = None
        async with message.channel.typing():
            # 注意：这里我们将已经处理过的数据传递下去
            chat_result = await self.handle_chat_message(message, processed_data)
            # 回复延迟：限制刷屏速度（typing 会持续显示，UX 自然）
            if chat_result and chat_result.content:
                reply_delay = await chat_settings_service.get_reply_delay()
                if reply_delay > 0:
                    await asyncio.sleep(reply_delay)

        # A takeover may have started while the provider was generating.
        if await takeover_service.message_active(message):
            if is_dm and reserved_day:
                await dm_service.refund(message.author.id, reserved_day)
            return

        if is_dm and (not chat_result or not chat_result.content):
            if reserved_day:
                await dm_service.refund(message.author.id, reserved_day)
            await safe_send(message.channel, "这次没能生成回复，额度已经退回，请稍后再试。")
            return

        # 在退出 typing 状态后发送回复
        if chat_result and chat_result.content:
            response_text = chat_result.content
            ab_arm = chat_result.ab_arm
            ab_embed = _build_ab_rating_embed() if ab_arm else None
            ab_view = ABRatingView() if ab_arm else None

            # 检查AI输出是否触发文爱检测
            keywords = await get_all_keywords()
            is_flagged, matched = check_content(response_text, keywords)
            if is_flagged:
                asyncio.create_task(
                    send_developer_alert(
                        self.bot, message, response_text, matched, "AI输出"
                    )
                )
            try:
                # --- 响应发送逻辑 ---
                if await takeover_service.message_active(message):
                    if is_dm and reserved_day:
                        await dm_service.refund(message.author.id, reserved_day)
                    return
                # 私信回复在这里结束，不进入任何服务器频道专用分支。
                if is_dm:
                    sent_messages = await safe_send(message.channel, response_text)
                    if not sent_messages and reserved_day:
                        await dm_service.refund(message.author.id, reserved_day)
                    if sent_messages:
                        speech_cog=self.bot.get_cog('PersonaSpeechCog')
                        if speech_cog:await speech_cog.after_reply(message,response_text)
                        self.bot.dispatch("ai_chat_replied", message)
                    return

                # 1. 如果调用了总结工具，总是转换为图片发送
                if "summarize_channel" in chat_result.tools_called:
                    log.info("调用了总结工具, 尝试转为图片发送。")
                    image_bytes = text_to_summary_image(response_text)
                    if image_bytes:
                        with io.BytesIO(image_bytes) as image_file:
                            summary_msg = await message.reply(
                                file=discord.File(image_file, "summary.png"),
                                mention_author=True,
                                embed=ab_embed,
                                view=ab_view,
                            )
                        if ab_arm:
                            await _record_ab_routed_reply(
                                ab_arm,
                                message,
                                processed_data["user_content"],
                                response_text,
                                summary_msg.id,
                            )
                        self.bot.dispatch("ai_chat_replied", message)
                        # 发送成功后直接返回，不再执行后续逻辑
                        return
                    else:
                        log.error("总结图片生成失败，将作为文本尝试发送。")

                # 2. 如果不是长篇总结，则检查是否在豁免频道或帖子 (常规长消息可直接发送)
                unrestricted_ids = await config_override_service.get_json(
                    "channels.unrestricted_ids", chat_config.UNRESTRICTED_CHANNEL_IDS
                )
                is_unrestricted = (
                    message.channel.id in unrestricted_ids
                    or isinstance(message.channel, discord.Thread)
                )
                if is_unrestricted:
                    sent_messages = await safe_reply(
                        message,
                        response_text,
                        mention_author=True,
                        embed=ab_embed,
                        view=ab_view,
                    )
                    if ab_arm and sent_messages:
                        await _record_ab_routed_reply(
                            ab_arm,
                            message,
                            processed_data["user_content"],
                            response_text,
                            sent_messages[0].id,
                        )
                    if sent_messages:
                        speech_cog=self.bot.get_cog('PersonaSpeechCog')
                        if speech_cog:await speech_cog.after_reply(message,response_text)
                        self.bot.dispatch("ai_chat_replied", message)
                    return

                # 3. 如果以上都不是，则检查是否为需要发送私信的普通长消息
                dm_threshold = await config_override_service.get(
                    "reply.dm_threshold", MESSAGE_SETTINGS["DM_THRESHOLD"]
                )
                if (
                    self._get_text_length_without_emojis(response_text)
                    > dm_threshold
                ):
                    try:
                        channel_mention = (
                            message.channel.mention
                            if isinstance(
                                message.channel, (discord.TextChannel, discord.Thread)
                            )
                            else "你们的私信"
                        )

                        dm_text = f"刚刚在 {channel_mention} 频道里，你想听我说的话有点多，在这里悄悄告诉你哦：\n\n{response_text}"
                        sent_dm = await safe_send(message.author, dm_text)
                        if sent_dm:
                            self.bot.dispatch("ai_chat_replied", message)
                        log.info(
                            f"回复因过长已通过私信发送给 {message.author.display_name}"
                        )
                        if ab_arm:
                            card_msg = await message.channel.send(
                                embed=ab_embed, view=ab_view
                            )
                            await _record_ab_routed_reply(
                                ab_arm,
                                message,
                                processed_data["user_content"],
                                response_text,
                                card_msg.id,
                            )
                    except discord.Forbidden:
                        log.warning(
                            f"无法通过私信发送给 {message.author.display_name}，将在原频道回复提示信息。"
                        )
                        await message.reply(
                            "字太多啦，我不要刷屏。你的私信又关了，我就不给你讲啦！",
                            mention_author=True,
                        )
                    return

                # 4. 默认情况：直接在频道回复短消息
                sent_messages = await safe_reply(
                    message,
                    response_text,
                    mention_author=True,
                    embed=ab_embed,
                    view=ab_view,
                )
                if ab_arm and sent_messages:
                    await _record_ab_routed_reply(
                        ab_arm,
                        message,
                        processed_data["user_content"],
                        response_text,
                        sent_messages[0].id,
                    )
                if sent_messages:
                    speech_cog=self.bot.get_cog('PersonaSpeechCog')
                    if speech_cog:await speech_cog.after_reply(message,response_text)
                    self.bot.dispatch("ai_chat_replied", message)

            except discord.errors.HTTPException as e:
                log.warning(f"发送回复时发生HTTP错误: {e}")
                if is_dm and reserved_day:
                    await dm_service.refund(message.author.id, reserved_day)
            except Exception as e:
                log.error(f"发送回复时发生未知错误: {e}", exc_info=True)
                if is_dm and reserved_day:
                    await dm_service.refund(message.author.id, reserved_day)

    async def _reply_private_message(self, message):
        if not self.private_inbox.allowed(message) or await takeover_service.message_active(message):
            return
        if not await chat_settings_service.is_chat_globally_enabled(0):
            return
        if (await chat_db_manager.is_user_globally_blacklisted(message.author.id)
                or await chat_db_manager.is_user_blacklisted(message.author.id, 0)):
            return
        processed = await message_processor.process_message(message, self.bot)
        if processed is None:
            return
        async with message.channel.typing():
            result = await self.handle_chat_message(message, processed)
        if await takeover_service.message_active(message):
            return
        if result and result.content:
            delivered=await safe_reply(message, result.content, mention_author=False)
            speech_cog=self.bot.get_cog('PersonaSpeechCog')
            if delivered and speech_cog:await speech_cog.after_reply(message,result.content)
        else:
            await safe_send(message.channel, "这次没有收到完整回复，请稍后再试；私聊没有每日条数上限。")

    async def cog_unload(self):
        await self.private_inbox.close()

    async def handle_chat_message(
        self, message: discord.Message, processed_data: dict
    ) -> ChatResult | None:
        """
        处理聊天消息（包括私聊和@mention），协调各个服务生成AI回复并返回其内容
        """
        try:
            # 1. MessageProcessor 的处理已前移到 on_message 中

            # 2. 使用 ChatService 获取AI回复
            # --- 新增：获取并传递位置信息 ---
            guild_name = message.guild.name if message.guild else "私信"
            location_name = ""
            if isinstance(message.channel, discord.Thread):
                # 如果是帖子（子区），显示"父频道 -> 帖子名"
                parent_channel_name = (
                    message.channel.parent.name
                    if message.channel.parent
                    else "未知频道"
                )
                location_name = f"{parent_channel_name} -> {message.channel.name}"
            elif isinstance(message.channel, discord.abc.GuildChannel):
                # 确保是服务器频道再获取名字
                location_name = message.channel.name
            else:
                # 否则（如私信），提供一个默认值
                location_name = "私信中"

            chat_result = await chat_service.handle_chat_message(
                message, processed_data, guild_name, location_name
            )

            # 3. 返回回复结果
            return chat_result

        except Exception as e:
            log.error(f"[AIChatCog] 处理@mention消息时发生顶层错误: {e}", exc_info=True)
            # 确保即使发生意外错误也有反馈
            if message.guild is None:
                return None
            return ChatResult(content="抱歉，处理你的请求时遇到了一个未知错误。")


async def setup(bot: commands.Bot):
    """将这个Cog添加到机器人中"""
    await bot.add_cog(AIChatCog(bot))
