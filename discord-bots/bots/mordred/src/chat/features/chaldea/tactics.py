"""Static tactical actions exposed by the Chaldea battle activity."""

from __future__ import annotations

from typing import Any


def _effect(
    kind: str,
    value: int = 0,
    duration: int = 1,
    target: str = "self",
) -> dict[str, Any]:
    return {"kind": kind, "value": value, "duration": duration, "target": target}


MASTER_SKILLS = {
    "mystic_heal": {
        "id": "mystic_heal",
        "name": "应急灵子修复",
        "description": "回复己方全体 1800 HP，并解除弱化。每场一次。",
        "effects": [_effect("heal", 1800, target="team"), _effect("debuff_cleanse", target="team")],
    },
    "gandr": {
        "id": "gandr",
        "name": "甘德",
        "description": "眩晕当前敌方从者，并降低其防御 20%。每场一次。",
        "effects": [_effect("stun", 1, 1, "enemy"), _effect("defense_down", 20, 2, "enemy")],
    },
    "command_seal": {
        "id": "command_seal",
        "name": "令咒强化",
        "description": "当前从者获得 50% NP，并提升攻击力 30%。每场一次。",
        "effects": [_effect("np_charge", 50), _effect("attack_up", 30, 1)],
    },
    "atlas_dust": {
        "id": "atlas_dust",
        "name": "奥西里斯之尘",
        "description": "解除己方全体弱化，并赋予整轮无敌。每场一次。",
        "effects": [_effect("debuff_cleanse", target="team"), _effect("invincible", 1, 1, "team")],
    },
    "atlas_reduction": {
        "id": "atlas_reduction",
        "name": "灵子演算缩减",
        "description": "己方全体技能冷却缩短 1 回合，并获得 15% NP。每场一次。",
        "effects": [_effect("cooldown_reduce", 1, target="team"), _effect("np_charge", 15, target="team")],
    },
    "atlas_forecast": {
        "id": "atlas_forecast",
        "name": "未来测算",
        "description": "敌方全体攻击与速度降低 18%，持续两回合。每场一次。",
        "effects": [_effect("attack_down", 18, 2, "enemy_team"), _effect("speed_down", 18, 2, "enemy_team")],
    },
    "association_transfer": {
        "id": "association_transfer",
        "name": "灵脉转让",
        "description": "当前从者获得 50% NP，并提升 NP 获取率 30%。每场一次。",
        "effects": [_effect("np_charge", 50), _effect("np_gain_up", 30, 2)],
    },
    "association_evocation": {
        "id": "association_evocation",
        "name": "使魔唤星",
        "description": "己方全体获得 24 颗暴击星，暴击率提升 25%。每场一次。",
        "effects": [_effect("stars", 24, target="team"), _effect("crit_chance_up", 25, 2, "team")],
    },
    "association_reinforce": {
        "id": "association_reinforce",
        "name": "全系强化",
        "description": "己方全体三色性能提升 22%，持续两回合。每场一次。",
        "effects": [_effect("card_up_all", 22, 2, "team")],
    },
    "combat_burst": {
        "id": "combat_burst",
        "name": "全军突击",
        "description": "己方全体攻击与 Buster 性能提升 25%，持续两回合。每场一次。",
        "effects": [_effect("attack_up", 25, 2, "team"), _effect("card_up_b", 25, 2, "team")],
    },
    "combat_lock": {
        "id": "combat_lock",
        "name": "战术封锁",
        "description": "敌方全体防御与速度降低 22%，持续两回合。每场一次。",
        "effects": [_effect("defense_down", 22, 2, "enemy_team"), _effect("speed_down", 22, 2, "enemy_team")],
    },
    "combat_guard": {
        "id": "combat_guard",
        "name": "紧急防护",
        "description": "己方全体防御提升 30%，并获得一次回避。每场一次。",
        "effects": [_effect("defense_up", 30, 2, "team"), _effect("evade", 1, 1, "team")],
    },
}


