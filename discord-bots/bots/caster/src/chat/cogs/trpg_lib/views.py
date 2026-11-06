"""Persistent panels (DynamicItem buttons survive restarts), ephemeral flows and modals."""
from __future__ import annotations

import io
import logging
import re
from typing import Any

import discord

from . import render
from .api import TrpgApi, TrpgApiError

log = logging.getLogger(__name__)

EPHEMERAL_TIMEOUT = 300


class Ctx:
    api: TrpgApi | None = None


CTX = Ctx()


def api() -> TrpgApi:
    assert CTX.api is not None, "trpg api not initialised"
    return CTX.api


# ---------------------------------------------------------------- utilities
async def send_ephemeral(interaction: discord.Interaction, content: str | None = None, **kw):
    kw.setdefault("ephemeral", True)
    if interaction.response.is_done():
        return await interaction.followup.send(content, **kw)
    await interaction.response.send_message(content, **kw)
    return await interaction.original_response()


async def report_error(interaction: discord.Interaction, exc: Exception) -> None:
    if isinstance(exc, TrpgApiError):
        msg = f"⚠️ {exc.message}"
    else:
        log.exception("trpg ui error", exc_info=exc)
        msg = "⚠️ 出了点问题，请稍后再试或联系管理员"
    try:
        await send_ephemeral(interaction, msg)
    except discord.HTTPException:
        pass


def is_admin(user) -> bool:
    perms = getattr(user, "guild_permissions", None)
    return bool(perms and (perms.manage_guild or perms.administrator))


def role_of(campaign: dict, user) -> str | None:
    if is_admin(user) or str(user.id) == campaign["dm_user_id"]:
        return "dm"
    for m in campaign.get("members", []):
        if m["user_id"] == str(user.id):
            return m["role"]
    return None


def member_label(guild: discord.Guild | None, user_id: str) -> str:
    if guild:
        m = guild.get_member(int(user_id))
        if m:
            return m.display_name[:80]
    return f"用户 {user_id}"


def portrait_file(ch: dict, data: bytes | None) -> tuple[discord.File | None, str | None]:
    if not data or not ch.get("portrait_path"):
        return None, None
    ext = ch["portrait_path"].rsplit(".", 1)[-1]
    fname = f"portrait_{ch['id']}.{ext}"
    return discord.File(io.BytesIO(data), filename=fname), fname


async def character_card_payload(ch: dict, campaign: dict | None) -> dict[str, Any]:
    data = await api().get_portrait(ch["id"])
    f, fname = portrait_file(ch, data)
    payload: dict[str, Any] = {"embed": render.character_embed(ch, campaign, fname)}
    if f:
        payload["file"] = f
    return payload


async def safe_edit(message: discord.Message | None, **kw) -> None:
    if not message:
        return
    try:
        await message.edit(**kw)
    except discord.HTTPException as e:
        log.info("panel edit failed: %s", e)


async def refresh_campaign_panel(message: discord.Message | None, campaign_id: int) -> dict:
    c = await api().get_campaign(campaign_id)
    view = CampaignPanelView(campaign_id) if c["status"] == "active" else None
    await safe_edit(message, embed=render.campaign_embed(c), view=view)
    return c


async def refresh_combat_panel(message: discord.Message | None, encounter_id: int, campaign: dict | None = None) -> dict:
    enc = await api().get_combat(encounter_id)
    if campaign is None:
        campaign = await api().get_campaign(enc["campaign_id"])
    view = CombatPanelView(encounter_id) if enc["status"] == "active" else None
    await safe_edit(message, embed=render.combat_embed(enc, campaign), view=view)
    return enc


def combatant_options(enc: dict, only_ids: set[int] | None = None) -> list[discord.SelectOption]:
    opts = []
    for i, cb in enumerate(enc["combatants"][:25]):
        if only_ids is not None and cb["id"] not in only_ids:
            continue
        hp = f"{cb['hp']}/{cb['max_hp']}" if cb["max_hp"] else str(cb["hp"])
        opts.append(discord.SelectOption(label=f"{i + 1}. {cb['name']}"[:100], description=f"{'PC' if cb['is_pc'] else 'NPC'}  HP {hp}"[:100], value=str(cb["id"])))
    return opts


