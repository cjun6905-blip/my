"""Versioned servant catalogue shared by the bot and battle service.

Each released servant references locally bundled, optimized Activity artwork.
"""

from __future__ import annotations

from typing import Any


def _effect(
    kind: str,
    value: int = 0,
    duration: int = 1,
    target: str = "self",
    *,
    timing: str | None = None,
) -> dict[str, Any]:
    effect = {"kind": kind, "value": value, "duration": duration, "target": target}
    if timing:
        effect["timing"] = timing
    return effect


def _skill(name: str, cooldown: int, description: str, *effects: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "cooldown": cooldown,
        "description": description,
        "effects": list(effects),
    }


def _passive(name: str, description: str, *effects: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "effects": list(effects)}


def _servant(
    servant_id: str,
    name: str,
    class_name: str,
    rarity: int,
    hp: int,
    attack: int,
    deck: str,
    skills: list[dict[str, Any]],
    np_name: str,
    np_card: str,
    np_target: str,
    np_multiplier: int,
    np_effects: list[dict[str, Any]] | None = None,
    np_quote: str | None = None,
    *,
    event_only: bool = False,
    passives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": servant_id,
        "name": name,
        "class": class_name,
        "rarity": rarity,
        "hp": hp,
        # Catalogue source values stay compact; the public stat uses a FGO-like
        # five-digit scale so HP/ATK and damage feedback are immediately legible.
        "attack": attack * 8,
        "deck": list(deck),
        "event_only": event_only,
        "passives": list(passives or []),
        "skills": skills,
        "np": {
            "name": np_name,
            "card": np_card,
            "target": np_target,
            "multiplier": np_multiplier,
            "effects": np_effects or [],
            "quote": np_quote,
            "cg_url": f"noble-phantasms/{servant_id}.webp" if np_quote else None,
        },
    }


