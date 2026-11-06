from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from src.chat.features.chaldea.auth_ticket import create_browser_ticket
from src.chat.features.chaldea.catalog import EVENT_SERVANT_IDS, SERVANTS
from src.chat.features.chaldea.tactics import MASTER_SKILLS, MASTER_TEMPLATES
from src.chat.features.chaldea.services.chaldea_service import (
    ChaldeaError,
    chaldea_service,
)
log = logging.getLogger(__name__)


async def _event_servant_autocomplete(
    _interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    needle = current.strip().casefold()
    # Discord accepts at most 25 autocomplete choices. Show newly released
    # event servants first so the newest additions never fall off the default
    # list; text search still covers the complete event catalogue.
    matches = [
        servant_id
        for servant_id in reversed(EVENT_SERVANT_IDS)
        if not needle
        or needle in servant_id.casefold()
        or needle in SERVANTS[servant_id]["name"].casefold()
    ]
    return [
        app_commands.Choice(
            name=f"{SERVANTS[servant_id]['name']}〔{SERVANTS[servant_id]['class']}〕",
            value=servant_id,
        )
        for servant_id in matches[:25]
    ]


def _battle_url(user_id: int | str) -> str:
    base_url = os.getenv(
        "CHALDEA_PUBLIC_URL", "https://odysseia-niang.aireck.xyz/chaldea/"
    ).rstrip("/") + "/"
    return f"{base_url}#ticket={create_browser_ticket(user_id)}"


def _spectator_url(user_id: int | str, battle_id: str) -> str:
    base_url = os.getenv(
        "CHALDEA_PUBLIC_URL", "https://odysseia-niang.aireck.xyz/chaldea/"
    ).rstrip("/") + "/"
    ticket = create_browser_ticket(user_id, scope="spectator", battle_id=battle_id)
    return f"{base_url}?mode=spectate&battle={battle_id}#ticket={ticket}"


def _management_url(user_id: int | str, *, admin: bool = False) -> str:
    base_url = os.getenv(
        "CHALDEA_PUBLIC_URL", "https://odysseia-niang.aireck.xyz/chaldea/"
    ).rstrip("/") + "/"
    mode = "admin" if admin else "manage"
    scope = "admin" if admin else "player"
    return f"{base_url}?mode={mode}#ticket={create_browser_ticket(user_id, scope=scope)}"


async def _view_error(interaction: discord.Interaction, error: Exception) -> None:
    message = str(error) if isinstance(error, ChaldeaError) else "操作失败，请稍后重试。"
    if not isinstance(error, ChaldeaError):
        log.error("Chaldea battle panel failed", exc_info=True)
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def _battle_embed(
    challenger_mention: str,
    opponent_mention: str,
    battle_id: str,
    *,
    active: bool,
) -> discord.Embed:
    if active:
        embed = discord.Embed(
            title="⚔️ 灵基演算已展开",
            description=(
                f"{challenger_mention}  VS  {opponent_mention}\n\n"
                "双方请点击各自的入口按钮。入口会以仅本人可见的消息发送，"
                "不会在公屏暴露身份票据。其他成员可点击“观战与弹幕”进入只读战场。"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="状态", value="战斗进行中", inline=True)
    else:
        embed = discord.Embed(
            title="◇ 迦勒底决斗邀请",
            description=(
                f"{challenger_mention} 向 {opponent_mention} 发起三对三灵基演算。\n\n"
                "被挑战者可接受或拒绝；发起者可在接受前取消。邀请 30 分钟后失效。"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="状态", value="等待回应", inline=True)
    embed.add_field(name="对局", value=f"`{battle_id}`", inline=False)
    return embed


class ActiveBattleView(discord.ui.View):
    def __init__(self, battle_id: str, challenger_id: int, opponent_id: int):
        super().__init__(timeout=4 * 60 * 60)
        self.battle_id = battle_id
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id

    async def _send_entry(self, interaction: discord.Interaction, expected_id: int) -> None:
        if interaction.user.id != expected_id:
            await interaction.response.send_message("这是另一位玩家的入口。", ephemeral=True)
            return
        battle = await chaldea_service.get_battle(interaction.user.id, self.battle_id)
        if not battle or battle["status"] not in ("active", "finished"):
            await interaction.response.send_message("这场战斗已经结束。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"专属入口在 4 小时内有效：\n[进入战斗界面]({_battle_url(interaction.user.id)})",
            ephemeral=True,
        )

    @discord.ui.button(label="发起者进入", style=discord.ButtonStyle.primary, emoji="🔵")
    async def challenger_entry(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ):
        try:
            await self._send_entry(interaction, self.challenger_id)
        except Exception as exc:
            await _view_error(interaction, exc)

    @discord.ui.button(label="被挑战者进入", style=discord.ButtonStyle.primary, emoji="🔴")
    async def opponent_entry(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ):
        try:
            await self._send_entry(interaction, self.opponent_id)
        except Exception as exc:
            await _view_error(interaction, exc)

    @discord.ui.button(label="观战与弹幕", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def spectator_entry(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ):
        try:
            battle = await chaldea_service.get_public_battle(self.battle_id)
            if not battle:
                await interaction.response.send_message("这场战斗当前不可观战。", ephemeral=True)
                return
            await interaction.response.send_message(
                "观战入口在 4 小时内有效；你只能观看战局和发送弹幕：\n"
                f"[进入观战界面]({_spectator_url(interaction.user.id, self.battle_id)})",
                ephemeral=True,
            )
        except Exception as exc:
            await _view_error(interaction, exc)

    @discord.ui.button(label="结束战斗", style=discord.ButtonStyle.danger, emoji="❌")
    async def abandon(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id not in (self.challenger_id, self.opponent_id):
            await interaction.response.send_message("只有对局双方可以结束战斗。", ephemeral=True)
            return
        try:
            await chaldea_service.abandon_battle(interaction.user.id, self.battle_id)
            embed = discord.Embed(
                title="对局已结束",
                description=f"由 {interaction.user.mention} 主动结束，双方现在可以重新发起决斗。",
                color=discord.Color.dark_grey(),
            )
            embed.add_field(name="对局", value=f"`{self.battle_id}`", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as exc:
            await _view_error(interaction, exc)


class PendingChallengeView(discord.ui.View):
    def __init__(
        self,
        battle_id: str,
        challenger: discord.Member,
        opponent: discord.Member,
    ):
        super().__init__(timeout=30 * 60)
        self.battle_id = battle_id
        self.challenger = challenger
        self.opponent = opponent

    @discord.ui.button(label="接受挑战", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("只有被挑战者可以接受。", ephemeral=True)
            return
        try:
            await chaldea_service.accept_challenge(self.battle_id, interaction.user.id)
            view = ActiveBattleView(
                self.battle_id, self.challenger.id, self.opponent.id
            )
            embed = _battle_embed(
                self.challenger.mention,
                self.opponent.mention,
                self.battle_id,
                active=True,
            )
            await interaction.response.edit_message(
                content=f"{self.challenger.mention} 与 {self.opponent.mention} 的战斗已开始。",
                embed=embed,
                view=view,
            )
            await interaction.followup.send(
                f"[进入你的战斗界面]({_battle_url(interaction.user.id)})",
                ephemeral=True,
            )
        except Exception as exc:
            await _view_error(interaction, exc)

    @discord.ui.button(label="拒绝", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("只有被挑战者可以拒绝。", ephemeral=True)
            return
        try:
            await chaldea_service.decline_challenge(interaction.user.id, self.battle_id)
            await interaction.response.edit_message(
                content=f"{self.opponent.mention} 拒绝了这场决斗。", embed=None, view=None
            )
        except Exception as exc:
            await _view_error(interaction, exc)

    @discord.ui.button(label="取消邀请", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.challenger.id:
            await interaction.response.send_message("只有发起者可以取消邀请。", ephemeral=True)
            return
        try:
            await chaldea_service.cancel_challenge(interaction.user.id, self.battle_id)
            await interaction.response.edit_message(
                content=f"{self.challenger.mention} 取消了这场决斗。", embed=None, view=None
            )
        except Exception as exc:
            await _view_error(interaction, exc)


class ChaldeaCog(commands.Cog):
    chaldea = app_commands.Group(name="迦勒底", description="签到、召唤、编队与玩家战斗")
    admin = app_commands.Group(name="迦勒底管理", description="迦勒底管理员操作")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _error(self, interaction: discord.Interaction, error: Exception) -> None:
        message = str(error) if isinstance(error, ChaldeaError) else "操作失败，请稍后重试。"
        if not isinstance(error, ChaldeaError):
            log.error("Chaldea command failed", exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.NotFound:
            log.warning("Chaldea interaction expired before the error response was sent")

    @chaldea.command(name="签到", description="领取每日固定圣晶石")
    async def daily(self, interaction: discord.Interaction):
        try:
            result = await chaldea_service.claim_daily(interaction.user.id)
            if result["granted"]:
                message = (
                    "签到成功，获得 **3 圣晶石、500 QP、80 战斗经验**。\n"
                    f"当前：**{result['quartz']} 圣晶石 / {result['qp']} QP / "
                    f"{result['training_exp']} 战斗经验**。"
                )
            else:
                message = (
                    "今天已经签到过了。\n"
                    f"当前：**{result['quartz']} 圣晶石 / {result['qp']} QP / "
                    f"{result['training_exp']} 战斗经验**。"
                )
            await interaction.response.send_message(message, ephemeral=True)
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="召唤", description="使用圣晶石进行单抽或十一连")
    @app_commands.describe(次数="只能填写 1 或 11")
    async def summon(self, interaction: discord.Interaction, 次数: int = 1):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await chaldea_service.summon(
                interaction.user.id, 次数, str(interaction.id)
            )
            lines = []
            for servant_id in result["results"]:
                servant = SERVANTS[servant_id]
                lines.append(
                    f"{'★' * servant['rarity']} {servant['name']}〔{servant['class']}〕"
                )
            replay = "\n（本次请求已安全重放，未重复扣款）" if result["replayed"] else ""
            await interaction.followup.send(
                "**召唤结果**\n" + "\n".join(lines) + f"\n\n剩余：**{result['balance']} 圣晶石**{replay}",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="图鉴", description="查看自己拥有的从者")
    async def roster(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            roster = await chaldea_service.get_roster(interaction.user.id)
            lines = [
                f"`{row['servant_id']}` · {'★' * row['servant']['rarity']} "
                f"{row['servant']['name']}〔{row['servant']['class']}〕 "
                f"Lv.{row['level']} / NP{row['np_level']}"
                for row in roster
            ]
            await interaction.followup.send(
                "**你的灵基一览**\n" + "\n".join(lines), ephemeral=True
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="编队", description="用三个从者 ID 设置出战队伍")
    async def team(
        self,
        interaction: discord.Interaction,
        第一位: str,
        第二位: str,
        第三位: str,
    ):
        try:
            selected = await chaldea_service.set_team(
                interaction.user.id, [第一位, 第二位, 第三位]
            )
            names = [SERVANTS[sid]["name"] for sid in selected]
            await interaction.response.send_message(
                "编队已保存：" + " / ".join(names), ephemeral=True
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="决斗", description="向另一名玩家发起三对三挑战")
    async def challenge(self, interaction: discord.Interaction, 对手: discord.Member):
        try:
            if 对手.bot:
                raise ChaldeaError("首版暂不支持挑战机器人")
            battle_id = await chaldea_service.create_challenge(
                interaction.user.id, 对手.id
            )
            view = PendingChallengeView(battle_id, interaction.user, 对手)
            embed = _battle_embed(
                interaction.user.mention, 对手.mention, battle_id, active=False
            )
            await interaction.response.send_message(
                f"{对手.mention}，你收到了一封迦勒底决斗邀请。",
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="撤销", description="撤销自己发起且尚未接受的决斗")
    async def cancel(self, interaction: discord.Interaction, 对局: str | None = None):
        try:
            battle_id = await chaldea_service.cancel_challenge(
                interaction.user.id, 对局
            )
            await interaction.response.send_message(
                f"已撤销决斗 `{battle_id}`。", ephemeral=True
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="拒绝", description="拒绝别人发起且尚未接受的决斗")
    async def decline(self, interaction: discord.Interaction, 对局: str | None = None):
        try:
            battle_id = await chaldea_service.decline_challenge(
                interaction.user.id, 对局
            )
            await interaction.response.send_message(
                f"已拒绝决斗 `{battle_id}`。", ephemeral=True
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="接受", description="接受指定的决斗并启动战斗界面")
    async def accept(self, interaction: discord.Interaction, 对局: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await chaldea_service.accept_challenge(对局, interaction.user.id)
            await interaction.followup.send(
                f"决斗已接受。入口在 4 小时内有效：\n[打开战斗界面]({_battle_url(interaction.user.id)})",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="资源", description="查看圣晶石、QP 与战斗经验")
    async def resources(self, interaction: discord.Interaction):
        try:
            profile = await chaldea_service.get_profile(interaction.user.id)
            template = MASTER_TEMPLATES.get(
                profile.get("master_template_id"), MASTER_TEMPLATES["chaldea_uniform"]
            )
            await interaction.response.send_message(
                f"**迦勒底资源**\n圣晶石：**{profile['quartz']}**\n"
                f"QP：**{profile['qp']}**\n战斗经验：**{profile['training_exp']}**\n"
                f"御主礼装：**{template['name']}**",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="御主礼装", description="选择下一场战斗使用的御主技能模板")
    @app_commands.choices(
        礼装=[
            app_commands.Choice(name=template["name"], value=template_id)
            for template_id, template in MASTER_TEMPLATES.items()
        ]
    )
    async def master_template(
        self,
        interaction: discord.Interaction,
        礼装: app_commands.Choice[str],
    ):
        try:
            template = await chaldea_service.set_master_template(
                interaction.user.id, 礼装.value
            )
            skill_names = " / ".join(
                MASTER_SKILLS[skill_id]["name"] for skill_id in template["skill_ids"]
            )
            await interaction.response.send_message(
                f"已装备 **{template['name']}**。\n{template['description']}\n"
                f"御主技能：{skill_names}\n随机魔术与陷阱会在每轮由该礼装的牌池抽取。",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="培养", description="消耗 QP 与战斗经验提升英灵等级")
    @app_commands.describe(英灵="图鉴中的英灵 ID", 等级数="本次提升 1 到 10 级")
    async def train(
        self,
        interaction: discord.Interaction,
        英灵: str,
        等级数: app_commands.Range[int, 1, 10] = 1,
    ):
        try:
            result = await chaldea_service.train_servant(
                interaction.user.id, 英灵, int(等级数)
            )
            await interaction.response.send_message(
                f"**{SERVANTS[英灵]['name']}** 已提升至 **Lv.{result['level']}**。\n"
                f"消耗：{result['qp_cost']} QP / {result['exp_cost']} 战斗经验。\n"
                f"剩余：{result['qp']} QP / {result['training_exp']} 战斗经验。",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="战斗", description="打开当前战斗的网页界面")
    async def battle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            battle = await chaldea_service.get_battle(interaction.user.id)
            if not battle or battle["status"] not in ("active", "finished"):
                raise ChaldeaError("你当前没有可进入的战斗")
            await interaction.followup.send(
                f"入口在 4 小时内有效：\n[打开战斗界面]({_battle_url(interaction.user.id)})",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="观战", description="凭对局 ID 进入只读观战与弹幕界面")
    async def spectate(self, interaction: discord.Interaction, 对局: str):
        try:
            battle = await chaldea_service.get_public_battle(对局)
            if not battle:
                raise ChaldeaError("该对局不存在、尚未开始或已不可观战")
            await interaction.response.send_message(
                "观战入口在 4 小时内有效：\n"
                f"[进入观战与弹幕]({_spectator_url(interaction.user.id, 对局)})",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @chaldea.command(name="管理", description="打开个人迦勒底管理中心")
    async def management(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "管理入口在 4 小时内有效，可查看图鉴、技能、编队、礼装与培养：\n"
            f"[进入个人管理中心]({_management_url(interaction.user.id)})",
            ephemeral=True,
        )

    @chaldea.command(name="结束", description="结束自己参与的当前战斗")
    async def end_battle(self, interaction: discord.Interaction, 对局: str | None = None):
        try:
            battle_id = await chaldea_service.abandon_battle(interaction.user.id, 对局)
            await interaction.response.send_message(
                f"已结束战斗 `{battle_id}`，双方现在可以重新发起决斗。", ephemeral=True
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @admin.command(name="发放", description="向指定玩家发放圣晶石")
    @app_commands.checks.has_permissions(administrator=True)
    async def grant(
        self,
        interaction: discord.Interaction,
        玩家: discord.Member,
        数量: app_commands.Range[int, 1, 100000],
        原因: str = "管理员活动奖励",
    ):
        try:
            balance = await chaldea_service.grant_quartz(
                玩家.id,
                int(数量),
                原因,
                f"admin:{interaction.id}",
            )
            await interaction.response.send_message(
                f"已向 {玩家.mention} 发放 **{数量} 圣晶石**，当前余额 **{balance}**。",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @admin.command(name="面板", description="打开网页管理员控制台")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "管理员入口在 4 小时内有效，票据仅允许管理员 API：\n"
            f"[进入迦勒底管理控制台]({_management_url(interaction.user.id, admin=True)})",
            ephemeral=True,
        )

    @admin.command(name="解锁全部英灵", description="为指定玩家解锁全部常规英灵（不含活动英灵）")
    @app_commands.checks.has_permissions(administrator=True)
    async def unlock_all_servants(
        self,
        interaction: discord.Interaction,
        玩家: discord.Member,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await chaldea_service.unlock_all_servants(玩家.id)
            await interaction.followup.send(
                f"已为 {玩家.mention} 解锁全部英灵：本次新增 **{result['added']}**，"
                f"当前已拥有 **{result['total']}** 名可用英灵。",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @admin.command(name="发放活动英灵", description="向指定玩家发放一名限定活动英灵")
    @app_commands.autocomplete(英灵=_event_servant_autocomplete)
    @app_commands.checks.has_permissions(administrator=True)
    async def grant_event_servant(
        self,
        interaction: discord.Interaction,
        玩家: discord.Member,
        英灵: str,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await chaldea_service.grant_event_servant(玩家.id, 英灵)
            if result["added"]:
                message = f"已向 {玩家.mention} 发放活动英灵 **{result['name']}**（NP1 / Lv.1）。"
            else:
                message = f"{玩家.mention} 已拥有活动英灵 **{result['name']}**，未重复发放。"
            await interaction.followup.send(message, ephemeral=True)
        except Exception as exc:
            await self._error(interaction, exc)

    @admin.command(name="发放qp", description="向指定玩家发放 QP")
    @app_commands.checks.has_permissions(administrator=True)
    async def grant_qp(
        self,
        interaction: discord.Interaction,
        玩家: discord.Member,
        数量: app_commands.Range[int, 1, 10000000],
        原因: str = "管理员活动奖励",
    ):
        try:
            balance = await chaldea_service.grant_qp(
                玩家.id, int(数量), 原因, f"admin:qp:{interaction.id}"
            )
            await interaction.response.send_message(
                f"已向 {玩家.mention} 发放 **{数量} QP**，当前余额 **{balance} QP**。",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)

    @admin.command(name="发放经验", description="向指定玩家发放战斗经验")
    @app_commands.checks.has_permissions(administrator=True)
    async def grant_exp(
        self,
        interaction: discord.Interaction,
        玩家: discord.Member,
        数量: app_commands.Range[int, 1, 10000000],
        原因: str = "管理员活动奖励",
    ):
        try:
            balance = await chaldea_service.grant_training_exp(
                玩家.id, int(数量), 原因, f"admin:exp:{interaction.id}"
            )
            await interaction.response.send_message(
                f"已向 {玩家.mention} 发放 **{数量} 战斗经验**，"
                f"当前余额 **{balance}**。",
                ephemeral=True,
            )
        except Exception as exc:
            await self._error(interaction, exc)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChaldeaCog(bot))
