"""trpg_cog：跑团（TRPG）骰子、角色卡、本（战役）管理与战斗追踪。

独立模块：仅依赖 discord.py 2.x 与 aiohttp，不 import 宿主项目任何模块。
业务逻辑与数据都在独立容器 trpg_server 中（HTTP API），本文件只做 Discord 交互。

环境变量：
  TRPG_API_BASE   服务地址（默认 http://trpg_server:8090）
  TRPG_API_TOKEN  与服务共享的内部令牌（必填，否则本 cog 不加载）

命令：
  /本   创建 面板 列表 绑定 解绑 加入 移除
  /角色 创建 卡 设置 编辑 立绘 列表 切换 删除 历史
  /r  /rc
  /剑世界 威力 查威力 检定 初始 成长
  /战斗 开始 面板 加入 添加敌人 先攻 下一个 伤害 治疗 攻击 撤销 结束
"""
from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from .trpg_lib import render, views
from .trpg_lib.api import TrpgApi, TrpgApiError

log = logging.getLogger(__name__)

TRPG_API_BASE = os.environ.get("TRPG_API_BASE", "http://trpg_server:8090")
TRPG_API_TOKEN = os.environ.get("TRPG_API_TOKEN", "")
MAX_PORTRAIT_BYTES = 8 * 1024 * 1024

SYSTEM_CHOICES = [
    app_commands.Choice(name="CoC 克苏鲁的呼唤（d100）", value="coc"),
    app_commands.Choice(name="DnD 龙与地下城（d20）", value="dnd"),
    app_commands.Choice(name="剑世界 2.5（2d6 / 威力表）", value="sw"),
    app_commands.Choice(name="通用", value="generic"),
]
ROLE_CHOICES = [app_commands.Choice(name="玩家", value="player"), app_commands.Choice(name="DM", value="dm")]


def channel_ids(interaction: discord.Interaction) -> list[int]:
    ch = interaction.channel
    ids = [interaction.channel_id]
    parent = getattr(ch, "parent_id", None)
    if parent:
        ids.append(parent)
    return [i for i in ids if i]