_CATALOGUE = [
    _servant("artoria_saber", "阿尔托莉雅·潘德拉贡", "Saber", 5, 11200, 1180, "BBAAQ", [
        _skill("魔力放出 A", 5, "大幅强化自身的 Buster 性能。", _effect("card_up_b", 35, 1)),
        _skill("龙之炉心", 6, "增加自身 NP，并强化攻击。", _effect("np_charge", 25), _effect("attack_up", 18, 2)),
        _skill("领袖气质 B", 6, "提升己方全体攻击力。", _effect("attack_up", 15, 2, "team")),
    ], "誓约胜利之剑", "B", "all", 300, [_effect("np_charge", 15)]),
    _servant("nero_saber", "尼禄·克劳狄乌斯", "Saber", 4, 10600, 980, "BBAAQ", [
        _skill("富之杯 B", 6, "回复自身生命并增加 NP。", _effect("heal", 1600), _effect("np_charge", 15)),
        _skill("皇帝特权 EX", 7, "强化攻防并恢复生命。", _effect("attack_up", 22, 3), _effect("defense_up", 22, 3), _effect("heal", 900)),
        _skill("三度落阳", 8, "获得一次战续。", _effect("guts", 1800, 3)),
    ], "童女讴歌的荣华帝政", "A", "all", 240, [_effect("defense_down", 15, 2, "enemy_team")]),
    _servant("caesar_saber", "盖乌斯·尤利乌斯·恺撒", "Saber", 3, 9000, 920, "BBAQQ", [
        _skill("军略 B", 6, "提升己方全体宝具威力。", _effect("np_damage_up", 20, 2, "team")),
        _skill("领袖气质 C", 6, "提升己方全体攻击力。", _effect("attack_up", 12, 2, "team")),
        _skill("煽动 EX", 5, "强化一名队友的暴击并降低其防御。", _effect("crit_up", 35, 2, "ally"), _effect("defense_down", 10, 2, "ally")),
    ], "黄之死", "Q", "single", 420, [_effect("stars", 18)]),
    _servant("gilgamesh_archer", "吉尔伽美什", "Archer", 5, 10800, 1230, "BBAAQ", [
        _skill("领袖气质 A+", 6, "提升己方全体攻击力。", _effect("attack_up", 18, 2, "team")),
        _skill("黄金律 A", 6, "大幅提升自身 NP 获取。", _effect("np_gain_up", 40, 3)),
        _skill("巴比伦之藏 EX", 5, "获得 NP 与暴击星。", _effect("np_charge", 25), _effect("stars", 15)),
    ], "天地乖离开辟之星", "B", "all", 330, [_effect("defense_down", 18, 2, "enemy_team")]),
    _servant("emiya_archer", "卫宫", "Archer", 4, 10100, 1010, "BAAAQ", [
        _skill("心眼（真） B", 6, "获得回避并提升防御。", _effect("evade", 1), _effect("defense_up", 20, 2)),
        _skill("鹰之瞳 B+", 6, "提升暴击威力并获得暴击星。", _effect("crit_up", 45, 3), _effect("stars", 12)),
        _skill("投影魔术 A", 5, "强化三色指令卡。", _effect("card_up_all", 20, 1)),
    ], "无限剑制", "B", "all", 270, [_effect("stars", 20)]),
    _servant("robin_archer", "罗宾汉", "Archer", 3, 8700, 900, "BAAQQ", [
        _skill("破坏工作 A", 5, "降低敌方全体攻击并附加毒。", _effect("attack_down", 15, 3, "enemy_team"), _effect("poison", 350, 3, "enemy_team")),
        _skill("黄金律 E", 6, "提升自身 NP 获取。", _effect("np_gain_up", 28, 3)),
        _skill("皐月之王 B", 6, "获得回避和暴击星。", _effect("evade", 1), _effect("stars", 15)),
    ], "祈祷之弓", "A", "single", 390, [_effect("poison_bonus", 80)]),
    _servant("cu_lancer", "库·丘林", "Lancer", 3, 9600, 940, "BBAQQ", [
        _skill("战斗续行 A", 7, "获得战续。", _effect("guts", 2000, 4)),
        _skill("避矢之加护 B", 6, "获得三次回避。", _effect("evade", 3)),
        _skill("重整旗鼓 C", 5, "解除弱化并回复生命。", _effect("debuff_cleanse"), _effect("heal", 1200)),
    ], "刺穿死棘之枪", "Q", "single", 460, [_effect("defense_down", 12, 2, "enemy")]),
    _servant("scathach_lancer", "斯卡哈", "Lancer", 5, 11000, 1200, "BBAQQ", [
        _skill("魔境的智慧 A+", 6, "获得回避并强化暴击。", _effect("evade", 1), _effect("crit_up", 35, 3)),
        _skill("原初之卢恩", 5, "大幅强化一名队友的 Quick。", _effect("card_up_q", 40, 1, "ally")),
        _skill("弑神 B", 6, "提升攻击并对神性目标强化。", _effect("attack_up", 25, 2), _effect("trait_damage_up", 25, 2)),
    ], "贯穿死翔之枪", "Q", "single", 500, [_effect("stun", 1, 1, "enemy")]),
    _servant("leonidas_lancer", "列奥尼达一世", "Lancer", 3, 10800, 790, "BBAQQ", [
        _skill("殿军的矜持 A", 5, "吸引攻击并提升防御。", _effect("taunt", 1), _effect("defense_up", 25, 1)),
        _skill("战斗续行 A", 7, "获得战续。", _effect("guts", 2200, 4)),
        _skill("战士的雄叫 B", 6, "提升己方全体 Buster。", _effect("card_up_b", 18, 3, "team")),
    ], "炎门的守护者", "B", "team", 0, [_effect("defense_up", 35, 3, "team"), _effect("stars", 12)]),
    _servant("medusa_rider", "美杜莎", "Rider", 3, 9000, 930, "BBAQQ", [
        _skill("魔眼 A+", 6, "眩晕一名敌人。", _effect("stun", 1, 1, "enemy")),
        _skill("怪力 B", 5, "提升自身攻击力。", _effect("attack_up", 28, 2)),
        _skill("鲜血神殿 B", 6, "增加 NP 并提升 NP 获取。", _effect("np_charge", 20), _effect("np_gain_up", 25, 3)),
    ], "骑英之缰绳", "Q", "all", 260, [_effect("stars", 15)]),
    _servant("iskandar_rider", "伊斯坎达尔", "Rider", 5, 11600, 1160, "BBAAQ", [
        _skill("领袖气质 A", 6, "提升己方全体攻击力。", _effect("attack_up", 18, 2, "team")),
        _skill("军略 B", 6, "提升己方全体宝具威力。", _effect("np_damage_up", 20, 2, "team")),
        _skill("雷之征服者 EX", 5, "强化 Buster 并获得暴击星。", _effect("card_up_b", 35, 1), _effect("stars", 18)),
    ], "王之军势", "B", "all", 315, [_effect("defense_down", 15, 3, "enemy_team")]),
    _servant("ushiwakamaru_rider", "牛若丸", "Rider", 3, 8500, 970, "BAAQQ", [
        _skill("天狗的兵法 A", 6, "提升己方全体 NP 获取。", _effect("np_gain_up", 20, 3, "team")),
        _skill("燕之早业 B", 5, "获得回避与暴击星。", _effect("evade", 1), _effect("stars", 15)),
        _skill("领袖气质 C+", 6, "提升己方全体攻击力。", _effect("attack_up", 13, 2, "team")),
    ], "坛之浦·八艘跳", "Q", "single", 430, [_effect("quick_resist_down", 15, 2, "enemy")]),
    _servant("medea_caster", "美狄亚", "Caster", 3, 8200, 890, "BAAAQ", [
        _skill("高速神言 A", 7, "大幅增加自身 NP。", _effect("np_charge", 80)),
        _skill("金羊毛", 5, "回复自身生命。", _effect("heal", 1800)),
        _skill("喀耳刻的教诲 A", 6, "解除一名队友弱化并提升 NP 获取。", _effect("debuff_cleanse", target="ally"), _effect("np_gain_up", 28, 3, "ally")),
    ], "万疵必应修补", "A", "single", 400, [_effect("buff_remove", target="enemy")]),
    _servant("waver_caster", "诸葛孔明〔埃尔梅罗Ⅱ世〕", "Caster", 5, 11800, 900, "BAAAQ", [
        _skill("鉴识眼 A", 5, "增加一名队友 NP 并强化暴击。", _effect("np_charge", 30, target="ally"), _effect("crit_up", 35, 3, "ally")),
        _skill("军师的忠言 A+", 6, "提升全队防御并增加 NP。", _effect("defense_up", 25, 3, "team"), _effect("np_charge", 10, target="team")),
        _skill("军师的指挥 A+", 6, "提升全队攻击并增加 NP。", _effect("attack_up", 25, 3, "team"), _effect("np_charge", 10, target="team")),
    ], "石兵八阵", "A", "all", 0, [_effect("defense_down", 30, 3, "enemy_team"), _effect("stun", 1, 1, "enemy_team")]),
    _servant("hans_caster", "汉斯·克里斯蒂安·安徒生", "Caster", 2, 7800, 720, "BAAAQ", [
        _skill("人类观察 A", 6, "提升全队暴击威力。", _effect("crit_up", 30, 3, "team")),
        _skill("高速咏唱 E", 6, "增加自身 NP。", _effect("np_charge", 50)),
        _skill("无辜的怪物 D", 5, "持续获得暴击星。", _effect("stars_per_turn", 8, 3)),
    ], "为你撰写的故事", "A", "team", 0, [_effect("attack_up", 15, 3, "team"), _effect("defense_up", 15, 3, "team"), _effect("regen", 650, 3, "team")]),
    _servant("jack_assassin", "开膛手杰克", "Assassin", 5, 10300, 1150, "BAQQQ", [
        _skill("雾夜杀人 A", 5, "获得回避并强化 Quick。", _effect("evade", 1), _effect("card_up_q", 30, 1)),
        _skill("情报抹消 B", 6, "解除敌方强化并降低暴击。", _effect("buff_remove", target="enemy"), _effect("crit_down", 25, 3, "enemy")),
        _skill("外科手术 E", 4, "回复一名队友生命。", _effect("heal", 1600, target="ally")),
    ], "解体圣母", "Q", "single", 480, [_effect("stars", 20)]),
    _servant("hundred_faces_assassin", "百貌哈桑", "Assassin", 3, 8800, 880, "BAAQQ", [
        _skill("蔵知的司书 C", 6, "提升 NP 与暴击星获取。", _effect("np_gain_up", 30, 3), _effect("star_gain_up", 30, 3)),
        _skill("专科百般 A+", 6, "强化三色卡。", _effect("card_up_all", 22, 3)),
        _skill("战斗撤退 B", 5, "回复生命并解除弱化。", _effect("heal", 1800), _effect("debuff_cleanse")),
    ], "妄想幻像", "A", "single", 390, [_effect("crit_down", 25, 3, "enemy")]),
    _servant("kojiro_assassin", "佐佐木小次郎", "Assassin", 1, 7600, 810, "BAQQQ", [
        _skill("心眼（伪） A", 5, "获得回避并强化暴击。", _effect("evade", 1), _effect("crit_up", 30, 3)),
        _skill("透化 B+", 5, "解除弱化并获得暴击星。", _effect("debuff_cleanse"), _effect("stars", 12)),
        _skill("宗和的心得 B++", 6, "提升必中与 Quick 性能。", _effect("sure_hit", 1, 3), _effect("card_up_q", 25, 3)),
    ], "燕返", "Q", "single", 430, [_effect("stars", 12)]),
    _servant("heracles_berserker", "赫拉克勒斯", "Berserker", 4, 12000, 1280, "BBBAQ", [
        _skill("勇猛 A+", 5, "提升攻击并抵抗精神弱化。", _effect("attack_up", 30, 3)),
        _skill("心眼（伪） B", 6, "获得回避并强化暴击。", _effect("evade", 1), _effect("crit_up", 25, 3)),
        _skill("战斗续行 A", 7, "获得战续。", _effect("guts", 2600, 4)),
    ], "射杀百头", "B", "single", 500, [_effect("defense_down", 20, 3, "enemy")]),
    _servant("kiyohime_berserker", "清姬", "Berserker", 3, 9300, 1040, "BBAAQ", [
        _skill("变化 C", 5, "提升自身防御力。", _effect("defense_up", 25, 3)),
        _skill("跟踪 B", 5, "降低敌方防御但提升其攻击。", _effect("defense_down", 28, 3, "enemy"), _effect("attack_up", 10, 3, "enemy")),
        _skill("焰色接吻 A", 6, "解除弱化并强化 Buster。", _effect("debuff_cleanse"), _effect("card_up_b", 30, 1)),
    ], "转身火生三昧", "B", "all", 280, [_effect("burn", 450, 3, "enemy_team")]),
    _servant("mash_shielder", "玛修·基列莱特", "Shielder", 4, 13200, 780, "BBAAQ", [
        _skill("誉为雪花之壁", 5, "提升己方全体防御。", _effect("defense_up", 20, 3, "team")),
        _skill("时为朦胧的白垩之壁", 7, "赋予一名队友无敌并增加 NP。", _effect("invincible", 1, target="ally"), _effect("np_charge", 20, target="ally")),
        _skill("决意奋起之盾", 6, "吸引攻击并提升 NP 获取。", _effect("taunt", 1), _effect("np_gain_up", 50, 1)),
    ], "已然遥远的理想之城", "A", "team", 0, [_effect("defense_up", 35, 3, "team"), _effect("damage_cut", 500, 3, "team")]),
    _servant("aesc_savior", "救世主梣", "Caster", 5, 12100, 1190, "BAAAQ", [
        _skill("救世的巡礼 A", 6, "全队攻击力与 NP 获取提升。", _effect("attack_up", 20, 3, "team"), _effect("np_gain_up", 25, 3, "team")),
        _skill("雨之国的记忆 EX", 6, "赋予一名队友无敌并增加 NP。", _effect("invincible", 1, target="ally"), _effect("np_charge", 30, target="ally")),
        _skill("最后的希望", 7, "大幅增加自身 NP，并提升宝具威力。", _effect("np_charge", 50), _effect("np_damage_up", 35, 1)),
    ], "遥远之国，终焉之理想乡", "A", "all", 335, [_effect("defense_up", 25, 3, "team")],
       "此乃通往明日的巡礼——在尽头，仍有希望。"),
    _servant("morgan_queen", "女王摩根", "Berserker", 5, 11600, 1310, "BBAAQ", [
        _skill("渴望的王座 B", 5, "提升自身攻击力并增加 NP。", _effect("attack_up", 30, 3), _effect("np_charge", 30)),
        _skill("湖之加护 C", 6, "增加一名队友 NP，并提升全队 NP 获取。", _effect("np_charge", 25, target="ally"), _effect("np_gain_up", 20, 3, "team")),
        _skill("最果的魅影 A", 6, "降低敌方全体防御，并提升自身宝具威力。", _effect("defense_down", 25, 3, "enemy_team"), _effect("np_damage_up", 30, 1)),
    ], "业已无法抵达的理想乡", "B", "all", 350, [_effect("attack_down", 20, 2, "enemy_team")],
       "跪下吧。此处即是我的不列颠，我的王座。"),
    _servant("draco_beast", "德拉科", "Beast", 5, 10900, 1320, "BBBAQ", [
        _skill("兽之冠冕 EX", 5, "提升自身攻击力并获得暴击星。", _effect("attack_up", 30, 3), _effect("stars", 20)),
        _skill("七丘之火 A", 6, "降低敌方全体防御并附加灼烧。", _effect("defense_down", 20, 3, "enemy_team"), _effect("burn", 700, 3, "enemy_team")),
        _skill("黄金杯的残响", 7, "赋予自身无敌并增加 NP。", _effect("invincible", 1), _effect("np_charge", 40)),
    ], "拥抱罪恶的黄金剧场", "B", "single", 560, [_effect("burn", 1000, 3, "enemy")],
       "喝彩吧，坠落吧——余乃盛宴尽头的兽。"),
    _servant("tiamat_mother", "提亚马特", "AlterEgo", 5, 13600, 1200, "BBAAQ", [
        _skill("生命之海 EX", 5, "回复全队生命并赋予持续回复。", _effect("heal", 2200, target="team"), _effect("regen", 700, 3, "team")),
        _skill("母神的怀抱 A", 6, "提升全队防御并降低敌方全体攻击。", _effect("defense_up", 25, 3, "team"), _effect("attack_down", 20, 3, "enemy_team")),
        _skill("创世的胎动", 7, "增加自身 NP，并获得战斗续行。", _effect("np_charge", 50), _effect("guts", 3200, 4)),
    ], "归来吧，吾之创世之海", "B", "all", 325, [_effect("heal", 1800, target="team")],
       "孩子们，无需恐惧。母亲会拥抱一切。"),
    _servant("artoria_event_saber", "阿尔托莉雅·潘德拉贡〔星冠〕", "Saber", 5, 12400, 1390, "BBAAQ", [
        _skill("星炉全开 EX", 5, "唤醒星之炉心，强化自身 Buster 与宝具威力。", _effect("card_up_b", 45, 2), _effect("np_damage_up", 25, 2)),
        _skill("湖光龙心 A+", 6, "增加自身 NP，并获得一次无敌。", _effect("np_charge", 35), _effect("invincible", 1)),
        _skill("永恒王权 EX", 6, "提升己方全体攻击力与防御力。", _effect("attack_up", 22, 3, "team"), _effect("defense_up", 18, 3, "team")),
    ], "星冠·誓约胜利之剑", "B", "all", 360, [_effect("defense_down", 20, 2, "enemy_team"), _effect("np_charge", 20)],
       "群星汇聚于王冠——此剑将照亮最后的胜利！", event_only=True),
    _servant("castoria_caster", "阿尔托莉雅·卡斯特", "Caster", 5, 12600, 1190, "BAAAQ", [
        _skill("希望的领袖 B", 5, "提升全队攻击力并增加 NP。", _effect("attack_up", 20, 3, "team"), _effect("np_charge", 20, target="team")),
        _skill("湖之加护 A", 6, "增加一名队友 NP，并提升其 NP 获取。", _effect("np_charge", 30, target="ally"), _effect("np_gain_up", 30, 3, "ally")),
        _skill("选定之剑 EX", 6, "强化一名队友的 Arts，并赋予一次无敌。", _effect("card_up_a", 40, 2, "ally"), _effect("invincible", 1, target="ally")),
    ], "环抱你的希望之星", "A", "team", 0, [_effect("invincible", 1, target="team"), _effect("defense_up", 30, 3, "team"), _effect("regen", 900, 3, "team")],
       "即使旅途抵达尽头，愿这颗星仍守护你。", event_only=True),
    _servant("mordred_saber", "莫德雷德", "Saber", 5, 11600, 1320, "BBBAQ", [
        _skill("赤雷魔力放出 B+", 5, "以赤雷强化自身 Buster 与攻击力。", _effect("card_up_b", 40, 1), _effect("attack_up", 20, 2)),
        _skill("隐藏不贞的头盔 EX", 6, "增加自身 NP，并强化暴击。", _effect("np_charge", 30), _effect("crit_up", 35, 3)),
        _skill("叛逆的勋章 A", 6, "提升全队攻击力，并提升自身防御力。", _effect("attack_up", 18, 3, "team"), _effect("defense_up", 15, 3)),
    ], "向端丽吾父发起叛逆", "B", "all", 345, [_effect("defense_down", 20, 2, "enemy_team")],
       "这是对完美之王的叛逆——Clarent Blood Arthur！", event_only=True),
    _servant("gilgamesh_event_archer", "吉尔伽美什〔英雄王〕", "Archer", 5, 11500, 1400, "BBAAQ", [
        _skill("王之财宝 EX", 5, "展开宝库，提升自身攻击力并获得暴击星。", _effect("attack_up", 28, 3), _effect("stars", 20)),
        _skill("黄金律 A+", 6, "提升自身 NP 获取并增加 NP。", _effect("np_gain_up", 45, 3), _effect("np_charge", 25)),
        _skill("天之锁 EX", 6, "束缚一名敌人并降低其防御力。", _effect("stun", 1, 1, "enemy"), _effect("defense_down", 22, 3, "enemy")),
    ], "天地乖离·开辟之星", "B", "all", 370, [_effect("defense_down", 22, 3, "enemy_team")],
       "见识原初的地狱吧——天地乖离，开辟之星！", event_only=True),
    _servant("lord_logres_saber", "领主洛格雷斯", "Saber", 5, 13635, 1588, "BBAAQ", [
        _skill("最后之龙 EX", 8, "五回合内每次行动大量获得 NP，并获得一次弱化无效；龙炉同时持续消耗生命。", _effect("np_per_turn", 35, 5), _effect("debuff_immunity", 1, 5), _effect("hp_loss_per_turn", 700, 5)),
        _skill("王之镜鉴 A", 6, "提升全队攻击与暴击威力，并立即获得大量暴击星。", _effect("attack_up", 25, 3, "team"), _effect("crit_up", 35, 3, "team"), _effect("stars", 30)),
        _skill("伊尼斯·古特灵", 10, "获得两次对肃正防御与强力 Buster 强化，使全队技能冷却缩短；三回合后进入一次湖水之梦。", _effect("solemn_defense", 2, 3), _effect("card_up_b", 50, 3), _effect("cooldown_reduce", 2, target="team"), _effect("delayed_stun", 1, 3)),
    ], "由此，展现誓约胜利之剑", "B", "all", 390, [
        _effect("invincible_pierce", 1, 1, timing="pre"),
        _effect("np_damage_up", 25, 1, timing="pre"),
        _effect("attack_up", 22, 3, "team"),
        _effect("np_charge", 20, target="team"),
        _effect("heal", 2000, target="team"),
    ], "所有誓约在此归于一剑——Excalibur Excelsus！", event_only=True),
    _servant("aesc_final_caster", "救世主梣〔终末巡礼〕", "Caster", 5, 13000, 1480, "BAAAQ", [
        _skill("终末巡礼 EX", 5, "提升全队攻击力，并赋予持续获得 NP 的星之引导。", _effect("attack_up", 25, 3, "team"), _effect("np_per_turn", 15, 3, "team")),
        _skill("雨之国的镜湖 A++", 6, "为一名队友增加 NP、解除弱化并赋予两次无敌。", _effect("np_charge", 40, target="ally"), _effect("debuff_cleanse", target="ally"), _effect("invincible", 2, 3, "ally")),
        _skill("最后的救世之星 EX", 7, "大幅增加自身 NP，强化宝具并获得无敌贯通，同时缩短全队技能冷却。", _effect("np_charge", 70), _effect("np_damage_up", 35, 2), _effect("invincible_pierce", 1, 2), _effect("cooldown_reduce", 1, target="team")),
    ], "雨尽之处·最后的救世之星", "A", "all", 365, [_effect("defense_down", 25, 3, "enemy_team"), _effect("defense_up", 30, 3, "team"), _effect("heal", 1800, target="team")],
       "若巡礼终将结束，就让最后的星替所有人照亮归途。", event_only=True),
    _servant("jeanne_ruler", "贞德〔Ruler〕", "Ruler", 5, 15000, 960, "BAAAQ", [
        _skill("启示 A+", 5, "全队持续获得暴击星，并获得一次弱化无效。", _effect("stars_per_turn", 12, 3, "team"), _effect("debuff_immunity", 1, 3, "team")),
        _skill("神明裁决 A", 6, "眩晕一名敌人，减少其 NP 并降低防御。", _effect("stun", 1, 1, "enemy"), _effect("np_drain", 25, target="enemy"), _effect("defense_down", 20, 3, "enemy")),
        _skill("圣旗守护 EX", 7, "解除全队弱化，并赋予无敌与防御提升。", _effect("debuff_cleanse", target="team"), _effect("invincible", 1, 1, "team"), _effect("defense_up", 25, 3, "team")),
    ], "吾主在此·永恒光辉", "A", "team", 0, [_effect("solemn_defense", 1, 2, "team"), _effect("defense_up", 30, 3, "team"), _effect("regen", 1000, 3, "team"), _effect("heal", 2500, target="team")],
       "此旗聚集所有祈愿——吾主在此，永恒光辉！", event_only=True),
    _servant("merlin_caster", "梅林", "Caster", 5, 13200, 1050, "BAAAQ", [
        _skill("梦幻的领袖气质 EX", 5, "提升全队攻击力并增加 NP。", _effect("attack_up", 25, 3, "team"), _effect("np_charge", 20, target="team")),
        _skill("幻术 A", 7, "赋予全队无敌，并降低敌方全体暴击威力。", _effect("invincible", 1, 1, "team"), _effect("crit_down", 35, 3, "enemy_team")),
        _skill("英雄塑造 EX", 6, "大幅强化一名队友的 Buster 与暴击威力，并回复生命。", _effect("card_up_b", 50, 3, "ally"), _effect("crit_up", 50, 3, "ally"), _effect("heal", 3000, target="ally")),
    ], "永世隔绝的理想乡", "A", "team", 0, [_effect("regen", 1200, 5, "team"), _effect("np_per_turn", 15, 5, "team"), _effect("stars_per_turn", 10, 5, "team")],
       "那里无罪亦无悲——开启吧，永世隔绝的理想乡。", event_only=True),
    _servant("ishtar_archer", "伊什塔尔", "Archer", 5, 11800, 1500, "BBAAQ", [
        _skill("闪耀的水之冠 A", 5, "大幅增加自身 NP，并强化 Buster。", _effect("np_charge", 50), _effect("card_up_b", 35, 2)),
        _skill("美之显现 EX", 6, "提升全队攻击与暴击威力，并获得暴击星。", _effect("attack_up", 22, 3, "team"), _effect("crit_up", 35, 3, "team"), _effect("stars", 25)),
        _skill("维纳斯驱动 EX", 6, "获得无敌贯通、宝具威力与速度提升。", _effect("invincible_pierce", 1, 3), _effect("np_damage_up", 35, 2), _effect("speed_up", 20, 3)),
    ], "山脉震撼明星之薪", "B", "all", 385, [_effect("np_damage_up", 20, 1, timing="pre"), _effect("defense_down", 25, 3, "enemy_team")],
       "从金星到冥界，全都给我贯穿——An Gal Ta Kigal！", event_only=True),
    _servant("ereshkigal_lancer", "艾蕾什基伽尔", "Lancer", 5, 14000, 1320, "BBAAQ", [
        _skill("冥界之冠 EX", 6, "增加自身 NP，并获得一次无敌。", _effect("np_charge", 50), _effect("invincible", 1, 2)),
        _skill("冥界守护 A+", 6, "提升全队攻击与防御，并赋予持续回复。", _effect("attack_up", 20, 3, "team"), _effect("defense_up", 30, 3, "team"), _effect("regen", 800, 3, "team")),
        _skill("秘藏的大王冠 A", 7, "全队获得弱化无效、持续 NP 与速度提升。", _effect("debuff_immunity", 1, 3, "team"), _effect("np_per_turn", 10, 3, "team"), _effect("speed_up", 15, 3, "team")),
    ], "灵峰踏抱冥府之鞴", "B", "all", 360, [_effect("heal", 1800, target="team"), _effect("defense_up", 25, 3, "team"), _effect("attack_down", 20, 3, "enemy_team")],
       "冥界并非终点——Kur Kigal Irkalla，拥抱他们吧！", event_only=True),
    _servant("aesc_rainwitch_caster", "救世主梣〔雨之魔女〕", "Caster", 5, 14500, 1520, "BAAAQ", [
        _skill("巡礼之始 EX", 5, "提升全队攻击力并持续获得 NP，同时获得一次弱化无效。", _effect("attack_up", 30, 3, "team"), _effect("np_per_turn", 20, 3, "team"), _effect("debuff_immunity", 1, 3, "team")),
        _skill("雨之国的守护者 A++", 6, "为一名队友回复生命、增加 NP，并赋予持续整轮的无敌。", _effect("heal", 3000, target="ally"), _effect("np_charge", 40, target="ally"), _effect("invincible", 1, 1, "ally")),
        _skill("救世的尽头 EX", 7, "大幅增加自身 NP，获得无敌贯通，并缩短全队技能冷却。", _effect("np_charge", 80), _effect("invincible_pierce", 1, 2), _effect("np_damage_up", 40, 2), _effect("cooldown_reduce", 1, target="team")),
    ], "雨之国·未竟的救世巡礼", "A", "all", 390, [_effect("defense_down", 30, 3, "enemy_team"), _effect("solemn_defense", 1, 2, "team"), _effect("heal", 2200, target="team")],
       "雨会停下，而巡礼不会——让最后的钟声引领未来。", event_only=True),
    _servant("medusa_anime_rider", "美杜莎〔第五次圣杯战争〕", "Rider", 5, 11800, 1420, "BAQQQ", [
        _skill("石化之魔眼 A+", 5, "封锁一名敌人并大幅降低其防御。", _effect("stun", 1, 1, "enemy"), _effect("defense_down", 30, 3, "enemy")),
        _skill("神性怪力 A", 5, "大幅强化 Quick、速度与暴击威力。", _effect("card_up_q", 50, 3), _effect("speed_up", 25, 3), _effect("crit_up", 50, 3)),
        _skill("鲜血神殿 EX", 6, "增加 NP 与暴击星，并获得持续整轮的无敌。", _effect("np_charge", 40), _effect("stars", 30), _effect("invincible", 1, 1)),
    ], "骑英之缰绳·贝勒罗丰", "Q", "single", 600, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("quick_resist_down", 30, 3, "enemy")],
       "解放缰绳——以天马之光粉碎一切，Bellerophon！", event_only=True),
    _servant("artoria_avalon_saber", "阿尔托莉雅〔遥远理想乡〕", "Saber", 5, 14800, 1680, "BBAAQ", [
        _skill("遥远的理想乡 EX", 7, "吸引敌方攻击，提升防御，并在整轮内将所受伤害完全反射给攻击者。", _effect("taunt", 1, 1), _effect("defense_up", 40, 1), _effect("damage_reflect", 100, 1)),
        _skill("星之圣剑炉心 EX", 5, "增加 NP，大幅强化 Buster，并获得无敌贯通。", _effect("np_charge", 50), _effect("card_up_b", 50, 3), _effect("invincible_pierce", 1, 2)),
        _skill("王之终裁 A++", 7, "处决生命低于 35% 的一名敌人，并强化自身攻击。", _effect("execute", 35, target="enemy"), _effect("attack_up", 30, 3)),
    ], "阿瓦隆·誓约胜利之剑", "B", "all", 430, [_effect("np_damage_up", 30, 1, timing="pre"), _effect("defense_down", 25, 3, "enemy_team")],
       "此剑连接理想乡——于终焉归还胜利，Excalibur Avalon！", event_only=True),
    _servant("gilgamesh_golden_archer", "吉尔伽美什〔黄金之王〕", "Archer", 5, 12700, 1710, "BBAAQ", [
        _skill("王之财宝·全门开放 EX", 5, "大幅提升攻击与暴击威力，并获得大量暴击星。", _effect("attack_up", 35, 3), _effect("crit_up", 50, 3), _effect("stars", 30)),
        _skill("黄金律·原典 A++", 5, "大量增加 NP，强化宝具并获得无敌贯通。", _effect("np_charge", 50), _effect("np_damage_up", 40, 2), _effect("invincible_pierce", 1, 2)),
        _skill("天之锁·神性拘束 EX", 6, "眩晕一名敌人，减少其 NP 并降低防御。", _effect("stun", 1, 1, "enemy"), _effect("np_drain", 30, target="enemy"), _effect("defense_down", 30, 3, "enemy")),
    ], "天地乖离·开辟之星〔原典〕", "B", "all", 430, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 30, 3, "enemy_team")],
       "认清王与臣的差距吧——天地乖离，开辟之星！", event_only=True),
    _servant("ishtar_rin_archer", "伊什塔尔〔远坂凛〕", "Archer", 5, 12500, 1600, "BBAAQ", [
        _skill("辉冠的魔术回路 EX", 5, "大量增加 NP，并强化 Buster 与攻击力。", _effect("np_charge", 60), _effect("card_up_b", 45, 3), _effect("attack_up", 25, 3)),
        _skill("金星女神的显现 A++", 6, "强化全队攻击与暴击威力，并获得大量暴击星。", _effect("attack_up", 25, 3, "team"), _effect("crit_up", 45, 3, "team"), _effect("stars", 30)),
        _skill("马安娜全速驱动 EX", 5, "提升速度、宝具威力并获得无敌贯通。", _effect("speed_up", 30, 3), _effect("np_damage_up", 40, 2), _effect("invincible_pierce", 1, 3)),
    ], "山脉震撼明星之薪·金星", "B", "all", 410, [_effect("np_damage_up", 25, 1, timing="pre"), _effect("defense_down", 28, 3, "enemy_team")],
       "看好了，这就是女神与远坂凛的全力——An Gal Ta Kigal！", event_only=True),
    _servant("gilgamesh_uruk_caster", "吉尔伽美什〔贤王〕", "Caster", 5, 15000, 1430, "BAAAQ", [
        _skill("魔杖支配者 EX", 5, "提升全队 Arts、攻击力与 NP 获取。", _effect("card_up_a", 35, 3, "team"), _effect("attack_up", 25, 3, "team"), _effect("np_gain_up", 30, 3, "team")),
        _skill("乌鲁克城塞 A++", 6, "提升全队防御并赋予两次弱化无效。", _effect("defense_up", 35, 3, "team"), _effect("debuff_immunity", 2, 3, "team"), _effect("damage_cut", 800, 3, "team")),
        _skill("王之号令 EX", 6, "回复全队生命、增加 NP，并缩短技能冷却。", _effect("heal", 2200, target="team"), _effect("np_charge", 25, target="team"), _effect("cooldown_reduce", 1, target="team")),
    ], "王之号炮·梅拉姆丁基拉", "A", "all", 370, [_effect("defense_down", 28, 3, "enemy_team"), _effect("np_charge", 20, target="team"), _effect("stars_per_turn", 12, 3, "team")],
       "乌鲁克仍在此处！仰望王之号炮——Melammu Dingir！", event_only=True),
    _servant("astraea_ruler", "阿斯特莱雅〔金钻头〕", "Ruler", 5, 14200, 1560, "BBAAQ", [
        _skill("天秤的裁定 A+", 5, "提升攻击和暴击威力，并获得暴击星。", _effect("attack_up", 30, 3), _effect("crit_up", 50, 3), _effect("stars", 25)),
        _skill("贵族淑女的援护 EX", 6, "为一名队友解除弱化、回复生命并赋予持续整轮的无敌。", _effect("debuff_cleanse", target="ally"), _effect("heal", 3000, target="ally"), _effect("invincible", 1, 1, "ally")),
        _skill("金钻头处刑式 EX", 6, "大幅降低一名敌人的防御；生命低于 25% 时将其处决。", _effect("defense_down", 35, 3, "enemy"), _effect("execute", 25, target="enemy")),
    ], "裁决之时已至·库斯蒂提亚", "A", "single", 620, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("attack_down", 30, 3, "enemy")],
       "以星之天秤宣告裁决——接受淑女的最后一击吧！", event_only=True),
    _servant("artoria_crowned_avalon_saber", "阿尔托莉雅〔星冠阿瓦隆〕", "Saber", 6, 16800, 1980, "BBAAQ", [
        _skill("阿瓦隆的星冠 EX", 5, "己方全体获得整轮无敌、攻击强化与弱化无效。", _effect("invincible", 1, 1, "team"), _effect("attack_up", 32, 2, "team"), _effect("debuff_immunity", 2, 3, "team")),
        _skill("圣剑炉心·无限 A++", 5, "获得 80% NP、无敌贯通与极高宝具威力。", _effect("np_charge", 80), _effect("invincible_pierce", 1, 2), _effect("np_damage_up", 55, 2)),
        _skill("终焉裁定 EX", 6, "降低一名敌人的防御；生命不高于 45% 时立即处决。", _effect("defense_down", 40, 3, "enemy"), _effect("execute", 45, target="enemy")),
    ], "星之王冠·终焉阿瓦隆", "B", "all", 520, [_effect("np_damage_up", 35, 1, timing="pre"), _effect("invincible_pierce", 1, 1, timing="pre"), _effect("damage_reflect", 100, 1, "team")],
       "群星为冠，理想乡为鞘——让终焉也向胜利俯首！", event_only=True, passives=[
           _passive("理想乡的守护", "开战时获得两次弱化无效、20% NP 与永久 25% 伤害反射。", _effect("debuff_immunity", 2, 99), _effect("np_charge", 20), _effect("damage_reflect", 25, 99)),
       ]),
    _servant("aesc_genesis_caster", "救世主梣〔创世巡礼〕", "Caster", 6, 17400, 1900, "BAAAQ", [
        _skill("创世巡礼 EX", 5, "己方全体获得攻击、Arts、NP 获取强化与每次行动 NP。", _effect("attack_up", 30, 3, "team"), _effect("card_up_a", 45, 3, "team"), _effect("np_gain_up", 40, 3, "team"), _effect("np_per_turn", 12, 3, "team")),
        _skill("最后的雨之国 EX", 6, "回复全队生命，解除弱化并赋予两次对肃正防御。", _effect("heal", 3600, target="team"), _effect("debuff_cleanse", target="team"), _effect("solemn_defense", 2, 2, "team")),
        _skill("救世主的钟声 EX", 6, "全队增加 NP、缩短冷却，并使敌方全体速度下降。", _effect("np_charge", 35, target="team"), _effect("cooldown_reduce", 1, target="team"), _effect("speed_down", 20, 3, "enemy_team")),
    ], "创世之雨·十二钟巡礼", "A", "all", 460, [_effect("defense_down", 35, 3, "enemy_team", timing="pre"), _effect("heal", 2500, target="team"), _effect("invincible", 1, 1, "team")],
       "十二道钟声将雨化作星——这一次，巡礼会抵达幸福的明日。", event_only=True, passives=[
           _passive("救世主的旅途", "开战时全队获得持续 NP 与一次弱化无效。", _effect("np_per_turn", 8, 99, "team"), _effect("debuff_immunity", 1, 99, "team")),
       ]),
    _servant("oberon_vortigern_pretender", "奥伯龙·沃提根〔奈落之虫〕", "Pretender", 6, 16100, 2020, "BBAAQ", [
        _skill("夜之帷幕 EX", 5, "全队增加 NP 并提升宝具威力，敌方全体攻击下降。", _effect("np_charge", 30, target="team"), _effect("np_damage_up", 45, 3, "team"), _effect("attack_down", 20, 3, "enemy_team")),
        _skill("朝之云雀 EX", 5, "获得大量 NP 与暴击星，并提升暴击率。", _effect("np_charge", 70), _effect("stars", 35), _effect("crit_chance_up", 35, 2)),
        _skill("梦之终结 EX", 7, "极大强化自身攻击与宝具，并赋予无敌贯通；行动后承受代价。", _effect("attack_up", 60, 1), _effect("np_damage_up", 80, 1), _effect("invincible_pierce", 1, 1), _effect("hp_loss_per_turn", 2500, 1)),
    ], "彼方坠落之梦·沃提根", "B", "all", 540, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("delayed_stun", 1, 1, "enemy_team"), _effect("np_drain", 30, target="enemy_team")],
       "童话已经闭幕——坠入连梦也无法抵达的奈落吧。", event_only=True, passives=[
           _passive("反人理 D", "开战时削弱敌方全体攻击，并获得精神弱化无效。", _effect("attack_down", 12, 99, "enemy_team"), _effect("debuff_immunity", 2, 99)),
       ]),
    _servant("space_ishtar_origin_avenger", "太空伊什塔尔〔阿斯塔蒂·起源〕", "Avenger", 6, 16500, 2050, "BBAAQ", [
        _skill("恶之半身·阿斯塔蒂 EX", 5, "大幅强化攻击、暴击率与暴击威力，并获得暴击星。", _effect("attack_up", 45, 3), _effect("crit_chance_up", 40, 3), _effect("crit_up", 70, 3), _effect("stars", 40)),
        _skill("女神的星际航路 A++", 5, "全队增加 NP 与速度，并赋予无敌贯通。", _effect("np_charge", 35, target="team"), _effect("speed_up", 22, 3, "team"), _effect("invincible_pierce", 1, 2, "team")),
        _skill("银河灵基 EX", 6, "获得整轮无敌、回复生命，并立刻充满 NP。", _effect("invincible", 1, 1), _effect("heal", 4200), _effect("np_charge", 100)),
    ], "原始宇宙·伊甸休格拉奎萨", "A", "all", 560, [_effect("np_damage_up", 45, 1, timing="pre"), _effect("defense_down", 35, 3, "enemy_team"), _effect("stars", 30, target="team")],
       "善与恶皆归于银河——见证原始女神的宇宙吧！", event_only=True, passives=[
           _passive("银河女神的灵核", "开战时获得 30% NP、25 颗星与永久暴击强化。", _effect("np_charge", 30), _effect("stars", 25), _effect("crit_chance_up", 20, 99), _effect("crit_up", 35, 99)),
       ]),
    _servant("artoria_azure_star_saber", "阿尔托莉雅〔苍星圣王〕", "Saber", 6, 17400, 2080, "BBAAQ", [
        _skill("苍星王权 EX", 5, "强化全队攻击与三色性能，并获得暴击星。", _effect("attack_up", 32, 3, "team"), _effect("card_up_all", 25, 3, "team"), _effect("stars", 28, target="team")),
        _skill("圣剑返照·阿瓦隆 EX", 6, "吸引敌方攻击，获得整轮无敌，并将所受伤害完全反射。", _effect("taunt", 1, 1), _effect("invincible", 1, 1), _effect("damage_reflect", 100, 1)),
        _skill("苍白龙炉心 A++", 5, "大量增加 NP，强化宝具与暴击威力，并获得无敌贯通。", _effect("np_charge", 80), _effect("np_damage_up", 55, 2), _effect("crit_up", 60, 3), _effect("invincible_pierce", 1, 2)),
    ], "苍星圣剑·理想乡的终光", "B", "all", 550, [_effect("np_damage_up", 35, 1, timing="pre"), _effect("invincible_pierce", 1, 1, timing="pre"), _effect("solemn_defense", 1, 1, "team")],
       "苍星为冠，白龙为证——于理想乡尽头，解放圣剑！", event_only=True, passives=[
           _passive("白龙王的星核", "开战时获得 25% NP、一次弱化无效与永久 18% 伤害反射。", _effect("np_charge", 25), _effect("debuff_immunity", 1, 99), _effect("damage_reflect", 18, 99)),
       ]),
    _servant("ciel_executor_mooncancer", "谜之代行者 C.I.E.L", "MoonCancer", 6, 16800, 2090, "BBAQQ", [
        _skill("第七圣典·展开 EX", 5, "提升攻击、暴击率与暴击威力，并获得暴击星。", _effect("attack_up", 38, 3), _effect("crit_chance_up", 35, 3), _effect("crit_up", 65, 3), _effect("stars", 32)),
        _skill("不死狩猎者 A++", 6, "获得整轮无敌、持续恢复与弱化无效。", _effect("invincible", 1, 1), _effect("regen", 1200, 3), _effect("debuff_immunity", 2, 3)),
        _skill("黑键埋葬式 EX", 5, "降低一名敌人的防御与速度，并增加自身 NP。", _effect("defense_down", 38, 3, "enemy"), _effect("speed_down", 28, 3, "enemy"), _effect("np_charge", 55)),
    ], "卡尔瓦利亚之星·断罪", "B", "single", 720, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("buff_remove", target="enemy", timing="pre"), _effect("execute", 30, target="enemy")],
       "代行结束——让卡尔瓦利亚之星在此完成最终断罪！", event_only=True, passives=[
           _passive("不死者处刑机关", "开战时获得 20% NP、两次弱化无效与永久暴击强化。", _effect("np_charge", 20), _effect("debuff_immunity", 2, 99), _effect("crit_up", 30, 99)),
       ]),
    _servant("archetype_earth_princess_mooncancer", "公主〔Archetype: Earth〕", "MoonCancer", 6, 18000, 2070, "BAAAQ", [
        _skill("千年城显现 EX", 6, "强化全队攻防、回复生命并增加 NP。", _effect("attack_up", 28, 3, "team"), _effect("defense_up", 30, 3, "team"), _effect("heal", 2600, target="team"), _effect("np_charge", 25, target="team")),
        _skill("星球的吐息 EX", 5, "提升三色性能、NP 获取与速度，并持续获得 NP。", _effect("card_up_all", 38, 3), _effect("np_gain_up", 45, 3), _effect("speed_up", 25, 3), _effect("np_per_turn", 15, 3)),
        _skill("空想具现化 A++", 6, "解除敌方全体强化，降低防御与攻击。", _effect("buff_remove", target="enemy_team"), _effect("defense_down", 35, 3, "enemy_team"), _effect("attack_down", 25, 3, "enemy_team")),
    ], "千年城·月之王庭", "A", "all", 525, [_effect("defense_down", 35, 3, "enemy_team", timing="pre"), _effect("heal", 3000, target="team"), _effect("invincible", 1, 1, "team")],
       "月之王庭已经降临——于千年城中，见证星球的梦。", event_only=True, passives=[
           _passive("真祖之姬", "开战时全队获得持续恢复，自己获得 30% NP。", _effect("regen", 500, 99, "team"), _effect("np_charge", 30)),
       ]),
    _servant("arcueid_lunar_berserker", "爱尔奎特〔月下真祖〕", "Berserker", 6, 17000, 2110, "BBBQQ", [
        _skill("真祖冲动 EX", 5, "大幅强化攻击、Buster 与暴击率，并获得暴击星。", _effect("attack_up", 45, 3), _effect("card_up_b", 45, 3), _effect("crit_chance_up", 40, 3), _effect("stars", 35)),
        _skill("月下再生 A++", 6, "回复生命，解除弱化，并获得整轮无敌与持续恢复。", _effect("heal", 4200), _effect("debuff_cleanse"), _effect("invincible", 1, 1), _effect("regen", 1100, 3)),
        _skill("红月疾走 EX", 5, "提升速度、暴击威力与宝具威力，并获得无敌贯通。", _effect("speed_up", 35, 3), _effect("crit_up", 75, 3), _effect("np_damage_up", 50, 2), _effect("invincible_pierce", 1, 2)),
    ], "幻想血统·红月爪痕", "B", "single", 750, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 40, 3, "enemy"), _effect("heal", 1800)],
       "抓到你了——就用这轮红月，把一切撕开！", event_only=True, passives=[
           _passive("月之生命", "开战时获得永久再生、速度与暴击率强化。", _effect("regen", 650, 99), _effect("speed_up", 12, 99), _effect("crit_chance_up", 18, 99)),
       ]),
    _servant("aoko_fifth_magic_foreigner", "苍崎青子〔第五魔法〕", "Foreigner", 6, 16600, 2100, "BBAAQ", [
        _skill("第五魔法 EX", 6, "大量增加 NP，强化宝具并缩短技能冷却。", _effect("np_charge", 100), _effect("np_damage_up", 60, 2), _effect("cooldown_reduce", 1)),
        _skill("魔弹星群 A++", 5, "提升攻击与暴击率，并获得大量暴击星。", _effect("attack_up", 38, 3), _effect("crit_chance_up", 38, 3), _effect("crit_up", 55, 3), _effect("stars", 36)),
        _skill("时间加速·逆行 EX", 6, "提升全队速度与 NP 获取，并使敌方全体速度下降。", _effect("speed_up", 30, 3, "team"), _effect("np_gain_up", 35, 3, "team"), _effect("speed_down", 28, 3, "enemy_team")),
    ], "逆行银河·第五魔法", "A", "all", 560, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("np_drain", 30, target="enemy_team"), _effect("np_charge", 25, target="team")],
       "过去与未来都让开——这就是只属于现在的第五魔法！", event_only=True, passives=[
           _passive("魔法使之夜", "开战时获得 30% NP、一次回避与永久 Arts 强化。", _effect("np_charge", 30), _effect("evade", 1, 99), _effect("card_up_a", 20, 99)),
       ]),
    _servant("ryougi_shiki_void_assassin", "两仪式〔空之境界〕", "Assassin", 6, 16000, 2060, "BAAQQ", [
        _skill("直死之魔眼 EX", 5, "获得无敌贯通，降低一名敌人的防御，并提升处决线。", _effect("invincible_pierce", 1, 3), _effect("defense_down", 42, 3, "enemy"), _effect("execute", 32, target="enemy")),
        _skill("自我暗示 A++", 5, "解除弱化，提升攻击、暴击率与速度。", _effect("debuff_cleanse"), _effect("attack_up", 38, 3), _effect("crit_chance_up", 40, 3), _effect("speed_up", 30, 3)),
        _skill("境界切断 EX", 6, "大量增加 NP，强化 Arts 与宝具，并获得回避。", _effect("np_charge", 70), _effect("card_up_a", 45, 3), _effect("np_damage_up", 50, 2), _effect("evade", 2, 2)),
    ], "无垢识·空境一刀", "A", "single", 780, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("buff_remove", target="enemy", timing="pre"), _effect("execute", 42, target="enemy")],
       "若万物都有终点——那条线，我已经看见了。", event_only=True, passives=[
           _passive("根源接续", "开战时获得 25% NP、两次弱化无效与永久暴击威力强化。", _effect("np_charge", 25), _effect("debuff_immunity", 2, 99), _effect("crit_up", 35, 99)),
       ]),
    _servant("alice_kuonji_fairy_caster", "久远寺有珠〔童话魔女〕", "Caster", 6, 17200, 2040, "BAAAQ", [
        _skill("桥之巨人·PLOY EX", 6, "布置童话结界，削弱敌方全体攻防与速度。", _effect("attack_down", 28, 3, "enemy_team"), _effect("defense_down", 30, 3, "enemy_team"), _effect("speed_down", 22, 3, "enemy_team")),
        _skill("月夜之钟 A++", 5, "增加全队 NP 与防御，并获得一次肃正防御。", _effect("np_charge", 30, target="team"), _effect("defense_up", 28, 3, "team"), _effect("solemn_defense", 1, 1, "team")),
        _skill("三咲町的童话 EX", 6, "获得大量 NP 与整轮无敌，并使敌方延迟眩晕。", _effect("np_charge", 80), _effect("invincible", 1, 1), _effect("delayed_stun", 1, 1, "enemy_team")),
    ], "童话终夜·蔷薇猎犬", "A", "all", 535, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("np_drain", 35, target="enemy_team"), _effect("defense_up", 30, 3, "team")],
       "月夜的童话已合上书页——那么，请在钟声里安眠。", event_only=True, passives=[
           _passive("纯血魔女", "开战时获得 35% NP，全队获得持续 NP 与弱化耐性。", _effect("np_charge", 35), _effect("np_per_turn", 8, 99, "team"), _effect("debuff_immunity", 1, 99, "team")),
       ]),
    _servant("rin_jewel_mage_caster", "远坂凛〔宝石魔术〕", "Caster", 6, 16400, 2100, "BBAAQ", [
        _skill("百年宝石仓 EX", 5, "提升攻击、暴击率与暴击威力，并获得大量暴击星。", _effect("attack_up", 40, 3), _effect("crit_chance_up", 42, 3), _effect("crit_up", 70, 3), _effect("stars", 40)),
        _skill("五大元素·转换 A++", 5, "强化全队三色性能与 NP 获取，并增加 NP。", _effect("card_up_all", 28, 3, "team"), _effect("np_gain_up", 35, 3, "team"), _effect("np_charge", 25, target="team")),
        _skill("第二法残片 EX", 6, "大量增加自身 NP，获得整轮无敌与无敌贯通。", _effect("np_charge", 85), _effect("invincible", 1, 1), _effect("invincible_pierce", 1, 2)),
    ], "万华镜宝石·极光天枪", "B", "single", 735, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 38, 3, "enemy"), _effect("stars", 30, target="team")],
       "倾尽百年的光吧——这一击可贵得足够买下一座城！", event_only=True, passives=[
           _passive("名门的矜持", "开战时获得 25% NP、20 颗星与永久暴击率强化。", _effect("np_charge", 25), _effect("stars", 20), _effect("crit_chance_up", 18, 99)),
       ]),
    _servant("sakura_black_grail_avenger", "间桐樱〔黑圣杯〕", "Avenger", 6, 17800, 2130, "BBAAQ", [
        _skill("此世全部之恶 EX", 6, "降低敌方全体攻防并附加高额诅咒般灼烧。", _effect("attack_down", 32, 3, "enemy_team"), _effect("defense_down", 36, 3, "enemy_team"), _effect("burn", 1200, 3, "enemy_team")),
        _skill("影之吞噬 A++", 5, "吸取敌方全体 NP，增加自身 NP 并回复生命。", _effect("np_drain", 30, target="enemy_team"), _effect("np_charge", 70), _effect("heal", 3200)),
        _skill("黑圣杯显现 EX", 6, "获得整轮无敌、无敌贯通与强力宝具强化。", _effect("invincible", 1, 1), _effect("invincible_pierce", 1, 2), _effect("np_damage_up", 65, 2)),
    ], "天之杯·虚数蚀界", "A", "all", 570, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("defense_down", 40, 3, "enemy_team"), _effect("heal", 2800)],
       "如果世界只会伤害所爱之人——那就由影子把一切带走。", event_only=True, passives=[
           _passive("黑之圣杯", "开战时获得 30% NP、永久攻击强化与持续恢复。", _effect("np_charge", 30), _effect("attack_up", 15, 99), _effect("regen", 700, 99)),
       ]),
    _servant("jeanne_alter_dragon_avenger", "贞德·Alter〔龙之魔女〕", "Avenger", 6, 16600, 2150, "BBBAQ", [
        _skill("龙之魔女 EX", 5, "强化全队攻击与暴击威力，自身额外获得暴击率。", _effect("attack_up", 32, 3, "team"), _effect("crit_up", 45, 3, "team"), _effect("crit_chance_up", 38, 3)),
        _skill("泡沫般的梦 A++", 6, "获得整轮无敌并大幅强化攻击，回合后付出生命代价。", _effect("invincible", 1, 1), _effect("attack_up", 55, 1), _effect("hp_loss_per_turn", 1800, 1)),
        _skill("漆黑的憎恶 EX", 5, "增加 NP 与暴击星，降低敌方全体防御。", _effect("np_charge", 65), _effect("stars", 36), _effect("defense_down", 35, 3, "enemy_team")),
    ], "咆哮吧，吾之愤怒", "B", "all", 585, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("burn", 1400, 3, "enemy_team"), _effect("attack_down", 25, 3, "enemy_team")],
       "此身为憎恶所铸——咆哮吧，连同世界一起燃尽！", event_only=True, passives=[
           _passive("复仇的龙焰", "开战时获得 25% NP、25 颗星与永久 Buster 强化。", _effect("np_charge", 25), _effect("stars", 25), _effect("card_up_b", 22, 99)),
       ]),
    _servant("kama_assassin", "迦摩", "Assassin", 5, 11200, 1280, "BAQQQ", [
        _skill("女神的恩惠 B", 5, "回复生命、增加 NP，并提升弱化耐性。", _effect("heal", 1800), _effect("np_charge", 25), _effect("debuff_immunity", 1, 3)),
        _skill("无形之爱 A", 6, "降低一名敌人的防御与暴击率，并附加延迟眩晕。", _effect("defense_down", 28, 3, "enemy"), _effect("crit_chance_down", 25, 3, "enemy"), _effect("delayed_stun", 1, 1, "enemy")),
        _skill("魔罗之花 EX", 6, "强化 Quick、攻击与暴击威力，并获得暴击星。", _effect("card_up_q", 38, 3), _effect("attack_up", 25, 3), _effect("crit_up", 45, 3), _effect("stars", 20)),
    ], "爱神之花箭", "Q", "single", 550, [_effect("defense_down", 25, 3, "enemy"), _effect("np_drain", 25, target="enemy")],
       "无论逃到哪里，爱都会找到你——燃烧吧，魔罗之花。", passives=[
           _passive("爱欲之神", "开战时获得 15% NP，并永久提升暴击率。", _effect("np_charge", 15), _effect("crit_chance_up", 15, 99)),
       ]),
    _servant("senji_muramasa_saber", "千子村正", "Saber", 5, 11800, 1310, "BBAAQ", [
        _skill("业之目 A", 5, "强化暴击率、暴击威力与无敌贯通。", _effect("crit_chance_up", 32, 3), _effect("crit_up", 45, 3), _effect("invincible_pierce", 1, 2)),
        _skill("焰 EX", 6, "增加 NP，并强化 Arts 与宝具威力。", _effect("np_charge", 40), _effect("card_up_a", 35, 3), _effect("np_damage_up", 30, 2)),
        _skill("锻冶神髓 A+", 6, "提升全队攻击与 NP 获取，缩短自身技能冷却。", _effect("attack_up", 20, 3, "team"), _effect("np_gain_up", 22, 3, "team"), _effect("cooldown_reduce", 1)),
    ], "无元之剑制", "A", "all", 390, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 22, 3, "enemy_team")],
       "此身只为锻成一刀——斩断宿业，无元之剑制！", passives=[
           _passive("刀匠的执念", "永久提升 Arts 与攻击力。", _effect("card_up_a", 12, 99), _effect("attack_up", 8, 99)),
       ]),
    _servant("ryougi_shiki_assassin", "两仪式", "Assassin", 5, 10800, 1270, "BAAQQ", [
        _skill("直死之魔眼 A", 5, "获得无敌贯通并降低一名敌人的防御。", _effect("invincible_pierce", 1, 3), _effect("defense_down", 30, 3, "enemy")),
        _skill("心眼（伪） A", 6, "获得回避并提升暴击威力与速度。", _effect("evade", 2, 2), _effect("crit_up", 40, 3), _effect("speed_up", 18, 3)),
        _skill("阴阳鱼 B", 5, "回复生命并增加 NP，但短暂降低防御。", _effect("heal", 2200), _effect("np_charge", 35), _effect("defense_down", 10, 1)),
    ], "唯识·直死之魔眼", "A", "single", 560, [_effect("buff_remove", target="enemy", timing="pre"), _effect("execute", 22, target="enemy")],
       "活着的东西，就算是神也杀给你看。", passives=[
           _passive("境界感知", "开战时获得 12% NP 与永久暴击率强化。", _effect("np_charge", 12), _effect("crit_chance_up", 12, 99)),
       ]),
    _servant("olga_marie_foreigner", "奥尔加玛丽", "Foreigner", 5, 12600, 1200, "BAAAQ", [
        _skill("天体科君主 A", 6, "提升全队攻击与 NP 获取。", _effect("attack_up", 20, 3, "team"), _effect("np_gain_up", 25, 3, "team")),
        _skill("迦勒底亚斯观测 EX", 6, "增加全队 NP，并降低敌方全体攻击。", _effect("np_charge", 20, target="team"), _effect("attack_down", 22, 3, "enemy_team")),
        _skill("所长的矜持 A+", 7, "赋予全队整轮无敌并回复生命。", _effect("invincible", 1, 1, "team"), _effect("heal", 1800, target="team")),
    ], "天球演算·阿尼姆斯菲亚", "A", "all", 350, [_effect("defense_down", 25, 3, "enemy_team"), _effect("np_charge", 20, target="team")],
       "观测完成——以阿尼姆斯菲亚之名，展开天球演算！", passives=[
           _passive("灵子观测者", "开战时全队获得 10% NP 与一次弱化无效。", _effect("np_charge", 10, target="team"), _effect("debuff_immunity", 1, 99, "team")),
       ]),
    _servant("scathach_skadi_caster", "斯卡哈·斯卡蒂", "Caster", 5, 12300, 1230, "BAAAQ", [
        _skill("原初之卢恩·冰 A+", 5, "强化一名队友的 Quick、暴击率与暴击威力。", _effect("card_up_q", 42, 3, "ally"), _effect("crit_chance_up", 28, 3, "ally"), _effect("crit_up", 48, 3, "ally")),
        _skill("冻土领域 EX", 6, "降低敌方全体防御与速度，并削减 NP。", _effect("defense_down", 28, 3, "enemy_team"), _effect("speed_down", 20, 3, "enemy_team"), _effect("np_drain", 20, target="enemy_team")),
        _skill("大神的睿智 B+", 6, "大幅增加一名队友 NP，并赋予一次弱化无效。", _effect("np_charge", 50, target="ally"), _effect("debuff_immunity", 1, 3, "ally")),
    ], "通往死亡满溢的魔境之门", "Q", "team", 0, [_effect("attack_up", 25, 3, "team"), _effect("crit_up", 45, 3, "team"), _effect("evade", 1, 1, "team")],
       "冰雪会为勇士让路——开启吧，通往魔境的门！", passives=[
           _passive("北境女王", "开战时全队获得 10% NP，自身永久提升 Arts 与 Quick。", _effect("np_charge", 10, target="team"), _effect("card_up_a", 10, 99), _effect("card_up_q", 10, 99)),
       ]),
    _servant("melusine_lancer", "梅柳齐娜", "Lancer", 5, 11800, 1360, "BBAAQ", [
        _skill("龙之心脏 B", 5, "提升攻击、NP 获取与速度。", _effect("attack_up", 28, 3), _effect("np_gain_up", 35, 3), _effect("speed_up", 25, 3)),
        _skill("永远的武装 A", 6, "获得整轮无敌、暴击星与暴击威力。", _effect("invincible", 1, 1), _effect("stars", 24), _effect("crit_up", 45, 3)),
        _skill("雷霆之翼 EX", 6, "大量增加 NP，强化宝具并获得无敌贯通。", _effect("np_charge", 60), _effect("np_damage_up", 38, 2), _effect("invincible_pierce", 1, 2)),
    ], "谁也不知晓的无垢鼓动", "B", "all", 430, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("burn", 650, 3, "enemy_team")],
       "展开龙翼——让尽头的天空记住这道光！", passives=[
           _passive("妖精龙", "开战时获得 20% NP，并永久提升攻击与速度。", _effect("np_charge", 20), _effect("attack_up", 10, 99), _effect("speed_up", 10, 99)),
       ]),
    _servant("koyanskaya_light_assassin", "光之高扬斯卡娅", "Assassin", 5, 11100, 1320, "BBBAQ", [
        _skill("创新火器 B", 5, "强化一名队友的 Buster、攻击与暴击率。", _effect("card_up_b", 42, 3, "ally"), _effect("attack_up", 24, 3, "ally"), _effect("crit_chance_up", 30, 3, "ally")),
        _skill("杀戮技巧 A", 6, "增加一名队友 NP，缩短其技能冷却。", _effect("np_charge", 50, target="ally"), _effect("cooldown_reduce", 1, target="ally")),
        _skill("NFF特别服务 EX", 6, "获得大量暴击星，并降低敌方全体防御。", _effect("stars", 32), _effect("crit_up", 50, 3, "team"), _effect("defense_down", 25, 3, "enemy_team")),
    ], "灵裳重光·七驱", "B", "all", 405, [_effect("attack_down", 25, 3, "enemy_team"), _effect("np_drain", 20, target="enemy_team")],
       "NFF服务时间到——以最先进的火力清场吧！", passives=[
           _passive("兽之残香", "开战时获得 15% NP 与 15 颗星。", _effect("np_charge", 15), _effect("stars", 15)),
       ]),
    _servant("semiramis_assassin", "塞弥拉弥斯", "Assassin", 5, 12800, 1200, "BAAAQ", [
        _skill("使魔·鸽 A", 5, "增加 NP，并降低敌方全体攻击与暴击率。", _effect("np_charge", 35), _effect("attack_down", 15, 2, "enemy_team"), _effect("crit_chance_down", 22, 2, "enemy_team")),
        _skill("二重召唤 B", 6, "强化 Arts 与宝具威力，并获得一次弱化无效。", _effect("card_up_a", 35, 3), _effect("np_damage_up", 30, 2), _effect("debuff_immunity", 1, 3)),
        _skill("骄慢王的美酒 EX", 6, "降低敌方全体攻防，并施加毒。", _effect("attack_down", 25, 3, "enemy_team"), _effect("defense_down", 30, 3, "enemy_team"), _effect("poison", 800, 3, "enemy_team")),
    ], "虚荣的空中庭园", "B", "all", 370, [_effect("poison", 1100, 3, "enemy_team"), _effect("defense_up", 28, 3, "team")],
       "升起吧，空中庭园——女帝的毒将覆盖战场。", passives=[
           _passive("亚述女帝", "永久提升 NP 获取与 Arts 性能。", _effect("np_gain_up", 18, 99), _effect("card_up_a", 10, 99)),
       ]),
    _servant("musashi_saber", "宫本武藏", "Saber", 5, 12100, 1380, "BBBAQ", [
        _skill("第五势 A", 5, "提升攻击、暴击率与 NP 获取。", _effect("attack_up", 30, 3), _effect("crit_chance_up", 32, 3), _effect("np_gain_up", 35, 3)),
        _skill("天眼 A", 6, "获得无敌贯通，强化 Buster 与暴击威力。", _effect("invincible_pierce", 1, 3), _effect("card_up_b", 38, 3), _effect("crit_up", 45, 3)),
        _skill("无空 A", 6, "获得整轮无敌，解除弱化并获得暴击星。", _effect("invincible", 1, 1), _effect("debuff_cleanse"), _effect("stars", 20)),
    ], "六道五轮·俱利伽罗天象", "B", "single", 620, [_effect("buff_remove", target="enemy", timing="pre"), _effect("attack_up", 20, 3)],
       "南无天满大自在天神——这一刀，斩断六道！", passives=[
           _passive("二天一流", "永久提升 Buster 与暴击威力。", _effect("card_up_b", 12, 99), _effect("crit_up", 18, 99)),
       ]),
    _servant("jeanne_archer_summer", "贞德〔海滨圣女〕", "Archer", 5, 12500, 1270, "BAAAQ", [
        _skill("水边的圣女 A+", 5, "强化全队 Arts、NP 获取并回复生命。", _effect("card_up_a", 25, 3, "team"), _effect("np_gain_up", 25, 3, "team"), _effect("heal", 1400, target="team")),
        _skill("海滨乐园 EX", 6, "增加自身 NP，获得暴击星与回避。", _effect("np_charge", 40), _effect("stars", 22), _effect("evade", 1, 1)),
        _skill("姐姐的声援 B", 6, "提升一名队友攻防与速度。", _effect("attack_up", 28, 3, "ally"), _effect("defense_up", 25, 3, "ally"), _effect("speed_up", 18, 3, "ally")),
    ], "丰饶大海啊，欢喜相随", "A", "all", 390, [_effect("np_charge", 15, target="team"), _effect("stars", 20, target="team")],
       "让海风把祈愿送到每个人身边——一起向前吧！", passives=[
           _passive("海滨的祝福", "全队永久提升少量 NP 获取。", _effect("np_gain_up", 10, 99, "team")),
       ]),
    _servant("nero_star_bride_beast", "尼禄〔星海新娘〕", "Beast", 6, 17100, 2070, "BBBAQ", [
        _skill("黄金婚宴 EX", 5, "强化全队攻击、暴击率与 NP 获取。", _effect("attack_up", 34, 3, "team"), _effect("crit_chance_up", 28, 3, "team"), _effect("np_gain_up", 30, 3, "team")),
        _skill("花嫁特权 A++", 5, "回复一名队友生命，增加 NP 并缩短技能冷却。", _effect("heal", 3200, target="ally"), _effect("np_charge", 50, target="ally"), _effect("cooldown_reduce", 1, target="ally")),
        _skill("星海剧场 EX", 6, "获得整轮无敌与无敌贯通，大幅强化宝具。", _effect("invincible", 1, 1), _effect("invincible_pierce", 1, 2), _effect("np_damage_up", 58, 2)),
    ], "星海黄金剧场·爱之凯旋", "B", "all", 575, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("heal", 2500, target="team"), _effect("attack_up", 25, 3, "team")],
       "奏响婚礼的喝彩吧——星海也将成为余的黄金剧场！", event_only=True, passives=[
           _passive("兽冠新娘", "开战时全队获得 15% NP，自身持续恢复生命。", _effect("np_charge", 15, target="team"), _effect("regen", 650, 99)),
       ]),
    _servant("mash_decisive_shielder", "玛修〔决战灵衣〕", "Shielder", 6, 19200, 1800, "BBAAQ", [
        _skill("黑桶·限定解除 EX", 6, "提升攻击、无敌贯通与宝具威力。", _effect("attack_up", 42, 3), _effect("invincible_pierce", 1, 3), _effect("np_damage_up", 52, 2)),
        _skill("守护者的决意 A++", 5, "赋予全队整轮无敌、防御提升与弱化无效。", _effect("invincible", 1, 1, "team"), _effect("defense_up", 35, 3, "team"), _effect("debuff_immunity", 1, 3, "team")),
        _skill("迦勒底之盾 EX", 6, "回复全队生命、增加 NP，并缩短自身冷却。", _effect("heal", 2800, target="team"), _effect("np_charge", 25, target="team"), _effect("cooldown_reduce", 1)),
    ], "人理之光·黑桶终射", "B", "single", 810, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 45, 3, "enemy"), _effect("defense_up", 30, 3, "team")],
       "前辈，请看着我——这就是守护人理的最后一击！", event_only=True, passives=[
           _passive("最后的守护者", "开战时全队获得 20% NP、一次弱化无效与永久防御强化。", _effect("np_charge", 20, target="team"), _effect("debuff_immunity", 1, 99, "team"), _effect("defense_up", 12, 99, "team")),
       ]),
    _servant("okita_souji_saber", "冲田总司", "Saber", 5, 10900, 1390, "BAQQQ", [
        _skill("缩地 B+", 5, "强化 Quick、速度与 NP 获取。", _effect("card_up_q", 40, 3), _effect("speed_up", 28, 3), _effect("np_gain_up", 30, 3)),
        _skill("病弱 A", 5, "集中精神，获得高额暴击率、暴击威力与暴击星。", _effect("crit_chance_up", 42, 3), _effect("crit_up", 55, 3), _effect("stars", 20)),
        _skill("无明三段突 EX", 6, "获得回避与无敌贯通，并提升攻击。", _effect("evade", 2, 2), _effect("invincible_pierce", 1, 2), _effect("attack_up", 28, 3)),
    ], "无明三段突", "Q", "single", 625, [_effect("defense_down", 30, 3, "enemy"), _effect("stars", 18)],
       "一步超音，二步无间——无明三段突！", passives=[
           _passive("天然理心流", "永久提升 Quick、暴击率与速度。", _effect("card_up_q", 10, 99), _effect("crit_chance_up", 12, 99), _effect("speed_up", 8, 99)),
       ]),
    _servant("minamoto_raikou_berserker", "源赖光", "Berserker", 5, 12600, 1420, "BBBAQ", [
        _skill("源氏的武练 EX", 5, "提升攻击、暴击率，并获得暴击星。", _effect("attack_up", 28, 3), _effect("crit_chance_up", 32, 3), _effect("stars", 22)),
        _skill("雷神之子 A+", 6, "强化 Buster 与宝具威力，并获得无敌贯通。", _effect("card_up_b", 38, 3), _effect("np_damage_up", 35, 2), _effect("invincible_pierce", 1, 2)),
        _skill("神秘杀手 A", 6, "提升特攻与暴击威力，并增加 NP。", _effect("trait_damage_up", 38, 3), _effect("crit_up", 48, 3), _effect("np_charge", 35)),
    ], "牛王招雷·天网恢恢", "B", "all", 420, [_effect("stars", 30, target="team"), _effect("stun", 1, 1, "enemy_team")],
       "以母之雷霆扫清魔性——牛王招雷，天网恢恢！", passives=[
           _passive("神性雷霆", "永久提升攻击，并在每次行动获得暴击星。", _effect("attack_up", 9, 99), _effect("stars_per_turn", 5, 99)),
       ]),
    _servant("tamamo_no_mae_caster", "玉藻前", "Caster", 5, 13200, 1130, "BAAAQ", [
        _skill("咒术 EX", 5, "削减敌方全体 NP，并降低攻击。", _effect("np_drain", 25, target="enemy_team"), _effect("attack_down", 22, 3, "enemy_team")),
        _skill("变化 A", 5, "提升自身防御，回复生命并获得一次弱化无效。", _effect("defense_up", 35, 3), _effect("heal", 2200), _effect("debuff_immunity", 1, 3)),
        _skill("狐之婚嫁 EX", 5, "强化一名队友的 Arts，回复生命并增加 NP。", _effect("card_up_a", 45, 3, "ally"), _effect("heal", 2400, target="ally"), _effect("np_charge", 30, target="ally")),
    ], "水天日光天照八野镇石", "A", "team", 0, [_effect("heal", 2600, target="team"), _effect("np_charge", 25, target="team"), _effect("cooldown_reduce", 1, target="team")],
       "祓除灾厄，结缘良缘——水天日光，照临此处！", passives=[
           _passive("白面金毛", "全队永久提升少量 Arts 与 NP 获取。", _effect("card_up_a", 8, 99, "team"), _effect("np_gain_up", 8, 99, "team")),
       ]),
    _servant("katsushika_hokusai_foreigner", "葛饰北斋", "Foreigner", 5, 11600, 1350, "BAAAQ", [
        _skill("森罗万象 A+", 5, "增加 NP，强化 Arts 与 NP 获取。", _effect("np_charge", 35), _effect("card_up_a", 35, 3), _effect("np_gain_up", 30, 3)),
        _skill("父女的画工 EX", 6, "降低敌方全体防御，并获得暴击星。", _effect("defense_down", 26, 3, "enemy_team"), _effect("stars", 24)),
        _skill("雅号·异星蛸 B", 6, "获得整轮无敌，提升攻击与暴击威力。", _effect("invincible", 1, 1), _effect("attack_up", 28, 3), _effect("crit_up", 45, 3)),
    ], "富岳三十六景·神奈川冲浪里", "A", "all", 405, [_effect("defense_down", 25, 3, "enemy_team"), _effect("np_charge", 15)],
       "笔走龙蛇，浪卷富岳——且看这神奈川冲浪里！", passives=[
           _passive("画狂老人卍", "开战获得 20% NP，永久提升 Arts。", _effect("np_charge", 20), _effect("card_up_a", 12, 99)),
       ]),
    _servant("bb_moon_nurse_mooncancer", "BB〔月之护士〕", "MoonCancer", 5, 12800, 1210, "BAAAQ", [
        _skill("十之王冠 D", 5, "解除一名队友弱化，回复生命并赋予弱化无效。", _effect("debuff_cleanse", target="ally"), _effect("heal", 2200, target="ally"), _effect("debuff_immunity", 2, 3, "ally")),
        _skill("黄金之杯 C", 6, "解除一名敌人的强化，降低防御并延迟眩晕。", _effect("buff_remove", target="enemy"), _effect("defense_down", 30, 3, "enemy"), _effect("delayed_stun", 1, 1, "enemy")),
        _skill("月之护理 EX", 6, "增加全队 NP，提升暴击率与 NP 获取。", _effect("np_charge", 25, target="team"), _effect("crit_chance_up", 24, 3, "team"), _effect("np_gain_up", 25, 3, "team")),
    ], "C.C.C.月之终端诊疗", "A", "single", 565, [_effect("np_drain", 30, target="enemy"), _effect("heal", 1800, target="team")],
       "病历确认——由万能后辈为你执行月之诊疗！", passives=[
           _passive("月之AI", "开战时全队获得 8% NP，自身永久提升防御。", _effect("np_charge", 8, target="team"), _effect("defense_up", 10, 99)),
       ]),
    _servant("brynhild_lancer", "布伦希尔德", "Lancer", 5, 12400, 1370, "BBAAQ", [
        _skill("魔力放出·炎 B", 5, "强化 Buster、宝具与攻击。", _effect("card_up_b", 35, 3), _effect("np_damage_up", 28, 2), _effect("attack_up", 20, 3)),
        _skill("原初之卢恩", 6, "降低一名敌人的防御与暴击率，并施加灼烧。", _effect("defense_down", 30, 3, "enemy"), _effect("crit_chance_down", 25, 3, "enemy"), _effect("burn", 650, 3, "enemy")),
        _skill("英雄的介添 C++", 5, "强化一名队友的暴击并回复生命。", _effect("crit_chance_up", 35, 3, "ally"), _effect("crit_up", 60, 3, "ally"), _effect("heal", 2000, target="ally")),
    ], "直至死亡拆散两人", "B", "single", 640, [_effect("attack_down", 25, 3, "enemy"), _effect("stars", 20)],
       "爱与死亡同在——直至死亡将你我拆散！", passives=[
           _passive("女武神的宿命", "永久提升攻击与暴击威力。", _effect("attack_up", 9, 99), _effect("crit_up", 18, 99)),
       ]),
    _servant("taira_kagekiyo_avenger", "平景清", "Avenger", 5, 11900, 1430, "BBQQQ", [
        _skill("源氏必灭 A++", 5, "提升攻击、特攻与速度。", _effect("attack_up", 30, 3), _effect("trait_damage_up", 38, 3), _effect("speed_up", 24, 3)),
        _skill("痣丸之雾 B", 6, "获得回避、弱化无效与暴击星。", _effect("evade", 2, 2), _effect("debuff_immunity", 1, 3), _effect("stars", 22)),
        _skill("复仇的铁索 EX", 6, "增加 NP，提升暴击率并降低敌方防御。", _effect("np_charge", 45), _effect("crit_chance_up", 35, 3), _effect("defense_down", 28, 3, "enemy")),
    ], "诸行无常·盛者必衰", "Q", "single", 650, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("execute", 25, target="enemy")],
       "闻祇园钟声——源氏，必灭！", passives=[
           _passive("景清者", "开战时获得 20% NP，永久提升 Quick 与速度。", _effect("np_charge", 20), _effect("card_up_q", 12, 99), _effect("speed_up", 8, 99)),
       ]),
    _servant("cleopatra_assassin", "克娄巴特拉", "Assassin", 5, 12500, 1260, "BBAQQ", [
        _skill("皇帝特权 A", 5, "提升攻防并回复生命。", _effect("attack_up", 28, 3), _effect("defense_up", 28, 3), _effect("heal", 2200)),
        _skill("黄金律·富与体 B", 6, "增加 NP，持续回复生命并提升 NP 获取。", _effect("np_charge", 35), _effect("regen", 700, 3), _effect("np_gain_up", 28, 3)),
        _skill("女神的加护 C", 6, "获得整轮无敌、弱化无效与暴击星。", _effect("invincible", 1, 1), _effect("debuff_immunity", 1, 3), _effect("stars", 20)),
    ], "终焉闪耀之蛇", "B", "all", 390, [_effect("poison", 850, 3, "enemy_team"), _effect("heal", 1800)],
       "见证最后的法老之美——终焉闪耀之蛇！", passives=[
           _passive("伊西斯的宠爱", "永久提升防御与暴击星获取。", _effect("defense_up", 10, 99), _effect("star_gain_up", 18, 99)),
       ]),
    _servant("artoria_rhongomyniad_lancer", "阿尔托莉雅〔圣枪女神〕", "Lancer", 6, 18400, 2080, "BBBAQ", [
        _skill("尽头的加护 EX", 5, "强化全队攻击、防御与速度。", _effect("attack_up", 35, 3, "team"), _effect("defense_up", 30, 3, "team"), _effect("speed_up", 22, 3, "team")),
        _skill("圣枪解放 A++", 5, "大量增加 NP，强化 Buster 与宝具。", _effect("np_charge", 70), _effect("card_up_b", 48, 3), _effect("np_damage_up", 55, 2)),
        _skill("世界尽头之塔 EX", 6, "赋予全队整轮无敌与一次弱化无效，自身获得无敌贯通。", _effect("invincible", 1, 1, "team"), _effect("debuff_immunity", 1, 3, "team"), _effect("invincible_pierce", 1, 2)),
    ], "闪耀于终焉之枪", "B", "all", 610, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 38, 3, "enemy_team"), _effect("np_charge", 20, target="team")],
       "锚定星球，维系风暴——闪耀于终焉之枪！", event_only=True, passives=[
           _passive("狮子王", "开战时全队获得 20% NP，自身永久强化攻击与 Buster。", _effect("np_charge", 20, target="team"), _effect("attack_up", 15, 99), _effect("card_up_b", 18, 99)),
       ]),
    _servant("ibuki_amano_murakumo_saber", "伊吹童子〔天丛云〕", "Saber", 6, 17900, 2150, "BBBAQ", [
        _skill("八岐大蛇之神核 EX", 5, "提升攻击、暴击率与弱化抗性。", _effect("attack_up", 42, 3), _effect("crit_chance_up", 38, 3), _effect("debuff_immunity", 2, 3)),
        _skill("山河神气 A++", 5, "强化全队 Buster、暴击威力并获得暴击星。", _effect("card_up_b", 32, 3, "team"), _effect("crit_up", 48, 3, "team"), _effect("stars", 32)),
        _skill("天丛云解放 EX", 6, "大量增加 NP，获得整轮无敌与无敌贯通。", _effect("np_charge", 75), _effect("invincible", 1, 1), _effect("invincible_pierce", 1, 2)),
    ], "神剑·草那艺之大刀", "B", "all", 625, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("burn", 1300, 3, "enemy_team"), _effect("attack_up", 25, 3)],
       "山河为酒，大蛇为刃——天丛云，开天！", event_only=True, passives=[
           _passive("蛇神之躯", "开战时获得 30% NP，永久提升攻击并持续恢复。", _effect("np_charge", 30), _effect("attack_up", 16, 99), _effect("regen", 600, 99)),
       ]),
    _servant("kukulkan_solar_foreigner", "库库尔坎〔太阳纪元〕", "Foreigner", 6, 17500, 2120, "BBAAQ", [
        _skill("翡翠太阳 EX", 5, "强化全队攻击、暴击率与速度。", _effect("attack_up", 34, 3, "team"), _effect("crit_chance_up", 32, 3, "team"), _effect("speed_up", 26, 3, "team")),
        _skill("翼蛇降临 A++", 5, "增加全队 NP 与暴击星，提升 NP 获取。", _effect("np_charge", 30, target="team"), _effect("stars", 30, target="team"), _effect("np_gain_up", 30, 3, "team")),
        _skill("ORT心脏 EX", 6, "获得整轮无敌与无敌贯通，大幅强化宝具。", _effect("invincible", 1, 1), _effect("invincible_pierce", 1, 2), _effect("np_damage_up", 60, 2)),
    ], "星之内海·太阳纪元", "B", "all", 600, [_effect("defense_down", 40, 3, "enemy_team"), _effect("heal", 2200, target="team"), _effect("np_charge", 15, target="team")],
       "这颗心就是太阳——飞翔吧，新的太阳纪元！", event_only=True, passives=[
           _passive("水晶之心", "开战时全队获得 20% NP 与一次弱化无效。", _effect("np_charge", 20, target="team"), _effect("debuff_immunity", 1, 99, "team")),
       ]),
    _servant("solomon_grand_caster", "所罗门〔冠位魔术王〕", "Caster", 6, 18800, 2020, "BAAAQ", [
        _skill("启示·十之戒 EX", 5, "提升全队三色性能、NP 获取与暴击率。", _effect("card_up_all", 28, 3, "team"), _effect("np_gain_up", 35, 3, "team"), _effect("crit_chance_up", 25, 3, "team")),
        _skill("七十二柱统御 A++", 6, "降低敌方全体攻防、速度并削减 NP。", _effect("attack_down", 32, 3, "enemy_team"), _effect("defense_down", 35, 3, "enemy_team"), _effect("speed_down", 25, 3, "enemy_team"), _effect("np_drain", 30, target="enemy_team")),
        _skill("诀别之时已至 EX", 7, "全队获得整轮无敌、NP 与冷却缩减。", _effect("invincible", 1, 1, "team"), _effect("np_charge", 40, target="team"), _effect("cooldown_reduce", 1, target="team")),
    ], "诞生之时已至·戴冠之时已至", "A", "all", 560, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("attack_up", 30, 3, "team"), _effect("heal", 3000, target="team")],
       "以冠位之名归还一切——诞生之时已至，戴冠之时已至！", event_only=True, passives=[
           _passive("冠位魔术王", "开战时全队获得 25% NP、永久防御与持续 NP。", _effect("np_charge", 25, target="team"), _effect("defense_up", 12, 99, "team"), _effect("np_per_turn", 6, 99, "team")),
       ]),
    _servant("altera_saber", "阿蒂拉", "Saber", 5, 11800, 1430, "BBBAQ", [
        _skill("星之纹章 EX", 5, "强化攻击、暴击率并获得暴击星。", _effect("attack_up", 30, 3), _effect("crit_chance_up", 30, 3), _effect("stars", 22)),
        _skill("天性的肉体 D", 6, "解除弱化，回复生命并提升暴击威力。", _effect("debuff_cleanse"), _effect("heal", 2400), _effect("crit_up", 45, 3)),
        _skill("军略 B", 6, "提升全队宝具威力与攻击。", _effect("np_damage_up", 28, 2, "team"), _effect("attack_up", 18, 3, "team")),
    ], "军神之剑", "B", "all", 430, [_effect("defense_down", 28, 3, "enemy_team"), _effect("stars", 20)],
       "文明亦可化作光带——军神之剑，横扫大地！", passives=[
           _passive("游星尖兵", "永久提升攻击与暴击威力。", _effect("attack_up", 10, 99), _effect("crit_up", 18, 99)),
       ]),
    _servant("sei_shonagon_archer", "清少纳言", "Archer", 5, 10900, 1360, "BAQQQ", [
        _skill("歌仙的诗歌 B", 5, "强化全队 Quick、暴击威力与速度。", _effect("card_up_q", 26, 3, "team"), _effect("crit_up", 30, 3, "team"), _effect("speed_up", 16, 3, "team")),
        _skill("逢坂关 A", 6, "获得回避、NP 与暴击星。", _effect("evade", 2, 2), _effect("np_charge", 35), _effect("stars", 24)),
        _skill("星月夜 EX", 5, "大幅提升暴击率、特攻与 NP 获取。", _effect("crit_chance_up", 42, 3), _effect("trait_damage_up", 32, 3), _effect("np_gain_up", 35, 3)),
    ], "枕草子·春曙抄", "Q", "all", 410, [_effect("stars", 26, target="team"), _effect("speed_down", 20, 3, "enemy_team")],
       "春曙、夏夜、秋暮、冬晨——把闪耀的瞬间全部记下来！", passives=[
           _passive("闪耀的感性", "开战获得暴击星，并永久提升 Quick。", _effect("stars", 18), _effect("card_up_q", 12, 99)),
       ]),
    _servant("valkyrie_lancer", "女武神三姐妹", "Lancer", 5, 12600, 1310, "BAQQQ", [
        _skill("原初之卢恩·战 A", 5, "强化全队 Quick、攻击与暴击率。", _effect("card_up_q", 30, 3, "team"), _effect("attack_up", 18, 3, "team"), _effect("crit_chance_up", 24, 3, "team")),
        _skill("天鹅礼装 A", 6, "获得整轮回避、弱化无效与速度。", _effect("evade", 1, 1), _effect("debuff_immunity", 2, 3), _effect("speed_up", 28, 3)),
        _skill("命运编织 B+", 5, "持续获得 NP 与暴击星，并回复生命。", _effect("np_per_turn", 10, 3), _effect("stars_per_turn", 10, 3), _effect("regen", 650, 3)),
    ], "终末幻想·少女降临", "Q", "all", 420, [_effect("defense_down", 25, 3, "enemy_team"), _effect("evade", 1, 1, "team")],
       "奥特琳德、希露德、斯露德——引导勇士前往终末！", passives=[
           _passive("神性机械", "永久提升速度与 NP 获取。", _effect("speed_up", 10, 99), _effect("np_gain_up", 12, 99)),
       ]),
    _servant("ozymandias_rider", "奥斯曼狄斯", "Rider", 5, 13700, 1410, "BBBAQ", [
        _skill("太阳神的加护 A", 5, "增加全队 NP，强化攻击与弱化抗性。", _effect("np_charge", 25, target="team"), _effect("attack_up", 22, 3, "team"), _effect("debuff_immunity", 1, 3, "team")),
        _skill("皇帝特权 A+", 6, "大幅强化攻防并回复生命。", _effect("attack_up", 35, 3), _effect("defense_up", 35, 3), _effect("heal", 2600)),
        _skill("热砂王道 EX", 6, "强化 Buster、暴击威力并获得无敌贯通。", _effect("card_up_b", 38, 3), _effect("crit_up", 50, 3), _effect("invincible_pierce", 1, 2)),
    ], "光辉大复合神殿", "B", "all", 445, [_effect("np_drain", 25, target="enemy_team"), _effect("defense_down", 30, 3, "enemy_team")],
       "太阳在此俯瞰万物——跪拜吧，光辉大复合神殿！", passives=[
           _passive("太阳王", "开战时全队获得 10% NP，自身永久强化攻击。", _effect("np_charge", 10, target="team"), _effect("attack_up", 12, 99)),
       ]),
    _servant("murasaki_shikibu_caster", "紫式部", "Caster", 5, 13200, 1240, "BAAAQ", [
        _skill("歌仙的诗歌 A", 5, "强化全队 Arts、NP 获取与弱化抗性。", _effect("card_up_a", 28, 3, "team"), _effect("np_gain_up", 28, 3, "team"), _effect("debuff_immunity", 1, 3, "team")),
        _skill("咒术·词章 D+", 6, "降低敌方全体防御、攻击并施加诅咒般的灼烧。", _effect("defense_down", 25, 3, "enemy_team"), _effect("attack_down", 20, 3, "enemy_team"), _effect("burn", 700, 3, "enemy_team")),
        _skill("紫式部日记 B", 5, "增加 NP，获得整轮无敌并缩短冷却。", _effect("np_charge", 45), _effect("invincible", 1, 1), _effect("cooldown_reduce", 1)),
    ], "源氏物语·葵·物之怪", "A", "all", 405, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("attack_down", 25, 3, "enemy_team")],
       "翻开物语吧——那些被隐藏的心，也将在文字中显形。", passives=[
           _passive("图书馆的守护者", "全队永久提升 Arts 与弱化耐性。", _effect("card_up_a", 8, 99, "team"), _effect("debuff_immunity", 1, 99, "team")),
       ]),
    _servant("shuten_douji_assassin", "酒吞童子", "Assassin", 5, 12100, 1370, "BBAAQ", [
        _skill("果实的酒气 A", 6, "魅惑般降低敌方全体攻防与速度。", _effect("attack_down", 22, 3, "enemy_team"), _effect("defense_down", 25, 3, "enemy_team"), _effect("speed_down", 22, 3, "enemy_team")),
        _skill("鬼种之魔 A", 5, "强化全队攻击与自身宝具威力。", _effect("attack_up", 22, 3, "team"), _effect("np_damage_up", 38, 2)),
        _skill("战斗续行 A+", 6, "获得战续、回复生命并提升暴击率。", _effect("guts", 2600, 3), _effect("heal", 1600), _effect("crit_chance_up", 32, 3)),
    ], "千紫万红·神便鬼毒", "A", "all", 400, [_effect("poison", 1100, 3, "enemy_team"), _effect("defense_down", 25, 3, "enemy_team")],
       "这杯酒可甜得很——饮下吧，连骨头都染成我的颜色。", passives=[
           _passive("大江山鬼王", "永久提升攻击与弱化成功率风格的暴击率。", _effect("attack_up", 9, 99), _effect("crit_chance_up", 12, 99)),
       ]),
    _servant("xiang_yu_berserker", "项羽", "Berserker", 5, 14500, 1490, "BBBQQ", [
        _skill("未来预测 A", 5, "获得整轮回避、暴击率与速度。", _effect("evade", 1, 1), _effect("crit_chance_up", 38, 3), _effect("speed_up", 30, 3)),
        _skill("战术躯体 B", 6, "强化攻击、防御与暴击威力。", _effect("attack_up", 32, 3), _effect("defense_up", 24, 3), _effect("crit_up", 55, 3)),
        _skill("霸王之武 EX", 5, "强化 Buster、无敌贯通并获得暴击星。", _effect("card_up_b", 42, 3), _effect("invincible_pierce", 1, 2), _effect("stars", 26)),
    ], "力拔山兮气盖世", "B", "all", 455, [_effect("defense_down", 30, 3, "enemy_team"), _effect("speed_down", 25, 3, "enemy_team")],
       "演算结束——力拔山兮，气盖世！", passives=[
           _passive("会稽零式", "永久提升防御、速度与 Buster。", _effect("defense_up", 8, 99), _effect("speed_up", 8, 99), _effect("card_up_b", 10, 99)),
       ]),
    _servant("yang_guifei_foreigner", "杨贵妃", "Foreigner", 5, 12300, 1380, "BAAAQ", [
        _skill("三千宠爱在一身 A", 5, "增加 NP，强化 Arts 与暴击率。", _effect("np_charge", 40), _effect("card_up_a", 36, 3), _effect("crit_chance_up", 30, 3)),
        _skill("倾国之宠姬 A", 6, "降低敌方全体防御并施加灼烧。", _effect("defense_down", 28, 3, "enemy_team"), _effect("burn", 900, 3, "enemy_team")),
        _skill("妖星的火轮 EX", 6, "获得整轮无敌、宝具威力与持续 NP。", _effect("invincible", 1, 1), _effect("np_damage_up", 42, 2), _effect("np_per_turn", 10, 3)),
    ], "霓裳羽衣·比翼连理", "A", "single", 610, [_effect("burn", 1500, 3, "enemy"), _effect("poison_bonus", 45, 1, "enemy")],
       "星火啊，奏响霓裳羽衣——愿这份爱燃至宇宙尽头。", passives=[
           _passive("贵妃的妖星", "开战获得 NP，永久提升 Arts 与灼烧风格特攻。", _effect("np_charge", 20), _effect("card_up_a", 12, 99), _effect("trait_damage_up", 12, 99)),
       ]),
    _servant("artoria_black_dragon_saber", "阿尔托莉雅〔黑龙皇〕", "Saber", 6, 18600, 2190, "BBBAQ", [
        _skill("黑龙炉心 EX", 5, "大量增加 NP，强化攻击、Buster 与暴击率。", _effect("np_charge", 75), _effect("attack_up", 42, 3), _effect("card_up_b", 48, 3), _effect("crit_chance_up", 35, 3)),
        _skill("逆鳞王铠 A++", 6, "全队获得整轮无敌，自身获得伤害反弹与弱化无效。", _effect("invincible", 1, 1, "team"), _effect("damage_reflect", 70, 1), _effect("debuff_immunity", 2, 3)),
        _skill("终焉敕令 EX", 6, "降低敌方全体防御和速度，并赋予自身处决能力。", _effect("defense_down", 42, 3, "enemy_team"), _effect("speed_down", 30, 3, "enemy_team"), _effect("trait_damage_up", 55, 2)),
    ], "约束胜利之剑·黑龙终焉", "B", "all", 650, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("execute", 22, target="enemy_team"), _effect("attack_up", 25, 3)],
       "圣剑已被龙焰染黑——在终焉中宣告胜利！", event_only=True, passives=[
           _passive("不列颠黑龙皇", "开战时全队获得 20% NP，自身永久提升攻防与暴击威力。", _effect("np_charge", 20, target="team"), _effect("attack_up", 16, 99), _effect("defense_up", 14, 99), _effect("crit_up", 28, 99)),
       ]),
    _servant("arjuna_alter_berserker", "阿周那〔Alter〕", "Berserker", 6, 17900, 2210, "BBBAQ", [
        _skill("对邪恶·特殊 EX", 5, "大幅强化攻击与特攻，并获得无敌贯通。", _effect("attack_up", 45, 3), _effect("trait_damage_up", 58, 3), _effect("invincible_pierce", 1, 2)),
        _skill("千里眼·超越 EX", 5, "增加 NP、暴击率、暴击威力与速度。", _effect("np_charge", 60), _effect("crit_chance_up", 38, 3), _effect("crit_up", 65, 3), _effect("speed_up", 24, 3)),
        _skill("魂之灯火 EX", 6, "回复生命，获得战续、整轮无敌与持续 NP。", _effect("heal", 3200), _effect("guts", 3800, 3), _effect("invincible", 1, 1), _effect("np_per_turn", 12, 3)),
    ], "归灭之轮回·末法审判", "B", "all", 670, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("defense_down", 45, 3, "enemy_team"), _effect("burn", 1400, 3, "enemy_team")],
       "不完美的世界无需留存——归灭，而后重生。", event_only=True, passives=[
           _passive("神之集合体", "开战获得 35% NP，永久提升攻击与三色性能。", _effect("np_charge", 35), _effect("attack_up", 18, 99), _effect("card_up_all", 12, 99)),
       ]),
    _servant("kingprotea_alterego", "帝王花", "AlterEgo", 6, 20500, 2070, "BBBAQ", [
        _skill("巨大规模 EX", 5, "大幅回复生命并持续提升防御与再生。", _effect("heal", 4500), _effect("defense_up", 38, 3), _effect("regen", 1200, 3)),
        _skill("幼儿退行 C", 6, "缩短冷却、增加 NP 并解除弱化。", _effect("cooldown_reduce", 2), _effect("np_charge", 45), _effect("debuff_cleanse")),
        _skill("怪力 EX", 5, "强化攻击、Buster、暴击威力并获得嘲讽。", _effect("attack_up", 48, 3), _effect("card_up_b", 45, 3), _effect("crit_up", 60, 3), _effect("taunt", 1, 1)),
    ], "巨影吞噬·Airavata King Size", "B", "all", 625, [_effect("defense_down", 38, 3, "enemy_team"), _effect("heal", 3500), _effect("guts", 4200, 3)],
       "大、大、大到整个世界都装不下——帝王花，要压过去了！", event_only=True, passives=[
           _passive("无限增殖", "永久大幅提升生命回复、防御并持续再生。", _effect("defense_up", 15, 99), _effect("regen", 850, 99), _effect("np_per_turn", 5, 99)),
       ]),
    _servant("lady_avalon_pretender", "阿瓦隆女士", "Pretender", 6, 17800, 2030, "BAAAQ", [
        _skill("其手闪耀之路 EX", 5, "增加全队 NP，强化攻击与宝具威力。", _effect("np_charge", 35, target="team"), _effect("attack_up", 28, 3, "team"), _effect("np_damage_up", 32, 2, "team")),
        _skill("梦魔之畔 A++", 6, "全队获得整轮无敌、持续 NP 与回复。", _effect("invincible", 1, 1, "team"), _effect("np_per_turn", 10, 3, "team"), _effect("regen", 900, 3, "team")),
        _skill("英雄塑造·幻 EX", 5, "强化一名队友三色、暴击率、暴击威力并缩短冷却。", _effect("card_up_all", 35, 3, "ally"), _effect("crit_chance_up", 40, 3, "ally"), _effect("crit_up", 70, 3, "ally"), _effect("cooldown_reduce", 1, target="ally")),
    ], "彼方开放的理想乡", "A", "team", 0, [_effect("heal", 3600, target="team"), _effect("np_charge", 30, target="team"), _effect("stars_per_turn", 15, 3, "team")],
       "从梦的彼岸献上花冠——理想乡的大门一直为你敞开。", event_only=True, passives=[
           _passive("理想乡的梦魔", "开战时全队获得 25% NP，永久提升 NP 获取与暴击威力。", _effect("np_charge", 25, target="team"), _effect("np_gain_up", 14, 99, "team"), _effect("crit_up", 20, 99, "team")),
       ]),
    _servant("tomoe_gozen_archer", "巴御前", "Archer", 5, 12200, 1370, "BBAQQ", [
        _skill("鬼种之魔·焰 A", 5, "提升自身攻击与 Buster，并为敌方单体附加灼烧。", _effect("attack_up", 28, 3), _effect("card_up_b", 30, 3), _effect("burn", 700, 3, "enemy")),
        _skill("乱战的心得 B", 5, "获得暴击星，提升暴击率与暴击威力。", _effect("stars", 20), _effect("crit_chance_up", 32, 3), _effect("crit_up", 40, 3)),
        _skill("血脉觉醒 A", 6, "获得战续、速度提升与持续回血。", _effect("guts", 2400, 3), _effect("speed_up", 22, 3), _effect("regen", 600, 3)),
    ], "真言·圣观世音菩萨", "B", "single", 570, [_effect("burn", 1200, 3, "enemy"), _effect("stars", 15)],
       "火焰记得每一个名字——此箭为守护而放！", passives=[
           _passive("旭将军之誓", "永久提升攻击与暴击威力。", _effect("attack_up", 8, 99), _effect("crit_up", 15, 99)),
       ]),
    _servant("qin_liangyu_lancer", "秦良玉", "Lancer", 5, 13700, 1270, "BAAQQ", [
        _skill("白杆兵法 A", 5, "全队提升攻击、防御和速度。", _effect("attack_up", 17, 3, "team"), _effect("defense_up", 17, 3, "team"), _effect("speed_up", 14, 3, "team")),
        _skill("忠勇的矛 B", 5, "自身获得 NP、暴击率与无敌贯通。", _effect("np_charge", 30), _effect("crit_chance_up", 30, 3), _effect("invincible_pierce", 1, 2)),
        _skill("守城之将 A", 6, "赋予己方单体防御、持续回血与一次弱化无效。", _effect("defense_up", 35, 3, "ally"), _effect("regen", 650, 3, "ally"), _effect("debuff_immunity", 1, 3, "ally")),
    ], "崇祯帝四诗歌", "A", "team", 0, [_effect("attack_up", 28, 3, "team"), _effect("defense_up", 28, 3, "team"), _effect("np_charge", 18, target="team")],
       "白杆不折，忠魂不散——诗歌铭记此战！", passives=[
           _passive("白杆军统帅", "全队永久提升防御。", _effect("defense_up", 7, 99, "team")),
       ]),
    _servant("bradamante_lancer", "布拉达曼特", "Lancer", 5, 12600, 1360, "BBAQQ", [
        _skill("魔术解除 A", 5, "解除己方单体弱化并回复生命与 NP。", _effect("debuff_cleanse", target="ally"), _effect("heal", 2000, target="ally"), _effect("np_charge", 20, target="ally")),
        _skill("骑士的荣光 B", 5, "自身强化攻击、Quick、速度与暴击星。", _effect("attack_up", 25, 3), _effect("card_up_q", 32, 3), _effect("speed_up", 22, 3), _effect("stars", 16)),
        _skill("罗兰之援 A", 6, "全队获得防御提升与一回合无敌。", _effect("defense_up", 20, 3, "team"), _effect("invincible", 1, 1, "team")),
    ], "目映群光的魔盾", "Q", "all", 420, [_effect("stun", 1, 1, "enemy_team"), _effect("stars", 20, target="team")],
       "骑士的誓约与光同在——魔盾，照耀前路！", passives=[
           _passive("查理曼的圣骑士", "永久提升 Quick 与速度。", _effect("card_up_q", 9, 99), _effect("speed_up", 8, 99)),
       ]),
    _servant("marie_antoinette_rider", "玛丽·安托瓦内特", "Rider", 5, 13900, 1200, "BAAQQ", [
        _skill("王统的音色 A", 5, "全队回复生命，并提升攻击与 NP 获取。", _effect("heal", 1600, target="team"), _effect("attack_up", 18, 3, "team"), _effect("np_gain_up", 22, 3, "team")),
        _skill("丽人的微笑 A", 6, "自身获得三次回避和持续回血。", _effect("evade", 3, 3), _effect("regen", 750, 3)),
        _skill("凡尔赛的祝福 B", 5, "全队获得暴击星与弱化无效，己方单体回复 NP。", _effect("stars", 15, target="team"), _effect("debuff_immunity", 1, 3, "team"), _effect("np_charge", 20, target="ally")),
    ], "百合王冠·灿然永恒", "A", "team", 0, [_effect("heal", 3100, target="team"), _effect("defense_up", 28, 3, "team"), _effect("np_per_turn", 8, 3, "team")],
       "愿每一朵花都能在此绽放——Vive la France！", passives=[
           _passive("王妃的慈爱", "全队永久获得少量持续回复。", _effect("regen", 250, 99, "team")),
       ]),
    _servant("nitocris_caster", "尼托克丽丝", "Caster", 5, 11900, 1330, "BAAAQ", [
        _skill("埃及魔术 A", 5, "大幅增加自身 NP 并强化 Arts。", _effect("np_charge", 50), _effect("card_up_a", 30, 3)),
        _skill("冥镜的诅咒 B", 5, "降低敌方全体防御并附加毒。", _effect("defense_down", 25, 3, "enemy_team"), _effect("poison", 650, 3, "enemy_team")),
        _skill("天空神的宠爱 A", 6, "解除自身弱化，回复生命并提升宝具威力。", _effect("debuff_cleanse"), _effect("heal", 2300), _effect("np_damage_up", 34, 2)),
    ], "冥镜宝典·亡灵之门", "A", "all", 430, [_effect("np_drain", 15, target="enemy_team"), _effect("poison", 950, 3, "enemy_team")],
       "镜中通往冥界之门——请安静地归还一切。", passives=[
           _passive("法老的神性", "开战获得 NP，永久提升 Arts。", _effect("np_charge", 15), _effect("card_up_a", 10, 99)),
       ]),
    _servant("anastasia_caster", "阿纳斯塔西娅", "Caster", 5, 12400, 1390, "BAAAQ", [
        _skill("透视之魔眼 A", 5, "提升自身 Arts、暴击率并获得无敌贯通。", _effect("card_up_a", 34, 3), _effect("crit_chance_up", 32, 3), _effect("invincible_pierce", 1, 2)),
        _skill("绝冻的气息 B", 5, "降低敌方全体攻击、速度并附加灼烧。", _effect("attack_down", 23, 3, "enemy_team"), _effect("speed_down", 22, 3, "enemy_team"), _effect("burn", 450, 3, "enemy_team")),
        _skill("妖精维伊 A", 6, "获得 NP、整轮无敌和持续回血。", _effect("np_charge", 35), _effect("invincible", 1, 1), _effect("regen", 700, 3)),
    ], "疾走·精灵眼球", "A", "all", 435, [_effect("defense_down", 28, 3, "enemy_team"), _effect("np_charge", 15)],
       "维伊，睁开眼睛吧——让寒夜见证王女的决意。", passives=[
           _passive("雪境的皇女", "永久提升防御与 Arts。", _effect("defense_up", 8, 99), _effect("card_up_a", 9, 99)),
       ]),
    _servant("mochizuki_chiyome_assassin", "望月千代女", "Assassin", 5, 11600, 1400, "BAQQQ", [
        _skill("甲贺流忍术 A", 5, "获得两次回避、速度与暴击率。", _effect("evade", 2, 2), _effect("speed_up", 24, 3), _effect("crit_chance_up", 32, 3)),
        _skill("祸津蛇之咒 B", 5, "一名敌人中毒、降防并减少 NP。", _effect("poison", 1000, 3, "enemy"), _effect("defense_down", 27, 3, "enemy"), _effect("np_drain", 20, target="enemy")),
        _skill("信浓巫女 A", 6, "自身增加 NP、强化 Quick 并获得暴击星。", _effect("np_charge", 30), _effect("card_up_q", 35, 3), _effect("stars", 20)),
    ], "口寄·伊吹大明神缘起", "Q", "single", 590, [_effect("poison", 1500, 3, "enemy"), _effect("stun", 1, 1, "enemy")],
       "祟神之蛇，依约现身——将一切吞下吧。", passives=[
           _passive("蛇神的契约", "永久提升速度与暴击威力。", _effect("speed_up", 10, 99), _effect("crit_up", 18, 99)),
       ]),
    _servant("europa_rider", "欧罗巴", "Rider", 5, 15000, 1190, "BBAAQ", [
        _skill("无垢的公主 A", 5, "全队回复生命并提升防御。", _effect("heal", 1800, target="team"), _effect("defense_up", 24, 3, "team")),
        _skill("神牛的庇护 B", 6, "自身获得整轮无敌、嘲讽和战续。", _effect("invincible", 1, 1), _effect("taunt", 1, 1), _effect("guts", 2600, 3)),
        _skill("白牛巡礼 A", 5, "全队增加 NP，提升 Arts 与暴击率。", _effect("np_charge", 22, target="team"), _effect("card_up_a", 22, 3, "team"), _effect("crit_chance_up", 18, 3, "team")),
    ], "青铜巨人·欧罗巴之梦", "B", "all", 410, [_effect("attack_down", 25, 3, "enemy_team"), _effect("heal", 2000, target="team")],
       "白牛会带我们越过大海——塔洛斯，请守护大家。", passives=[
           _passive("众生的祖母", "全队永久获得持续回血。", _effect("regen", 300, 99, "team")),
       ]),
    _servant("hecate_triple_moon_foreigner", "赫卡忒〔三相之月〕", "Foreigner", 6, 18400, 2040, "BAAAQ", [
        _skill("三岔路的钥匙 EX", 5, "全队获得 NP 与 Arts 强化，敌方全体降低防御。", _effect("np_charge", 30, target="team"), _effect("card_up_a", 30, 3, "team"), _effect("defense_down", 27, 3, "enemy_team")),
        _skill("夜炬魔女 A++", 6, "敌方全体降速、灼烧并削减 NP。", _effect("speed_down", 27, 3, "enemy_team"), _effect("burn", 1100, 3, "enemy_team"), _effect("np_drain", 20, target="enemy_team")),
        _skill("三月守门 EX", 6, "全队获得整轮无敌、弱化无效与持续 NP。", _effect("invincible", 1, 1, "team"), _effect("debuff_immunity", 2, 3, "team"), _effect("np_per_turn", 8, 3, "team")),
    ], "三相月轮·万门齐开", "A", "all", 570, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("burn", 1600, 3, "enemy_team")],
       "三条道路在此交汇——以月之火，开启所有的门。", event_only=True, passives=[
           _passive("冥途守钥者", "开战全队获得 15% NP，自身永久提升 Arts。", _effect("np_charge", 15, target="team"), _effect("card_up_a", 14, 99)),
       ]),
    _servant("athena_aegis_ruler", "雅典娜〔神盾〕", "Ruler", 6, 20200, 1950, "BBAAQ", [
        _skill("神盾埃癸斯 EX", 6, "全队整轮无敌，自身嘲讽并反弹承受伤害。", _effect("invincible", 1, 1, "team"), _effect("taunt", 1, 1), _effect("damage_reflect", 50, 2)),
        _skill("帕拉斯之策 A++", 5, "全队强化攻击、暴击率和速度。", _effect("attack_up", 29, 3, "team"), _effect("crit_chance_up", 28, 3, "team"), _effect("speed_up", 18, 3, "team")),
        _skill("胜利女神之眸 EX", 6, "敌方全体降低攻击与防御，己方全体缩短冷却。", _effect("attack_down", 30, 3, "enemy_team"), _effect("defense_down", 30, 3, "enemy_team"), _effect("cooldown_reduce", 1, target="team")),
    ], "帕拉斯·不可陨落之城", "A", "team", 0, [_effect("heal", 3800, target="team"), _effect("defense_up", 38, 3, "team"), _effect("np_charge", 25, target="team")],
       "城墙由每一个人的意志筑成——神盾，绝不失守。", event_only=True, passives=[
           _passive("智慧战争女神", "全队永久提升防御与暴击威力。", _effect("defense_up", 11, 99, "team"), _effect("crit_up", 12, 99, "team")),
       ]),
    _servant("sun_wukong_star_alterego", "孙悟空〔齐天星君〕", "AlterEgo", 6, 18800, 2150, "BBBAQ", [
        _skill("七十二变化 EX", 5, "自身获得回避、速度、暴击率与大量暴击星。", _effect("evade", 2, 2), _effect("speed_up", 35, 3), _effect("crit_chance_up", 38, 3), _effect("stars", 25)),
        _skill("火眼金睛 A++", 5, "看破敌方全体强化并降防，自身获得无敌贯通。", _effect("buff_remove", target="enemy_team"), _effect("defense_down", 32, 3, "enemy_team"), _effect("invincible_pierce", 1, 2)),
        _skill("不死金身 EX", 6, "回复生命，获得战续、攻击与暴击威力。", _effect("heal", 2700), _effect("guts", 3400, 3), _effect("attack_up", 35, 3), _effect("crit_up", 55, 3)),
    ], "如意金箍·十万八千里", "B", "all", 610, [_effect("speed_down", 30, 3, "enemy_team"), _effect("stars", 25, target="team")],
       "筋斗云，借个道——这一棒，直上九霄！", event_only=True, passives=[
           _passive("齐天大圣", "永久提升速度、攻击与暴击率。", _effect("speed_up", 14, 99), _effect("attack_up", 14, 99), _effect("crit_chance_up", 12, 99)),
       ]),
    _servant("arthur_prototype_saber", "亚瑟〔原型圣剑〕", "Saber", 6, 19300, 2110, "BBBAQ", [
        _skill("圣剑十三拘束 EX", 5, "自身强化攻击、Buster 与宝具威力，并增加 NP。", _effect("attack_up", 36, 3), _effect("card_up_b", 40, 3), _effect("np_damage_up", 40, 2), _effect("np_charge", 45)),
        _skill("王者的守护 A++", 6, "全队获得整轮无敌、回复生命和一次弱化无效。", _effect("invincible", 1, 1, "team"), _effect("heal", 1700, target="team"), _effect("debuff_immunity", 1, 3, "team")),
        _skill("遥远理想的骑士 EX", 5, "全队提升攻击与速度，自身获得暴击率和无敌贯通。", _effect("attack_up", 25, 3, "team"), _effect("speed_up", 18, 3, "team"), _effect("crit_chance_up", 32, 3), _effect("invincible_pierce", 1, 2)),
    ], "誓约胜利之剑·十三解放", "B", "all", 640, [_effect("invincible_pierce", 1, 1, timing="pre"), _effect("defense_down", 35, 3, "enemy_team")],
       "十三拘束，议决开始——圣剑，照亮世界的未来！", event_only=True, passives=[
           _passive("骑士王的约定", "开战全队获得 NP，永久提升攻击。", _effect("np_charge", 18, target="team"), _effect("attack_up", 9, 99, "team")),
       ]),
    _servant("zheng_he_starsea_rider", "郑和〔星海提督〕", "Rider", 5, 13200, 1370, "BBAQQ", [
        _skill("星槎统御 A+", 6, "提升全队攻击力与 NP 获取。", _effect("attack_up", 24, 3, "team"), _effect("np_gain_up", 26, 3, "team")),
        _skill("牵星罗盘 EX", 5, "增加自身 NP，提升速度并获得必中。", _effect("np_charge", 40), _effect("speed_up", 24, 3), _effect("sure_hit", 1, 3)),
        _skill("宝船万里 B", 6, "提升全队防御，回复生命并获得暴击星。", _effect("defense_up", 22, 3, "team"), _effect("heal", 1800, target="team"), _effect("stars", 18, target="team")),
    ], "混一海图·万邦星路", "B", "all", 460, [_effect("defense_down", 24, 3, "enemy_team"), _effect("np_drain", 15, target="enemy_team")],
       "星辰为标，沧海为途——宝船列阵，开辟万邦星路！", event_only=True, passives=[
           _passive("四海通舶", "开战时全队获得 NP，并永久提升 NP 获取。", _effect("np_charge", 12, target="team"), _effect("np_gain_up", 10, 99, "team")),
       ]),
    _servant("hypatia_astral_caster", "希帕提娅〔星轨学者〕", "Caster", 5, 12100, 1390, "BAAAQ", [
        _skill("天球演算 A++", 5, "强化全队 Arts 与 NP 获取。", _effect("card_up_a", 30, 3, "team"), _effect("np_gain_up", 28, 3, "team")),
        _skill("圆锥曲线结界 B", 6, "赋予一名队友无敌与弱化无效。", _effect("invincible", 1, 1, "ally"), _effect("debuff_immunity", 2, 3, "ally")),
        _skill("亚历山大晨星 EX", 6, "增加自身 NP，并缩短全队技能冷却。", _effect("np_charge", 55), _effect("cooldown_reduce", 1, target="team")),
    ], "阿斯特拉比翁·群星证明", "A", "team", 0, [_effect("heal", 2600, target="team"), _effect("np_charge", 25, target="team"), _effect("stars_per_turn", 10, 3, "team")],
       "让推演越过黑夜——群星会证明，真理从未熄灭。", event_only=True, passives=[
           _passive("缪斯神殿的学者", "永久提升全队 Arts 与暴击率。", _effect("card_up_a", 8, 99, "team"), _effect("crit_chance_up", 8, 99, "team")),
       ]),
    _servant("hou_yi_eclipse_archer", "后羿〔逐蚀神弓〕", "Archer", 5, 11600, 1450, "BBAQQ", [
        _skill("九日之瞳 EX", 5, "提升暴击率与暴击威力，并获得暴击星。", _effect("crit_chance_up", 40, 3), _effect("crit_up", 55, 3), _effect("stars", 20)),
        _skill("落日神射 A++", 6, "提升攻击与特攻，并获得无敌贯通。", _effect("attack_up", 32, 3), _effect("trait_damage_up", 38, 3), _effect("invincible_pierce", 1, 2)),
        _skill("月桂清辉 B", 6, "获得回避，回复生命并增加 NP。", _effect("evade", 1), _effect("heal", 2200), _effect("np_charge", 35)),
    ], "九曜坠天·金乌尽灭", "B", "single", 580, [_effect("defense_down", 30, 3, "enemy"), _effect("burn", 1200, 3, "enemy")],
       "天有十日，我留其一——九曜坠落，长夜退散！", event_only=True, passives=[
           _passive("射日者", "永久提升攻击、暴击威力与必中。", _effect("attack_up", 10, 99), _effect("crit_up", 18, 99), _effect("sure_hit", 1, 99)),
       ]),
    _servant("tomoe_winter_saber", "巴御前〔雪祭剑姬〕", "Saber", 5, 12400, 1410, "BBQQQ", [
        _skill("霜华一闪 A+", 5, "强化 Quick，提升速度与暴击威力。", _effect("card_up_q", 36, 3), _effect("speed_up", 26, 3), _effect("crit_up", 42, 3)),
        _skill("月下雪见 B", 5, "获得回避、暴击星与暴击率提升。", _effect("evade", 1), _effect("stars", 22), _effect("crit_chance_up", 35, 3)),
        _skill("御前之誓 A", 6, "提升全队攻击力并解除弱化。", _effect("attack_up", 22, 3, "team"), _effect("debuff_cleanse", target="team")),
    ], "白岭冻月·鬼火乱刃", "Q", "all", 430, [_effect("speed_down", 28, 3, "enemy_team"), _effect("stun", 1, 1, "enemy_team")],
       "雪月照刃，鬼火为华——白岭冻月，一骑尽斩！", event_only=True, passives=[
           _passive("雪原骑射", "永久提升 Quick、速度与暴击星获取。", _effect("card_up_q", 10, 99), _effect("speed_up", 10, 99), _effect("star_gain_up", 16, 99)),
       ]),
    _servant("sun_wukong_heaven_lancer", "孙悟空〔齐天行者〕", "Lancer", 6, 18100, 2180, "BBQQQ", [
        _skill("七十二变 EX", 5, "获得回避，解除弱化并提升暴击威力。", _effect("evade", 2), _effect("debuff_cleanse"), _effect("crit_up", 60, 3)),
        _skill("筋斗云 A++", 5, "大幅提升速度，增加 NP 并强化 Quick。", _effect("speed_up", 40, 3), _effect("np_charge", 55), _effect("card_up_q", 42, 3)),
        _skill("如意金箍棒 EX", 6, "提升攻击与特攻，并获得无敌贯通。", _effect("attack_up", 45, 3), _effect("trait_damage_up", 48, 3), _effect("invincible_pierce", 1, 3)),
    ], "大闹天宫·万钧如意", "B", "all", 660, [_effect("defense_down", 40, 3, "enemy_team"), _effect("stun", 1, 1, "enemy_team")],
       "老孙来也——一棒掀翻凌霄，齐天大圣在此！", event_only=True, passives=[
           _passive("齐天大圣", "开战获得 NP，永久提升攻击、速度与暴击率。", _effect("np_charge", 30), _effect("attack_up", 15, 99), _effect("speed_up", 15, 99), _effect("crit_chance_up", 15, 99)),
       ]),
    _servant("wu_zhao_phoenix_ruler", "武曌〔曦凰天后〕", "Ruler", 6, 19400, 2040, "BBAAQ", [
        _skill("曦凰临朝 EX", 5, "提升全队攻防并增加 NP。", _effect("attack_up", 30, 3, "team"), _effect("defense_up", 28, 3, "team"), _effect("np_charge", 25, target="team")),
        _skill("明镜照罪 A++", 6, "降低敌方全体攻防与速度。", _effect("attack_down", 28, 3, "enemy_team"), _effect("defense_down", 32, 3, "enemy_team"), _effect("speed_down", 24, 3, "enemy_team")),
        _skill("无字天命 EX", 6, "赋予一名队友无敌，缩短冷却并增加 NP。", _effect("invincible", 1, 1, "ally"), _effect("cooldown_reduce", 2, target="ally"), _effect("np_charge", 35, target="ally")),
    ], "日月当空·神都凤阙", "A", "team", 0, [_effect("heal", 3800, target="team"), _effect("guts", 2800, 3, "team"), _effect("np_per_turn", 10, 3, "team")],
       "日月当空，凤阙开天——此世功过，由朕亲自裁定。", event_only=True, passives=[
           _passive("天授圣图", "全队永久提升防御与 NP 获取。", _effect("defense_up", 12, 99, "team"), _effect("np_gain_up", 12, 99, "team")),
       ]),
    _servant("sinbad_sevenseas_rider", "辛巴达〔七海航星〕", "Rider", 6, 18300, 2130, "BAAQQ", [
        _skill("七航传奇 EX", 5, "提升攻击、Quick 与 NP 获取。", _effect("attack_up", 38, 3), _effect("card_up_q", 40, 3), _effect("np_gain_up", 38, 3)),
        _skill("大鹏之翼 A+", 5, "提升速度，获得回避与暴击星。", _effect("speed_up", 34, 3), _effect("evade", 2), _effect("stars", 25)),
        _skill("海王宝库 A++", 6, "全队增加 NP、暴击星与暴击率。", _effect("np_charge", 30, target="team"), _effect("stars", 18, target="team"), _effect("crit_chance_up", 30, 3, "team")),
    ], "七海尽头·翡翠航路", "A", "all", 610, [_effect("np_drain", 25, target="enemy_team"), _effect("defense_down", 35, 3, "enemy_team")],
       "第七次航海尚未结束——海门洞开，向世界尽头进发！", event_only=True, passives=[
           _passive("七海征服者", "开战时全队获得 NP，自身永久提升速度。", _effect("np_charge", 15, target="team"), _effect("speed_up", 18, 99)),
       ]),
    _servant("atalanta_aurora_archer", "阿塔兰忒〔极光猎手〕", "Archer", 6, 17600, 2200, "BAQQQ", [
        _skill("极光疾走 A++", 5, "强化 Quick，提升速度与暴击威力。", _effect("card_up_q", 48, 3), _effect("speed_up", 36, 3), _effect("crit_up", 58, 3)),
        _skill("星座箭雨 EX", 6, "全队获得暴击星、持续暴击星与暴击率。", _effect("stars", 24, target="team"), _effect("stars_per_turn", 12, 3, "team"), _effect("crit_chance_up", 32, 3, "team")),
        _skill("圣兽狩猎 A+", 5, "获得无敌贯通，并提升攻击与特攻。", _effect("invincible_pierce", 1, 3), _effect("attack_up", 42, 3), _effect("trait_damage_up", 50, 3)),
    ], "北辰天穹·苍猎星雨", "Q", "all", 620, [_effect("speed_down", 38, 3, "enemy_team"), _effect("crit_chance_down", 35, 3, "enemy_team")],
       "奔跑吧，群星的箭矢——极光之下，无处可逃！", event_only=True, passives=[
           _passive("阿尔卡迪亚的猎风", "永久提升 Quick、速度与暴击率。", _effect("card_up_q", 14, 99), _effect("speed_up", 14, 99), _effect("crit_chance_up", 12, 99)),
       ]),
    _servant("nuwa_genesis_alterego", "女娲〔补天创世〕", "AlterEgo", 7, 24800, 2480, "BBAAQ", [
        _skill("五色神石 EX", 5, "大幅提升全队防御，回复生命并持续再生。", _effect("defense_up", 42, 3, "team"), _effect("heal", 3600, target="team"), _effect("regen", 1200, 3, "team")),
        _skill("抟土造生 EX", 5, "缩短全队冷却，增加 NP 并解除弱化。", _effect("cooldown_reduce", 2, target="team"), _effect("np_charge", 35, target="team"), _effect("debuff_cleanse", target="team")),
        _skill("天倾地维 EX", 6, "全队获得对肃正防御与战斗续行。", _effect("solemn_defense", 1, 1, "team"), _effect("guts", 4500, 4, "team")),
    ], "炼石补天·万象再编", "A", "team", 0, [_effect("heal", 6000, target="team"), _effect("np_charge", 45, target="team"), _effect("invincible", 1, 1, "team")],
       "五色炼石，重系天维——万象归位，众生再启！", event_only=True, passives=[
           _passive("大地母神", "全队永久提升攻防并持续回复生命。", _effect("attack_up", 15, 99, "team"), _effect("defense_up", 18, 99, "team"), _effect("regen", 700, 99, "team")),
       ]),
    _servant("odin_runeking_foreigner", "奥丁〔万象卢恩〕", "Foreigner", 7, 23200, 2590, "BBAAQ", [
        _skill("万象卢恩 EX", 5, "强化全队三色与 NP 获取，并缩短冷却。", _effect("card_up_all", 36, 3, "team"), _effect("np_gain_up", 35, 3, "team"), _effect("cooldown_reduce", 1, target="team")),
        _skill("冈格尼尔·原典 EX", 5, "强化攻击与暴击，并获得无敌贯通。", _effect("attack_up", 50, 3), _effect("crit_up", 75, 3), _effect("invincible_pierce", 1, 3)),
        _skill("双鸦观世 A++", 6, "降低敌方全体防御、速度与暴击率。", _effect("defense_down", 42, 3, "enemy_team"), _effect("speed_down", 35, 3, "enemy_team"), _effect("crit_chance_down", 40, 3, "enemy_team")),
    ], "诸神黄昏·世界树倒悬", "B", "all", 720, [_effect("buff_remove", target="enemy_team", timing="pre"), _effect("stun", 1, 1, "enemy_team"), _effect("defense_down", 45, 3, "enemy_team")],
       "以独眼见证终局——九界倒悬，诸神黄昏就此降临！", event_only=True, passives=[
           _passive("悬于世界树者", "开战获得大量 NP，永久提升攻击与 NP 威力。", _effect("np_charge", 45), _effect("attack_up", 18, 99), _effect("np_damage_up", 22, 99)),
       ]),
    _servant("amaterasu_dawn_beast", "天照〔万曦御灵〕", "Beast", 7, 24100, 2540, "BAAAQ", [
        _skill("八咫明镜 EX", 5, "提升全队攻击、Arts 并增加 NP。", _effect("attack_up", 38, 3, "team"), _effect("card_up_a", 42, 3, "team"), _effect("np_charge", 30, target="team")),
        _skill("天岩户开 EX", 6, "全队获得整轮无敌、持续回复与弱化无效。", _effect("invincible", 1, 1, "team"), _effect("regen", 1400, 3, "team"), _effect("debuff_immunity", 2, 3, "team")),
        _skill("八重曦光 A++", 5, "全队获得暴击星，并提升暴击率与暴击威力。", _effect("stars", 28, target="team"), _effect("crit_chance_up", 42, 3, "team"), _effect("crit_up", 65, 3, "team")),
    ], "高天原·万世天照", "A", "all", 700, [_effect("burn", 1800, 3, "enemy_team"), _effect("defense_down", 42, 3, "enemy_team"), _effect("np_drain", 30, target="enemy_team")],
       "岩户既开，长夜终结——照临万世，高天原！", event_only=True, passives=[
           _passive("日轮御魂", "开战时全队获得 NP，永久提升攻击并持续回复。", _effect("np_charge", 25, target="team"), _effect("attack_up", 16, 99, "team"), _effect("regen", 600, 99, "team")),
       ]),
    _servant("prometheus_firstfire_pretender", "普罗米修斯〔原初之火〕", "Pretender", 7, 22600, 2630, "BBBAQ", [
        _skill("盗火者 EX", 5, "提升全队攻击，并持续获得 NP 与暴击星。", _effect("attack_up", 40, 3, "team"), _effect("np_per_turn", 14, 3, "team"), _effect("stars_per_turn", 14, 3, "team")),
        _skill("先见之明 A++", 5, "全队获得回避，并提升暴击率与速度。", _effect("evade", 1, 1, "team"), _effect("crit_chance_up", 38, 3, "team"), _effect("speed_up", 24, 3, "team")),
        _skill("解缚高加索 EX", 6, "解除全队弱化，自身获得无敌贯通与特攻。", _effect("debuff_cleanse", target="team"), _effect("invincible_pierce", 1, 3), _effect("trait_damage_up", 58, 3)),
    ], "人理黎明·永不熄灭之火", "B", "all", 730, [_effect("burn", 2000, 3, "enemy_team"), _effect("execute", 18, target="enemy_team")],
       "这火焰不属于神——人类啊，以自己的双手点亮黎明！", event_only=True, passives=[
           _passive("不屈的盗火者", "永久提升攻击与 Buster，首次倒下时复起。", _effect("attack_up", 20, 99), _effect("card_up_b", 18, 99), _effect("guts", 5000, 99)),
       ]),
]


