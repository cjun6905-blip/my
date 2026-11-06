"""Embed / text renderers. Pure functions over API dicts."""
from __future__ import annotations

import discord

COLOR_CAMPAIGN = 0x5865F2
COLOR_CHAR = 0x57F287
COLOR_COMBAT = 0xED4245
COLOR_ROLL = 0xFEE75C

MODE_NAMES = {"manual": "手动（bot 只记录，不自动扣血）", "assisted": "托管（bot 掷骰并自动结算）"}
ATTACK_NAMES = {"d100_skill": "d100 技能检定（CoC）", "d20_vs_ac": "d20 对抗 AC（DnD）", "sw2d6": "2d6 对抗回避（剑世界）"}
SYSTEM_NAMES = {"coc": "CoC 克苏鲁的呼唤", "dnd": "DnD 龙与地下城", "sw": "剑世界 2.5", "generic": "通用"}
LEVEL_EMOJI = {"大成功": "🌟", "极难成功": "✨", "困难成功": "✅", "成功": "✅", "失败": "❌", "大失败": "💀"}


def mention(user_id: str | int) -> str:
    return f"<@{user_id}>"


def campaign_embed(c: dict) -> discord.Embed:
    s = c["settings"]
    status = "进行中" if c["status"] == "active" else "已归档"
    e = discord.Embed(title=f"📖 {c['name']}", color=COLOR_CAMPAIGN)
    e.description = f"状态：{status}　规则：{SYSTEM_NAMES.get(s['system'], s['system'])}　本 ID：{c['id']}"
    dms = [m["user_id"] for m in c["members"] if m["role"] == "dm"]
    players = [m["user_id"] for m in c["members"] if m["role"] == "player"]
    e.add_field(name="DM", value=" ".join(mention(u) for u in dms) or "—", inline=False)
    e.add_field(name=f"玩家（{len(players)}）", value=" ".join(mention(u) for u in players[:30]) or "还没有玩家，用「成员」按钮添加", inline=False)
    chans = " ".join(f"<#{ch}>" for ch in c["channels"][:10]) or "未绑定，在目标频道点「绑定本频道」"
    e.add_field(name="绑定频道", value=chans, inline=False)
    e.add_field(name="角色数", value=str(c.get("character_count", 0)), inline=True)
    e.add_field(name="战斗模式", value=MODE_NAMES.get(s["combat_mode"], s["combat_mode"]), inline=True)
    e.add_field(name="攻击判定", value=ATTACK_NAMES.get(s["attack_mode"], s["attack_mode"]), inline=True)
    e.add_field(
        name="公式",
        value=(
            f"先攻：`{s['initiative_expr']}`　攻击：`{s['attack_expr']}`　默认伤害：`{s['default_damage']}`\n"
            f"默认攻击技能：`{s['default_attack_skill']}`　HP 属性：`{s['hp_attr']}` / `{s['max_hp_attr']}`　AC 属性：`{s['ac_attr']}`"
        ),
        inline=False,
    )
    if c.get("active_encounter_id"):
        e.add_field(name="⚔ 战斗", value=f"进行中（战斗 #{c['active_encounter_id']}），用 /战斗 面板 查看", inline=False)
    e.set_footer(text="DM 专用按钮：成员 / 设置 / 攻击设置 / 绑定 / 归档；所有人可用：角色 / 刷新")
    return e


def _fmt_val(v) -> str:
    return str(v)


