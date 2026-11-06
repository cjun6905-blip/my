from __future__ import annotations

import unittest

from src.chat.features.chaldea.battle_engine import (
    SUPPORTED_EFFECT_KINDS,
    _apply_effect,
    _consume_defense,
    _tick_member,
    _tick_round_effects,
    class_multiplier,
    create_battle_state,
    public_view,
    resolve_phase,
    resolve_skill,
    resolve_tactic,
    resolve_turn,
    validate_action,
)
from src.chat.features.chaldea.catalog import (
    EVENT_SERVANT_IDS,
    INITIAL_RELEASE_SERVANTS,
    SERVANTS,
    STARTER_SERVANTS,
)
from src.chat.features.chaldea.gacha import summon
from src.chat.features.chaldea.tactics import MASTER_TEMPLATES


class HighRollRandom:
    def randbelow(self, upper: int) -> int:
        return upper - 1


class PityRandom:
    def randbelow(self, upper: int) -> int:
        return upper - 1 if upper == 10_000 else 0


def _active_action(state: dict, *, target_slot: int | None = None) -> tuple[str, dict]:
    user_id = str(state["active_player_id"])
    slot = int(state["active_servant_slot"])
    member = state["teams"][user_id][slot]
    if any(effect["kind"] == "stun" for effect in member["debuffs"]):
        return user_id, {"commands": []}
    enemy_id = next(uid for uid in state["teams"] if uid != user_id)
    if target_slot is None:
        target_slot = next(item["slot"] for item in state["teams"][enemy_id] if item["hp"] > 0)
    return user_id, {
        "commands": [{"servant_slot": slot, "kind": "attack", "target_slot": target_slot}],
    }


def _resolve_active(state: dict, *, target_slot: int | None = None) -> dict:
    user_id, action = _active_action(state, target_slot=target_slot)
    return resolve_phase(state, user_id, action)


def _skill_for_active(state: dict, skill_index: int = 0) -> tuple[str, dict]:
    user_id = str(state["active_player_id"])
    slot = int(state["active_servant_slot"])
    member = state["teams"][user_id][slot]
    skill = SERVANTS[member["servant_id"]]["skills"][skill_index]
    targets = {effect.get("target", "self") for effect in skill["effects"]}
    action = {"servant_slot": slot, "skill_index": skill_index}
    if "ally" in targets:
        action["target_slot"] = next(item["slot"] for item in state["teams"][user_id] if item["hp"] > 0)
    elif "enemy" in targets:
        enemy_id = next(uid for uid in state["teams"] if uid != user_id)
        action["target_slot"] = next(item["slot"] for item in state["teams"][enemy_id] if item["hp"] > 0)
    return user_id, action