NP_QUOTES = {
    "artoria_saber": "汇聚的星之吐息——照亮终焉吧，誓约胜利之剑！",
    "nero_saber": "喝彩吧！此处正是余之黄金剧场！",
    "caesar_saber": "胜利早已写在交易之中——黄之死！",
    "gilgamesh_archer": "仰望吧，开辟天地的原初之星！",
    "emiya_archer": "此身即为无限之剑所成。",
    "robin_archer": "森林会记住你的罪——祈祷之弓！",
    "cu_lancer": "此枪必中其心——刺穿死棘之枪！",
    "scathach_lancer": "跨越死境吧——贯穿死翔之枪！",
    "leonidas_lancer": "此处绝不后退——炎门的守护者！",
    "medusa_rider": "解放缰绳，冲破天穹——骑英之缰绳！",
    "iskandar_rider": "远征仍未结束——王之军势！",
    "ushiwakamaru_rider": "越过八艘，取下敌将——坛之浦·八艘跳！",
    "medea_caster": "一切契约皆可斩断——万疵必应修补！",
    "waver_caster": "乾坤布阵，八门皆闭——石兵八阵！",
    "hans_caster": "这并非童话，而是为你撰写的人生。",
    "jack_assassin": "雾都已封闭——解体圣母。",
    "hundred_faces_assassin": "一为百，百为一——妄想幻像！",
    "kojiro_assassin": "三途同时斩落——燕返！",
    "heracles_berserker": "九击合一——射杀百头！",
    "kiyohime_berserker": "谎言就烧尽吧——转身火生三昧！",
    "mash_shielder": "此处即为守护众人的城墙——已然遥远的理想之城！",
    "aesc_savior": "此乃通往明日的巡礼——在尽头，仍有希望。",
    "morgan_queen": "跪下吧。此处即是我的不列颠，我的王座。",
    "draco_beast": "喝彩吧，坠落吧——余乃盛宴尽头的兽。",
    "tiamat_mother": "孩子们，无需恐惧。母亲会拥抱一切。",
    "artoria_event_saber": "群星汇聚于王冠——此剑将照亮最后的胜利！",
    "castoria_caster": "即使旅途抵达尽头，愿这颗星仍守护你。",
    "mordred_saber": "这是对完美之王的叛逆——Clarent Blood Arthur！",
    "gilgamesh_event_archer": "见识原初的地狱吧——天地乖离，开辟之星！",
    "lord_logres_saber": "所有誓约在此归于一剑——Excalibur Excelsus！",
    "aesc_final_caster": "若巡礼终将结束，就让最后的星替所有人照亮归途。",
    "jeanne_ruler": "此旗聚集所有祈愿——吾主在此，永恒光辉！",
    "merlin_caster": "那里无罪亦无悲——开启吧，永世隔绝的理想乡。",
    "ishtar_archer": "从金星到冥界，全都给我贯穿——An Gal Ta Kigal！",
    "ereshkigal_lancer": "冥界并非终点——Kur Kigal Irkalla，拥抱他们吧！",
    "aesc_rainwitch_caster": "雨会停下，而巡礼不会——让最后的钟声引领未来。",
    "medusa_anime_rider": "解放缰绳——以天马之光粉碎一切，Bellerophon！",
    "artoria_avalon_saber": "此剑连接理想乡——于终焉归还胜利，Excalibur Avalon！",
    "gilgamesh_golden_archer": "认清王与臣的差距吧——天地乖离，开辟之星！",
    "ishtar_rin_archer": "看好了，这就是女神与远坂凛的全力——An Gal Ta Kigal！",
    "gilgamesh_uruk_caster": "乌鲁克仍在此处！仰望王之号炮——Melammu Dingir！",
    "astraea_ruler": "以星之天秤宣告裁决——接受淑女的最后一击吧！",
    "artoria_crowned_avalon_saber": "群星为冠，理想乡为鞘——让终焉也向胜利俯首！",
    "aesc_genesis_caster": "十二道钟声将雨化作星——这一次，巡礼会抵达幸福的明日。",
    "oberon_vortigern_pretender": "童话已经闭幕——坠入连梦也无法抵达的奈落吧。",
    "space_ishtar_origin_avenger": "善与恶皆归于银河——见证原始女神的宇宙吧！",
    "artoria_azure_star_saber": "苍星为冠，白龙为证——于理想乡尽头，解放圣剑！",
    "ciel_executor_mooncancer": "代行结束——让卡尔瓦利亚之星在此完成最终断罪！",
    "archetype_earth_princess_mooncancer": "月之王庭已经降临——于千年城中，见证星球的梦。",
    "arcueid_lunar_berserker": "抓到你了——就用这轮红月，把一切撕开！",
    "aoko_fifth_magic_foreigner": "过去与未来都让开——这就是只属于现在的第五魔法！",
    "ryougi_shiki_void_assassin": "若万物都有终点——那条线，我已经看见了。",
    "alice_kuonji_fairy_caster": "月夜的童话已合上书页——那么，请在钟声里安眠。",
    "rin_jewel_mage_caster": "倾尽百年的光吧——这一击可贵得足够买下一座城！",
    "sakura_black_grail_avenger": "如果世界只会伤害所爱之人——那就由影子把一切带走。",
    "jeanne_alter_dragon_avenger": "此身为憎恶所铸——咆哮吧，连同世界一起燃尽！",
    "kama_assassin": "无论逃到哪里，爱都会找到你——燃烧吧，魔罗之花。",
    "senji_muramasa_saber": "此身只为锻成一刀——斩断宿业，无元之剑制！",
    "ryougi_shiki_assassin": "活着的东西，就算是神也杀给你看。",
    "olga_marie_foreigner": "观测完成——以阿尼姆斯菲亚之名，展开天球演算！",
    "scathach_skadi_caster": "冰雪会为勇士让路——开启吧，通往魔境的门！",
    "melusine_lancer": "展开龙翼——让尽头的天空记住这道光！",
    "koyanskaya_light_assassin": "NFF服务时间到——以最先进的火力清场吧！",
    "semiramis_assassin": "升起吧，空中庭园——女帝的毒将覆盖战场。",
    "musashi_saber": "南无天满大自在天神——这一刀，斩断六道！",
    "jeanne_archer_summer": "让海风把祈愿送到每个人身边——一起向前吧！",
    "nero_star_bride_beast": "奏响婚礼的喝彩吧——星海也将成为余的黄金剧场！",
    "mash_decisive_shielder": "前辈，请看着我——这就是守护人理的最后一击！",
    "okita_souji_saber": "一步超音，二步无间——无明三段突！",
    "minamoto_raikou_berserker": "以母之雷霆扫清魔性——牛王招雷，天网恢恢！",
    "tamamo_no_mae_caster": "祓除灾厄，结缘良缘——水天日光，照临此处！",
    "katsushika_hokusai_foreigner": "笔走龙蛇，浪卷富岳——且看这神奈川冲浪里！",
    "bb_moon_nurse_mooncancer": "病历确认——由万能后辈为你执行月之诊疗！",
    "brynhild_lancer": "爱与死亡同在——直至死亡将你我拆散！",
    "taira_kagekiyo_avenger": "闻祇园钟声——源氏，必灭！",
    "cleopatra_assassin": "见证最后的法老之美——终焉闪耀之蛇！",
    "artoria_rhongomyniad_lancer": "锚定星球，维系风暴——闪耀于终焉之枪！",
    "ibuki_amano_murakumo_saber": "山河为酒，大蛇为刃——天丛云，开天！",
    "kukulkan_solar_foreigner": "这颗心就是太阳——飞翔吧，新的太阳纪元！",
    "solomon_grand_caster": "以冠位之名归还一切——诞生之时已至，戴冠之时已至！",
    "altera_saber": "文明亦可化作光带——军神之剑，横扫大地！",
    "sei_shonagon_archer": "春曙、夏夜、秋暮、冬晨——把闪耀的瞬间全部记下来！",
    "valkyrie_lancer": "奥特琳德、希露德、斯露德——引导勇士前往终末！",
    "ozymandias_rider": "太阳在此俯瞰万物——跪拜吧，光辉大复合神殿！",
    "murasaki_shikibu_caster": "翻开物语吧——那些被隐藏的心，也将在文字中显形。",
    "shuten_douji_assassin": "这杯酒可甜得很——饮下吧，连骨头都染成我的颜色。",
    "xiang_yu_berserker": "演算结束——力拔山兮，气盖世！",
    "yang_guifei_foreigner": "星火啊，奏响霓裳羽衣——愿这份爱燃至宇宙尽头。",
    "artoria_black_dragon_saber": "圣剑已被龙焰染黑——在终焉中宣告胜利！",
    "arjuna_alter_berserker": "不完美的世界无需留存——归灭，而后重生。",
    "kingprotea_alterego": "大、大、大到整个世界都装不下——帝王花，要压过去了！",
    "lady_avalon_pretender": "从梦的彼岸献上花冠——理想乡的大门一直为你敞开。",
    "tomoe_gozen_archer": "火焰记得每一个名字——此箭为守护而放！",
    "qin_liangyu_lancer": "白杆不折，忠魂不散——诗歌铭记此战！",
    "bradamante_lancer": "骑士的誓约与光同在——魔盾，照耀前路！",
    "marie_antoinette_rider": "愿每一朵花都能在此绽放——Vive la France！",
    "nitocris_caster": "镜中通往冥界之门——请安静地归还一切。",
    "anastasia_caster": "维伊，睁开眼睛吧——让寒夜见证王女的决意。",
    "mochizuki_chiyome_assassin": "祟神之蛇，依约现身——将一切吞下吧。",
    "europa_rider": "白牛会带我们越过大海——塔洛斯，请守护大家。",
    "hecate_triple_moon_foreigner": "三条道路在此交汇——以月之火，开启所有的门。",
    "athena_aegis_ruler": "城墙由每一个人的意志筑成——神盾，绝不失守。",
    "sun_wukong_star_alterego": "筋斗云，借个道——这一棒，直上九霄！",
    "arthur_prototype_saber": "十三拘束，议决开始——圣剑，照亮世界的未来！",
    "zheng_he_starsea_rider": "星辰为标，沧海为途——宝船列阵，开辟万邦星路！",
    "hypatia_astral_caster": "让推演越过黑夜——群星会证明，真理从未熄灭。",
    "hou_yi_eclipse_archer": "天有十日，我留其一——九曜坠落，长夜退散！",
    "tomoe_winter_saber": "雪月照刃，鬼火为华——白岭冻月，一骑尽斩！",
    "sun_wukong_heaven_lancer": "老孙来也——一棒掀翻凌霄，齐天大圣在此！",
    "wu_zhao_phoenix_ruler": "日月当空，凤阙开天——此世功过，由朕亲自裁定。",
    "sinbad_sevenseas_rider": "第七次航海尚未结束——海门洞开，向世界尽头进发！",
    "atalanta_aurora_archer": "奔跑吧，群星的箭矢——极光之下，无处可逃！",
    "nuwa_genesis_alterego": "五色炼石，重系天维——万象归位，众生再启！",
    "odin_runeking_foreigner": "以独眼见证终局——九界倒悬，诸神黄昏就此降临！",
    "amaterasu_dawn_beast": "岩户既开，长夜终结——照临万世，高天原！",
    "prometheus_firstfire_pretender": "这火焰不属于神——人类啊，以自己的双手点亮黎明！",
}