async def own_combatant_ids(enc: dict, user, campaign: dict) -> set[int] | None:
    """None means 'all' (DM); otherwise the set of combatant ids the user controls."""
    if role_of(campaign, user) == "dm":
        return None
    chars = await api().list_characters(campaign["id"], owner_user_id=user.id)
    mine = {c["id"] for c in chars}
    return {cb["id"] for cb in enc["combatants"] if cb.get("character_id") in mine}


def parse_int(text: str, what: str) -> int:
    t = (text or "").strip().replace("＋", "+").replace("－", "-")
    if not re.fullmatch(r"[-+]?\d+", t):
        raise TrpgApiError(400, f"{what}必须是整数，例如 5 或 -3")
    return int(t)


def parse_optional_int(text: str, what: str) -> int | None:
    return parse_int(text, what) if (text or "").strip() else None


# ======================================================== campaign panel
class PanelButton(discord.ui.DynamicItem[discord.ui.Button], template=r"trpg:panel:(?P<action>[a-z_]+):(?P<cid>\d+)"):
    def __init__(self, action: str, cid: int, label: str = "", style: discord.ButtonStyle = discord.ButtonStyle.secondary, emoji=None, row: int | None = None):
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji, custom_id=f"trpg:panel:{action}:{cid}", row=row))
        self.action = action
        self.cid = cid

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["cid"]), item.label or "", item.style, item.emoji)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await handle_panel_action(interaction, self.action, self.cid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class CampaignPanelView(discord.ui.View):
    def __init__(self, cid: int):
        super().__init__(timeout=None)
        B = discord.ButtonStyle
        self.add_item(PanelButton("members", cid, "成员", B.primary, "👥", 0))
        self.add_item(PanelButton("chars", cid, "角色", B.secondary, "🧝", 0))
        self.add_item(PanelButton("combat", cid, "战斗", B.danger, "⚔️", 0))
        self.add_item(PanelButton("refresh", cid, "刷新", B.secondary, "🔄", 0))
        self.add_item(PanelButton("settings", cid, "设置", B.secondary, "⚙️", 1))
        self.add_item(PanelButton("attack_settings", cid, "攻击设置", B.secondary, "🗡️", 1))
        self.add_item(PanelButton("bind", cid, "绑定本频道", B.success, "📌", 1))
        self.add_item(PanelButton("unbind", cid, "解绑本频道", B.secondary, None, 1))
        self.add_item(PanelButton("archive", cid, "归档", B.danger, "🗄️", 1))


async def handle_panel_action(interaction: discord.Interaction, action: str, cid: int) -> None:
    c = await api().get_campaign(cid)
    user = interaction.user
    role = role_of(c, user)
    panel_msg = interaction.message

    if action == "refresh":
        await interaction.response.defer()
        await refresh_campaign_panel(panel_msg, cid)
        return

    if action == "chars":
        chars = await api().list_characters(cid)
        if not chars:
            await send_ephemeral(interaction, "这个本还没有角色。用 /角色 创建 建一个吧")
            return
        await send_ephemeral(interaction, "选择要查看的角色：", view=CharacterPickView(c, chars))
        return

    if action == "combat":
        try:
            enc = await api().active_combat(cid)
        except TrpgApiError as e:
            if e.status != 404:
                raise
            if role != "dm":
                await send_ephemeral(interaction, "当前没有战斗。只有 DM 可以开始战斗")
                return
            enc = await api().start_combat(user, cid)
        await interaction.response.send_message(embed=render.combat_embed(enc, c), view=CombatPanelView(enc["id"]))
        return

    if role != "dm":
        await send_ephemeral(interaction, "这个按钮只有 DM（或服务器管理员）可以用")
        return

    if action == "members":
        await send_ephemeral(interaction, "成员管理：", view=MembersView(c, interaction.guild, panel_msg))
    elif action == "settings":
        await interaction.response.send_modal(SettingsModal(c, panel_msg))
    elif action == "attack_settings":
        await interaction.response.send_modal(AttackSettingsModal(c, panel_msg))
    elif action == "bind":
        await api().bind_channel(user, cid, interaction.channel_id)
        await send_ephemeral(interaction, f"已把 <#{interaction.channel_id}> 绑定到「{c['name']}」")
        await refresh_campaign_panel(panel_msg, cid)
    elif action == "unbind":
        await api().unbind_channel(user, interaction.channel_id)
        await send_ephemeral(interaction, f"已解除 <#{interaction.channel_id}> 的绑定")
        await refresh_campaign_panel(panel_msg, cid)
    elif action == "archive":
        await interaction.response.send_modal(ArchiveModal(c, panel_msg))
    else:
        await send_ephemeral(interaction, "未知操作")


class MembersView(discord.ui.View):
    def __init__(self, campaign: dict, guild: discord.Guild | None, panel_msg: discord.Message | None):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.cid = campaign["id"]
        self.panel_msg = panel_msg
        add_players = discord.ui.UserSelect(placeholder="添加玩家（可多选）", min_values=1, max_values=10, row=0)
        add_players.callback = self._add_players  # type: ignore[method-assign]
        self.add_item(add_players)
        add_dm = discord.ui.UserSelect(placeholder="添加协同 DM", min_values=1, max_values=1, row=1)
        add_dm.callback = self._add_dm  # type: ignore[method-assign]
        self.add_item(add_dm)
        removable = [m for m in campaign["members"] if m["user_id"] != campaign["dm_user_id"]][:25]
        if removable:
            rm = discord.ui.Select(
                placeholder="移除成员",
                options=[discord.SelectOption(label=member_label(guild, m["user_id"]), description="DM" if m["role"] == "dm" else "玩家", value=m["user_id"]) for m in removable],
                row=2,
            )
            rm.callback = self._remove  # type: ignore[method-assign]
            self.add_item(rm)

    async def _add_players(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.UserSelect) and i.row == 0][0]
        try:
            for u in sel.values:
                await api().set_member(interaction.user, self.cid, u.id, "player")
            await interaction.response.send_message("已添加玩家：" + " ".join(u.mention for u in sel.values), ephemeral=True)
            await refresh_campaign_panel(self.panel_msg, self.cid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)

    async def _add_dm(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.UserSelect) and i.row == 1][0]
        try:
            u = sel.values[0]
            await api().set_member(interaction.user, self.cid, u.id, "dm")
            await interaction.response.send_message(f"已把 {u.mention} 设为 DM", ephemeral=True)
            await refresh_campaign_panel(self.panel_msg, self.cid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)

    async def _remove(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select)][0]
        try:
            uid = sel.values[0]
            await api().remove_member(interaction.user, self.cid, uid)
            await interaction.response.send_message(f"已移除 <@{uid}>", ephemeral=True)
            await refresh_campaign_panel(self.panel_msg, self.cid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class CharacterPickView(discord.ui.View):
    def __init__(self, campaign: dict, chars: list[dict]):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.campaign = campaign
        sel = discord.ui.Select(
            placeholder="选择角色",
            options=[discord.SelectOption(label=c["name"][:100], description=f"主人 {c['owner_user_id']}"[:100], value=str(c["id"])) for c in chars[:25]],
        )
        sel.callback = self._pick  # type: ignore[method-assign]
        self.add_item(sel)

    async def _pick(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select)][0]
        try:
            ch = await api().get_character(int(sel.values[0]))
            payload = await character_card_payload(ch, self.campaign)
            await interaction.response.send_message(**payload, view=CharacterCardView(ch, self.campaign), ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class CharacterCardView(discord.ui.View):
    """Transient buttons under a character card."""

    def __init__(self, ch: dict, campaign: dict | None):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.ch = ch
        self.campaign = campaign

    @discord.ui.button(label="编辑属性", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(CharacterEditModal(self.ch, self.campaign))

    @discord.ui.button(label="背包", style=discord.ButtonStyle.secondary, emoji="🎒")
    async def inventory(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            items = await api().list_items(self.ch["id"])
            await interaction.response.send_message(embed=render.inventory_embed(self.ch["name"], items, self.ch["owner_user_id"]), ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)

    @discord.ui.button(label="发到频道", style=discord.ButtonStyle.secondary, emoji="📣")
    async def publish(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            ch = await api().get_character(self.ch["id"])
            payload = await character_card_payload(ch, self.campaign)
            await interaction.response.defer(ephemeral=True)
            await interaction.channel.send(**payload)  # type: ignore[union-attr]
            await interaction.followup.send("已发送", ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class CharacterEditModal(discord.ui.Modal):
    def __init__(self, ch: dict, campaign: dict | None):
        super().__init__(title=f"编辑 {ch['name']}"[:45])
        self.ch = ch
        self.campaign = campaign
        self.name_in = discord.ui.TextInput(label="名字", default=ch["name"], max_length=40)
        current = "\n".join(f"{k}={v}" for k, v in (ch.get("attrs") or {}).items())[:4000]
        self.attrs_in = discord.ui.TextInput(
            label="属性（每行一条：名称=值；值填 - 表示删除）",
            style=discord.TextStyle.paragraph,
            default=current,
            required=False,
            max_length=4000,
            placeholder="力量=50\n敏捷=60\n职业=侦探",
        )
        self.notes_in = discord.ui.TextInput(label="备注", style=discord.TextStyle.paragraph, default=(ch.get("notes") or "")[:1500], required=False, max_length=1500)
        self.reason_in = discord.ui.TextInput(label="修改原因（可选，会记入历史）", required=False, max_length=60)
        for item in (self.name_in, self.attrs_in, self.notes_in, self.reason_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            attrs, dels = render.parse_attr_text(self.attrs_in.value)
            # keys omitted from the textarea are treated as deleted (the box shows the full sheet)
            omitted = [k for k in (self.ch.get("attrs") or {}) if k not in attrs and k not in dels]
            ch = await api().patch_character(
                interaction.user, self.ch["id"], name=self.name_in.value, attrs_set=attrs, attrs_del=dels + omitted, notes=self.notes_in.value, reason=self.reason_in.value or "面板编辑"
            )
            payload = await character_card_payload(ch, self.campaign)
            await interaction.response.send_message("已保存：", **payload, ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


MODE_ALIASES = {"手动": "manual", "manual": "manual", "托管": "assisted", "assisted": "assisted", "自动": "assisted"}
ATTACK_ALIASES = {
    "coc": "d100_skill", "d100": "d100_skill", "d100_skill": "d100_skill",
    "dnd": "d20_vs_ac", "d20": "d20_vs_ac", "d20_vs_ac": "d20_vs_ac",
    "sw": "sw2d6", "剑世界": "sw2d6", "sw2d6": "sw2d6",
}


class SettingsModal(discord.ui.Modal, title="本的设置"):
    def __init__(self, c: dict, panel_msg: discord.Message | None):
        super().__init__()
        self.cid = c["id"]
        self.panel_msg = panel_msg
        s = c["settings"]
        self.name_in = discord.ui.TextInput(label="本的名称", default=c["name"], max_length=40)
        self.mode_in = discord.ui.TextInput(label="战斗模式：手动 或 托管", default="托管" if s["combat_mode"] == "assisted" else "手动", max_length=10)
        self.init_in = discord.ui.TextInput(label="先攻公式（如 1d20+先攻，或直接写属性名 敏捷）", default=s["initiative_expr"], max_length=60)
        current_attack = {"d100_skill": "coc", "d20_vs_ac": "dnd", "sw2d6": "sw"}.get(s["attack_mode"], "coc")
        self.atk_mode_in = discord.ui.TextInput(label="攻击判定：coc / dnd / sw（剑世界）", default=current_attack, max_length=12)
        self.dmg_in = discord.ui.TextInput(label="默认伤害公式", default=s["default_damage"], max_length=60)
        for item in (self.name_in, self.mode_in, self.init_in, self.atk_mode_in, self.dmg_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mode = MODE_ALIASES.get(self.mode_in.value.strip().lower())
            if not mode:
                raise TrpgApiError(400, "战斗模式请填 手动 或 托管")
            atk = ATTACK_ALIASES.get(self.atk_mode_in.value.strip().lower())
            if not atk:
                raise TrpgApiError(400, "攻击判定请填 coc、dnd 或 sw")
            await api().patch_campaign(
                interaction.user, self.cid, name=self.name_in.value,
                settings={"combat_mode": mode, "initiative_expr": self.init_in.value.strip(), "attack_mode": atk, "default_damage": self.dmg_in.value.strip()},
            )
            await interaction.response.send_message("设置已保存", ephemeral=True)
            await refresh_campaign_panel(self.panel_msg, self.cid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class AttackSettingsModal(discord.ui.Modal, title="攻击与属性映射"):
    def __init__(self, c: dict, panel_msg: discord.Message | None):
        super().__init__()
        self.cid = c["id"]
        self.panel_msg = panel_msg
        s = c["settings"]
        self.skill_in = discord.ui.TextInput(label="默认攻击技能名（coc 模式用）", default=s["default_attack_skill"], max_length=32)
        self.expr_in = discord.ui.TextInput(label="攻击公式（dnd 模式用，如 1d20+攻击）", default=s["attack_expr"], max_length=60)
        self.hp_in = discord.ui.TextInput(label="HP 属性名", default=s["hp_attr"], max_length=32)
        self.maxhp_in = discord.ui.TextInput(label="最大 HP 属性名", default=s["max_hp_attr"], max_length=32)
        self.ac_in = discord.ui.TextInput(label="AC/防御属性名", default=s["ac_attr"], max_length=32)
        for item in (self.skill_in, self.expr_in, self.hp_in, self.maxhp_in, self.ac_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await api().patch_campaign(
                interaction.user, self.cid,
                settings={
                    "default_attack_skill": self.skill_in.value.strip(), "attack_expr": self.expr_in.value.strip(),
                    "hp_attr": self.hp_in.value.strip(), "max_hp_attr": self.maxhp_in.value.strip(), "ac_attr": self.ac_in.value.strip(),
                },
            )
            await interaction.response.send_message("攻击设置已保存", ephemeral=True)
            await refresh_campaign_panel(self.panel_msg, self.cid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class ArchiveModal(discord.ui.Modal, title="归档确认"):
    def __init__(self, c: dict, panel_msg: discord.Message | None):
        super().__init__()
        self.c = c
        self.panel_msg = panel_msg
        self.confirm = discord.ui.TextInput(label=f"输入本的名称「{c['name']}」以确认归档"[:45], max_length=40)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if self.confirm.value.strip() != self.c["name"]:
                raise TrpgApiError(400, "名称不匹配，已取消")
            await api().patch_campaign(interaction.user, self.c["id"], status="archived")
            await interaction.response.send_message(f"「{self.c['name']}」已归档。数据保留，如需恢复请联系管理员", ephemeral=True)
            await refresh_campaign_panel(self.panel_msg, self.c["id"])
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


# ========================================================== combat panel
class CombatButton(discord.ui.DynamicItem[discord.ui.Button], template=r"trpg:combat:(?P<action>[a-z_]+):(?P<eid>\d+)"):
    def __init__(self, action: str, eid: int, label: str = "", style: discord.ButtonStyle = discord.ButtonStyle.secondary, emoji=None, row: int | None = None):
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji, custom_id=f"trpg:combat:{action}:{eid}", row=row))
        self.action = action
        self.eid = eid

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["eid"]), item.label or "", item.style, item.emoji)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await handle_combat_action(interaction, self.action, self.eid)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class CombatPanelView(discord.ui.View):
    def __init__(self, eid: int):
        super().__init__(timeout=None)
        B = discord.ButtonStyle
        self.add_item(CombatButton("join", eid, "加入", B.success, "🙋", 0))
        self.add_item(CombatButton("add_npc", eid, "添加敌人", B.secondary, "👹", 0))
        self.add_item(CombatButton("init", eid, "先攻", B.secondary, "🎲", 0))
        self.add_item(CombatButton("setinit", eid, "设先攻", B.secondary, None, 0))
        self.add_item(CombatButton("next", eid, "下一个", B.primary, "⏭️", 1))
        self.add_item(CombatButton("hp", eid, "伤害/治疗", B.danger, "💔", 1))
        self.add_item(CombatButton("attack", eid, "攻击", B.danger, "⚔️", 1))
        self.add_item(CombatButton("undo", eid, "撤销", B.secondary, "↩️", 1))
        self.add_item(CombatButton("remove", eid, "移出", B.secondary, None, 2))
        self.add_item(CombatButton("refresh", eid, "刷新", B.secondary, "🔄", 2))
        self.add_item(CombatButton("end", eid, "结束战斗", B.secondary, "🏁", 2))


async def handle_combat_action(interaction: discord.Interaction, action: str, eid: int) -> None:
    enc = await api().get_combat(eid)
    c = await api().get_campaign(enc["campaign_id"])
    user = interaction.user
    role = role_of(c, user)
    panel_msg = interaction.message
    channel = interaction.channel

    if enc["status"] != "active" and action != "refresh":
        await send_ephemeral(interaction, "这场战斗已经结束")
        return

    if action == "refresh":
        await interaction.response.defer()
        await refresh_combat_panel(panel_msg, eid, c)
        return

    if action == "join":
        chars = await api().list_characters(c["id"], owner_user_id=None if role == "dm" else user.id)
        in_combat = {cb.get("character_id") for cb in enc["combatants"]}
        chars = [ch for ch in chars if ch["id"] not in in_combat]
        if not chars:
            await send_ephemeral(interaction, "没有可加入的角色（可能已经都在战斗里了，或你还没创建角色）")
            return
        await send_ephemeral(interaction, "选择要加入战斗的角色：", view=JoinView(eid, chars, panel_msg, c))
        return

    if action == "hp":
        ids = await own_combatant_ids(enc, user, c)
        opts = combatant_options(enc, ids)
        if not opts:
            await send_ephemeral(interaction, "没有你可以操作的参与者")
            return
        await send_ephemeral(interaction, "选择目标，然后填写数值（负数=伤害，正数=治疗）：", view=PickThenModalView(eid, opts, panel_msg, c, HpModal))
        return

    if action == "attack":
        atk_ids = await own_combatant_ids(enc, user, c)
        atk_opts = combatant_options(enc, atk_ids)
        tgt_opts = combatant_options(enc)
        if not atk_opts or len(tgt_opts) < 2:
            await send_ephemeral(interaction, "需要至少一个你控制的角色和一个目标在战斗中")
            return
        await send_ephemeral(interaction, "选择攻击者和目标：", view=AttackView(eid, atk_opts, tgt_opts, panel_msg, c))
        return

    if action == "setinit":
        ids = await own_combatant_ids(enc, user, c)
        opts = combatant_options(enc, ids)
        if not opts:
            await send_ephemeral(interaction, "没有你可以操作的参与者")
            return
        await send_ephemeral(interaction, "选择要设置先攻的参与者：", view=PickThenModalView(eid, opts, panel_msg, c, InitiativeModal))
        return

    if role != "dm":
        await send_ephemeral(interaction, "这个按钮只有 DM（或服务器管理员）可以用")
        return

    if action == "add_npc":
        await interaction.response.send_modal(NpcModal(eid, panel_msg, c))
    elif action == "init":
        res = await api().roll_initiative(user, eid)
        await interaction.response.defer()
        notes = res.get("notes") or []
        if notes and channel:
            await channel.send("🎲 先攻：\n" + "\n".join(f"• {n}" for n in notes)[:1900])
        await refresh_combat_panel(panel_msg, eid, c)
    elif action == "next":
        res = await api().next_turn(user, eid)
        await interaction.response.defer()
        cur = res.get("current")
        if cur and channel:
            await channel.send(f"⏭️ 第 {res['round']} 轮：轮到 **{cur['name']}** 行动")
        await refresh_combat_panel(panel_msg, eid, c)
    elif action == "undo":
        res = await api().undo(user, eid)
        await interaction.response.defer()
        if channel:
            await channel.send(f"↩️ {res['summary']}（原记录：{res['undone_summary']}）")
        await refresh_combat_panel(panel_msg, eid, c)
    elif action == "remove":
        opts = combatant_options(enc)
        if not opts:
            await send_ephemeral(interaction, "战斗里没有人")
            return
        await send_ephemeral(interaction, "选择要移出战斗的参与者：", view=RemoveView(eid, opts, panel_msg, c))
    elif action == "end":
        res = await api().end_combat(user, eid)
        await interaction.response.defer()
        await safe_edit(panel_msg, embed=render.combat_embed(res, c), view=None)
        if channel:
            await channel.send("🏁 战斗结束。PC 的 HP 已同步到角色卡")
    else:
        await send_ephemeral(interaction, "未知操作")


class JoinView(discord.ui.View):
    def __init__(self, eid: int, chars: list[dict], panel_msg, campaign: dict):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.eid, self.panel_msg, self.campaign = eid, panel_msg, campaign
        sel = discord.ui.Select(placeholder="选择角色", options=[discord.SelectOption(label=c["name"][:100], value=str(c["id"])) for c in chars[:25]])
        sel.callback = self._pick  # type: ignore[method-assign]
        self.add_item(sel)

    async def _pick(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select)][0]
        try:
            enc = await api().add_combatant(interaction.user, self.eid, character_id=int(sel.values[0]))
            name = next((cb["name"] for cb in enc["combatants"] if str(cb.get("character_id")) == sel.values[0]), "角色")
            await interaction.response.edit_message(content=f"{name} 已加入战斗", view=None)
            await refresh_combat_panel(self.panel_msg, self.eid, self.campaign)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class RemoveView(discord.ui.View):
    def __init__(self, eid: int, opts, panel_msg, campaign):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.eid, self.panel_msg, self.campaign = eid, panel_msg, campaign
        sel = discord.ui.Select(placeholder="选择参与者", options=opts)
        sel.callback = self._pick  # type: ignore[method-assign]
        self.add_item(sel)

    async def _pick(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select)][0]
        try:
            await api().remove_combatant(interaction.user, self.eid, int(sel.values[0]))
            await interaction.response.edit_message(content="已移出", view=None)
            await refresh_combat_panel(self.panel_msg, self.eid, self.campaign)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class PickThenModalView(discord.ui.View):
    """Ephemeral select; picking an entry opens the given modal for that combatant."""

    def __init__(self, eid: int, opts, panel_msg, campaign, modal_cls):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.eid, self.panel_msg, self.campaign, self.modal_cls = eid, panel_msg, campaign, modal_cls
        self.labels = {o.value: o.label for o in opts}
        sel = discord.ui.Select(placeholder="选择参与者", options=opts)
        sel.callback = self._pick  # type: ignore[method-assign]
        self.add_item(sel)

    async def _pick(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select)][0]
        cid = int(sel.values[0])
        await interaction.response.send_modal(self.modal_cls(self.eid, cid, self.labels[sel.values[0]], self.panel_msg, self.campaign))


class HpModal(discord.ui.Modal):
    def __init__(self, eid: int, combatant_id: int, label: str, panel_msg, campaign):
        super().__init__(title=f"HP 变动：{label}"[:45])
        self.eid, self.combatant_id, self.panel_msg, self.campaign = eid, combatant_id, panel_msg, campaign
        self.delta_in = discord.ui.TextInput(label="数值（负数=伤害，正数=治疗）", placeholder="-5 或 +3", max_length=6)
        self.reason_in = discord.ui.TextInput(label="原因（可选）", required=False, max_length=40)
        self.add_item(self.delta_in)
        self.add_item(self.reason_in)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            delta = parse_int(self.delta_in.value, "数值")
            res = await api().change_hp(interaction.user, self.eid, self.combatant_id, delta, self.reason_in.value.strip())
            await interaction.response.defer(ephemeral=True)
            if interaction.channel:
                await interaction.channel.send(("💔 " if delta < 0 else "💚 ") + res["summary"])
            await refresh_combat_panel(self.panel_msg, self.eid, self.campaign)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class InitiativeModal(discord.ui.Modal):
    def __init__(self, eid: int, combatant_id: int, label: str, panel_msg, campaign):
        super().__init__(title=f"设置先攻：{label}"[:45])
        self.eid, self.combatant_id, self.panel_msg, self.campaign = eid, combatant_id, panel_msg, campaign
        self.value_in = discord.ui.TextInput(label="先攻值（数字，越大越先）", max_length=8)
        self.add_item(self.value_in)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            try:
                value = float(self.value_in.value.strip())
            except ValueError:
                raise TrpgApiError(400, "先攻值必须是数字")
            await api().set_initiative(interaction.user, self.eid, self.combatant_id, value)
            await interaction.response.send_message("先攻已更新", ephemeral=True)
            await refresh_combat_panel(self.panel_msg, self.eid, self.campaign)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class NpcModal(discord.ui.Modal, title="添加敌人 / NPC"):
    def __init__(self, eid: int, panel_msg, campaign):
        super().__init__()
        self.eid, self.panel_msg, self.campaign = eid, panel_msg, campaign
        coc = campaign["settings"]["attack_mode"] == "d100_skill"
        self.name_in = discord.ui.TextInput(label="名字", max_length=40, placeholder="哥布林")
        self.hp_in = discord.ui.TextInput(label="HP", max_length=6, placeholder="7")
        sw = campaign["settings"]["attack_mode"] == "sw2d6"
        self.def_in = discord.ui.TextInput(
            label="技能值（coc 命中用，可空）" if coc else ("回避（剑世界，可空）" if sw else "AC（dnd 命中用，可空）"),
            required=False, max_length=6,
        )
        self.prot_in = discord.ui.TextInput(label="防护点（剑世界，可空）" if sw else "防护点（可空）", required=False, max_length=6)
        self.dmg_in = discord.ui.TextInput(label="伤害公式（可空，默认用本的设置）", required=False, max_length=40, placeholder="1d6")
        # Discord modals allow at most five text inputs. Initiative is
        # intentionally handled by the panel's initiative action after the
        # NPC is added (or rolled for everyone at once).
        for item in (self.name_in, self.hp_in, self.def_in, self.prot_in, self.dmg_in):
            self.add_item(item)
        self.coc = coc
        self.sw = sw

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hp = parse_int(self.hp_in.value, "HP")
            d = parse_optional_int(self.def_in.value, "技能值/AC")
            protection = parse_optional_int(self.prot_in.value, "防护点")
            fields = {"name": self.name_in.value.strip(), "hp": hp, "defense": protection, "damage_expr": self.dmg_in.value.strip() or None}
            if self.coc:
                fields["skill"] = d
            elif self.sw:
                fields["ac"] = d
            else:
                fields["ac"] = d
            await api().add_combatant(interaction.user, self.eid, **fields)
            await interaction.response.send_message(f"已添加 {fields['name']}（HP {hp}）", ephemeral=True)
            await refresh_combat_panel(self.panel_msg, self.eid, self.campaign)
        except Exception as e:  # noqa: BLE001
            await report_error(interaction, e)


class AttackView(discord.ui.View):
    def __init__(self, eid: int, atk_opts, tgt_opts, panel_msg, campaign):
        super().__init__(timeout=EPHEMERAL_TIMEOUT)
        self.eid, self.panel_msg, self.campaign = eid, panel_msg, campaign
        self.attacker: int | None = int(atk_opts[0].value) if len(atk_opts) == 1 else None
        self.target: int | None = None
        a = discord.ui.Select(placeholder="攻击者", options=atk_opts, row=0)
        a.callback = self._pick_attacker  # type: ignore[method-assign]
        if len(atk_opts) == 1:
            a.disabled = True
            a.placeholder = f"攻击者：{atk_opts[0].label}"
        t = discord.ui.Select(placeholder="目标", options=tgt_opts, row=1)
        t.callback = self._pick_target  # type: ignore[method-assign]
        self.add_item(a)
        self.add_item(t)

    async def _pick_attacker(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select) and i.row == 0][0]
        self.attacker = int(sel.values[0])
        await interaction.response.defer()

    async def _pick_target(self, interaction: discord.Interaction):
        sel = [i for i in self.children if isinstance(i, discord.ui.Select) and i.row == 1][0]
        self.target = int(sel.values[0])
        await interaction.response.defer()

    def _ready(self) -> bool:
        return self.attacker is not None and self.target is not None

    @discord.ui.button(label="攻击！", style=discord.ButtonStyle.danger, emoji="⚔️", row=2)
    async def go(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._ready():
            await send_ephemeral(interaction, "请先选择攻击者和目标")
            return
        await run_attack(interaction, self.eid, self.attacker, self.target, self.panel_msg, self.campaign)

    @discord.ui.button(label="自定义（技能/公式）", style=discord.ButtonStyle.secondary, row=2)
    async def custom(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._ready():
            await send_ephemeral(interaction, "请先选择攻击者和目标")
            return
        await interaction.response.send_modal(CustomAttackModal(self.eid, self.attacker, self.target, self.panel_msg, self.campaign))


async def run_attack(interaction: discord.Interaction, eid: int, attacker: int, target: int, panel_msg, campaign, skill=None, attack_expr=None, damage_expr=None):
    try:
        res = await api().attack(interaction.user, eid, attacker, target, skill=skill, attack_expr=attack_expr, damage_expr=damage_expr)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("已结算", ephemeral=True)
        if interaction.channel:
            await interaction.channel.send(render.attack_text(res)[:1900])
        await refresh_combat_panel(panel_msg, eid, campaign)
    except Exception as e:  # noqa: BLE001
        await report_error(interaction, e)


class CustomAttackModal(discord.ui.Modal, title="自定义攻击"):
    def __init__(self, eid: int, attacker: int, target: int, panel_msg, campaign):
        super().__init__()
        self.eid, self.attacker, self.target, self.panel_msg, self.campaign = eid, attacker, target, panel_msg, campaign
        coc = campaign["settings"]["attack_mode"] == "d100_skill"
        self.a_in = discord.ui.TextInput(label="技能名（如 射击）" if coc else "攻击公式（如 1d20+攻击）", required=False, max_length=60)
        self.d_in = discord.ui.TextInput(label="伤害公式（如 1d10+2）", required=False, max_length=60)
        self.coc = coc
        self.add_item(self.a_in)
        self.add_item(self.d_in)

    async def on_submit(self, interaction: discord.Interaction):
        a = self.a_in.value.strip() or None
        await run_attack(
            interaction, self.eid, self.attacker, self.target, self.panel_msg, self.campaign,
            skill=a if self.coc else None, attack_expr=None if self.coc else a, damage_expr=self.d_in.value.strip() or None,
        )
