# -*- coding: utf-8 -*-
"""房间管理：令牌签发、连接跟踪、广播、超时托管、过期清理。

只用内存，不碰数据库——按驾驶员要求，本功能不做押注也不落库，
进程重启即清空所有房间（对一局十几分钟的牌局是可接受的取舍）。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .engine import Game, Phase, RuleError

log = logging.getLogger(__name__)

# --- 可调参数 ---------------------------------------------------------------
ROOM_TTL_SECONDS = 3 * 60 * 60      # 房间最长存活 3 小时
TURN_SECONDS = 120                  # 单回合思考时间，超时自动托管
FINISHED_LINGER_SECONDS = 15 * 60   # 分出胜负后保留 15 分钟供查看
MAX_ROOMS = 40                      # 内存护栏：并发房间上限
CLEANUP_INTERVAL = 60


@dataclass
class Seat:
    user_id: str
    name: str
    token: str


@dataclass
class Room:
    id: str
    seats: list[Seat]
    game: Game
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    # user_id -> 该玩家当前的所有 websocket（同一人可能开了多个标签页）
    sockets: dict[str, set[Any]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    deadline: Optional[float] = None
    _turn_token: int = 0

    def seat_by_token(self, token: str) -> Optional[Seat]:
        for seat in self.seats:
            if secrets.compare_digest(seat.token, token):
                return seat
        return None

    @property
    def expired(self) -> bool:
        if time.time() - self.created_at > ROOM_TTL_SECONDS:
            return True
        if self.finished_at and time.time() - self.finished_at > FINISHED_LINGER_SECONDS:
            return True
        return False


class RoomManager:
    def __init__(self, public_base_url: str = ""):
        self.rooms: dict[str, Room] = {}
        self.public_base_url = public_base_url.rstrip("/")
        self._cleanup_task: Optional[asyncio.Task] = None

    # --- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                stale = [rid for rid, room in self.rooms.items() if room.expired]
                for rid in stale:
                    self.rooms.pop(rid, None)
                    log.info("清理过期房间 %s", rid)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("房间清理循环出错")

    # --- 创建 ---------------------------------------------------------------

    def create_room(self, players: list[dict]) -> dict:
        """players: [{"id": discord_user_id, "name": 显示名}, ...]，必须 3 人。"""
        # 先顺手清一次，避免长期不活跃时堆积
        for rid in [r for r, room in self.rooms.items() if room.expired]:
            self.rooms.pop(rid, None)
        if len(self.rooms) >= MAX_ROOMS:
            raise RuleError("同时进行的牌局太多了，请稍后再开")

        ids = [str(p["id"]) for p in players]
        if len(set(ids)) != len(ids):
            raise RuleError("同一个人不能占两个座位")

        room_id = secrets.token_urlsafe(6)
        seats = [
            Seat(user_id=str(p["id"]), name=str(p["name"])[:24], token=secrets.token_urlsafe(24))
            for p in players
        ]
        game = Game(room_id, [(s.user_id, s.name) for s in seats])
        room = Room(id=room_id, seats=seats, game=game)
        self.rooms[room_id] = room
        self._arm_deadline(room)

        log.info("创建房间 %s，玩家 %s", room_id, ids)
        return {
            "room_id": room_id,
            "expires_in": ROOM_TTL_SECONDS,
            "players": [
                {
                    "user_id": s.user_id,
                    "name": s.name,
                    "url": f"{self.public_base_url}/bluff/r/{room_id}?t={s.token}",
                }
                for s in seats
            ],
        }

    def get(self, room_id: str) -> Optional[Room]:
        room = self.rooms.get(room_id)
        if room and room.expired:
            self.rooms.pop(room_id, None)
            return None
        return room

    # --- 连接 ---------------------------------------------------------------

    def attach(self, room: Room, user_id: str, socket: Any) -> None:
        room.sockets.setdefault(user_id, set()).add(socket)
        room.game.player(user_id).connected = True

    def detach(self, room: Room, user_id: str, socket: Any) -> None:
        conns = room.sockets.get(user_id)
        if conns:
            conns.discard(socket)
            if not conns:
                room.sockets.pop(user_id, None)
                try:
                    room.game.player(user_id).connected = False
                except RuleError:
                    pass

    # --- 广播 ---------------------------------------------------------------

    async def broadcast(self, room: Room) -> None:
        """给每个连接单独发「他自己的」视图——手牌绝不串台。"""
        dead: list[tuple[str, Any]] = []
        for user_id, sockets in list(room.sockets.items()):
            try:
                payload = {"type": "state", "state": room.game.view_for(user_id)}
            except RuleError:
                continue
            # deadline 是绝对时间戳，同时带上服务端 now，让前端自己校准时钟偏差
            payload["state"]["deadline"] = room.deadline
            payload["state"]["now"] = time.time()
            for socket in list(sockets):
                try:
                    await socket.send_json(payload)
                except Exception:
                    dead.append((user_id, socket))
        for user_id, socket in dead:
            self.detach(room, user_id, socket)

    async def send_error(self, socket: Any, message: str) -> None:
        try:
            await socket.send_json({"type": "error", "message": message})
        except Exception:
            pass

    # --- 回合计时 -----------------------------------------------------------

    def _arm_deadline(self, room: Room) -> None:
        if room.game.phase is Phase.FINISHED:
            room.deadline = None
            room.finished_at = room.finished_at or time.time()
            return
        room._turn_token += 1
        token = room._turn_token
        room.deadline = time.time() + TURN_SECONDS
        asyncio.create_task(self._deadline_watch(room, token))

    async def _deadline_watch(self, room: Room, token: int) -> None:
        """到点后托管当前玩家。token 用于丢弃过期的定时器。"""
        try:
            await asyncio.sleep(TURN_SECONDS)
        except asyncio.CancelledError:
            return
        if room._turn_token != token or room.game.phase is Phase.FINISHED:
            return
        if self.rooms.get(room.id) is not room:
            return

        async with room.lock:
            if room._turn_token != token or room.game.phase is Phase.FINISHED:
                return
            game = room.game
            player = game.current_player
            try:
                if game.phase is Phase.FOLLOWING and "pass" in game.legal_actions(player.id):
                    game.passing(player.id)
                    note = f"{player.name} 超时，自动过牌"
                else:
                    # 领出方超时：出最小的一张，并如实声明其点数（最保守的托管）
                    card = min(game.player(player.id).hand, key=game._sort_key)
                    rank = card.rank if not card.is_joker else game.public_state()["ranks"][0]
                    game.lead(player.id, [card.id], rank)
                    note = f"{player.name} 超时，自动出了 1 张"
            except RuleError as exc:
                log.warning("房间 %s 托管失败：%s", room.id, exc)
                return
            log.info("房间 %s %s", room.id, note)
            self._arm_deadline(room)
        await self.broadcast(room)

    # --- 动作入口 -----------------------------------------------------------

    async def apply_action(self, room: Room, user_id: str, action: str, payload: dict) -> Optional[str]:
        """执行一个玩家动作。返回 None 表示成功，否则返回给该玩家看的错误文案。"""
        async with room.lock:
            game = room.game
            try:
                if action == "lead":
                    game.lead(user_id, list(payload.get("cards") or []), str(payload.get("rank") or ""))
                elif action == "follow":
                    game.follow(user_id, list(payload.get("cards") or []))
                elif action == "challenge":
                    game.challenge(user_id)
                elif action == "pass":
                    game.passing(user_id)
                else:
                    return "未知操作"
            except RuleError as exc:
                return str(exc)
            self._arm_deadline(room)
        await self.broadcast(room)
        return None
