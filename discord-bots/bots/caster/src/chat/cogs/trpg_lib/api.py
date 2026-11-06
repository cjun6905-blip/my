"""Thin async client for the trpg-server HTTP API."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class TrpgApiError(Exception):
    """Error with a message that is safe to show to the Discord user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class TrpgApi:
    def __init__(self, base_url: str, token: str, timeout_s: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session: aiohttp.ClientSession | None = None

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self, actor_id: int | str | None, admin: bool) -> dict[str, str]:
        h = {"X-Trpg-Token": self.token}
        if actor_id is not None:
            h["X-Actor-Id"] = str(actor_id)
            h["X-Actor-Admin"] = "1" if admin else "0"
        return h

    async def request(
        self,
        method: str,
        path: str,
        *,
        actor_id: int | str | None = None,
        admin: bool = False,
        json: Any = None,
        params: dict | None = None,
        data: Any = None,
        raw: bool = False,
    ) -> Any:
        s = await self.session()
        try:
            async with s.request(
                method, self.base_url + path, headers=self._headers(actor_id, admin), json=json, params=params, data=data
            ) as resp:
                if raw:
                    body = await resp.read()
                    if resp.status >= 400:
                        raise TrpgApiError(resp.status, _err_text(body))
                    return body
                if resp.status >= 400:
                    body = await resp.read()
                    raise TrpgApiError(resp.status, _err_text(body))
                if resp.content_type == "application/json":
                    return await resp.json()
                return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("trpg api %s %s failed: %r", method, path, e)
            raise TrpgApiError(503, "跑团服务暂时无法连接，请稍后再试") from e

    # -------------------------------------------------------------- campaigns
    async def create_campaign(self, actor, guild_id, name, channel_id, system):
        return await self.request(
            "POST", "/campaigns", actor_id=actor.id, admin=_admin(actor),
            json={"guild_id": str(guild_id), "name": name, "channel_id": str(channel_id) if channel_id else None, "system": system},
        )

    async def list_campaigns(self, guild_id, include_archived=False):
        return await self.request("GET", "/campaigns", params={"guild_id": str(guild_id), "include_archived": str(include_archived).lower()})

    async def resolve_campaign(self, guild_id, channel_ids):
        return await self.request(
            "GET", "/campaigns/resolve", params={"guild_id": str(guild_id), "channel_ids": ",".join(str(c) for c in channel_ids if c)}
        )

    async def get_campaign(self, campaign_id):
        return await self.request("GET", f"/campaigns/{campaign_id}")

    async def patch_campaign(self, actor, campaign_id, **fields):
        return await self.request("PATCH", f"/campaigns/{campaign_id}", actor_id=actor.id, admin=_admin(actor), json=fields)

    async def bind_channel(self, actor, campaign_id, channel_id):
        return await self.request(
            "POST", f"/campaigns/{campaign_id}/channels", actor_id=actor.id, admin=_admin(actor), json={"channel_id": str(channel_id)}
        )

    async def unbind_channel(self, actor, channel_id):
        return await self.request("DELETE", f"/channels/{channel_id}", actor_id=actor.id, admin=_admin(actor))

    async def set_member(self, actor, campaign_id, user_id, role):
        return await self.request(
            "PUT", f"/campaigns/{campaign_id}/members", actor_id=actor.id, admin=_admin(actor), json={"user_id": str(user_id), "role": role}
        )

    async def remove_member(self, actor, campaign_id, user_id):
        return await self.request("DELETE", f"/campaigns/{campaign_id}/members/{user_id}", actor_id=actor.id, admin=_admin(actor))

    # ------------------------------------------------------------- characters
    async def create_character(self, actor, campaign_id, name, attrs, notes=None, owner_user_id=None):
        return await self.request(
            "POST", f"/campaigns/{campaign_id}/characters", actor_id=actor.id, admin=_admin(actor),
            json={"name": name, "attrs": attrs, "notes": notes, "owner_user_id": str(owner_user_id) if owner_user_id else None},
        )

    async def list_characters(self, campaign_id, owner_user_id=None):
        params = {"owner_user_id": str(owner_user_id)} if owner_user_id else None
        return await self.request("GET", f"/campaigns/{campaign_id}/characters", params=params)

    async def find_character(self, actor, campaign_id, name=None):
        params = {"name": name} if name else None
        return await self.request("GET", f"/campaigns/{campaign_id}/characters/find", actor_id=actor.id, admin=_admin(actor), params=params)

    async def get_character(self, character_id):
        return await self.request("GET", f"/characters/{character_id}")

    async def patch_character(self, actor, character_id, **fields):
        return await self.request("PATCH", f"/characters/{character_id}", actor_id=actor.id, admin=_admin(actor), json=fields)

    async def delete_character(self, actor, character_id):
        return await self.request("DELETE", f"/characters/{character_id}", actor_id=actor.id, admin=_admin(actor))

    async def set_active(self, actor, character_id):
        return await self.request("POST", f"/characters/{character_id}/active", actor_id=actor.id, admin=_admin(actor))

    async def upload_portrait(self, actor, character_id, data: bytes, filename: str):
        form = aiohttp.FormData()
        form.add_field("file", data, filename=filename, content_type="application/octet-stream")
        return await self.request("PUT", f"/characters/{character_id}/portrait", actor_id=actor.id, admin=_admin(actor), data=form)

    async def get_portrait(self, character_id) -> bytes | None:
        try:
            return await self.request("GET", f"/characters/{character_id}/portrait", raw=True)
        except TrpgApiError as e:
            if e.status == 404:
                return None
            raise

    async def history(self, character_id, limit=15):
        return await self.request("GET", f"/characters/{character_id}/history", params={"limit": str(limit)})

    # ------------------------------------------------------------------- dice
    async def roll(self, actor, expr, campaign_id=None, character_id=None, hidden=False):
        return await self.request(
            "POST", "/roll", actor_id=actor.id, admin=_admin(actor),
            json={"expr": expr, "campaign_id": campaign_id, "character_id": character_id, "hidden": hidden},
        )

    async def check(self, actor, skill, campaign_id=None, character_id=None, target=None, bonus=0, penalty=0, hidden=False):
        return await self.request(
            "POST", "/check", actor_id=actor.id, admin=_admin(actor),
            json={"skill": skill, "campaign_id": campaign_id, "character_id": character_id, "target": target, "bonus": bonus, "penalty": penalty, "hidden": hidden},
        )

    # ----------------------------------------------------------------- combat
    async def start_combat(self, actor, campaign_id):
        return await self.request("POST", f"/campaigns/{campaign_id}/combat", actor_id=actor.id, admin=_admin(actor))

    async def active_combat(self, campaign_id):
        return await self.request("GET", f"/campaigns/{campaign_id}/combat")

    async def get_combat(self, encounter_id):
        return await self.request("GET", f"/combat/{encounter_id}")

    async def add_combatant(self, actor, encounter_id, **fields):
        return await self.request("POST", f"/combat/{encounter_id}/combatants", actor_id=actor.id, admin=_admin(actor), json=fields)

    async def remove_combatant(self, actor, encounter_id, combatant_id):
        return await self.request("DELETE", f"/combat/{encounter_id}/combatants/{combatant_id}", actor_id=actor.id, admin=_admin(actor))

    async def roll_initiative(self, actor, encounter_id, only_missing=False):
        return await self.request(
            "POST", f"/combat/{encounter_id}/initiative", actor_id=actor.id, admin=_admin(actor), params={"only_missing": str(only_missing).lower()}
        )

    async def set_initiative(self, actor, encounter_id, combatant_id, value):
        return await self.request(
            "PUT", f"/combat/{encounter_id}/initiative", actor_id=actor.id, admin=_admin(actor), json={"combatant_id": combatant_id, "value": value}
        )

    async def next_turn(self, actor, encounter_id):
        return await self.request("POST", f"/combat/{encounter_id}/next", actor_id=actor.id, admin=_admin(actor))

    async def change_hp(self, actor, encounter_id, combatant_id, delta, reason=""):
        return await self.request(
            "POST", f"/combat/{encounter_id}/hp", actor_id=actor.id, admin=_admin(actor),
            json={"combatant_id": combatant_id, "delta": delta, "reason": reason},
        )

    async def attack(self, actor, encounter_id, attacker_id, target_id, skill=None, attack_expr=None, damage_expr=None):
        return await self.request(
            "POST", f"/combat/{encounter_id}/attack", actor_id=actor.id, admin=_admin(actor),
            json={"attacker_id": attacker_id, "target_id": target_id, "skill": skill, "attack_expr": attack_expr, "damage_expr": damage_expr},
        )

    async def undo(self, actor, encounter_id):
        return await self.request("POST", f"/combat/{encounter_id}/undo", actor_id=actor.id, admin=_admin(actor))

    async def end_combat(self, actor, encounter_id):
        return await self.request("POST", f"/combat/{encounter_id}/end", actor_id=actor.id, admin=_admin(actor))

    # ------------------------------------------------------------------ items
    async def list_items(self, character_id):
        return await self.request("GET", f"/characters/{character_id}/items")

    async def add_item(self, actor, character_id, name, qty=1, note=None, reason=""):
        return await self.request(
            "POST", f"/characters/{character_id}/items", actor_id=actor.id, admin=_admin(actor),
            json={"name": name, "qty": qty, "note": note, "reason": reason},
        )

    async def remove_item(self, actor, character_id, name, qty=None, reason=""):
        return await self.request(
            "POST", f"/characters/{character_id}/items/remove", actor_id=actor.id, admin=_admin(actor),
            json={"name": name, "qty": qty, "reason": reason},
        )

    async def update_item(self, actor, character_id, name, new_name=None, note=None):
        return await self.request(
            "PATCH", f"/characters/{character_id}/items", actor_id=actor.id, admin=_admin(actor),
            json={"name": name, "new_name": new_name, "note": note},
        )

    async def transfer_item(self, actor, character_id, name, to_character_id, qty=None):
        return await self.request(
            "POST", f"/characters/{character_id}/items/transfer", actor_id=actor.id, admin=_admin(actor),
            json={"name": name, "to_character_id": to_character_id, "qty": qty},
        )

    # ------------------------------------------------------------ CoC helpers
    async def sanity_check(self, actor, character_id, success_expr, fail_expr, campaign_id=None):
        return await self.request(
            "POST", "/sc", actor_id=actor.id, admin=_admin(actor),
            json={"campaign_id": campaign_id, "character_id": character_id, "success_expr": success_expr, "fail_expr": fail_expr},
        )

    async def skill_growth(self, actor, character_id, skill, campaign_id=None):
        return await self.request(
            "POST", "/en", actor_id=actor.id, admin=_admin(actor),
            json={"campaign_id": campaign_id, "character_id": character_id, "skill": skill},
        )

    # --------------------------------------------------------- Sword World
    async def sw_rating(self, actor, expr, campaign_id=None, character_id=None, hidden=False):
        return await self.request(
            "POST", "/sw/rating", actor_id=actor.id, admin=_admin(actor),
            json={"campaign_id": campaign_id, "character_id": character_id, "expr": expr, "hidden": hidden},
        )

    async def sw_table(self, power):
        return await self.request("GET", f"/sw/table/{int(power)}")

    async def sw_check(self, actor, modifier="", target=None, campaign_id=None, character_id=None, hidden=False):
        return await self.request(
            "POST", "/sw/check", actor_id=actor.id, admin=_admin(actor),
            json={
                "campaign_id": campaign_id, "character_id": character_id,
                "modifier": modifier or "", "target": target, "hidden": hidden,
            },
        )

    async def sw_races(self):
        return await self.request("GET", "/sw/races")

    async def sw_births(self, race, source=None):
        params = {"race": race}
        if source:
            params["source"] = source
        return await self.request("GET", "/sw/births", params=params)

    async def sw_generate(self, actor, race, ji=None, tai=None, shin=None, level=1, magic_level=0, character_id=None, origin=None, source=None, birth_roll=None):
        return await self.request(
            "POST", "/sw/generate", actor_id=actor.id, admin=_admin(actor),
            json={
                "race": race, "origin": origin, "source": source, "birth_roll": birth_roll,
                "ji": ji, "tai": tai, "shin": shin,
                "level": level, "magic_level": magic_level, "character_id": character_id,
            },
        )

    async def sw_growth(self, actor, character_id=None, apply_to=None, dice=None):
        return await self.request(
            "POST", "/sw/growth", actor_id=actor.id, admin=_admin(actor),
            json={"character_id": character_id, "apply_to": apply_to, "dice": dice},
        )


def _admin(user) -> bool:
    perms = getattr(user, "guild_permissions", None)
    return bool(perms and (perms.manage_guild or perms.administrator))


def _err_text(body: bytes) -> str:
    try:
        import json

        d = json.loads(body.decode("utf-8", "replace"))
        if isinstance(d, dict):
            if "error" in d:
                return str(d["error"])
            if "detail" in d:
                det = d["detail"]
                if isinstance(det, list):
                    return "参数有误：" + "; ".join(f"{'.'.join(map(str, x.get('loc', [])))}: {x.get('msg')}" for x in det)
                return str(det)
    except Exception:
        pass
    return "服务返回了错误"
