"""Server-authoritative, JSON-serialisable three-versus-three battle engine."""

from __future__ import annotations

import copy
import hashlib
import random
from typing import Any

from .catalog import get_servant
from .tactics import (
    DEFAULT_MASTER_TEMPLATE_ID,
    MAGIC_CARDS,
    MASTER_SKILLS,
    MASTER_TEMPLATES,
    TACTICAL_CATALOGUE,
    TRAP_CARDS,
)


CARD_MULTIPLIER = {"B": 1.15, "A": 1.0, "Q": 0.9}
CARD_NP_GAIN = {"B": 5, "A": 20, "Q": 10}
LEVEL_CAP = 80
LEVEL_BONUS_MAX = 0.40
NP_LEVEL_MULTIPLIER = {1: 1.0, 2: 1.04, 3: 1.07, 4: 1.09, 5: 1.10}
MAX_BATTLE_ROUNDS = 10
CLASS_ADVANTAGE = {
    "Saber": "Lancer",
    "Lancer": "Archer",
    "Archer": "Saber",
    "Rider": "Caster",
    "Caster": "Assassin",
    "Assassin": "Rider",
    "Ruler": "MoonCancer",
    "MoonCancer": "Avenger",
    "Avenger": "Ruler",
}

DEBUFF_KINDS = {
    "attack_down",
    "defense_down",
    "stun",
    "poison",
    "burn",
    "crit_down",
    "crit_chance_down",
    "np_damage_down",
    "quick_resist_down",
    "speed_down",
}

EFFECT_NAMES = {
    "attack_up": "攻击力提升",
    "defense_up": "防御力提升",
    "card_up_b": "Buster 性能提升",
    "card_up_a": "Arts 性能提升",
    "card_up_q": "Quick 性能提升",
    "card_up_all": "三色性能提升",
    "np_gain_up": "NP 获取提升",
    "np_damage_up": "宝具威力提升",
    "crit_up": "暴击威力提升",
    "crit_chance_up": "暴击率提升",
    "trait_damage_up": "特攻威力提升",
    "star_gain_up": "暴击星获取提升",
    "defense_down": "防御力下降",
    "attack_down": "攻击力下降",
    "crit_down": "暴击威力下降",
    "crit_chance_down": "暴击率下降",
    "np_damage_down": "宝具威力下降",
    "quick_resist_down": "Quick 耐性下降",
    "stun": "眩晕",
    "poison": "毒",
    "burn": "灼烧",
    "evade": "回避",
    "invincible": "无敌",
    "sure_hit": "必中",
    "taunt": "目标集中",
    "guts": "战斗续行",
    "regen": "每回合回复",
    "damage_cut": "伤害减免",
    "stars_per_turn": "每回合获得暴击星",
    "speed_up": "速度提升",
    "speed_down": "速度下降",
    "np_per_turn": "每次行动获得 NP",
    "hp_loss_per_turn": "每次行动损失 HP",
    "debuff_immunity": "弱化无效",
    "invincible_pierce": "无敌贯通",
    "solemn_defense": "对肃正防御",
    "delayed_stun": "延迟睡眠",
    "damage_reflect": "伤害反射",
    "execute": "处决",
}

SUPPORTED_EFFECT_KINDS = set(EFFECT_NAMES) | {
    "heal",
    "np_charge",
    "stars",
    "debuff_cleanse",
    "buff_remove",
    "np_drain",
    "poison_bonus",
    "cooldown_reduce",
}


def class_multiplier(attacker: str, defender: str) -> float:
    if attacker == "Pretender":
        return 1.2 if defender in {"Saber", "Archer", "Lancer"} else 0.85 if defender in {"Rider", "Caster", "Assassin"} else 1.0
    if defender == "Pretender":
        return 0.85 if attacker in {"Saber", "Archer", "Lancer"} else 1.2 if attacker in {"Rider", "Caster", "Assassin"} else 1.0
    if attacker == "Foreigner" and defender == "Berserker":
        return 1.3
    if defender == "Foreigner" and attacker == "Berserker":
        return 0.8
    if attacker == "AlterEgo" and defender == "Foreigner":
        return 1.2
    if defender == "AlterEgo" and attacker == "Foreigner":
        return 0.85
    if attacker == "Berserker" and defender != "Shielder":
        return 1.3
    if defender == "Berserker" and attacker != "Shielder":
        return 1.3
    if CLASS_ADVANTAGE.get(attacker) == defender:
        return 1.3
    if CLASS_ADVANTAGE.get(defender) == attacker:
        return 0.8
    return 1.0


def level_stat_multiplier(level: int) -> float:
    bounded = max(1, min(LEVEL_CAP, int(level)))
    return 1.0 + LEVEL_BONUS_MAX * (bounded - 1) / (LEVEL_CAP - 1)


def _combatant(entry: str | dict[str, Any], slot: int) -> dict[str, Any]:
    if isinstance(entry, str):
        servant_id, level, np_level = entry, 1, 1
    else:
        servant_id = str(entry["servant_id"])
        level = max(1, min(LEVEL_CAP, int(entry.get("level", 1))))
        np_level = max(1, min(5, int(entry.get("np_level", 1))))
    servant = get_servant(servant_id)
    stat_scale = level_stat_multiplier(level)
    max_hp = int(round(int(servant["hp"]) * stat_scale))
    attack = int(round(int(servant["attack"]) * stat_scale))
    return {
        "slot": slot,
        "servant_id": servant_id,
        "level": level,
        "np_level": np_level,
        "attack": attack,
        "speed": int(servant["speed"]),
        "hp": max_hp,
        "max_hp": max_hp,
        "np": 0,
        "stars": 0,
        "cooldowns": [0, 0, 0],
        "buffs": [],
        "debuffs": [],
        "defeated_announced": False,
    }


def _round_draw(
    match_id: str,
    user_id: str,
    turn: int,
    category: str,
    options: list[str],
    previous: str | None = None,
) -> str:
    ordered = sorted(options)
    if not ordered:
        raise ValueError(f"{category} pool cannot be empty")
    digest = hashlib.sha256(
        f"{match_id}:{user_id}:{turn}:{category}".encode("utf-8")
    ).digest()
    index = int.from_bytes(digest[:4], "big") % len(ordered)
    selected = ordered[index]
    if len(ordered) > 1 and selected == previous:
        selected = ordered[(index + 1) % len(ordered)]
    return selected


def _player_tactics(
    match_id: str,
    user_id: str,
    turn: int,
    template_id: str = DEFAULT_MASTER_TEMPLATE_ID,
) -> dict[str, Any]:
    template = MASTER_TEMPLATES.get(template_id, MASTER_TEMPLATES[DEFAULT_MASTER_TEMPLATE_ID])
    return {
        "master_template": template["id"],
        "master_available": {skill_id: True for skill_id in template["skill_ids"]},
        "magic_card": _round_draw(match_id, user_id, turn, "magic", template["magic_pool"]),
        "magic_previous": None,
        "magic_round": int(turn),
        "magic_used": False,
        "trap_card": _round_draw(match_id, user_id, turn, "trap", template["trap_pool"]),
        "trap_previous": None,
        "trap_round": int(turn),
        "trap_charges": 2,
        "armed_trap": None,
        "used_this_phase": False,
    }