SERVANT_SPEEDS = {
    "artoria_saber": 104,
    "nero_saber": 102,
    "caesar_saber": 103,
    "gilgamesh_archer": 106,
    "emiya_archer": 108,
    "robin_archer": 111,
    "cu_lancer": 114,
    "scathach_lancer": 116,
    "leonidas_lancer": 82,
    "medusa_rider": 119,
    "iskandar_rider": 94,
    "ushiwakamaru_rider": 118,
    "medea_caster": 101,
    "waver_caster": 90,
    "hans_caster": 89,
    "jack_assassin": 124,
    "hundred_faces_assassin": 113,
    "kojiro_assassin": 121,
    "heracles_berserker": 84,
    "kiyohime_berserker": 97,
    "mash_shielder": 92,
    "aesc_savior": 98,
    "morgan_queen": 96,
    "draco_beast": 100,
    "tiamat_mother": 86,
    "artoria_event_saber": 109,
    "castoria_caster": 112,
    "mordred_saber": 111,
    "gilgamesh_event_archer": 110,
    "lord_logres_saber": 115,
    "aesc_final_caster": 108,
    "jeanne_ruler": 92,
    "merlin_caster": 100,
    "ishtar_archer": 118,
    "ereshkigal_lancer": 104,
    "aesc_rainwitch_caster": 111,
    "medusa_anime_rider": 126,
    "artoria_avalon_saber": 116,
    "gilgamesh_golden_archer": 119,
    "ishtar_rin_archer": 124,
    "gilgamesh_uruk_caster": 105,
    "astraea_ruler": 122,
    "artoria_crowned_avalon_saber": 130,
    "aesc_genesis_caster": 127,
    "oberon_vortigern_pretender": 134,
    "space_ishtar_origin_avenger": 136,
    "artoria_azure_star_saber": 133,
    "ciel_executor_mooncancer": 140,
    "archetype_earth_princess_mooncancer": 129,
    "arcueid_lunar_berserker": 142,
    "aoko_fifth_magic_foreigner": 141,
    "ryougi_shiki_void_assassin": 145,
    "alice_kuonji_fairy_caster": 132,
    "rin_jewel_mage_caster": 143,
    "sakura_black_grail_avenger": 128,
    "jeanne_alter_dragon_avenger": 138,
    "kama_assassin": 128,
    "senji_muramasa_saber": 121,
    "ryougi_shiki_assassin": 137,
    "olga_marie_foreigner": 109,
    "scathach_skadi_caster": 113,
    "melusine_lancer": 139,
    "koyanskaya_light_assassin": 135,
    "semiramis_assassin": 108,
    "musashi_saber": 126,
    "jeanne_archer_summer": 121,
    "nero_star_bride_beast": 137,
    "mash_decisive_shielder": 116,
    "okita_souji_saber": 146,
    "minamoto_raikou_berserker": 112,
    "tamamo_no_mae_caster": 105,
    "katsushika_hokusai_foreigner": 123,
    "bb_moon_nurse_mooncancer": 120,
    "brynhild_lancer": 125,
    "taira_kagekiyo_avenger": 141,
    "cleopatra_assassin": 132,
    "artoria_rhongomyniad_lancer": 128,
    "ibuki_amano_murakumo_saber": 130,
    "kukulkan_solar_foreigner": 144,
    "solomon_grand_caster": 118,
    "altera_saber": 120,
    "sei_shonagon_archer": 134,
    "valkyrie_lancer": 126,
    "ozymandias_rider": 110,
    "murasaki_shikibu_caster": 107,
    "shuten_douji_assassin": 129,
    "xiang_yu_berserker": 116,
    "yang_guifei_foreigner": 131,
    "artoria_black_dragon_saber": 132,
    "arjuna_alter_berserker": 127,
    "kingprotea_alterego": 88,
    "lady_avalon_pretender": 138,
    "tomoe_gozen_archer": 128,
    "qin_liangyu_lancer": 117,
    "bradamante_lancer": 124,
    "marie_antoinette_rider": 111,
    "nitocris_caster": 106,
    "anastasia_caster": 115,
    "mochizuki_chiyome_assassin": 139,
    "europa_rider": 102,
    "hecate_triple_moon_foreigner": 131,
    "athena_aegis_ruler": 121,
    "sun_wukong_star_alterego": 147,
    "arthur_prototype_saber": 135,
    "zheng_he_starsea_rider": 125,
    "hypatia_astral_caster": 117,
    "hou_yi_eclipse_archer": 139,
    "tomoe_winter_saber": 142,
    "sun_wukong_heaven_lancer": 154,
    "wu_zhao_phoenix_ruler": 123,
    "sinbad_sevenseas_rider": 148,
    "atalanta_aurora_archer": 156,
    "nuwa_genesis_alterego": 121,
    "odin_runeking_foreigner": 147,
    "amaterasu_dawn_beast": 145,
    "prometheus_firstfire_pretender": 151,
}