class TrpgCog(commands.Cog, name="跑团"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = TrpgApi(TRPG_API_BASE, TRPG_API_TOKEN)
        views.CTX.api = self.api

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(views.PanelButton, views.CombatButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(views.PanelButton, views.CombatButton)
        await self.api.close()

    # ------------------------------------------------------------ helpers
    async def campaign_for(self, interaction: discord.Interaction, name: str | None) -> dict:
        if not interaction.guild_id:
            raise TrpgApiError(400, "请在服务器频道里使用")
        if name:
            for c in await self.api.list_campaigns(interaction.guild_id):
                if c["name"].lower() == name.strip().lower():
                    return await self.api.get_campaign(c["id"])
            raise TrpgApiError(404, f"没有叫「{name}」的进行中的本")
        return await self.api.resolve_campaign(interaction.guild_id, channel_ids(interaction))

    async def ac_campaign(self, interaction: discord.Interaction, current: str):
        try:
            cs = await self.api.list_campaigns(interaction.guild_id)
        except Exception:  # noqa: BLE001
            return []
        return [app_commands.Choice(name=c["name"][:100], value=c["name"][:100]) for c in cs if current.lower() in c["name"].lower()][:25]

    async def ac_character(self, interaction: discord.Interaction, current: str):
        try:
            c = await self.campaign_for(interaction, getattr(interaction.namespace, "本", None))
            chars = await self.api.list_characters(c["id"])
        except Exception:  # noqa: BLE001
            return []
        mine = [ch for ch in chars if ch["owner_user_id"] == str(interaction.user.id)]
        others = [ch for ch in chars if ch["owner_user_id"] != str(interaction.user.id)]
        return [app_commands.Choice(name=ch["name"][:100], value=ch["name"][:100]) for ch in mine + others if current.lower() in ch["name"].lower()][:25]

    async def ac_sw_race(self, interaction: discord.Interaction, current: str):
        try:
            races = await self.api.sw_races()
        except Exception:  # noqa: BLE001
            return []
        return [
            app_commands.Choice(name=f"{r['name']}（{r['ja']}）"[:100], value=r["name"])
            for r in races if current.lower() in r["name"].lower() or current.lower() in r["ja"].lower()
        ][:25]

    async def ac_sw_source(self, interaction: discord.Interaction, current: str):
        race = getattr(interaction.namespace, "种族", None)
        if not race:
            return []
        try:
            races = await self.api.sw_races()
            data = next((item for item in races if item["name"] == race), None)
            sources = data["sources"] if data else []
        except Exception:  # noqa: BLE001
            return []
        return [app_commands.Choice(name=source, value=source) for source in sources if current.lower() in source.lower()][:25]

    async def ac_sw_birth(self, interaction: discord.Interaction, current: str):
        race = getattr(interaction.namespace, "种族", None)
        source = getattr(interaction.namespace, "来源", None)
        if not race:
            return []
        try:
            rows = await self.api.sw_births(race, source)
        except Exception:  # noqa: BLE001
            return []
        options = [app_commands.Choice(name="随机（按当前来源掷 2d6）", value="随机")]
        seen = set()
        for row in rows:
            value = f"{row['source']}/{row['origin']}"
            if value in seen:
                continue
            seen.add(value)
            label = f"{row['origin']} · {row['source']} · {row['roll']}"[:100]
            if not current or current.lower() in label.lower():
                options.append(app_commands.Choice(name=label, value=value))
        return options[:25]

    async def ac_combatant(self, interaction: discord.Interaction, current: str):
        try:
            c = await self.campaign_for(interaction, None)
            enc = await self.api.active_combat(c["id"])
        except Exception:  # noqa: BLE001
            return []
        return [app_commands.Choice(name=cb["name"][:100], value=cb["name"][:100]) for cb in enc["combatants"] if current.lower() in cb["name"].lower()][:25]

    async def encounter_for(self, interaction: discord.Interaction) -> tuple[dict, dict]:
        c = await self.campaign_for(interaction, None)
        return c, await self.api.active_combat(c["id"])

    @staticmethod
    def combatant_by_name(enc: dict, name: str) -> dict:
        for cb in enc["combatants"]:
            if cb["name"].lower() == name.strip().lower():
                return cb
        raise TrpgApiError(404, f"战斗里没有叫「{name}」的参与者")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        orig = getattr(error, "original", error)
        await views.report_error(interaction, orig)

    # ================================================================ /本
    ben = app_commands.Group(name="本", description="跑团本（战役）管理", guild_only=True)

    @ben.command(name="创建", description="创建一个新的本，你将成为它的 DM")
    @app_commands.describe(名称="本的名字", 规则="默认规则（影响先攻/攻击判定的默认公式）", 绑定本频道="把当前频道绑定到这个本（默认是）")
    @app_commands.choices(规则=SYSTEM_CHOICES)
    async def ben_create(self, interaction: discord.Interaction, 名称: str, 规则: app_commands.Choice[str] | None = None, 绑定本频道: bool = True):
        c = await self.api.create_campaign(interaction.user, interaction.guild_id, 名称, interaction.channel_id if 绑定本频道 else None, 规则.value if 规则 else "coc")
        await interaction.response.send_message(f"已创建本「{c['name']}」，你是 DM。下面是控制面板：", embed=render.campaign_embed(c), view=views.CampaignPanelView(c["id"]))

    @ben.command(name="面板", description="打开本的控制面板（成员、设置、绑定、战斗）")
    @app_commands.describe(本="不填则用当前频道绑定的本")
    @app_commands.autocomplete(本=ac_campaign)
    async def ben_panel(self, interaction: discord.Interaction, 本: str | None = None):
        c = await self.campaign_for(interaction, 本)
        await interaction.response.send_message(embed=render.campaign_embed(c), view=views.CampaignPanelView(c["id"]) if c["status"] == "active" else None)

    @ben.command(name="列表", description="列出本服务器的本")
    async def ben_list(self, interaction: discord.Interaction):
        cs = await self.api.list_campaigns(interaction.guild_id, include_archived=True)
        if not cs:
            await interaction.response.send_message("还没有本。用 /本 创建 开一个吧", ephemeral=True)
            return
        lines = [f"{'📖' if c['status'] == 'active' else '🗄️'} **{c['name']}**（ID {c['id']}）DM <@{c['dm_user_id']}>" for c in cs]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @ben.command(name="绑定", description="把当前频道绑定到某个本（DM）")
    @app_commands.autocomplete(本=ac_campaign)
    async def ben_bind(self, interaction: discord.Interaction, 本: str):
        c = await self.campaign_for(interaction, 本)
        await self.api.bind_channel(interaction.user, c["id"], interaction.channel_id)
        await interaction.response.send_message(f"已把 <#{interaction.channel_id}> 绑定到「{c['name']}」")

    @ben.command(name="解绑", description="解除当前频道的本绑定（DM）")
    async def ben_unbind(self, interaction: discord.Interaction):
        c = await self.api.unbind_channel(interaction.user, interaction.channel_id)
        await interaction.response.send_message(f"已解除 <#{interaction.channel_id}> 与「{c['name']}」的绑定")

    @ben.command(name="加入", description="把成员加入本（DM）")
    @app_commands.choices(身份=ROLE_CHOICES)
    @app_commands.autocomplete(本=ac_campaign)
    async def ben_add(self, interaction: discord.Interaction, 用户: discord.Member, 身份: app_commands.Choice[str] | None = None, 本: str | None = None):
        c = await self.campaign_for(interaction, 本)
        role = 身份.value if 身份 else "player"
        await self.api.set_member(interaction.user, c["id"], 用户.id, role)
        await interaction.response.send_message(f"已把 {用户.mention} 加入「{c['name']}」，身份：{'DM' if role == 'dm' else '玩家'}")

    @ben.command(name="移除", description="把成员移出本（DM）")
    @app_commands.autocomplete(本=ac_campaign)
    async def ben_remove(self, interaction: discord.Interaction, 用户: discord.Member, 本: str | None = None):
        c = await self.campaign_for(interaction, 本)
        await self.api.remove_member(interaction.user, c["id"], 用户.id)
        await interaction.response.send_message(f"已把 {用户.mention} 移出「{c['name']}」")

    # ============================================================== /角色
    role = app_commands.Group(name="角色", description="角色卡管理", guild_only=True)

    @role.command(name="创建", description="在当前本创建角色")
    @app_commands.describe(名称="角色名", 属性="可选，如：力量=50 敏捷=60 HP=11", 立绘="可选，PNG/JPG/GIF/WebP，最大 8MB", 本="不填则用当前频道绑定的本")
    @app_commands.autocomplete(本=ac_campaign)
    async def role_create(self, interaction: discord.Interaction, 名称: str, 属性: str | None = None, 立绘: discord.Attachment | None = None, 本: str | None = None):
        c = await self.campaign_for(interaction, 本)
        attrs, _ = render.parse_attr_text(属性 or "")
        await interaction.response.defer()
        ch = await self.api.create_character(interaction.user, c["id"], 名称, attrs)
        if 立绘:
            ch = await self._upload_portrait(interaction, ch, 立绘)
        payload = await views.character_card_payload(ch, c)
        await interaction.followup.send(f"已创建角色「{ch['name']}」", **payload)

    async def _upload_portrait(self, interaction: discord.Interaction, ch: dict, att: discord.Attachment) -> dict:
        if att.size > MAX_PORTRAIT_BYTES:
            raise TrpgApiError(413, "立绘最大 8MB")
        if att.content_type and not att.content_type.startswith("image/"):
            raise TrpgApiError(400, "立绘必须是图片文件")
        data = await att.read()
        return await self.api.upload_portrait(interaction.user, ch["id"], data, att.filename or "portrait")

    @role.command(name="卡", description="查看角色卡（不填名称则看自己当前角色）")
    @app_commands.autocomplete(名称=ac_character, 本=ac_campaign)
    async def role_card(self, interaction: discord.Interaction, 名称: str | None = None, 本: str | None = None, 仅自己可见: bool = False):
        c = await self.campaign_for(interaction, 本)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        await interaction.response.defer(ephemeral=仅自己可见)
        payload = await views.character_card_payload(ch, c)
        await interaction.followup.send(**payload, view=views.CharacterCardView(ch, c), ephemeral=仅自己可见)

    @role.command(name="设置", description="设置一项属性，如 力量 50（值填 - 可删除）")
    @app_commands.autocomplete(名称=ac_character)
    async def role_set(self, interaction: discord.Interaction, 属性: str, 值: str, 名称: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        if 值.strip() == "-":
            ch = await self.api.patch_character(interaction.user, ch["id"], attrs_del=[属性], reason="命令删除")
            await interaction.response.send_message(f"已删除「{ch['name']}」的属性 {属性}")
        else:
            old = (ch.get("attrs") or {}).get(属性)
            ch = await self.api.patch_character(interaction.user, ch["id"], attrs_set={属性: 值}, reason="命令设置")
            new = ch["attrs"].get(属性)
            await interaction.response.send_message(f"「{ch['name']}」{属性}：{old if old is not None else '—'} → **{new}**")

    @role.command(name="编辑", description="用表单批量编辑角色（名字、全部属性、备注）")
    @app_commands.autocomplete(名称=ac_character)
    async def role_edit(self, interaction: discord.Interaction, 名称: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        await interaction.response.send_modal(views.CharacterEditModal(ch, c))

    @role.command(name="立绘", description="上传或更换角色立绘")
    @app_commands.autocomplete(名称=ac_character)
    async def role_portrait(self, interaction: discord.Interaction, 图片: discord.Attachment, 名称: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        await interaction.response.defer()
        ch = await self._upload_portrait(interaction, ch, 图片)
        payload = await views.character_card_payload(ch, c)
        await interaction.followup.send(f"「{ch['name']}」的立绘已更新", **payload)

    @role.command(name="列表", description="列出本里的角色")
    @app_commands.autocomplete(本=ac_campaign)
    async def role_list(self, interaction: discord.Interaction, 本: str | None = None):
        c = await self.campaign_for(interaction, 本)
        chars = await self.api.list_characters(c["id"])
        if not chars:
            await interaction.response.send_message("这个本还没有角色", ephemeral=True)
            return
        lines = [f"{'⭐' if ch['is_active'] else '•'} **{ch['name']}** — <@{ch['owner_user_id']}>{' 🖼️' if ch.get('portrait_path') else ''}" for ch in chars]
        await interaction.response.send_message(f"「{c['name']}」的角色：\n" + "\n".join(lines)[:1800], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @role.command(name="切换", description="把某个角色设为你当前使用的角色")
    @app_commands.autocomplete(名称=ac_character)
    async def role_switch(self, interaction: discord.Interaction, 名称: str):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        ch = await self.api.set_active(interaction.user, ch["id"])
        await interaction.response.send_message(f"当前角色已切换为「{ch['name']}」", ephemeral=True)

    @role.command(name="删除", description="删除角色（可由 DM 恢复数据）")
    @app_commands.autocomplete(名称=ac_character)
    async def role_delete(self, interaction: discord.Interaction, 名称: str):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        await self.api.delete_character(interaction.user, ch["id"])
        await interaction.response.send_message(f"已删除角色「{ch['name']}」")

    @role.command(name="导入", description="批量导入属性（海豹 .st 风格：力量50敏捷60体质70，或 力量=50 敏捷=60）")
    @app_commands.describe(文本="属性文本，支持 名称数字 紧凑写法或 名称=值", 名称="默认当前角色")
    @app_commands.autocomplete(名称=ac_character)
    async def role_import(self, interaction: discord.Interaction, 文本: str, 名称: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        attrs, dels = render.parse_attr_text(文本)
        if not attrs and not dels:
            raise TrpgApiError(400, "没有解析出任何属性。示例：力量50敏捷60体质70 或 力量=50 敏捷=60")
        ch = await self.api.patch_character(interaction.user, ch["id"], attrs_set=attrs, attrs_del=dels, reason="批量导入")
        await interaction.response.defer()
        payload = await views.character_card_payload(ch, c)
        await interaction.followup.send(f"已导入 {len(attrs)} 项属性到「{ch['name']}」", **payload)

    @role.command(name="历史", description="查看角色的修改记录")
    @app_commands.autocomplete(名称=ac_character)
    async def role_history(self, interaction: discord.Interaction, 名称: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 名称)
        rows = await self.api.history(ch["id"], 15)
        await interaction.response.send_message(f"「{ch['name']}」最近的修改：\n" + render.history_lines(rows), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    # ============================================================== dice
    @app_commands.command(name="r", description="掷骰，如 1d20+3、2d6、4d6kh3、1d20+力量（可引用角色属性）")
    @app_commands.guild_only()
    @app_commands.describe(表达式="骰子表达式", 暗骰="只有你和 DM 能看到结果", 角色="用哪个角色的属性（默认当前角色）")
    @app_commands.autocomplete(角色=ac_character)
    async def roll(self, interaction: discord.Interaction, 表达式: str, 暗骰: bool = False, 角色: str | None = None):
        c, ch = await self._campaign_and_char(interaction, 角色)
        res = await self.api.roll(interaction.user, 表达式, c["id"] if c else None, ch["id"] if ch else None, 暗骰)
        text = render.roll_text(res, interaction.user.mention)
        await self._send_roll(interaction, c, text, 暗骰)

    @app_commands.command(name="rc", description="d100 技能检定（CoC），如 /rc 侦查；可用目标值覆盖角色卡数值")
    @app_commands.guild_only()
    @app_commands.describe(技能="技能/属性名", 目标值="不填则读取角色卡", 奖励骰="0-2", 惩罚骰="0-2", 暗骰="只有你和 DM 能看到结果", 角色="默认当前角色")
    @app_commands.autocomplete(角色=ac_character)
    async def check(self, interaction: discord.Interaction, 技能: str, 目标值: app_commands.Range[int, 0, 999] | None = None, 奖励骰: app_commands.Range[int, 0, 2] = 0, 惩罚骰: app_commands.Range[int, 0, 2] = 0, 暗骰: bool = False, 角色: str | None = None):
        c, ch = await self._campaign_and_char(interaction, 角色)
        res = await self.api.check(interaction.user, 技能, c["id"] if c else None, ch["id"] if ch else None, 目标值, 奖励骰, 惩罚骰, 暗骰)
        text = render.check_text(res, interaction.user.mention)
        await self._send_roll(interaction, c, text, 暗骰)

    async def _campaign_and_char(self, interaction: discord.Interaction, name: str | None) -> tuple[dict | None, dict | None]:
        try:
            c = await self.campaign_for(interaction, None)
        except TrpgApiError as e:
            if e.status != 404 or name:
                raise
            return None, None
        try:
            ch = await self.api.find_character(interaction.user, c["id"], name)
        except TrpgApiError as e:
            if e.status != 404 or name:
                raise
            ch = None
        return c, ch

    async def _send_roll(self, interaction: discord.Interaction, c: dict | None, text: str, hidden: bool) -> None:
        if not hidden:
            await interaction.response.send_message(text)
            return
        await interaction.response.send_message("🙈 暗骰：\n" + text, ephemeral=True)
        if c:
            for uid in {c["dm_user_id"], *[m["user_id"] for m in c["members"] if m["role"] == "dm"]}:
                if uid == str(interaction.user.id):
                    continue
                try:
                    user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                    await user.send(f"🙈 「{c['name']}」暗骰（<#{interaction.channel_id}>）：\n{text}")
                except discord.HTTPException:
                    pass

    @app_commands.command(name="sc", description="理智检定（CoC）：/sc 成功损失 失败损失，例如 /sc 1 1d6")
    @app_commands.guild_only()
    @app_commands.describe(成功损失="检定成功时的损失表达式，如 1 或 1d3", 失败损失="检定失败时的损失表达式，如 1d6", 角色="默认当前角色")
    @app_commands.autocomplete(角色=ac_character)
    async def sc(self, interaction: discord.Interaction, 成功损失: str, 失败损失: str, 角色: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        res = await self.api.sanity_check(interaction.user, ch["id"], 成功损失, 失败损失, c["id"])
        await interaction.response.send_message(render.sc_text(res, interaction.user.mention))

    @app_commands.command(name="en", description="技能成长检定（CoC）：1d100 大于技能值则 +1d10")
    @app_commands.guild_only()
    @app_commands.describe(技能="技能名，如 侦查", 角色="默认当前角色")
    @app_commands.autocomplete(角色=ac_character)
    async def en(self, interaction: discord.Interaction, 技能: str, 角色: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        res = await self.api.skill_growth(interaction.user, ch["id"], 技能, c["id"])
        await interaction.response.send_message(render.en_text(res, interaction.user.mention))

    # ============================================================ /剑世界
    sword = app_commands.Group(name="剑世界", description="剑世界 2.5：2d6、威力表、初始属性与成长", guild_only=True)

    @sword.command(name="威力", description="掷剑世界威力表，如 k20+5@10；可用角色卡属性简写为 k")
    @app_commands.describe(表达式="如 k20+5@10、hk10、k20#1r5", 暗骰="只有你和 DM 能看到结果", 角色="默认当前角色")
    @app_commands.autocomplete(角色=ac_character)
    async def sword_rating(self, interaction: discord.Interaction, 表达式: str = "k10", 暗骰: bool = False, 角色: str | None = None):
        c, ch = await self._campaign_and_char(interaction, 角色)
        res = await self.api.sw_rating(interaction.user, 表达式, c["id"] if c else None, ch["id"] if ch else None, 暗骰)
        await self._send_roll(interaction, c, render.sw_rating_text(res, interaction.user.mention), 暗骰)

    @sword.command(name="查威力", description="查询一行威力表，返回 2d6 出目 3-12 的结果")
    @app_commands.describe(威力="0-100 的威力值")
    async def sword_table(self, interaction: discord.Interaction, 威力: app_commands.Range[int, 0, 100]):
        row = await self.api.sw_table(威力)
        await interaction.response.send_message(render.sw_table_text(row), ephemeral=True)

    @sword.command(name="检定", description="剑世界 2d6 检定：2d6+加值，对比目标值")
    @app_commands.describe(加值="数字或角色卡属性名，例如 8、命中", 目标值="可选，对比总值", 暗骰="只有你和 DM 能看到结果", 角色="默认当前角色")
    @app_commands.autocomplete(角色=ac_character)
    async def sword_check(self, interaction: discord.Interaction, 加值: str = "", 目标值: int | None = None, 暗骰: bool = False, 角色: str | None = None):
        c, ch = await self._campaign_and_char(interaction, 角色)
        res = await self.api.sw_check(interaction.user, 加值, 目标值, c["id"] if c else None, ch["id"] if ch else None, 暗骰)
        await self._send_roll(interaction, c, render.sw_check_text(res, interaction.user.mention), 暗骰)

    @sword.command(name="初始", description="按种族和技体心快速生成剑世界初始属性，可直接写入角色卡")
    @app_commands.describe(
        种族="如 人类、精灵、矮人、塔比特；可用自动补全",
        出身="留空沿用默认；可选随机、来源/出身名，或直接填 2d6 出目",
        来源="规则书Ⅰ/Ⅱ、ML、BM、AR、BR、BS；用于筛选出身表",
        技="生まれ表的 技；填写后覆盖表中基础值", 体="生まれ表的 体；填写后覆盖表中基础值",
        心="生まれ表的 心；填写后覆盖表中基础值", 等级="冒险者等级",
        魔法等级合计="用于计算 MP 的魔法技能等级合计", 角色="填后写入该角色卡；不填只显示",
    )
    @app_commands.autocomplete(种族=ac_sw_race)
    @app_commands.autocomplete(出身=ac_sw_birth)
    @app_commands.autocomplete(来源=ac_sw_source)
    @app_commands.autocomplete(角色=ac_character)
    async def sword_generate(
        self, interaction: discord.Interaction, 种族: str, 出身: str | None = None, 来源: str | None = None,
        技: app_commands.Range[int, 0, 30] | None = None,
        体: app_commands.Range[int, 0, 30] | None = None,
        心: app_commands.Range[int, 0, 30] | None = None,
        等级: app_commands.Range[int, 1, 20] = 1,
        魔法等级合计: app_commands.Range[int, 0, 30] = 0,
        角色: str | None = None,
    ):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色) if 角色 else None
        res = await self.api.sw_generate(
            interaction.user, 种族, 技, 体, 心, 等级, 魔法等级合计,
            ch["id"] if ch else None, origin=出身 or "随机", source=来源,
        )
        await interaction.response.send_message(render.sw_generate_text(res, ch["name"] if ch else None))

    @sword.command(name="成长", description="掷成长骰；填属性和刚才两颗骰子可把结果写入角色卡")
    @app_commands.describe(属性="不填只掷骰；应用时填结果中的属性", 骰子1="应用已显示的第一颗骰子", 骰子2="应用已显示的第二颗骰子", 角色="默认当前角色")
    @app_commands.autocomplete(角色=ac_character)
    async def sword_growth(
        self, interaction: discord.Interaction, 属性: str | None = None,
        骰子1: app_commands.Range[int, 1, 6] | None = None,
        骰子2: app_commands.Range[int, 1, 6] | None = None,
        角色: str | None = None,
    ):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色) if 角色 else None
        if 属性 and (骰子1 is None or 骰子2 is None):
            raise TrpgApiError(400, "请先不填属性掷一次；确认结果后，把两颗骰子和属性一起填入应用")
        res = await self.api.sw_growth(
            interaction.user, ch["id"] if ch else None, 属性,
            [骰子1, 骰子2] if 骰子1 is not None and 骰子2 is not None else None,
        )
        await interaction.response.send_message(render.sw_growth_text(res, ch["name"] if ch else None))

    # ============================================================== /背包
    bag = app_commands.Group(name="背包", description="角色背包：物品、数量、转移", guild_only=True)

    async def ac_item(self, interaction: discord.Interaction, current: str):
        try:
            c = await self.campaign_for(interaction, None)
            ch = await self.api.find_character(interaction.user, c["id"], getattr(interaction.namespace, "角色", None))
            items = await self.api.list_items(ch["id"])
        except Exception:  # noqa: BLE001
            return []
        return [app_commands.Choice(name=f"{it['name']} ×{it['qty']}"[:100], value=it["name"][:100]) for it in items if current.lower() in it["name"].lower()][:25]

    @bag.command(name="查看", description="查看背包（不填角色则看自己当前角色）")
    @app_commands.autocomplete(角色=ac_character)
    async def bag_show(self, interaction: discord.Interaction, 角色: str | None = None, 仅自己可见: bool = False):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        items = await self.api.list_items(ch["id"])
        await interaction.response.send_message(embed=render.inventory_embed(ch["name"], items, ch["owner_user_id"]), ephemeral=仅自己可见)

    @bag.command(name="添加", description="放入物品（已有同名物品则累加数量）")
    @app_commands.describe(名称="物品名", 数量="默认 1", 备注="可选说明", 角色="默认当前角色；DM 可指定任何角色")
    @app_commands.autocomplete(角色=ac_character)
    async def bag_add(self, interaction: discord.Interaction, 名称: str, 数量: app_commands.Range[int, 1, 999999] = 1, 备注: str | None = None, 角色: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        res = await self.api.add_item(interaction.user, ch["id"], 名称, 数量, 备注)
        await interaction.response.send_message(f"🎒 {ch['name']} 获得 **{名称}** ×{数量}", embed=render.inventory_embed(ch["name"], res["items"]))

    @bag.command(name="移除", description="取出/消耗物品（不填数量则全部移除）")
    @app_commands.autocomplete(名称=ac_item, 角色=ac_character)
    async def bag_remove(self, interaction: discord.Interaction, 名称: str, 数量: app_commands.Range[int, 1, 999999] | None = None, 角色: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        res = await self.api.remove_item(interaction.user, ch["id"], 名称, 数量)
        await interaction.response.send_message(f"🎒 {ch['name']} 失去 **{res['name']}** ×{res['removed']}（剩余 {res['remaining']}）", embed=render.inventory_embed(ch["name"], res["items"]))

    @bag.command(name="转移", description="把物品交给同一个本里的另一个角色")
    @app_commands.autocomplete(名称=ac_item, 目标角色=ac_character, 角色=ac_character)
    async def bag_transfer(self, interaction: discord.Interaction, 名称: str, 目标角色: str, 数量: app_commands.Range[int, 1, 999999] | None = None, 角色: str | None = None):
        c = await self.campaign_for(interaction, None)
        src = await self.api.find_character(interaction.user, c["id"], 角色)
        dst = await self.api.find_character(interaction.user, c["id"], 目标角色)
        res = await self.api.transfer_item(interaction.user, src["id"], 名称, dst["id"], 数量)
        await interaction.response.send_message(f"🎒 {res['from']} 把 **{res['name']}** ×{res['qty']} 交给了 {res['to']}（{res['from']} 剩余 {res['remaining']}）")

    @bag.command(name="备注", description="修改物品名称或备注")
    @app_commands.autocomplete(名称=ac_item, 角色=ac_character)
    async def bag_note(self, interaction: discord.Interaction, 名称: str, 新名称: str | None = None, 备注: str | None = None, 角色: str | None = None):
        c = await self.campaign_for(interaction, None)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        res = await self.api.update_item(interaction.user, ch["id"], 名称, 新名称, 备注)
        await interaction.response.send_message("已更新", embed=render.inventory_embed(ch["name"], res["items"]), ephemeral=True)

    # ============================================================== /战斗
    combat = app_commands.Group(name="战斗", description="战斗追踪：先攻、HP、攻击结算", guild_only=True)

    async def _send_combat_panel(self, interaction: discord.Interaction, c: dict, enc: dict, prefix: str = ""):
        await interaction.response.send_message(prefix or None, embed=render.combat_embed(enc, c), view=views.CombatPanelView(enc["id"]) if enc["status"] == "active" else None)

    @combat.command(name="开始", description="开始一场战斗并打开战斗面板（DM）")
    async def combat_start(self, interaction: discord.Interaction):
        c = await self.campaign_for(interaction, None)
        enc = await self.api.start_combat(interaction.user, c["id"])
        await self._send_combat_panel(interaction, c, enc, "⚔️ 战斗开始！玩家点「加入」，DM 点「添加敌人」，然后「先攻」。")

    @combat.command(name="面板", description="显示当前战斗的面板")
    async def combat_panel(self, interaction: discord.Interaction):
        c, enc = await self.encounter_for(interaction)
        await self._send_combat_panel(interaction, c, enc)

    @combat.command(name="加入", description="让你的角色加入战斗")
    @app_commands.autocomplete(角色=ac_character)
    async def combat_join(self, interaction: discord.Interaction, 角色: str | None = None):
        c, enc = await self.encounter_for(interaction)
        ch = await self.api.find_character(interaction.user, c["id"], 角色)
        await self.api.add_combatant(interaction.user, enc["id"], character_id=ch["id"])
        await interaction.response.send_message(f"🙋 {ch['name']} 加入战斗")

    @combat.command(name="添加敌人", description="添加 NPC/敌人（DM）")
    @app_commands.describe(名字="名字", hp="生命值", 技能值="coc 命中用的技能值", ac="dnd 的 AC / 剑世界的回避", 防护点="剑世界防护点", 伤害="伤害公式，如 1d6 或 k10+2", 先攻="先攻值")
    async def combat_add_npc(self, interaction: discord.Interaction, 名字: str, hp: app_commands.Range[int, 0, 99999], 技能值: int | None = None, ac: int | None = None, 防护点: int | None = None, 伤害: str | None = None, 先攻: float | None = None):
        c, enc = await self.encounter_for(interaction)
        await self.api.add_combatant(interaction.user, enc["id"], name=名字, hp=hp, skill=技能值, ac=ac, defense=防护点, damage_expr=伤害, initiative=先攻)
        await interaction.response.send_message(f"👹 {名字} 加入战斗（HP {hp}）")

    @combat.command(name="先攻", description="为所有参与者掷先攻并排序（DM）")
    @app_commands.describe(仅未设置的="只给还没有先攻的人掷")
    async def combat_init(self, interaction: discord.Interaction, 仅未设置的: bool = False):
        c, enc = await self.encounter_for(interaction)
        res = await self.api.roll_initiative(interaction.user, enc["id"], 仅未设置的)
        notes = res.get("notes") or ["没有参与者"]
        await interaction.response.send_message("🎲 先攻：\n" + "\n".join(f"• {n}" for n in notes)[:1800], embed=render.combat_embed(res, c))

    @combat.command(name="下一个", description="进入下一个人的回合（DM）")
    async def combat_next(self, interaction: discord.Interaction):
        c, enc = await self.encounter_for(interaction)
        res = await self.api.next_turn(interaction.user, enc["id"])
        cur = res.get("current")
        await interaction.response.send_message(f"⏭️ 第 {res['round']} 轮：轮到 **{cur['name'] if cur else '?'}** 行动", embed=render.combat_embed(res, c))

    @combat.command(name="伤害", description="对目标造成伤害（自动扣 HP，PC 会同步到角色卡）")
    @app_commands.autocomplete(目标=ac_combatant)
    async def combat_damage(self, interaction: discord.Interaction, 目标: str, 数值: app_commands.Range[int, 1, 10000], 原因: str | None = None):
        c, enc = await self.encounter_for(interaction)
        cb = self.combatant_by_name(enc, 目标)
        res = await self.api.change_hp(interaction.user, enc["id"], cb["id"], -数值, 原因 or "")
        await interaction.response.send_message("💔 " + res["summary"])

    @combat.command(name="治疗", description="为目标恢复 HP")
    @app_commands.autocomplete(目标=ac_combatant)
    async def combat_heal(self, interaction: discord.Interaction, 目标: str, 数值: app_commands.Range[int, 1, 10000], 原因: str | None = None):
        c, enc = await self.encounter_for(interaction)
        cb = self.combatant_by_name(enc, 目标)
        res = await self.api.change_hp(interaction.user, enc["id"], cb["id"], 数值, 原因 or "")
        await interaction.response.send_message("💚 " + res["summary"])

    @combat.command(name="攻击", description="发起攻击：托管模式自动结算，手动模式只报告结果")
    @app_commands.describe(攻击者="你的角色或 NPC", 目标="目标", 技能="coc：技能名（默认本设置）", 攻击公式="dnd：如 1d20+攻击", 伤害="伤害公式覆盖")
    @app_commands.autocomplete(攻击者=ac_combatant, 目标=ac_combatant)
    async def combat_attack(self, interaction: discord.Interaction, 攻击者: str, 目标: str, 技能: str | None = None, 攻击公式: str | None = None, 伤害: str | None = None):
        c, enc = await self.encounter_for(interaction)
        a = self.combatant_by_name(enc, 攻击者)
        t = self.combatant_by_name(enc, 目标)
        res = await self.api.attack(interaction.user, enc["id"], a["id"], t["id"], skill=技能, attack_expr=攻击公式, damage_expr=伤害)
        await interaction.response.send_message(render.attack_text(res)[:1900])

    @combat.command(name="撤销", description="撤销最近一次 HP 变动（DM）")
    async def combat_undo(self, interaction: discord.Interaction):
        c, enc = await self.encounter_for(interaction)
        res = await self.api.undo(interaction.user, enc["id"])
        await interaction.response.send_message(f"↩️ {res['summary']}（原记录：{res['undone_summary']}）")

    @combat.command(name="结束", description="结束当前战斗（DM）")
    async def combat_end(self, interaction: discord.Interaction):
        c, enc = await self.encounter_for(interaction)
        res = await self.api.end_combat(interaction.user, enc["id"])
        await interaction.response.send_message("🏁 战斗结束。PC 的 HP 已同步到角色卡", embed=render.combat_embed(res, c))


async def setup(bot: commands.Bot) -> None:
    if not TRPG_API_TOKEN:
        log.warning("TRPG_API_TOKEN 未设置，跑团 cog 不加载")
        return
    await bot.add_cog(TrpgCog(bot))
    log.info("trpg cog loaded, api=%s", TRPG_API_BASE)