def create_battle_state(
    match_id: str,
    teams: dict[str, list[str | dict[str, Any]]],
    *,
    first_player_id: str | None = None,
    master_templates: dict[str, str] | None = None,
) -> dict[str, Any]:
    if len(teams) != 2 or any(len(team) != 3 for team in teams.values()):
        raise ValueError("A battle requires exactly two three-servant teams")
    player_ids = [str(player_id) for player_id in teams]
    if first_player_id is not None and str(first_player_id) not in player_ids:
        raise ValueError("First player must be one of the battle participants")
    state = {
        "match_id": match_id,
        "ruleset": "initiative_v3_master_codes",
        "status": "active",
        "turn": 1,
        "phase_no": 1,
        "state_version": 1,
        "first_player_id": "",
        "active_player_id": "",
        "active_servant_slot": 0,
        "initiative_order": [],
        "initiative_index": 0,
        "winner_id": None,
        "teams": {
            str(user_id): [_combatant(entry, slot) for slot, entry in enumerate(team)]
            for user_id, team in teams.items()
        },
        "log": [],
        "last_events": [],
        "phase_used_skills": {},
        "tactics": {
            str(user_id): _player_tactics(
                match_id,
                str(user_id),
                1,
                (master_templates or {}).get(str(user_id), DEFAULT_MASTER_TEMPLATE_ID),
            )
            for user_id in teams
        },
        "passives_applied": True,
    }
    passive_logs: list[str] = []
    _apply_battle_passives(state, passive_logs)
    state["initiative_order"] = _build_initiative_order(state)
    _sync_active_actor(state)
    state["first_player_id"] = state["active_player_id"]
    first = _active_member(state)
    state["log"] = [
        f"双方灵基展开，{_name(first)} 以速度 {_effective_speed(first)} 取得首个行动。",
        *passive_logs,
    ][-30:]
    return state


def _effective_speed(member: dict[str, Any]) -> int:
    return max(
        1,
        int(member.get("speed", get_servant(member["servant_id"])["speed"]))
        + _sum_effect(member, "speed_up")
        - _sum_effect(member, "speed_down"),
    )


def _build_initiative_order(state: dict[str, Any]) -> list[dict[str, Any]]:
    actors: list[dict[str, Any]] = []
    for player_id, team in state["teams"].items():
        for member in _living(team):
            tie = hashlib.sha256(
                f"{state['match_id']}:{state['turn']}:{player_id}:{member['slot']}".encode("utf-8")
            ).hexdigest()
            actors.append({
                "player_id": str(player_id),
                "servant_slot": int(member["slot"]),
                "speed": _effective_speed(member),
                "tie": tie,
            })
    actors.sort(key=lambda item: (-int(item["speed"]), str(item["tie"])))
    for item in actors:
        item.pop("tie", None)
    return actors


def _sync_active_actor(state: dict[str, Any]) -> None:
    order = state.get("initiative_order") or []
    if not order:
        return
    actor = order[int(state.get("initiative_index", 0))]
    state["active_player_id"] = str(actor["player_id"])
    state["active_servant_slot"] = int(actor["servant_slot"])


def _active_member(state: dict[str, Any]) -> dict[str, Any]:
    return _member(
        state["teams"][str(state["active_player_id"])],
        int(state["active_servant_slot"]),
    )


def upgrade_battle_state(state: dict[str, Any]) -> dict[str, Any]:
    """Upgrade persisted battles without injecting passives halfway through a match."""
    player_ids = list(state.get("teams", {}))
    previous_active = str(state.get("active_player_id") or (player_ids[0] if player_ids else ""))
    for team in state.get("teams", {}).values():
        for member in team:
            servant = get_servant(member["servant_id"])
            member.setdefault("level", 1)
            member.setdefault("np_level", 1)
            member.setdefault("attack", int(servant["attack"]))
            member.setdefault("speed", int(servant["speed"]))
    state.setdefault("phase_no", max(1, int(state.get("turn", 1))))
    state.setdefault("state_version", max(1, int(state.get("turn", 1))))
    state.setdefault("last_events", [])
    state.setdefault("phase_used_skills", {})
    if state.get("ruleset") not in {"initiative_v1", "initiative_v2_tactics", "initiative_v3_master_codes"}:
        order = _build_initiative_order(state)
        if previous_active:
            split = next(
                (index for index, actor in enumerate(order) if actor["player_id"] == previous_active),
                0,
            )
            order = order[split:] + order[:split]
        state["initiative_order"] = order
        state["initiative_index"] = 0
        state["phase_used_skills"] = {}
    state["ruleset"] = "initiative_v3_master_codes"
    state.setdefault("passives_applied", True)
    tactics = state.setdefault("tactics", {})
    for uid in player_ids:
        existing = tactics.get(str(uid), {})
        template_id = str(existing.get("master_template", DEFAULT_MASTER_TEMPLATE_ID))
        if template_id not in MASTER_TEMPLATES:
            template_id = DEFAULT_MASTER_TEMPLATE_ID
        current = tactics.setdefault(
            str(uid),
            _player_tactics(
                str(state.get("match_id", "legacy")),
                str(uid),
                int(state.get("turn", 1)),
                template_id,
            ),
        )
        defaults = _player_tactics(
            str(state.get("match_id", "legacy")),
            str(uid),
            int(state.get("turn", 1)),
            template_id,
        )
        for key, value in defaults.items():
            current.setdefault(key, copy.deepcopy(value))
        current["master_template"] = template_id
        allowed_skills = set(MASTER_TEMPLATES[template_id]["skill_ids"])
        current["master_available"] = {
            skill_id: bool(current.get("master_available", {}).get(skill_id, True))
            for skill_id in allowed_skills
        }
        if int(current.get("magic_round", 0)) != int(state.get("turn", 1)):
            template = MASTER_TEMPLATES[template_id]
            current["magic_previous"] = current.get("magic_card")
            current["magic_card"] = _round_draw(
                str(state.get("match_id", "legacy")),
                str(uid),
                int(state.get("turn", 1)),
                "magic",
                template["magic_pool"],
                current.get("magic_previous"),
            )
            current["magic_round"] = int(state.get("turn", 1))
            current["magic_used"] = False
        if int(current.get("trap_round", 0)) != int(state.get("turn", 1)):
            template = MASTER_TEMPLATES[template_id]
            current["trap_previous"] = current.get("trap_card")
            current["trap_card"] = _round_draw(
                str(state.get("match_id", "legacy")),
                str(uid),
                int(state.get("turn", 1)),
                "trap",
                template["trap_pool"],
                current.get("trap_previous"),
            )
            current["trap_round"] = int(state.get("turn", 1))
    state.setdefault("initiative_order", _build_initiative_order(state))
    state.setdefault("initiative_index", 0)
    if state.get("initiative_order"):
        _sync_active_actor(state)
        state.setdefault("first_player_id", state["active_player_id"])
    return state