CLASS_PASSIVES = {
    "Saber": _passive("对魔力", "开战时获得一次弱化无效。", _effect("debuff_immunity", 1, 99)),
    "Archer": _passive("单独行动", "暴击威力永久提升 15%。", _effect("crit_up", 15, 99)),
    "Lancer": _passive("战斗续行", "首次倒下时以 800 HP 复起。", _effect("guts", 800, 99)),
    "Rider": _passive("骑乘", "Quick 性能永久提升 12%。", _effect("card_up_q", 12, 99)),
    "Caster": _passive("阵地作成", "Arts 性能永久提升 12%。", _effect("card_up_a", 12, 99)),
    "Assassin": _passive("气息遮断", "暴击星获取永久提升 20%。", _effect("star_gain_up", 20, 99)),
    "Berserker": _passive("狂化", "Buster 性能永久提升 15%。", _effect("card_up_b", 15, 99)),
    "Shielder": _passive("守护骑士", "防御力永久提升 10%。", _effect("defense_up", 10, 99)),
    "Ruler": _passive("神明裁决", "防御力与弱化耐性得到强化。", _effect("defense_up", 10, 99), _effect("debuff_immunity", 1, 99)),
    "Avenger": _passive("复仇者", "攻击与暴击率永久提升。", _effect("attack_up", 10, 99), _effect("crit_chance_up", 10, 99)),
    "MoonCancer": _passive("阵地作成·月", "Arts 性能与 NP 获取永久提升。", _effect("card_up_a", 12, 99), _effect("np_gain_up", 12, 99)),
    "Foreigner": _passive("领域外生命", "开战时获得两次弱化无效与持续暴击星。", _effect("debuff_immunity", 2, 99), _effect("stars_per_turn", 6, 99)),
    "Pretender": _passive("伪装者", "开战时获得 20% NP 与暴击率强化。", _effect("np_charge", 20), _effect("crit_chance_up", 15, 99)),
    "AlterEgo": _passive("复合神性", "攻击与三色性能永久提升。", _effect("attack_up", 8, 99), _effect("card_up_all", 8, 99)),
    "Beast": _passive("兽之权能", "攻击提升并持续恢复生命。", _effect("attack_up", 10, 99), _effect("regen", 300, 99)),
}


