# -*- coding: utf-8 -*-

import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio

# 导入游戏服务和UI组件
from src.chat.features.games.services.ghost_card_service import ghost_card_service
from src.chat.features.games.ui.ghost_card_ui import GhostCardUI
from src.chat.features.games.ui.confirm_draw_modal import DrawConfirmationView
from src.chat.features.games.ui.bet_view import BetView
from src.chat.features.games.config.text_config import text_config
from src.chat.features.odysseia_coin.service.coin_service import coin_service

log = logging.getLogger(__name__)


class GhostCardCog(commands.Cog):
    """抽鬼牌游戏Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="抽鬼牌", description="和类脑娘玩一局抽鬼牌游戏")
    async def play_ghost_card(self, interaction: discord.Interaction):
        """开始一局抽鬼牌游戏"""
        try:
            # 1. 决定本局的AI策略
            ai_strategy = ghost_card_service.determine_ai_strategy()
            strategy_name = ai_strategy.name

            # 2. 获取对应的开局文本和缩略图
            opening_text = text_config.opening.ai_strategy_text.get(
                strategy_name, "让我们开始吧！"
            )
            thumbnail_url = text_config.opening.ai_strategy_thumbnail.get(strategy_name)

            # 3. 创建初始的下注Embed
            embed = discord.Embed(
                title="🃏 抽鬼牌挑战",
                description=opening_text,
                color=discord.Color.gold(),
            )
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)

            embed.set_footer(text="请在下方选择你的下注金额")

            # 4. 创建下注视图
            view = BetView(self)

            # 5. 发送消息
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )

        except discord.NotFound:
            log.error(f"交互已失效，无法发送下注界面")
            # 交互已失效，不再尝试发送消息
        except Exception as e:
            log.error(f"发送下注界面时出错: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ 准备游戏时发生错误，请稍后再试。", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ 准备游戏时发生错误，请稍后再试。", ephemeral=True
                    )
            except discord.NotFound:
                log.error(f"交互已失效，无法发送错误消息")
            except Exception as send_error:
                log.error(f"发送错误消息时出错: {send_error}")

    def create_game_view(self, game_id: str) -> discord.ui.View:
        """创建游戏视图"""
        view = discord.ui.View(timeout=900)  # 15分钟超时

        # 添加抽牌按钮
        card_buttons = GhostCardUI.create_card_buttons(game_id)
        for button in card_buttons:
            view.add_item(button)

        # 添加控制按钮
        control_buttons = GhostCardUI.create_control_buttons(game_id)
        for button in control_buttons:
            view.add_item(button)

        return view

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """处理按钮交互"""
        if not interaction.data or "custom_id" not in interaction.data:
            return

        custom_id = interaction.data["custom_id"]

        # 处理抽鬼牌游戏相关的交互
        if custom_id.startswith("ghost_"):
            await self.handle_ghost_card_interaction(interaction, custom_id)

    async def handle_ghost_card_interaction(
        self, interaction: discord.Interaction, custom_id: str
    ):
        """处理抽鬼牌游戏的交互"""
        try:
            parts = custom_id.split("_")
            action = parts[1]

            # log.info(f"Handling interaction, action: {action}, custom_id: {custom_id}, parts: {parts}")

            if action == "draw":
                # 玩家点击抽牌，显示确认面板
                # custom_id 格式: ghost_draw_USERID_GUILDID_INDEX
                if len(parts) < 5:
                    log.error(f"Invalid custom_id format for draw action: {custom_id}")
                    await interaction.response.send_message(
                        "无效的操作。", ephemeral=True
                    )
                    return

                user_id = parts[2]
                guild_id = parts[3]
                game_id = f"{user_id}_{guild_id}"
                card_index = int(parts[4])

                # log.info(f"Handling draw action for game_id: {game_id}, card_index: {card_index}")

                game = ghost_card_service.get_game_state(game_id)

                # log.info(f"Game state for {game_id}: {game}")

                if game and not game["game_over"]:
                    # 获取要抽的牌 (现在是从AI手牌中抽牌)
                    # 确保AI手牌不为空，否则可能出现索引错误
                    if not game["ai_hand"]:
                        log.warning(f"AI hand is empty for game {game_id}")
                        await interaction.response.send_message(
                            text_config.errors.ai_no_cards, ephemeral=True
                        )
                        return

                    card_name = game["ai_hand"][card_index]

                    # 获取AI对玩家选择的反应
                    reaction_text, reaction_image_url = (
                        ghost_card_service.get_reaction_for_selection(
                            game_id, card_index, "selected"
                        )
                    )

                    if not reaction_text:
                        # 如果获取反应失败，可能是游戏状态问题
                        log.warning(
                            f"Failed to get reaction for selection in game {game_id}"
                        )
                        await interaction.response.send_message(
                            text_config.errors.default, ephemeral=True
                        )
                        return

                    # 显示带有AI反应的确认面板
                    confirmation_view = DrawConfirmationView(
                        game_id,
                        card_index,
                        card_name,
                        reaction_text,
                        reaction_image_url,
                    )

                    try:
                        # 编辑原始消息以显示确认视图
                        embed = discord.Embed(
                            description=f"**{reaction_text}**",
                            color=discord.Color.blue(),
                        )
                        # embed.add_field(name="牌面", value=card_name, inline=False)
                        # 设置缩略图为反应图片
                        if reaction_image_url:
                            embed.set_thumbnail(url=reaction_image_url)

                        await interaction.response.edit_message(
                            embed=embed, view=confirmation_view
                        )
                    except discord.NotFound:
                        log.error(
                            f"Interaction not found when sending draw confirmation for game {game_id}. It may have expired."
                        )
                        # 不再尝试发送消息，因为交互已经失效
                    except discord.HTTPException as e:
                        log.error(
                            f"HTTP error when sending draw confirmation for game {game_id}: {e}"
                        )
                        # 不再尝试发送消息
                    except Exception as e:
                        log.error(
                            f"Unexpected error when sending draw confirmation for game {game_id}: {e}"
                        )
                        # 不再尝试发送消息
                else:
                    log.warning(
                        f"Game not found or already ended for game_id: {game_id}"
                    )
                    try:
                        await interaction.response.send_message(
                            text_config.errors.game_ended, ephemeral=True
                        )
                    except discord.NotFound:
                        log.error(
                            f"Interaction not found when sending game ended message for game {game_id}. It may have expired."
                        )
                    except discord.HTTPException as e:
                        log.error(
                            f"HTTP error when sending game ended message for game {game_id}: {e}"
                        )
                    except Exception as e:
                        log.error(
                            f"Unexpected error when sending game ended message for game {game_id}: {e}"
                        )

            elif action == "restart":
                # 重新开始游戏
                # custom_id 格式: ghost_restart_USERID_GUILDID
                if len(parts) < 4:
                    log.error(
                        f"Invalid custom_id format for restart action: {custom_id}"
                    )
                    await interaction.response.send_message(
                        "无效的操作。", ephemeral=True
                    )
                    return

                user_id = parts[2]
                guild_id = parts[3]
                # 重新开始游戏需要再次显示下注界面
                await self.play_ghost_card(interaction)
                return  # 避免执行 edit_message

                # 创建新游戏界面
                # embed = GhostCardUI.create_game_embed(new_game_id, "🔄 游戏已重新开始")
                # view = self.create_game_view(new_game_id)

                # await interaction.response.edit_message(embed=embed, view=view)

            elif action == "end":
                # 结束游戏
                # custom_id 格式: ghost_end_USERID_GUILDID
                if len(parts) < 4:
                    log.error(f"Invalid custom_id format for end action: {custom_id}")
                    await interaction.response.send_message(
                        "无效的操作。", ephemeral=True
                    )
                    return

                user_id = parts[2]
                guild_id = parts[3]
                game_id = f"{user_id}_{guild_id}"

                ghost_card_service.end_game(game_id)
                await interaction.response.edit_message(
                    content="🎮 游戏已结束", embed=None, view=None
                )

        except Exception as e:
            log.error(f"处理抽鬼牌交互时出错: {e}")
            try:
                await interaction.response.send_message(
                    "❌ 处理操作时出现错误，请稍后再试。", ephemeral=True
                )
            except:
                pass  # 如果已经响应过，忽略错误

    async def handle_confirmed_draw(
        self, interaction: discord.Interaction, game_id: str, card_index: int
    ):
        """处理确认抽牌"""
        try:
            # log.info(f"Handling confirmed draw for game_id: {game_id}, card_index: {card_index}")
            success, message, reaction_text, reaction_image_url = (
                ghost_card_service.player_draw_card(game_id, card_index)
            )

            # log.info(f"Player draw result for {game_id}: success={success}, message={message}, reaction={reaction_text}")

            if not success:
                await interaction.followup.send(message, ephemeral=True)
                return

            # 1. 检查游戏是否结束
            game = ghost_card_service.get_game_state(game_id)
            if game and game["game_over"]:
                # 游戏已结束，直接显示最终结果
                await self.handle_game_over(interaction, game_id)
                return

            # 2. 显示抽牌结果和AI反应（游戏未结束）
            reaction_embed = discord.Embed(
                description=f"*{message}*\n\n**{reaction_text}**",
                color=discord.Color.gold(),
            )
            if reaction_image_url:
                reaction_embed.set_thumbnail(url=reaction_image_url)

            await interaction.edit_original_response(embed=reaction_embed, view=None)
            await asyncio.sleep(4)  # 等待4秒

            # 3. 如果游戏未结束，轮到AI行动
            if game and game["current_turn"] == "ai":
                # 显示AI正在抽牌
                ai_thinking_embed = GhostCardUI.create_ai_draw_embed(
                    game_id, text_config.ai_draw.drawing
                )
                await interaction.edit_original_response(
                    embed=ai_thinking_embed, view=None
                )
                await asyncio.sleep(3)

                # AI抽牌
                ai_success, ai_message, reaction_text, reaction_image_url = (
                    ghost_card_service.ai_draw_card(game_id)
                )
                if not ai_success:
                    error_embed = GhostCardUI.create_game_embed(game_id)
                    await interaction.edit_original_response(
                        embed=error_embed, view=self.create_game_view(game_id)
                    )
                    return

                # 检查AI抽牌后游戏是否结束
                game = ghost_card_service.get_game_state(game_id)
                if game and game["game_over"]:
                    await self.handle_game_over(interaction, game_id)
                    return
                else:  # 游戏未结束，显示AI抽牌结果和反应，并切换回玩家回合
                    ai_drawn_embed = GhostCardUI.create_ai_draw_embed(
                        game_id, ai_message, reaction_text, reaction_image_url
                    )
                    await interaction.edit_original_response(
                        embed=ai_drawn_embed, view=None
                    )
                    await asyncio.sleep(4)

                    # 切换回玩家回合
                    player_turn_embed = GhostCardUI.create_game_embed(game_id)
                    player_turn_view = self.create_game_view(game_id)
                    await interaction.edit_original_response(
                        embed=player_turn_embed, view=player_turn_view
                    )

        except discord.NotFound:
            log.error(
                f"Interaction not found in handle_confirmed_draw for game {game_id}. It may have expired."
            )
        except discord.HTTPException as e:
            log.error(f"HTTP error in handle_confirmed_draw for game {game_id}: {e}")
        except Exception as e:
            log.error(f"处理确认抽牌时出错: {e}")

    async def handle_game_over(self, interaction: discord.Interaction, game_id: str):
        """处理游戏结束的逻辑，包括发送最终结果和处理赌注"""
        game = ghost_card_service.get_game_state(game_id)
        if not game:
            return

        user_id = int(game_id.split("_")[0])
        winnings = game.get("winnings", 0)
        bet_amount = game.get("bet_amount", 0)

        if game["winner"] == "player":
            # 玩家胜利，返还本金(bet_amount)，并发放奖金(winnings)
            total_payout = bet_amount + winnings
            log.info(
                f"游戏胜利: 玩家 {user_id} 赢得 {winnings}，返还本金 {bet_amount}，总计 {total_payout}"
            )
            if total_payout > 0:
                await coin_service.add_coins(
                    user_id,
                    total_payout,
                    f"抽鬼牌游戏胜利 (返还赌注 {bet_amount} + 奖金 {winnings})",
                )

        final_embed = GhostCardUI.create_game_over_embed(game_id)

        try:
            await interaction.edit_original_response(embed=final_embed, view=None)
        except discord.NotFound:
            await interaction.followup.send(embed=final_embed)
        except Exception as e:
            log.error(f"发送游戏结束消息时出错: {e}")

    async def cog_unload(self):
        """Cog卸载时清理所有游戏"""
        ghost_card_service.active_games.clear()


async def setup(bot: commands.Bot):
    """将这个Cog添加到机器人中"""
    await bot.add_cog(GhostCardCog(bot))