def draw_hand(state: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    team = state["teams"].get(str(user_id))
    if team is None:
        raise ValueError("Player is not part of this battle")

    deck: list[dict[str, Any]] = []
    for member in team:
        servant = get_servant(member["servant_id"])
        for card_index, card_type in enumerate(servant["deck"]):
            deck.append(
                {
                    "id": f"{member['slot']}:{card_index}",
                    "servant_slot": member["slot"],
                    "type": card_type,
                    "servant_id": member["servant_id"],
                }
            )

    cycle = (int(state["turn"]) - 1) // 3
    seed_bytes = hashlib.sha256(
        f"{state['match_id']}:{user_id}:{cycle}".encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(seed_bytes[:8], "big"))
    rng.shuffle(deck)
    offset = ((int(state["turn"]) - 1) % 3) * 5
    return deck[offset : offset + 5]


def _living(team: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [member for member in team if member["hp"] > 0]


def _member(team: list[dict[str, Any]], slot: int) -> dict[str, Any]:
    try:
        member = team[int(slot)]
    except (IndexError, ValueError, TypeError) as exc:
        raise ValueError("Invalid servant slot") from exc
    if member["hp"] <= 0:
        raise ValueError("Defeated servants cannot act")
    return member


def _sum_effect(member: dict[str, Any], kind: str) -> int:
    return sum(
        int(effect.get("value", 0))
        for group in (member["buffs"], member["debuffs"])
        for effect in group
        if effect.get("kind") == kind
    )


def _is_stunned(member: dict[str, Any]) -> bool:
    return _sum_effect(member, "stun") > 0


def _name(member: dict[str, Any]) -> str:
    return get_servant(member["servant_id"])["name"]


def _effect_text(effect: dict[str, Any]) -> str:
    kind = effect["kind"]
    name = EFFECT_NAMES.get(kind, kind)
    value = int(effect.get("value", 0))
    duration = int(effect.get("duration", 1))
    if kind in {
        "stun", "evade", "invincible", "sure_hit", "taunt", "invincible_pierce",
        "solemn_defense", "debuff_immunity", "delayed_stun",
    }:
        value_text = (
            f"（{value} 次）"
            if kind in {"evade", "solemn_defense", "debuff_immunity"} and value > 1
            else ""
        )
    elif value:
        suffix = "" if kind in {
            "poison", "burn", "guts", "regen", "damage_cut", "stars_per_turn",
            "hp_loss_per_turn",
        } else "%"
        value_text = f" {value}{suffix}"
    else:
        value_text = ""
    return f"{name}{value_text}（{duration} 回合）"


def _targets(
    source_team: list[dict[str, Any]],
    enemy_team: list[dict[str, Any]],
    source: dict[str, Any],
    target_kind: str,
    requested_slot: int | None,
) -> list[dict[str, Any]]:
    if target_kind == "self":
        return [source]
    if target_kind == "team":
        return _living(source_team)
    if target_kind in ("enemy_team", "all_enemies"):
        return _living(enemy_team)
    if target_kind == "ally":
        return [_member(source_team, source["slot"] if requested_slot is None else requested_slot)]
    living_enemies = _living(enemy_team)
    if not living_enemies:
        return []
    taunter = next((m for m in living_enemies if _sum_effect(m, "taunt") > 0), None)
    if taunter:
        return [taunter]
    if requested_slot is None:
        return [living_enemies[0]]
    return [_member(enemy_team, requested_slot)]


def _apply_effect(
    target: dict[str, Any],
    effect: dict[str, Any],
    logs: list[str],
    *,
    defer_tick: bool = True,
) -> None:
    kind = effect["kind"]
    if kind not in SUPPORTED_EFFECT_KINDS:
        raise ValueError(f"Unsupported battle effect: {kind}")
    value = int(effect.get("value", 0))
    if kind == "heal":
        before = target["hp"]
        target["hp"] = min(target["max_hp"], target["hp"] + value)
        logs.append(f"{get_servant(target['servant_id'])['name']} 回复 {target['hp'] - before} HP。")
    elif kind == "np_charge":
        target["np"] = min(100, target["np"] + value)
        logs.append(f"{_name(target)} 的 NP 增加 {value}%。")
    elif kind == "stars":
        gained = max(0, int(value * (100 + _sum_effect(target, "star_gain_up")) / 100))
        target["stars"] = min(50, target["stars"] + gained)
        logs.append(f"{_name(target)} 获得 {gained} 颗暴击星。")
    elif kind == "debuff_cleanse":
        target["debuffs"] = []
        logs.append(f"{_name(target)} 的弱化状态已解除。")
    elif kind == "buff_remove":
        target["buffs"] = []
        logs.append(f"{_name(target)} 的强化状态已解除。")
    elif kind == "np_drain":
        target["np"] = max(0, target["np"] - value)
        logs.append(f"{_name(target)} 的 NP 减少 {value}%。")
    elif kind == "cooldown_reduce":
        target["cooldowns"] = [max(0, int(cooldown) - value) for cooldown in target["cooldowns"]]
        logs.append(f"{_name(target)} 的技能冷却缩短 {value} 回合。")
    elif kind == "execute":
        threshold = max(0, min(100, value))
        hp_percent = target["hp"] * 100 / max(1, target["max_hp"])
        if target["hp"] > 0 and hp_percent <= threshold:
            target["hp"] = 0
            logs.append(f"{_name(target)} 的生命低于 {threshold}%，被立即处决。")
        else:
            logs.append(f"{_name(target)} 的生命高于 {threshold}%，抵抗了处决。")
    elif kind == "poison_bonus":
        return
    else:
        if kind in DEBUFF_KINDS:
            immunity = next(
                (
                    buff for buff in target["buffs"]
                    if buff.get("kind") == "debuff_immunity" and int(buff.get("value", 1)) > 0
                ),
                None,
            )
            if immunity:
                immunity["value"] = int(immunity.get("value", 1)) - 1
                if immunity["value"] <= 0:
                    target["buffs"].remove(immunity)
                logs.append(f"{_name(target)} 的弱化无效抵消了「{EFFECT_NAMES.get(kind, kind)}」。")
                return
        record = copy.deepcopy(effect)
        if kind == "invincible":
            # Invincibility is a round window rather than a hit-count shield.
            # It is removed only when the complete initiative round ends.
            record["round_remaining"] = max(1, int(effect.get("duration", 1)))
            record["remaining"] = record["round_remaining"]
        else:
            record["remaining"] = max(1, int(effect.get("duration", 1))) + int(defer_tick)
        if kind in DEBUFF_KINDS:
            target["debuffs"].append(record)
        else:
            target["buffs"].append(record)
        logs.append(f"{_name(target)} 获得「{_effect_text(effect)}」。")


def _apply_battle_passives(state: dict[str, Any], logs: list[str]) -> None:
    """Apply every servant's declared passive once when a new battle is created."""
    for uid, own_team in state["teams"].items():
        enemy_id = next(player_id for player_id in state["teams"] if player_id != uid)
        enemy_team = state["teams"][enemy_id]
        for source in own_team:
            for passive in get_servant(source["servant_id"]).get("passives", []):
                logs.append(f"{_name(source)} 的被动「{passive['name']}」生效。")
                for effect in passive.get("effects", []):
                    for target in _targets(
                        own_team, enemy_team, source, effect.get("target", "self"), None
                    ):
                        _apply_effect(target, effect, logs, defer_tick=False)


def _activate_skill(
    own_team: list[dict[str, Any]],
    enemy_team: list[dict[str, Any]],
    skill_action: dict[str, Any] | None,
    logs: list[str],
) -> tuple[int, int] | None:
    if not skill_action:
        return None
    source = _member(own_team, int(skill_action["servant_slot"]))
    skill_index = int(skill_action["skill_index"])
    servant = get_servant(source["servant_id"])
    if skill_index not in (0, 1, 2):
        raise ValueError("Invalid skill index")
    if source["cooldowns"][skill_index] > 0:
        raise ValueError("Skill is on cooldown")

    skill = servant["skills"][skill_index]
    requested_slot = skill_action.get("target_slot")
    logs.append(f"{servant['name']} 使用「{skill['name']}」。")
    for effect in skill["effects"]:
        for target in _targets(
            own_team, enemy_team, source, effect.get("target", "self"), requested_slot
        ):
            _apply_effect(
                target,
                effect,
                logs,
                defer_tick=any(target is member for member in own_team),
            )
    source["cooldowns"][skill_index] = int(skill["cooldown"])
    return source["slot"], skill_index


def _canonical_action(state: dict[str, Any], user_id: str, action: dict[str, Any]) -> dict[str, Any]:
    """Normalise one active servant's skill and attack payload."""
    skills = list(action.get("skills") or [])
    commands: list[dict[str, Any]] = []
    for command in action.get("commands") or []:
        if command.get("kind") == "skill":
            skills.append(command)
            commands.append({"servant_slot": command["servant_slot"], "kind": "attack"})
        else:
            commands.append(command)
    return {"skills": skills, "commands": commands}


def validate_action(state: dict[str, Any], user_id: str, action: dict[str, Any]) -> None:
    if state.get("status") != "active":
        raise ValueError("Battle is not active")
    team = state["teams"].get(str(user_id))
    if team is None:
        raise ValueError("Player is not part of this battle")
    enemy_id = next(uid for uid in state["teams"] if uid != str(user_id))
    enemy_team = state["teams"][enemy_id]
    canonical = _canonical_action(state, str(user_id), action)
    commands = canonical["commands"]
    skills = canonical["skills"]
    if str(state.get("active_player_id")) != str(user_id):
        raise ValueError("It is not this player's turn")
    active_slot = int(state.get("active_servant_slot", -1))
    active_member = _member(team, active_slot)
    command_slots = [int(command.get("servant_slot", -1)) for command in commands]
    expected_commands = 0 if _is_stunned(active_member) else 1
    if len(command_slots) != expected_commands or any(slot != active_slot for slot in command_slots):
        raise ValueError("Only the active servant may choose one action")

    if len(skills) > 1:
        raise ValueError("The active servant may use at most one skill")
    skill_slots = [int(skill.get("servant_slot", -1)) for skill in skills]
    if any(slot != active_slot for slot in skill_slots):
        raise ValueError("Only the active servant may use a skill")

    for skill_action in skills:
        member = _member(team, int(skill_action["servant_slot"]))
        if _is_stunned(member):
            raise ValueError("Stunned servants cannot use skills")
        skill_index = int(skill_action.get("skill_index", -1))
        if skill_index not in (0, 1, 2):
            raise ValueError("Invalid skill index")
        if member["cooldowns"][skill_index] > 0:
            raise ValueError("Skill is on cooldown")
        target_slot = skill_action.get("target_slot")
        targets = {
            effect.get("target", "self")
            for effect in get_servant(member["servant_id"])["skills"][skill_index]["effects"]
        }
        if "ally" in targets:
            if target_slot is None:
                raise ValueError("Ally-targeted skills require a target")
            if _member(team, int(target_slot))["hp"] <= 0:
                raise ValueError("Defeated servants cannot be targeted")
        elif "enemy" in targets:
            if target_slot is None:
                raise ValueError("Enemy-targeted skills require a target")
            if _member(enemy_team, int(target_slot))["hp"] <= 0:
                raise ValueError("Defeated servants cannot be targeted")

    for command in commands:
        member = _member(team, int(command["servant_slot"]))
        kind = command.get("kind")
        target_slot = command.get("target_slot")
        if kind == "attack":
            if target_slot is not None:
                if _member(enemy_team, int(target_slot))["hp"] <= 0:
                    raise ValueError("Defeated servants cannot be targeted")
            continue
        if kind == "np":
            if member["np"] < 100:
                raise ValueError("Noble Phantasm is not ready")
            if target_slot is not None:
                if _member(enemy_team, int(target_slot))["hp"] <= 0:
                    raise ValueError("Defeated servants cannot be targeted")
            continue
        raise ValueError("Unknown servant action")


def _card_damage(attacker: dict[str, Any], defender: dict[str, Any], card_type: str, first_card: str) -> int:
    attacker_data = get_servant(attacker["servant_id"])
    defender_data = get_servant(defender["servant_id"])
    attack_mod = 100 + _sum_effect(attacker, "attack_up") - _sum_effect(attacker, "attack_down")
    defense_mod = 100 + _sum_effect(defender, "defense_up") - _sum_effect(defender, "defense_down")
    card_mod = _sum_effect(attacker, f"card_up_{card_type.lower()}") + _sum_effect(attacker, "card_up_all")
    first_bonus = 1.18 if first_card == "B" else 1.0
    special_mod = _sum_effect(attacker, "trait_damage_up")
    if card_type == "Q":
        special_mod += _sum_effect(defender, "quick_resist_down")
    base = int(attacker.get("attack", attacker_data["attack"])) * 0.13 * CARD_MULTIPLIER[card_type]
    damage = base * first_bonus * (attack_mod / 100) * ((100 + card_mod) / 100)
    damage *= (100 + special_mod) / 100
    damage *= class_multiplier(attacker_data["class"], defender_data["class"])
    damage *= 100 / max(25, defense_mod)
    damage -= _sum_effect(defender, "damage_cut")
    return max(1, int(damage))


def _consume_defense(attacker: dict[str, Any], target: dict[str, Any]) -> str | None:
    for effect in list(target["buffs"]):
        if effect.get("kind") == "solemn_defense" and int(effect.get("value", 1)) > 0:
            effect["value"] = int(effect.get("value", 1)) - 1
            if effect["value"] <= 0:
                target["buffs"].remove(effect)
            return "solemn_defense"
    pierces_invincibility = _sum_effect(attacker, "invincible_pierce") > 0
    for kind in ("invincible", "evade"):
        if pierces_invincibility or (kind == "evade" and _sum_effect(attacker, "sure_hit") > 0):
            continue
        for effect in list(target["buffs"]):
            if effect.get("kind") == kind and int(effect.get("value", 1)) > 0:
                if kind != "invincible":
                    effect["value"] = int(effect.get("value", 1)) - 1
                    if effect["value"] <= 0:
                        target["buffs"].remove(effect)
                return kind
    return None


def _critical_modifier(
    state: dict[str, Any], user_id: str, attacker: dict[str, Any]
) -> tuple[float, bool, int]:
    chance = max(0, min(
        100,
        5
        + attacker["stars"] * 2
        + _sum_effect(attacker, "crit_chance_up")
        - _sum_effect(attacker, "crit_chance_down"),
    ))
    seed = hashlib.sha256(
        f"{state['match_id']}:{state['phase_no']}:{state['turn']}:{user_id}:{attacker['slot']}:critical".encode("utf-8")
    ).digest()
    critical = int.from_bytes(seed[:4], "big") % 100 < chance
    attacker["stars"] = max(0, attacker["stars"] - min(10, attacker["stars"]))
    if not critical:
        return 1.0, False, chance
    modifier = 1.75 * max(
        0.5,
        (100 + _sum_effect(attacker, "crit_up") - _sum_effect(attacker, "crit_down")) / 100,
    )
    return modifier, True, chance


def _np_level_scale(member: dict[str, Any]) -> float:
    return NP_LEVEL_MULTIPLIER[max(1, min(5, int(member.get("np_level", 1))))]


def _scaled_np_effect(effect: dict[str, Any], member: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(effect)
    if result.get("kind") not in {
        "stun", "taunt", "evade", "invincible", "sure_hit",
        "debuff_cleanse", "buff_remove", "poison_bonus", "cooldown_reduce",
        "debuff_immunity", "invincible_pierce", "solemn_defense", "delayed_stun",
        "damage_reflect", "execute",
    } and int(result.get("value", 0)):
        result["value"] = int(round(int(result["value"]) * _np_level_scale(member)))
    return result


def _plan_damage(
    state: dict[str, Any], user_id: str, action: dict[str, Any], logs: list[str]
) -> list[tuple[int, int, bool, int]]:
    player_ids = list(state["teams"])
    enemy_id = next(pid for pid in player_ids if pid != str(user_id))
    own_team = state["teams"][str(user_id)]
    enemy_team = state["teams"][enemy_id]
    living_enemies = _living(enemy_team)
    if not living_enemies:
        return []

    damage_events: list[tuple[int, int, bool, int]] = []
    for command in sorted(action["commands"], key=lambda item: int(item["servant_slot"])):
        if command.get("kind") == "skill" or not _living(enemy_team):
            continue
        attacker = _member(own_team, int(command["servant_slot"]))
        if _is_stunned(attacker):
            logs.append(f"{get_servant(attacker['servant_id'])['name']} 陷入眩晕，行动失败。")
            continue
        attacker_data = get_servant(attacker["servant_id"])
        if command.get("kind") == "attack":
            requested = command.get("target_slot")
            target = _targets(own_team, enemy_team, attacker, "enemy", requested)[0]
            defense = _consume_defense(attacker, target)
            if defense:
                logs.append(f"{_name(target)} 以{EFFECT_NAMES[defense]}挡下了 {_name(attacker)} 的攻击。")
                continue
            attack_type = attacker_data["np"]["card"]
            crit_modifier, critical, crit_chance = _critical_modifier(state, user_id, attacker)
            damage = int(_card_damage(attacker, target, attack_type, attack_type) * crit_modifier)
            damage_events.append((target["slot"], damage, critical, crit_chance))
            gain = int(18 * (100 + _sum_effect(attacker, "np_gain_up")) / 100)
            attacker["np"] = min(100, attacker["np"] + gain)
            base_stars = {"B": 2, "A": 5, "Q": 12}[attack_type]
            star_gain = int(base_stars * (100 + _sum_effect(attacker, "star_gain_up")) / 100)
            attacker["stars"] = min(50, attacker["stars"] + star_gain)
            critical_text = "【暴击】" if critical else ""
            logs.append(
                f"{critical_text}{attacker_data['name']} 攻击 {_name(target)}，造成 {damage} 点伤害，"
                f"NP +{gain}%，暴击星 +{star_gain}（本次暴击率 {crit_chance}%）。"
            )
            continue

        np_data = attacker_data["np"]
        attacker["np"] = 0
        requested = command.get("target_slot")
        for raw_effect in np_data["effects"]:
            if raw_effect.get("timing") != "pre":
                continue
            effect = _scaled_np_effect(raw_effect, attacker)
            effect_target = effect.get("target", "self")
            effect_slot = requested if effect_target in {"enemy", "ally"} else None
            for target in _targets(own_team, enemy_team, attacker, effect_target, effect_slot):
                _apply_effect(
                    target,
                    effect,
                    logs,
                    # A pre-NP effect is consumed by the same action and must not
                    # leak into the servant's next initiative turn.
                    defer_tick=False,
                )
        targets = (
            _living(enemy_team)
            if np_data["target"] == "all"
            else _targets(own_team, enemy_team, attacker, "enemy", requested)
        )
        if np_data["target"] == "team" or int(np_data["multiplier"]) <= 0:
            targets = []
        logs.append(f"{attacker_data['name']} 解放宝具「{np_data['name']}」！")
        for target in targets:
            defense = _consume_defense(attacker, target)
            if defense:
                logs.append(f"{_name(target)} 以{EFFECT_NAMES[defense]}挡下了宝具。")
                continue
            target_data = get_servant(target["servant_id"])
            modifier = 1 + (
                _sum_effect(attacker, "np_damage_up")
                - _sum_effect(attacker, "np_damage_down")
                + _sum_effect(attacker, "trait_damage_up")
            ) / 100
            if np_data["card"] == "Q":
                modifier *= 1 + _sum_effect(target, "quick_resist_down") / 100
            poison_bonus = sum(
                int(effect.get("value", 0))
                for effect in np_data["effects"]
                if effect.get("kind") == "poison_bonus"
            )
            if poison_bonus and _sum_effect(target, "poison") > 0:
                modifier *= 1 + poison_bonus / 100
            target_coefficient = 0.10 if np_data["target"] == "single" else 0.09
            damage = int(
                int(attacker.get("attack", attacker_data["attack"]))
                * np_data["multiplier"] / 100
                * target_coefficient
                * modifier
                * _np_level_scale(attacker)
            )
            damage = int(damage * class_multiplier(attacker_data["class"], target_data["class"]))
            damage_events.append((target["slot"], max(1, damage), False, 0))
            logs.append(f"宝具命中 {_name(target)}，造成 {max(1, damage)} 点伤害。")
        for raw_effect in np_data["effects"]:
            if raw_effect.get("timing") == "pre":
                continue
            effect = _scaled_np_effect(raw_effect, attacker)
            if effect.get("kind") == "poison_bonus":
                continue
            effect_target = effect.get("target", "self")
            effect_slot = requested if effect_target in {"enemy", "ally"} else None
            for target in _targets(own_team, enemy_team, attacker, effect_target, effect_slot):
                _apply_effect(
                    target,
                    effect,
                    logs,
                    defer_tick=any(target is member for member in own_team),
                )
    return damage_events


def _resolve_defeat(member: dict[str, Any], logs: list[str]) -> None:
    if member["hp"] > 0:
        return
    guts = next((b for b in member["buffs"] if b.get("kind") == "guts"), None)
    if guts:
        member["hp"] = max(1, int(guts.get("value", 1)))
        member["buffs"].remove(guts)
        member["defeated_announced"] = False
        logs.append(f"{_name(member)} 发动战斗续行，以 {member['hp']} HP 重新站起。")
    elif not member.get("defeated_announced"):
        member["defeated_announced"] = True
        logs.append(f"{_name(member)} 无法继续战斗。")


def _tick_member(
    member: dict[str, Any],
    just_used: set[tuple[int, int]],
    logs: list[str],
) -> None:
    for index, value in enumerate(member["cooldowns"]):
        if value > 0 and (member["slot"], index) not in just_used:
            member["cooldowns"][index] -= 1
    for group_name in ("buffs", "debuffs"):
        for effect in list(member[group_name]):
            kind = effect.get("kind")
            if kind == "invincible":
                continue
            if kind in ("poison", "burn") and member["hp"] > 0:
                damage = min(member["hp"], int(effect.get("value", 0)))
                member["hp"] -= damage
                logs.append(f"{_name(member)} 受到{EFFECT_NAMES[kind]}伤害 {damage}。")
            elif kind == "regen" and member["hp"] > 0:
                before = member["hp"]
                member["hp"] = min(member["max_hp"], member["hp"] + int(effect.get("value", 0)))
                logs.append(f"{_name(member)} 每次行动回复 {member['hp'] - before} HP。")
            elif kind == "stars_per_turn":
                member["stars"] = min(50, member["stars"] + int(effect.get("value", 0)))
            elif kind == "np_per_turn" and member["hp"] > 0:
                gained = int(effect.get("value", 0))
                member["np"] = min(100, member["np"] + gained)
                logs.append(f"{_name(member)} 每次行动获得 NP {gained}%。")
            elif kind == "hp_loss_per_turn" and member["hp"] > 0:
                loss = min(max(0, member["hp"] - 1), int(effect.get("value", 0)))
                member["hp"] -= loss
                logs.append(f"{_name(member)} 因代价损失 {loss} HP。")
            effect["remaining"] = int(effect.get("remaining", 1)) - 1
            if effect["remaining"] <= 0:
                member[group_name].remove(effect)
                if kind == "delayed_stun" and member["hp"] > 0:
                    member["debuffs"].append({
                        "kind": "stun", "value": 1, "duration": 1, "remaining": 2,
                        "source": "lake_dream",
                    })
                    logs.append(f"{_name(member)} 进入「湖水之梦」，下一次行动无法进行。")
    _resolve_defeat(member, logs)


def _tick_round_effects(state: dict[str, Any], logs: list[str]) -> None:
    """Expire effects whose promise is explicitly tied to a complete round."""
    for team in state["teams"].values():
        for member in team:
            for effect in list(member["buffs"]):
                if effect.get("kind") != "invincible":
                    continue
                remaining = int(effect.get("round_remaining", effect.get("remaining", 1))) - 1
                effect["round_remaining"] = remaining
                effect["remaining"] = remaining
                if remaining <= 0:
                    member["buffs"].remove(effect)
                    logs.append(f"{_name(member)} 的整轮无敌效果结束。")


def _skill_reaction(kind: str) -> str:
    if kind in {"heal", "regen", "np_charge", "debuff_cleanse"}:
        return "heal"
    return "debuff" if kind in DEBUFF_KINDS or kind == "buff_remove" else "buff"


def _skill_events(
    own_team: list[dict[str, Any]],
    enemy_team: list[dict[str, Any]],
    uid: str,
    enemy_id: str,
    skill_action: dict[str, Any],
) -> list[dict[str, Any]]:
    source = _member(own_team, int(skill_action["servant_slot"]))
    skill = get_servant(source["servant_id"])["skills"][int(skill_action["skill_index"])]
    events: list[dict[str, Any]] = [{
        "type": "skill", "source_player_id": uid, "source_slot": source["slot"],
        "label": skill["name"],
    }]
    requested = skill_action.get("target_slot")
    for effect in skill["effects"]:
        for target in _targets(own_team, enemy_team, source, effect.get("target", "self"), requested):
            target_player = uid if any(target is member for member in own_team) else enemy_id
            events.append({
                "type": _skill_reaction(effect["kind"]), "target_player_id": target_player,
                "target_slot": target["slot"], "label": EFFECT_NAMES.get(effect["kind"], effect["kind"]),
                "value": int(effect.get("value", 0)),
            })
    return events


def resolve_skill(state: dict[str, Any], user_id: str, skill_action: dict[str, Any]) -> dict[str, Any]:
    """Resolve the active servant's one optional skill without advancing initiative."""
    next_state = upgrade_battle_state(copy.deepcopy(state))
    uid = str(user_id)
    if next_state.get("active_player_id") != uid:
        raise ValueError("It is not this player's turn")
    active_slot = int(next_state["active_servant_slot"])
    validate_action(
        next_state,
        uid,
        {
            "skills": [skill_action],
            "commands": [{"servant_slot": active_slot, "kind": "attack"}],
        },
    )

    source_slot = int(skill_action["servant_slot"])
    used_for_player = next_state["phase_used_skills"].setdefault(uid, [])
    if any(int(item[0]) == source_slot for item in used_for_player):
        raise ValueError("The active servant may use at most one skill")

    enemy_id = next(pid for pid in next_state["teams"] if pid != uid)
    own_team = next_state["teams"][uid]
    enemy_team = next_state["teams"][enemy_id]
    events = _skill_events(own_team, enemy_team, uid, enemy_id, skill_action)
    logs = [f"── 第 {next_state['turn']} 轮 · {_name(own_team[source_slot])} 技能 ──"]
    used = _activate_skill(own_team, enemy_team, skill_action, logs)
    if used:
        used_for_player.append([used[0], used[1]])
    for team in next_state["teams"].values():
        for member in team:
            _resolve_defeat(member, logs)
    _finish_if_needed(next_state, logs)

    next_state["state_version"] = int(next_state.get("state_version", 1)) + 1
    next_state["last_events"] = events[-12:]
    next_state["log"] = (next_state.get("log", []) + logs)[-30:]
    return next_state


def resolve_tactic(state: dict[str, Any], user_id: str, tactic_action: dict[str, Any]) -> dict[str, Any]:
    """Resolve one master skill, random magic card, or hidden trap without advancing initiative."""
    next_state = upgrade_battle_state(copy.deepcopy(state))
    uid = str(user_id)
    if next_state.get("status") != "active" or next_state.get("active_player_id") != uid:
        raise ValueError("It is not this player's turn")
    tactical_state = next_state["tactics"][uid]
    if tactical_state.get("used_this_phase"):
        raise ValueError("Only one tactical action may be used during this servant's action")

    category = str(tactic_action.get("category", ""))
    tactic_id = str(tactic_action.get("id", ""))
    source = _active_member(next_state)
    enemy_id = next(player_id for player_id in next_state["teams"] if player_id != uid)
    own_team = next_state["teams"][uid]
    enemy_team = next_state["teams"][enemy_id]
    logs = [f"── 第 {next_state['turn']} 轮 · 战术行动 ──"]
    events: list[dict[str, Any]] = []

    if category == "master":
        tactic = MASTER_SKILLS.get(tactic_id)
        template = MASTER_TEMPLATES.get(
            str(tactical_state.get("master_template")),
            MASTER_TEMPLATES[DEFAULT_MASTER_TEMPLATE_ID],
        )
        if (
            not tactic
            or tactic_id not in template["skill_ids"]
            or not tactical_state["master_available"].get(tactic_id, False)
        ):
            raise ValueError("Master skill is unavailable")
        tactical_state["master_available"][tactic_id] = False
        label = f"御主技能·{tactic['name']}"
        effects = tactic["effects"]
    elif category == "magic":
        if tactical_state.get("magic_used") or tactical_state.get("magic_card") != tactic_id:
            raise ValueError("This round's random magic is unavailable")
        tactic = MAGIC_CARDS.get(tactic_id)
        if not tactic:
            raise ValueError("Unknown random magic")
        tactical_state["magic_used"] = True
        label = f"随机魔术·{tactic['name']}"
        effects = tactic["effects"]
    elif category == "trap":
        tactic = TRAP_CARDS.get(tactic_id)
        if not tactic:
            raise ValueError("Unknown trap card")
        if tactical_state.get("trap_card") != tactic_id:
            raise ValueError("This round's random trap is unavailable")
        if int(tactical_state.get("trap_charges", 0)) <= 0:
            raise ValueError("No trap charges remain")
        if tactical_state.get("armed_trap"):
            raise ValueError("A trap is already armed")
        tactical_state["armed_trap"] = tactic_id
        tactical_state["trap_charges"] = int(tactical_state["trap_charges"]) - 1
        tactical_state["used_this_phase"] = True
        label = f"陷阱牌·{tactic['name']}"
        logs.append("御主在战场上布置了一张隐藏陷阱牌。")
        events.append({"type": "tactic", "source_player_id": uid, "label": "陷阱已布置"})
        next_state["state_version"] = int(next_state.get("state_version", 1)) + 1
        next_state["last_events"] = events
        next_state["log"] = (next_state.get("log", []) + logs)[-30:]
        return next_state
    else:
        raise ValueError("Unknown tactical action")

    logs.append(f"御主发动「{label}」。")
    events.append({
        "type": "tactic", "source_player_id": uid, "source_slot": source["slot"], "label": label,
    })
    for effect in effects:
        for target in _targets(own_team, enemy_team, source, effect.get("target", "self"), None):
            _apply_effect(
                target,
                effect,
                logs,
                defer_tick=any(target is member for member in own_team),
            )
            events.append({
                "type": _skill_reaction(effect["kind"]),
                "target_player_id": uid if any(target is member for member in own_team) else enemy_id,
                "target_slot": target["slot"],
                "label": EFFECT_NAMES.get(effect["kind"], effect["kind"]),
                "value": int(effect.get("value", 0)),
            })
    tactical_state["used_this_phase"] = True
    for team in next_state["teams"].values():
        for member in team:
            _resolve_defeat(member, logs)
    _finish_if_needed(next_state, logs)
    next_state["state_version"] = int(next_state.get("state_version", 1)) + 1
    next_state["last_events"] = events[-16:]
    next_state["log"] = (next_state.get("log", []) + logs)[-30:]
    return next_state


def _trigger_trap(
    state: dict[str, Any],
    defender_id: str,
    attacker: dict[str, Any],
    logs: list[str],
    events: list[dict[str, Any]],
) -> int:
    tactical_state = state["tactics"][defender_id]
    trap_id = tactical_state.get("armed_trap")
    if not trap_id:
        return 0
    tactical_state["armed_trap"] = None
    trap = TRAP_CARDS[trap_id]
    logs.append(f"隐藏陷阱「{trap['name']}」被触发！")
    events.append({"type": "trap", "source_player_id": defender_id, "label": trap["name"]})
    if trap_id == "aegis_rune":
        for target in _living(state["teams"][defender_id]):
            _apply_effect(
                target,
                {"kind": "solemn_defense", "value": 1, "duration": 1, "target": "team"},
                logs,
                defer_tick=False,
            )
    elif trap_id == "binding_curse":
        _apply_effect(
            attacker,
            {"kind": "stun", "value": 1, "duration": 1, "target": "enemy"},
            logs,
            defer_tick=False,
        )
    elif trap_id == "mirror_prism":
        return 50
    return 0


def _finish_if_needed(state: dict[str, Any], logs: list[str]) -> bool:
    alive = {uid: bool(_living(team)) for uid, team in state["teams"].items()}
    survivors = [uid for uid, is_alive in alive.items() if is_alive]
    if len(survivors) == 1:
        state["status"] = "finished"
        state["winner_id"] = survivors[0]
        logs.append(f"玩家 {survivors[0]} 获得胜利。")
        return True
    if not survivors:
        state["status"] = "finished"
        state["winner_id"] = None
        logs.append("双方灵基同时崩解，战斗以平局结束。")
        return True
    return False


def _finish_on_round_limit(state: dict[str, Any], logs: list[str]) -> None:
    state["status"] = "finished"
    hp_totals = {
        uid: sum(max(0, int(member["hp"])) for member in team)
        for uid, team in state["teams"].items()
    }
    state["winner_id"] = (
        max(hp_totals, key=hp_totals.get) if len(set(hp_totals.values())) > 1 else None
    )
    logs.append("战斗达到轮次上限，按双方剩余生命结算。")


def _advance_initiative(state: dict[str, Any], logs: list[str]) -> None:
    order = state.get("initiative_order") or []
    next_index = int(state.get("initiative_index", 0)) + 1
    while next_index < len(order):
        actor = order[next_index]
        member = state["teams"][str(actor["player_id"])][int(actor["servant_slot"])]
        if member["hp"] > 0:
            state["initiative_index"] = next_index
            _sync_active_actor(state)
            return
        next_index += 1

    _tick_round_effects(state, logs)
    if int(state["turn"]) >= MAX_BATTLE_ROUNDS:
        _finish_on_round_limit(state, logs)
        return
    state["turn"] = int(state["turn"]) + 1
    for uid, tactical_state in state.get("tactics", {}).items():
        template = MASTER_TEMPLATES.get(
            str(tactical_state.get("master_template")),
            MASTER_TEMPLATES[DEFAULT_MASTER_TEMPLATE_ID],
        )
        tactical_state["magic_previous"] = tactical_state.get("magic_card")
        tactical_state["magic_card"] = _round_draw(
            state["match_id"],
            uid,
            state["turn"],
            "magic",
            template["magic_pool"],
            tactical_state.get("magic_previous"),
        )
        tactical_state["magic_round"] = state["turn"]
        tactical_state["magic_used"] = False
        tactical_state["trap_previous"] = tactical_state.get("trap_card")
        tactical_state["trap_card"] = _round_draw(
            state["match_id"],
            uid,
            state["turn"],
            "trap",
            template["trap_pool"],
            tactical_state.get("trap_previous"),
        )
        tactical_state["trap_round"] = state["turn"]
        tactical_state["used_this_phase"] = False
    state["initiative_order"] = _build_initiative_order(state)
    state["initiative_index"] = 0
    state["phase_used_skills"] = {}
    _sync_active_actor(state)
    logs.append(f"── 第 {state['turn']} 轮行动顺序已重新计算 ──")


def resolve_phase(state: dict[str, Any], user_id: str, action: dict[str, Any]) -> dict[str, Any]:
    next_state = upgrade_battle_state(copy.deepcopy(state))
    uid = str(user_id)
    if next_state.get("active_player_id") != uid:
        raise ValueError("It is not this player's turn")
    validate_action(next_state, uid, action)
    canonical = _canonical_action(next_state, uid, action)
    player_ids = list(next_state["teams"])
    enemy_id = next(pid for pid in player_ids if pid != uid)
    own_team = next_state["teams"][uid]
    enemy_team = next_state["teams"][enemy_id]
    active_slot = int(next_state["active_servant_slot"])
    active_member = _member(own_team, active_slot)
    logs: list[str] = [f"── 第 {next_state['turn']} 轮 · {_name(active_member)} 行动 ──"]
    events: list[dict[str, Any]] = []
    used_skills: set[tuple[int, int]] = {
        (int(item[0]), int(item[1]))
        for item in next_state.get("phase_used_skills", {}).get(uid, [])
    }

    for skill_action in canonical["skills"]:
        if any(slot == int(skill_action["servant_slot"]) for slot, _ in used_skills):
            raise ValueError("Each servant may use at most one skill per phase")
        events.extend(_skill_events(own_team, enemy_team, uid, enemy_id, skill_action))
        used = _activate_skill(own_team, enemy_team, skill_action, logs)
        if used:
            used_skills.add(used)

    total = 0
    if _is_stunned(active_member):
        logs.append(f"{_name(active_member)} 陷入眩晕，本次行动被跳过。")
    for command in canonical["commands"]:
        if not _living(enemy_team):
            break
        source_slot = int(command["servant_slot"])
        events.append({
            "type": "np" if command["kind"] == "np" else "attack",
            "source_player_id": uid, "source_slot": source_slot,
            "label": get_servant(own_team[source_slot]["servant_id"])["np"]["name"] if command["kind"] == "np" else "普通攻击",
        })
        trap_reflect = _trigger_trap(next_state, enemy_id, own_team[source_slot], logs, events)
        for target_slot, damage, critical, crit_chance in _plan_damage(next_state, uid, {"commands": [command]}, logs):
            target = enemy_team[target_slot]
            actual = min(target["hp"], damage)
            target["hp"] = max(0, target["hp"] - damage)
            _resolve_defeat(target, logs)
            total += actual
            if critical:
                events.append({
                    "type": "critical", "source_player_id": uid, "source_slot": source_slot,
                    "target_player_id": enemy_id, "target_slot": target_slot,
                    "value": actual, "chance": crit_chance, "label": "CRITICAL",
                })
            events.append({
                "type": "damage", "source_player_id": uid, "source_slot": source_slot,
                "target_player_id": enemy_id, "target_slot": target_slot, "value": actual,
            })
            reflected_percent = max(trap_reflect, _sum_effect(target, "damage_reflect"), 0)
            if actual > 0 and reflected_percent > 0:
                source = own_team[source_slot]
                reflected = min(source["hp"], int(round(actual * reflected_percent / 100)))
                source["hp"] = max(0, source["hp"] - reflected)
                _resolve_defeat(source, logs)
                logs.append(f"{_name(target)} 将 {reflected} 点伤害反射给 {_name(source)}。")
                events.append({
                    "type": "damage", "source_player_id": enemy_id, "source_slot": target_slot,
                    "target_player_id": uid, "target_slot": source_slot, "value": reflected,
                    "label": "伤害反射",
                })
    logs.append(f"{_name(active_member)} 本次行动造成 {total} 点伤害。")
    _tick_member(active_member, used_skills, logs)
    used_for_player = next_state.get("phase_used_skills", {}).get(uid, [])
    next_state["phase_used_skills"][uid] = [
        item for item in used_for_player if int(item[0]) != active_slot
    ]
    if not next_state["phase_used_skills"][uid]:
        next_state["phase_used_skills"].pop(uid, None)
    next_state["tactics"][uid]["used_this_phase"] = False

    if not _finish_if_needed(next_state, logs):
        _advance_initiative(next_state, logs)

    next_state["phase_no"] = int(next_state.get("phase_no", 1)) + 1
    next_state["state_version"] = int(next_state.get("state_version", 1)) + 1
    next_state["last_events"] = events[-24:]
    next_state["log"] = (next_state.get("log", []) + logs)[-30:]
    return next_state


def resolve_turn(state: dict[str, Any], actions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compatibility helper resolving one complete six-servant initiative round."""
    next_state = upgrade_battle_state(copy.deepcopy(state))
    if set(actions) != set(next_state["teams"]):
        raise ValueError("Both players must submit an action")
    starting_round = int(next_state["turn"])
    safety = 0
    while next_state["status"] == "active" and int(next_state["turn"]) == starting_round:
        safety += 1
        if safety > 6:
            raise RuntimeError("Initiative round did not advance")
        uid = next_state["active_player_id"]
        slot = int(next_state["active_servant_slot"])
        member = next_state["teams"][uid][slot]
        compatible = {
            "skills": [
                item for item in actions[uid].get("skills", [])
                if int(item.get("servant_slot", -1)) == slot
            ],
            "commands": [
                item for item in actions[uid].get("commands", [])
                if int(item.get("servant_slot", -1)) == slot
            ],
        }
        if member["hp"] > 0 and not _is_stunned(member) and not compatible["commands"]:
            compatible["commands"] = [{"servant_slot": slot, "kind": "attack"}]
        next_state = resolve_phase(next_state, uid, compatible)
    return next_state


def public_view(state: dict[str, Any], user_id: str) -> dict[str, Any]:
    if str(user_id) not in state["teams"]:
        raise ValueError("Player is not part of this battle")
    safe_state = copy.deepcopy(state)
    for uid, tactical_state in safe_state.get("tactics", {}).items():
        if uid == str(user_id):
            continue
        tactical_state["armed_trap"] = bool(tactical_state.get("armed_trap"))
        tactical_state.pop("master_available", None)
        tactical_state.pop("magic_card", None)
        tactical_state.pop("magic_previous", None)
        tactical_state.pop("magic_used", None)
        tactical_state.pop("trap_card", None)
        tactical_state.pop("trap_previous", None)
    return {
        "state": safe_state,
        "player_id": str(user_id),
        "opponent_id": next(uid for uid in state["teams"] if uid != str(user_id)),
        "tactical_catalogue": TACTICAL_CATALOGUE,
    }


def spectator_view(state: dict[str, Any]) -> dict[str, Any]:
    """Return a neutral read-only view without revealing either player's hand."""
    safe_state = copy.deepcopy(state)
    player_ids = list(safe_state["teams"])
    if len(player_ids) != 2:
        raise ValueError("Battle state must contain exactly two players")
    for tactical_state in safe_state.get("tactics", {}).values():
        tactical_state["armed_trap"] = bool(tactical_state.get("armed_trap"))
        for key in (
            "master_available", "magic_card", "magic_previous", "magic_used",
            "trap_card", "trap_previous",
        ):
            tactical_state.pop(key, None)
    return {
        "state": safe_state,
        "player_id": player_ids[0],
        "opponent_id": player_ids[1],
        "tactical_catalogue": TACTICAL_CATALOGUE,
        "spectator": True,
    }