EVENT_SERVANT_IDS = tuple(item["id"] for item in _CATALOGUE if item["event_only"])
INITIAL_RELEASE_SERVANTS = tuple(item["id"] for item in _CATALOGUE if not item["event_only"])

for item in _CATALOGUE:
    item["passives"] = [dict(CLASS_PASSIVES[item["class"]]), *item["passives"]]
    item["speed"] = SERVANT_SPEEDS[item["id"]]
    item["np"]["quote"] = NP_QUOTES[item["id"]]
    item["np"]["cg_url"] = f"noble-phantasms/{item['id']}.webp"
    item["art_url"] = f"servants/{item['id']}.webp"
    item["skill_art_url"] = f"skills/{item['id']}.webp"
    item["released"] = True


SERVANTS: dict[str, dict[str, Any]] = {item["id"]: item for item in _CATALOGUE}
CATALOGUE_VERSION = "2026.09-merged-24-servants-v12"
STARTER_SERVANTS = ("mash_shielder", "nero_saber", "medusa_rider")


def get_servant(servant_id: str) -> dict[str, Any]:
    try:
        return SERVANTS[servant_id]
    except KeyError as exc:
        raise ValueError(f"Unknown servant: {servant_id}") from exc


def servants_by_rarity(rarity: int) -> list[dict[str, Any]]:
    return [item for item in _CATALOGUE if item["rarity"] == rarity]


def public_catalogue() -> list[dict[str, Any]]:
    return list(_CATALOGUE)