MAGIC_CARDS = {
    "starfall": {
        "id": "starfall",
        "name": "星降术式",
        "description": "己方全体获得 15 颗暴击星，暴击率提升 20%。",
        "effects": [_effect("stars", 15, target="team"), _effect("crit_chance_up", 20, 1, "team")],
    },
    "healing_rain": {
        "id": "healing_rain",
        "name": "治愈之雨",
        "description": "己方全体回复 1500 HP，并获得两回合持续恢复。",
        "effects": [_effect("heal", 1500, target="team"), _effect("regen", 500, 2, "team")],
    },
    "mana_surge": {
        "id": "mana_surge",
        "name": "魔力潮汐",
        "description": "己方全体获得 20% NP，并提升 NP 获取率。",
        "effects": [_effect("np_charge", 20, target="team"), _effect("np_gain_up", 20, 2, "team")],
    },
    "frost_binding": {
        "id": "frost_binding",
        "name": "霜环束缚",
        "description": "降低敌方全体攻击力与速度 12%，持续两回合。",
        "effects": [_effect("attack_down", 12, 2, "enemy_team"), _effect("speed_down", 12, 2, "enemy_team")],
    },
}


TRAP_CARDS = {
    "aegis_rune": {
        "id": "aegis_rune",
        "name": "埃癸斯刻印",
        "description": "敌方攻击或宝具发动时触发：己方存活从者各获得一次对肃正防御。",
    },
    "binding_curse": {
        "id": "binding_curse",
        "name": "拘束咒印",
        "description": "敌方攻击或宝具发动时触发：令攻击者眩晕，本次行动失败。",
    },
    "mirror_prism": {
        "id": "mirror_prism",
        "name": "镜返棱晶",
        "description": "敌方造成伤害时触发：将实际伤害的 50% 反射给攻击者。",
    },
}


MASTER_TEMPLATES = {
    "chaldea_uniform": {
        "id": "chaldea_uniform",
        "name": "迦勒底标准礼装",
        "description": "攻守均衡，适合初次使用御主战术的玩家。",
        "skill_ids": ["mystic_heal", "gandr", "command_seal"],
        "magic_pool": ["starfall", "healing_rain", "mana_surge", "frost_binding"],
        "trap_pool": ["aegis_rune", "binding_curse", "mirror_prism"],
    },
    "atlas_uniform": {
        "id": "atlas_uniform",
        "name": "阿特拉斯院制服",
        "description": "擅长解除异常、缩短冷却与压制敌方节奏。",
        "skill_ids": ["atlas_dust", "atlas_reduction", "atlas_forecast"],
        "magic_pool": ["healing_rain", "mana_surge", "frost_binding"],
        "trap_pool": ["aegis_rune", "binding_curse"],
    },
    "association_uniform": {
        "id": "association_uniform",
        "name": "魔术协会制服",
        "description": "偏向 NP 循环、暴击与三色强化。",
        "skill_ids": ["association_transfer", "association_evocation", "association_reinforce"],
        "magic_pool": ["starfall", "healing_rain", "mana_surge"],
        "trap_pool": ["aegis_rune", "mirror_prism"],
    },
    "combat_uniform": {
        "id": "combat_uniform",
        "name": "迦勒底战斗服",
        "description": "高压进攻与团队防护并重，适合主动抢节奏。",
        "skill_ids": ["combat_burst", "combat_lock", "combat_guard"],
        "magic_pool": ["starfall", "mana_surge", "frost_binding"],
        "trap_pool": ["aegis_rune", "binding_curse", "mirror_prism"],
    },
}

DEFAULT_MASTER_TEMPLATE_ID = "chaldea_uniform"


TACTICAL_CATALOGUE = {
    "master_templates": list(MASTER_TEMPLATES.values()),
    "master_skills": list(MASTER_SKILLS.values()),
    "magic_cards": list(MAGIC_CARDS.values()),
    "trap_cards": list(TRAP_CARDS.values()),
}