class ChaldeaEngineTests(unittest.TestCase):
    def test_speed_builds_six_servant_initiative_order(self):
        state = create_battle_state(
            "initiative-fixture",
            {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
        )
        order = state["initiative_order"]
        self.assertEqual(len(order), 6)
        self.assertEqual(len({(item["player_id"], item["servant_slot"]) for item in order}), 6)
        self.assertEqual([item["speed"] for item in order], sorted((item["speed"] for item in order), reverse=True))
        self.assertEqual(state["active_player_id"], order[0]["player_id"])
        self.assertEqual(state["active_servant_slot"], order[0]["servant_slot"])

    def test_legacy_first_player_argument_no_longer_overrides_speed(self):
        state = create_battle_state(
            "speed-wins",
            {"1": ["medusa_rider", "mash_shielder", "leonidas_lancer"], "2": ["nero_saber", "waver_caster", "hans_caster"]},
            first_player_id="2",
        )
        self.assertEqual(state["active_player_id"], "1")
        self.assertEqual(state["teams"]["1"][state["active_servant_slot"]]["servant_id"], "medusa_rider")

    def test_invalid_legacy_first_player_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "First player"):
            create_battle_state(
                "invalid-first-player",
                {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
                first_player_id="3",
            )

    def test_one_actor_resolves_immediately_then_queue_advances(self):
        state = create_battle_state("phase-fixture", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        first_actor = (state["active_player_id"], state["active_servant_slot"])
        enemy_id = next(uid for uid in state["teams"] if uid != state["active_player_id"])
        hp_before = sum(member["hp"] for member in state["teams"][enemy_id])
        result = _resolve_active(state)
        self.assertEqual(result["turn"], 1)
        self.assertEqual(result["initiative_index"], 1)
        self.assertNotEqual((result["active_player_id"], result["active_servant_slot"]), first_actor)
        self.assertLess(sum(member["hp"] for member in result["teams"][enemy_id]), hp_before)
        self.assertTrue(any(event["type"] == "damage" for event in result["last_events"]))

    def test_complete_compatibility_round_gives_every_living_servant_one_action(self):
        state = create_battle_state("round-fixture", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        actions = {
            uid: {"commands": [{"servant_slot": slot, "kind": "attack"} for slot in range(3)]}
            for uid in state["teams"]
        }
        result = resolve_turn(state, actions)
        self.assertEqual(result["turn"], 2)
        self.assertEqual(result["initiative_index"], 0)
        self.assertTrue(all(sum(m["hp"] for m in result["teams"][uid]) < sum(m["max_hp"] for m in result["teams"][uid]) for uid in result["teams"]))

    def test_confirmed_skill_resolves_immediately_without_advancing_actor(self):
        state = create_battle_state("instant-skill", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        user_id, skill = _skill_for_active(state)
        actor = (state["active_player_id"], state["active_servant_slot"])
        result = resolve_skill(state, user_id, skill)
        self.assertEqual((result["active_player_id"], result["active_servant_slot"]), actor)
        self.assertEqual(result["initiative_index"], 0)
        self.assertEqual(result["state_version"], 2)
        self.assertEqual(result["last_events"][0]["type"], "skill")
        source = result["teams"][user_id][actor[1]]
        self.assertEqual(source["cooldowns"][skill["skill_index"]], SERVANTS[source["servant_id"]]["skills"][skill["skill_index"]]["cooldown"])

    def test_active_servant_can_use_only_one_skill_before_attacking(self):
        state = create_battle_state("one-skill", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        user_id, skill = _skill_for_active(state)
        skilled = resolve_skill(state, user_id, skill)
        _, second = _skill_for_active(skilled, 1)
        with self.assertRaisesRegex(ValueError, "at most one skill"):
            resolve_skill(skilled, user_id, second)
        source = skilled["teams"][user_id][skilled["active_servant_slot"]]
        expected = SERVANTS[source["servant_id"]]["skills"][skill["skill_index"]]["cooldown"]
        ended = _resolve_active(skilled)
        self.assertEqual(ended["teams"][user_id][skill["servant_slot"]]["cooldowns"][skill["skill_index"]], expected)

    def test_stunned_active_servant_must_submit_empty_action_and_is_skipped(self):
        state = create_battle_state("stun-fixture", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        uid = state["active_player_id"]
        slot = state["active_servant_slot"]
        state["teams"][uid][slot]["debuffs"].append({"kind": "stun", "value": 1, "remaining": 1})
        with self.assertRaisesRegex(ValueError, "Only the active servant"):
            validate_action(state, uid, {"commands": [{"servant_slot": slot, "kind": "attack"}]})
        result = resolve_phase(state, uid, {"commands": []})
        self.assertEqual(result["initiative_index"], 1)
        self.assertFalse(any(effect["kind"] == "stun" for effect in result["teams"][uid][slot]["debuffs"]))

    def test_inactive_player_and_non_active_servant_are_rejected(self):
        state = create_battle_state("wrong-actor", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        inactive = next(uid for uid in state["teams"] if uid != state["active_player_id"])
        with self.assertRaisesRegex(ValueError, "not this player's turn"):
            validate_action(state, inactive, {"commands": []})
        wrong_slot = (int(state["active_servant_slot"]) + 1) % 3
        with self.assertRaisesRegex(ValueError, "Only the active servant"):
            validate_action(state, state["active_player_id"], {"commands": [{"servant_slot": wrong_slot, "kind": "attack"}]})

    def test_defeated_target_is_rejected(self):
        state = create_battle_state("dead-target", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        uid = state["active_player_id"]
        enemy_id = next(item for item in state["teams"] if item != uid)
        state["teams"][enemy_id][2]["hp"] = 0
        with self.assertRaisesRegex(ValueError, "Defeated servants"):
            validate_action(state, uid, {"commands": [{"servant_slot": state["active_servant_slot"], "kind": "attack", "target_slot": 2}]})

    def test_level_80_caps_hp_and_attack_growth_at_forty_percent(self):
        team = [{"servant_id": "medusa_rider", "level": 80, "np_level": 1}, "mash_shielder", "leonidas_lancer"]
        state = create_battle_state("growth", {"1": team, "2": list(STARTER_SERVANTS)})
        member = state["teams"]["1"][0]
        base = SERVANTS["medusa_rider"]
        self.assertEqual(member["level"], 80)
        self.assertEqual(member["attack"], round(base["attack"] * 1.40))
        self.assertEqual(member["max_hp"], round(base["hp"] * 1.40))
        self.assertEqual(member["speed"], base["speed"])

    def test_np5_is_stronger_but_only_ten_percent_above_np1(self):
        def fixture(np_level: int) -> dict:
            teams = {
                "1": [{"servant_id": "medusa_rider", "level": 1, "np_level": np_level}, "mash_shielder", "leonidas_lancer"],
                "2": ["nero_saber", "waver_caster", "hans_caster"],
            }
            value = create_battle_state("np-scale", teams)
            value["teams"]["1"][0]["np"] = 100
            return value

        np1 = fixture(1)
        np5 = fixture(5)
        action = {"commands": [{"servant_slot": 0, "kind": "np"}]}
        result1 = resolve_phase(np1, "1", action)
        result5 = resolve_phase(np5, "1", action)
        damage1 = sum(before["hp"] - after["hp"] for before, after in zip(np1["teams"]["2"], result1["teams"]["2"]))
        damage5 = sum(before["hp"] - after["hp"] for before, after in zip(np5["teams"]["2"], result5["teams"]["2"]))
        self.assertGreater(damage5, damage1)
        self.assertLessEqual(damage5, int(damage1 * 1.11) + 3)

    def test_normal_attack_is_positive_and_below_three_thousand_damage(self):
        state = create_battle_state("damage-band", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        result = _resolve_active(state)
        damage = sum(event.get("value", 0) for event in result["last_events"] if event["type"] == "damage")
        self.assertGreater(damage, 0)
        self.assertLess(damage, 3000)

    def test_class_advantage_is_meaningful_without_one_shot_multiplier(self):
        self.assertEqual(class_multiplier("Saber", "Lancer"), 1.3)
        self.assertEqual(class_multiplier("Lancer", "Saber"), 0.8)
        self.assertEqual(class_multiplier("Berserker", "Caster"), 1.3)
        self.assertEqual(class_multiplier("Shielder", "Berserker"), 1.0)
        self.assertEqual(class_multiplier("MoonCancer", "Avenger"), 1.3)
        self.assertEqual(class_multiplier("Foreigner", "Berserker"), 1.3)
        self.assertEqual(class_multiplier("Berserker", "Foreigner"), 0.8)

    def test_catalogue_has_complete_unique_servants_with_speed(self):
        self.assertEqual(len(SERVANTS), 104)
        self.assertEqual(len(INITIAL_RELEASE_SERVANTS), 51)
        self.assertEqual(len(set(INITIAL_RELEASE_SERVANTS)), 51)
        self.assertEqual(len(EVENT_SERVANT_IDS), 53)
        self.assertTrue(set(EVENT_SERVANT_IDS).isdisjoint(INITIAL_RELEASE_SERVANTS))
        self.assertTrue(set(STARTER_SERVANTS).issubset(INITIAL_RELEASE_SERVANTS))
        for servant_id in SERVANTS:
            servant = SERVANTS[servant_id]
            self.assertTrue(servant["released"])
            self.assertGreater(servant["speed"], 0)
            self.assertEqual(len(servant["skills"]), 3)
            self.assertGreaterEqual(len(servant["passives"]), 1)
            self.assertEqual(len({skill["name"] for skill in servant["skills"]}), 3)
            self.assertEqual(servant["art_url"], f"servants/{servant_id}.webp")
            self.assertEqual(servant["skill_art_url"], f"skills/{servant_id}.webp")
        for servant_id in EVENT_SERVANT_IDS:
            self.assertTrue(SERVANTS[servant_id]["event_only"])

    def test_new_event_release_has_four_servants_at_each_requested_rarity(self):
        release_ids = {
            "zheng_he_starsea_rider", "hypatia_astral_caster", "hou_yi_eclipse_archer", "tomoe_winter_saber",
            "sun_wukong_heaven_lancer", "wu_zhao_phoenix_ruler", "sinbad_sevenseas_rider", "atalanta_aurora_archer",
            "nuwa_genesis_alterego", "odin_runeking_foreigner", "amaterasu_dawn_beast", "prometheus_firstfire_pretender",
        }
        self.assertEqual(len(release_ids), 12)
        self.assertTrue(release_ids.issubset(EVENT_SERVANT_IDS))
        for rarity in (5, 6, 7):
            self.assertEqual(sum(SERVANTS[sid]["rarity"] == rarity for sid in release_ids), 4)

    def test_new_event_skill_effects_resolve_on_the_server(self):
        state = create_battle_state(
            "new-event-authority",
            {
                "1": ["sun_wukong_heaven_lancer", "nuwa_genesis_alterego", "hypatia_astral_caster"],
                "2": ["prometheus_firstfire_pretender", "odin_runeking_foreigner", "amaterasu_dawn_beast"],
            },
        )
        active_uid = state["active_player_id"]
        active_slot = state["active_servant_slot"]
        active = state["teams"][active_uid][active_slot]
        skill = SERVANTS[active["servant_id"]]["skills"][0]
        before = state["state_version"]
        resolved = resolve_skill(
            state,
            active_uid,
            {"servant_slot": active_slot, "skill_index": 0},
        )
        self.assertEqual(resolved["state_version"], before + 1)
        self.assertTrue(resolved["last_events"])
        self.assertTrue(all(effect["kind"] in SUPPORTED_EFFECT_KINDS for effect in skill["effects"]))

    def test_event_mechanics_are_enforced_by_the_engine(self):
        state = create_battle_state(
            "event-mechanics",
            {"1": ["lord_logres_saber", "aesc_final_caster", "jeanne_ruler"],
             "2": ["ishtar_archer", "merlin_caster", "ereshkigal_lancer"]},
        )
        defender = state["teams"]["1"][0]
        attacker = state["teams"]["2"][0]
        logs: list[str] = []
        defender["buffs"] = []

        _apply_effect(defender, {"kind": "debuff_immunity", "value": 1, "duration": 3}, logs)
        _apply_effect(defender, {"kind": "stun", "value": 1, "duration": 1}, logs)
        self.assertFalse(any(effect["kind"] == "stun" for effect in defender["debuffs"]))
        self.assertFalse(any(effect["kind"] == "debuff_immunity" for effect in defender["buffs"]))

        defender["cooldowns"] = [5, 4, 3]
        _apply_effect(defender, {"kind": "cooldown_reduce", "value": 2}, logs)
        self.assertEqual(defender["cooldowns"], [3, 2, 1])

        _apply_effect(defender, {"kind": "solemn_defense", "value": 1, "duration": 2}, logs)
        _apply_effect(attacker, {"kind": "invincible_pierce", "value": 1, "duration": 2}, logs)
        self.assertEqual(_consume_defense(attacker, defender), "solemn_defense")
        _apply_effect(defender, {"kind": "invincible", "value": 1, "duration": 2}, logs)
        self.assertIsNone(_consume_defense(attacker, defender))

    def test_periodic_np_cost_and_delayed_lake_dream_tick(self):
        state = create_battle_state(
            "event-periodic",
            {"1": ["lord_logres_saber", *STARTER_SERVANTS[:2]], "2": list(STARTER_SERVANTS)},
        )
        member = state["teams"]["1"][0]
        logs: list[str] = []
        starting_hp = member["hp"]
        _apply_effect(member, {"kind": "np_per_turn", "value": 20, "duration": 2}, logs, defer_tick=False)
        _apply_effect(member, {"kind": "hp_loss_per_turn", "value": 500, "duration": 2}, logs, defer_tick=False)
        _apply_effect(member, {"kind": "delayed_stun", "value": 1, "duration": 2}, logs, defer_tick=False)

        _tick_member(member, set(), logs)
        _tick_member(member, set(), logs)
        self.assertEqual(member["np"], 40)
        self.assertEqual(member["hp"], starting_hp - 1000)
        self.assertTrue(any(effect["kind"] == "stun" for effect in member["debuffs"]))

    def test_invincible_blocks_every_hit_until_complete_round_end(self):
        state = create_battle_state(
            "round-invincible",
            {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
        )
        defender = state["teams"]["1"][0]
        attacker = state["teams"]["2"][0]
        logs: list[str] = []
        _apply_effect(defender, {"kind": "invincible", "value": 1, "duration": 1}, logs)
        self.assertEqual(_consume_defense(attacker, defender), "invincible")
        self.assertEqual(_consume_defense(attacker, defender), "invincible")
        self.assertTrue(any(effect["kind"] == "invincible" for effect in defender["buffs"]))
        _tick_member(defender, set(), logs)
        self.assertTrue(any(effect["kind"] == "invincible" for effect in defender["buffs"]))
        _tick_round_effects(state, logs)
        self.assertFalse(any(effect["kind"] == "invincible" for effect in defender["buffs"]))

    def test_avalon_execute_and_full_damage_reflection_are_authoritative(self):
        execute_state = create_battle_state(
            "avalon-execute",
            {"1": ["artoria_avalon_saber", "mash_shielder", "leonidas_lancer"],
             "2": ["waver_caster", "hans_caster", "tiamat_mother"]},
        )
        self.assertEqual(execute_state["active_player_id"], "1")
        target = execute_state["teams"]["2"][0]
        target["hp"] = int(target["max_hp"] * 0.35)
        executed = resolve_skill(execute_state, "1", {"servant_slot": 0, "skill_index": 2, "target_slot": 0})
        self.assertEqual(executed["teams"]["2"][0]["hp"], 0)

        reflect_state = create_battle_state(
            "avalon-reflect",
            {"1": ["medusa_anime_rider", "mash_shielder", "leonidas_lancer"],
             "2": ["artoria_avalon_saber", "waver_caster", "hans_caster"]},
        )
        defender = reflect_state["teams"]["2"][0]
        _apply_effect(defender, {"kind": "damage_reflect", "value": 100, "duration": 1}, [])
        attacker_before = reflect_state["teams"]["1"][0]["hp"]
        defender_before = defender["hp"]
        reflected = resolve_phase(
            reflect_state,
            "1",
            {"commands": [{"servant_slot": 0, "kind": "attack", "target_slot": 0}]},
        )
        damage_taken = defender_before - reflected["teams"]["2"][0]["hp"]
        self.assertGreater(damage_taken, 0)
        self.assertEqual(attacker_before - reflected["teams"]["1"][0]["hp"], damage_taken)

    def test_public_stats_keep_five_digit_scale_and_all_effects_are_supported(self):
        self.assertGreaterEqual(SERVANTS["artoria_saber"]["attack"], 9000)
        self.assertGreaterEqual(SERVANTS["heracles_berserker"]["attack"], 10000)
        used = {
            effect["kind"]
            for servant in SERVANTS.values()
            for source in [*servant["skills"], servant["np"], *servant["passives"]]
            for effect in source["effects"]
        }
        self.assertEqual(used - SUPPORTED_EFFECT_KINDS, set())

    def test_passives_tactics_hidden_traps_and_critical_feedback(self):
        teams = {
            "1": ["artoria_crowned_avalon_saber", "aesc_genesis_caster", "space_ishtar_origin_avenger"],
            "2": ["oberon_vortigern_pretender", "mash_shielder", "nero_saber"],
        }
        state = create_battle_state("p9-tactics", teams)
        artoria = state["teams"]["1"][0]
        self.assertEqual(SERVANTS[artoria["servant_id"]]["rarity"], 6)
        self.assertTrue(any(effect["kind"] == "damage_reflect" for effect in artoria["buffs"]))
        self.assertTrue(any(effect["kind"] == "np_per_turn" for effect in state["teams"]["1"][1]["buffs"]))

        uid = state["active_player_id"]
        strengthened = resolve_tactic(state, uid, {"category": "master", "id": "command_seal"})
        active = strengthened["teams"][uid][strengthened["active_servant_slot"]]
        self.assertGreaterEqual(active["np"], 50)
        with self.assertRaises(ValueError):
            resolve_tactic(strengthened, uid, {"category": "magic", "id": strengthened["tactics"][uid]["magic_card"]})

        trapped = create_battle_state("p9-hidden-trap", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        attacker_id = trapped["active_player_id"]
        defender_id = next(player_id for player_id in trapped["teams"] if player_id != attacker_id)
        trapped["tactics"][defender_id]["armed_trap"] = "binding_curse"
        opponent_view = public_view(trapped, attacker_id)["state"]
        self.assertIs(opponent_view["tactics"][defender_id]["armed_trap"], True)
        attacker = trapped["teams"][attacker_id][trapped["active_servant_slot"]]
        target = trapped["teams"][defender_id][0]
        target_hp = target["hp"]
        resolved = resolve_phase(
            trapped,
            attacker_id,
            {"commands": [{"servant_slot": attacker["slot"], "kind": "attack", "target_slot": 0}]},
        )
        self.assertEqual(resolved["teams"][defender_id][0]["hp"], target_hp)
        self.assertIsNone(resolved["tactics"][defender_id]["armed_trap"])
        self.assertTrue(any(event["type"] == "trap" for event in resolved["last_events"]))

        critical = create_battle_state("p9-critical", {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)})
        critical_uid = critical["active_player_id"]
        critical_member = critical["teams"][critical_uid][critical["active_servant_slot"]]
        critical_member["stars"] = 50
        _apply_effect(critical_member, {"kind": "crit_chance_up", "value": 100, "duration": 1}, [])
        critical_result = _resolve_active(critical)
        self.assertTrue(any(event["type"] == "critical" for event in critical_result["last_events"]))

    def test_random_magic_and_defensive_traps_resolve_authoritatively(self):
        magic = create_battle_state(
            "p9-magic",
            {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
        )
        caster_id = magic["active_player_id"]
        before_stars = [member["stars"] for member in magic["teams"][caster_id]]
        magic["tactics"][caster_id]["magic_card"] = "starfall"
        enchanted = resolve_tactic(magic, caster_id, {"category": "magic", "id": "starfall"})
        self.assertTrue(enchanted["tactics"][caster_id]["magic_used"])
        self.assertEqual(
            [member["stars"] for member in enchanted["teams"][caster_id]],
            [value + 15 for value in before_stars],
        )

        for trap_id in ("aegis_rune", "mirror_prism"):
            with self.subTest(trap=trap_id):
                trapped = create_battle_state(
                    f"p9-{trap_id}",
                    {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
                )
                attacker_id = trapped["active_player_id"]
                defender_id = next(uid for uid in trapped["teams"] if uid != attacker_id)
                trapped["tactics"][defender_id]["armed_trap"] = trap_id
                attacker = trapped["teams"][attacker_id][trapped["active_servant_slot"]]
                defender = trapped["teams"][defender_id][0]
                attacker_hp = attacker["hp"]
                defender_hp = defender["hp"]
                result = resolve_phase(
                    trapped,
                    attacker_id,
                    {"commands": [{"servant_slot": attacker["slot"], "kind": "attack", "target_slot": 0}]},
                )
                defender_loss = defender_hp - result["teams"][defender_id][0]["hp"]
                attacker_loss = attacker_hp - result["teams"][attacker_id][attacker["slot"]]["hp"]
                self.assertIsNone(result["tactics"][defender_id]["armed_trap"])
                self.assertTrue(any(event["type"] == "trap" for event in result["last_events"]))
                if trap_id == "aegis_rune":
                    self.assertEqual(defender_loss, 0)
                    self.assertEqual(attacker_loss, 0)
                else:
                    self.assertGreater(defender_loss, 0)
                    self.assertEqual(attacker_loss, round(defender_loss * 0.5))

    def test_master_templates_limit_skills_and_random_traps_are_authoritative(self):
        templates = {"1": "atlas_uniform", "2": "combat_uniform"}
        state = create_battle_state(
            "p10-master-templates",
            {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
            master_templates=templates,
        )
        for uid, template_id in templates.items():
            tactical = state["tactics"][uid]
            self.assertEqual(tactical["master_template"], template_id)
            self.assertEqual(
                set(tactical["master_available"]),
                set(MASTER_TEMPLATES[template_id]["skill_ids"]),
            )
            self.assertIn(tactical["magic_card"], MASTER_TEMPLATES[template_id]["magic_pool"])
            self.assertIn(tactical["trap_card"], MASTER_TEMPLATES[template_id]["trap_pool"])

        active_uid = state["active_player_id"]
        with self.assertRaisesRegex(ValueError, "Master skill"):
            resolve_tactic(state, active_uid, {"category": "master", "id": "command_seal"})

        trap_state = create_battle_state(
            "p10-random-trap",
            {"1": list(STARTER_SERVANTS), "2": list(STARTER_SERVANTS)},
            master_templates=templates,
        )
        active_uid = trap_state["active_player_id"]
        drawn = trap_state["tactics"][active_uid]["trap_card"]
        wrong = next(trap_id for trap_id in MASTER_TEMPLATES[templates[active_uid]]["trap_pool"] if trap_id != drawn)
        with self.assertRaisesRegex(ValueError, "random trap"):
            resolve_tactic(trap_state, active_uid, {"category": "trap", "id": wrong})
        armed = resolve_tactic(trap_state, active_uid, {"category": "trap", "id": drawn})
        self.assertEqual(armed["tactics"][active_uid]["armed_trap"], drawn)
        enemy_uid = next(uid for uid in armed["teams"] if uid != active_uid)
        enemy_view = public_view(armed, enemy_uid)["state"]
        self.assertNotIn("trap_card", enemy_view["tactics"][active_uid])
        self.assertEqual(enemy_view["tactics"][active_uid]["master_template"], templates[active_uid])

    def test_gacha_guarantees_remain_unchanged(self):
        eleven = summon(11, 0, HighRollRandom())
        self.assertEqual(len(eleven.servant_ids), 11)
        self.assertTrue(set(eleven.servant_ids).isdisjoint(EVENT_SERVANT_IDS))
        self.assertTrue(any(SERVANTS[servant_id]["rarity"] >= 4 for servant_id in eleven.servant_ids))
        pity = summon(1, 59, PityRandom())
        self.assertNotIn(pity.servant_ids[0], EVENT_SERVANT_IDS)
        self.assertEqual(SERVANTS[pity.servant_ids[0]]["rarity"], 5)
        self.assertEqual(pity.new_pity, 0)


if __name__ == "__main__":
    unittest.main()