def character_embed(ch: dict, campaign: dict | None = None, portrait_filename: str | None = None) -> discord.Embed:
    e = discord.Embed(title=f"🧝 {ch['name']}", color=COLOR_CHAR)
    owner = mention(ch["owner_user_id"])
    parts = [f"主人：{owner}"]
    if campaign:
        parts.append(f"本：{campaign['name']}")
    if ch.get("is_active"):
        parts.append("（当前使用中）")
    e.description = "　".join(parts)
    attrs: dict = ch.get("attrs") or {}
    nums = [(k, v) for k, v in attrs.items() if isinstance(v, int)]
    texts = [(k, v) for k, v in attrs.items() if not isinstance(v, int)]
    if nums:
        width = max(len(k) for k, _ in nums)
        lines = [f"{k.ljust(width)} {v:>4}" for k, v in nums]
        # split into up to 3 columns of fields
        cols = 3 if len(lines) > 12 else (2 if len(lines) > 6 else 1)
        per = -(-len(lines) // cols)
        for i in range(cols):
            chunk = lines[i * per : (i + 1) * per]
            if chunk:
                e.add_field(name="数值" if i == 0 else "​", value="```\n" + "\n".join(chunk)[:1000] + "\n```", inline=True)
    if texts:
        e.add_field(name="其他", value="\n".join(f"**{k}**：{_fmt_val(v)}" for k, v in texts)[:1024], inline=False)
    if not attrs:
        e.add_field(name="属性", value="还没有属性。用 /角色 设置 或「编辑」按钮添加，例如 `力量 50`", inline=False)
    if ch.get("notes"):
        e.add_field(name="备注", value=ch["notes"][:1024], inline=False)
    if portrait_filename:
        e.set_image(url=f"attachment://{portrait_filename}")
    e.set_footer(text=f"角色 ID {ch['id']}　最后更新 {ch.get('updated_at', '')[:16].replace('T', ' ')} UTC")
    return e


def hp_bar(hp: int, max_hp: int, width: int = 10) -> str:
    if max_hp <= 0:
        return ""
    filled = max(0, min(width, round(hp / max_hp * width)))
    return "█" * filled + "░" * (width - filled)


def combat_embed(enc: dict, campaign: dict | None = None) -> discord.Embed:
    cur = enc.get("current")
    title = f"⚔ 战斗 #{enc['id']}　第 {enc['round']} 轮"
    e = discord.Embed(title=title, color=COLOR_COMBAT)
    if enc["status"] != "active":
        e.description = "战斗已结束"
    elif cur:
        e.description = f"当前行动：**{cur['name']}**"
    else:
        e.description = "还没有参与者。玩家点「加入」，DM 点「添加敌人」。"
    lines = []
    for i, cb in enumerate(enc["combatants"]):
        marker = "▶" if enc["status"] == "active" and i == enc.get("turn_index", 0) else "　"
        init = f"{cb['initiative']:g}" if cb["initiative"] is not None else "?"
        hp = f"{cb['hp']}/{cb['max_hp']}" if cb["max_hp"] else str(cb["hp"])
        bar = hp_bar(cb["hp"], cb["max_hp"])
        tag = "PC" if cb["is_pc"] else "NPC"
        st = f"  [{cb['status']}]" if cb.get("status") else ""
        lines.append(f"{marker} {i + 1}. {cb['name']} ({tag})　先攻 {init}　HP {hp} {bar}{st}")
    if lines:
        e.add_field(name="先攻顺序", value="\n".join(lines)[:1024], inline=False)
    events = [ev for ev in enc.get("recent_events", []) if not ev.get("undone")][:5]
    if events:
        e.add_field(name="最近", value="\n".join(f"• {ev['summary']}" for ev in events)[:1024], inline=False)
    mode = campaign["settings"]["combat_mode"] if campaign else None
    foot = "模式：" + ("托管" if mode == "assisted" else "手动" if mode == "manual" else "?")
    e.set_footer(text=foot + "　按钮：加入 / 添加敌人 / 先攻 / 下一个 / 伤害治疗 / 攻击 / 撤销 / 结束")
    return e


def roll_text(res: dict, user_mention: str) -> str:
    who = f"{user_mention}" + (f"（{res['character_name']}）" if res.get("character_name") else "")
    return f"🎲 {who} 掷 `{res['expr']}`\n{res['detail']} = **{res['total']}**"


def check_text(res: dict, user_mention: str) -> str:
    who = f"{user_mention}" + (f"（{res['character_name']}）" if res.get("character_name") else "")
    extra = f"　十位候选 {res['tens_candidates']}" if len(res.get("tens_candidates", [])) > 1 else ""
    emoji = LEVEL_EMOJI.get(res["level"], "")
    return f"🎯 {who} 检定「{res['skill']}」({res['skill_value']})：1d100 = **{res['roll']}**{extra}\n{emoji} **{res['level']}**"


def attack_text(res: dict) -> str:
    return "\n".join(res["lines"])


def history_lines(rows: list[dict]) -> str:
    out = []
    names = {"__create__": "创建", "__delete__": "删除", "__name__": "改名", "__notes__": "备注", "__portrait__": "立绘"}
    for h in rows:
        f = names.get(h["field"], h["field"])
        when = h["created_at"][5:16].replace("T", " ")
        if h["field"] in ("__create__", "__delete__", "__portrait__"):
            out.append(f"`{when}` {mention(h['actor_user_id'])} {f}")
        else:
            reason = f"（{h['reason']}）" if h.get("reason") else ""
            out.append(f"`{when}` {mention(h['actor_user_id'])} {f}：{h['old_value']} → {h['new_value']}{reason}")
    return "\n".join(out)[:1900] or "没有记录"


_ST_COMPACT = None


def parse_attr_text(text: str) -> tuple[dict, list[str]]:
    """Parse attribute text into (attrs, keys_to_delete).

    Accepts the separated form '力量=50 敏捷 60, hp:11 职业=侦探' and the SealDice-style
    compact form '力量50敏捷60体质70hp11' (name immediately followed by digits). A value of '-' deletes.
    """
    import re

    global _ST_COMPACT
    if _ST_COMPACT is None:
        _ST_COMPACT = re.compile(r"([^\W\d_][^\W\d_]*?)\s*[=:：]?\s*(-?\d+)")
    text = (text or "").strip()
    attrs: dict = {}
    dels: list[str] = []
    if not text:
        return attrs, dels
    # compact form: every character is consumed by name+number pairs
    stripped = re.sub(r"[\s,，;；]+", "", text)
    pairs = _ST_COMPACT.findall(stripped)
    if pairs and "".join(k + v for k, v in pairs) == stripped.replace("=", "").replace(":", "").replace("：", ""):
        for k, v in pairs:
            attrs[k] = v
        return attrs, dels
    tokens = [t for t in re.split(r"[\s,，;；=:：]+", text) if t]
    for i in range(0, len(tokens) - 1, 2):
        k, v = tokens[i], tokens[i + 1]
        if v == "-":
            dels.append(k)
        else:
            attrs[k] = v
    return attrs, dels


def inventory_embed(ch_name: str, items: list[dict], owner_id: str | int | None = None) -> discord.Embed:
    e = discord.Embed(title=f"🎒 {ch_name} 的背包", color=0xE67E22)
    if owner_id:
        e.description = f"主人：{mention(owner_id)}"
    if not items:
        e.add_field(name="空空如也", value="用 /背包 添加 名称 数量 放东西进来", inline=False)
        return e
    lines = []
    for it in items:
        note = f" — {it['note']}" if it.get("note") else ""
        lines.append(f"• **{it['name']}** ×{it['qty']}{note}")
    body = "\n".join(lines)
    for i in range(0, len(body), 1000):
        e.add_field(name="物品" if i == 0 else "​", value=body[i : i + 1000], inline=False)
    e.set_footer(text=f"共 {len(items)} 种物品")
    return e


def sc_text(res: dict, user_mention: str) -> str:
    emoji = LEVEL_EMOJI.get(res["level"], "")
    lines = [
        f"🧠 {user_mention}（{res['character_name']}）理智检定：1d100 = **{res['roll']}** / {res['san_before']} → {emoji} **{res['level']}**",
        f"损失 {res['loss_detail']} = **{res['loss']}**　理智 {res['san_before']} → **{res['san_after']}**",
    ]
    lines += [f"⚠️ {n}" for n in res.get("notes", [])]
    return "\n".join(lines)


def en_text(res: dict, user_mention: str) -> str:
    if res["success"]:
        return f"📈 {user_mention}（{res['character_name']}）「{res['skill']}」成长检定：1d100 = **{res['roll']}** > {res['before']}，成功！+{res['gain']} → **{res['after']}**"
    return f"📉 {user_mention}（{res['character_name']}）「{res['skill']}」成长检定：1d100 = **{res['roll']}** ≤ {res['before']}，未成长"


def sw_rating_text(res: dict, user_mention: str) -> str:
    who = f"{user_mention}" + (f"（{res['character_name']}）" if res.get("character_name") else "")
    extra = "，首掷失败" if res.get("fumble") else (f"，暴击 {res.get('crit_count', 0)} 次" if res.get("crit_count") else "")
    return f"⚔️ {who} 威力 `{res['expr']}`：{res['detail']} = **{res['total']}**{extra}"


def sw_table_text(row: dict) -> str:
    values = row.get("values", {})
    cells = "　".join(f"{d}: **{values.get(str(d), 0)}**" for d in range(3, 13))
    return f"📋 剑世界威力表 K{row['power']}\n{cells}\n\n2 点为自动失败；暴击值和追加伤害请写在表达式里，例如 `k{row['power']}+5@10`。"


def sw_check_text(res: dict, user_mention: str) -> str:
    who = f"{user_mention}" + (f"（{res['character_name']}）" if res.get("character_name") else "")
    dice = "+".join(str(x) for x in res["dice"])
    mod = f" {res['modifier']:+d}" if res.get("modifier") else ""
    target = f" vs {res['target']}" if res.get("target") is not None else ""
    result = f" → **{res['outcome']}**" if res.get("outcome") else ""
    return f"🎲 {who} 剑世界检定：[{dice}] = {res['raw']}{mod} = **{res['total']}**{target}{result}"


def sw_generate_text(res: dict, character_name: str | None = None) -> str:
    a, b, d = res.get("abilities", {}), res.get("bonuses", {}), res.get("derived", {})
    base = res.get("base", {})
    rolls = "；".join(f"{r['letter']}={'+'.join(map(str, r['dice']))}{r['fixed']:+d}" for r in res.get("rolls", []))
    birth = res.get("birth")
    birth_line = "出身：未指定（手动技/体/心）"
    if birth:
        roll = f"，骰 {res['birth_roll']}" if res.get("birth_roll") is not None else ""
        birth_line = f"出身：{birth['origin']}（{birth['source']}，{birth['skills']}，初期经验 {birth['experience']}）{roll}"
    lines = [
        f"🧬 剑世界 2.5 快速生成{f'「{character_name}」' if character_name else ''}：{res['race']}（Lv.{res['level']}）",
        birth_line,
        f"生まれ基础：技 {base['技']} / 体 {base['体']} / 心 {base['心']}",
        "能力值：" + "　".join(f"{k} {v}（B{b[k]}）" for k, v in a.items()),
        f"派生：HP {d['HP']}　MP {d['MP']}　生命抵抗 {d['生命抵抗力']}　精神抵抗 {d['精神抵抗力']}",
        f"初始骰：{rolls}",
    ]
    if res.get("languages"):
        lines.append(f"语言：{res['languages'][:500]}")
    if res.get("corruption") is not None:
        lines.append(f"污秽：{res['corruption']}")
    if res.get("written_to"):
        lines.append(f"✅ 已写入角色卡「{res['written_to']}」；技能等级、武器防具和种族特征的具体选择仍需 DM/玩家确认。")
    else:
        lines.append("提示：填写「角色」可把这些数值和出身资料写入角色卡；复杂种族特征仍由 DM/玩家确认。")
    return "\n".join(lines)


def sw_growth_text(res: dict, character_name: str | None = None) -> str:
    dice = " + ".join(map(str, res.get("dice", [])))
    options = " / ".join(res.get("options", [])) or "—"
    line = f"📈 剑世界成长{f'（{character_name}）' if character_name else ''}：[{dice}] → 可选：**{options}**"
    if res.get("applied"):
        line += f"\n✅ {res['applied']}：{res['before']} → **{res['after']}**"
    else:
        line += "\n应用方式：把本次两颗骰子填回 `/剑世界 成长` 的「骰子1/骰子2」，再填写「属性」，避免重新掷出另一组结果。"
    return line
