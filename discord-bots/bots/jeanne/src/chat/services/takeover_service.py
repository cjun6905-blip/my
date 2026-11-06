"""Persistent, expiring manual-control sessions. No message bodies are stored."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
from src.config import DATA_DIR


class TakeoverError(ValueError):
    pass


@dataclass(frozen=True)
class Session:
    scope: str
    guild_id: int
    operator_id: int
    started_at: float
    expires_at: float


class TakeoverService:
    def __init__(self, path=None, clock=time.time):
        self.path = Path(path or Path(DATA_DIR) / "takeover.db")
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self._ready = False
        self._init_lock = asyncio.Lock()
        self._lock = asyncio.Lock()

    async def initialize(self):
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.path) as db:
                await db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                    scope TEXT PRIMARY KEY, guild_id INTEGER NOT NULL,
                    operator_id INTEGER NOT NULL, started_at REAL NOT NULL,
                    expires_at REAL NOT NULL)""")
                await db.execute("""CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL,
                    guild_id INTEGER NOT NULL, operator_id INTEGER NOT NULL,
                    scope TEXT NOT NULL, message_id INTEGER)""")
                rows = await (await db.execute(
                    "SELECT scope,guild_id,operator_id,started_at,expires_at FROM sessions WHERE expires_at>?",
                    (self.clock(),),
                )).fetchall()
                await db.commit()
            self.path.chmod(0o600)
            self.sessions = {row[0]: Session(*row) for row in rows}
            self._ready = True

    async def get(self, scope):
        await self.initialize()
        session = self.sessions.get(scope)
        return session if session and session.expires_at > self.clock() else None

    async def channel_active(self, channel):
        if await self.get(f"channel:{channel.id}"):
            return True
        parent = getattr(channel, "parent_id", None)
        if isinstance(parent, int) and await self.get(f"channel:{parent}"):
            return True
        recipient = getattr(channel, "recipient", None)
        recipient_id = getattr(recipient, "id", None)
        return isinstance(recipient_id, int) and bool(await self.get(f"dm:{recipient_id}"))

    async def message_active(self, message):
        if message.guild is None:
            return bool(await self.get(f"dm:{message.author.id}"))
        return await self.channel_active(message.channel)

    async def require_owner(self, scope, guild_id, operator_id, required=False):
        session = await self.get(scope)
        if session and (session.guild_id != guild_id or session.operator_id != operator_id):
            raise TakeoverError("该会话正由另一位管理员接管。")
        if required and session is None:
            raise TakeoverError("请先开始接管这个会话。")
        return session

    async def start(self, scope, guild_id, operator_id, minutes):
        await self.initialize()
        if not 5 <= minutes <= 240:
            raise TakeoverError("接管时间应为 5–240 分钟。")
        async with self._lock:
            await self.require_owner(scope, guild_id, operator_id)
            now = self.clock()
            session = Session(scope, guild_id, operator_id, now, now + minutes * 60)
            async with aiosqlite.connect(self.path) as db:
                await db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)",
                                 (scope, guild_id, operator_id, now, session.expires_at))
                await db.execute("INSERT INTO audit(at,action,guild_id,operator_id,scope) VALUES (?,?,?,?,?)",
                                 (now, "start", guild_id, operator_id, scope))
                await db.commit()
            self.sessions[scope] = session
            return session

    async def stop(self, scope, guild_id, operator_id):
        await self.initialize()
        async with self._lock:
            session = await self.get(scope)
            if session and session.guild_id != guild_id:
                raise TakeoverError("不能结束其他服务器创建的接管。")
            if session is None:
                return False
            async with aiosqlite.connect(self.path) as db:
                await db.execute("DELETE FROM sessions WHERE scope=?", (scope,))
                await db.execute("INSERT INTO audit(at,action,guild_id,operator_id,scope) VALUES (?,?,?,?,?)",
                                 (self.clock(), "stop", guild_id, operator_id, scope))
                await db.commit()
            self.sessions.pop(scope, None)
            return True

    async def audit(self, action, guild_id, operator_id, scope, message_id=None):
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO audit(at,action,guild_id,operator_id,scope,message_id) VALUES (?,?,?,?,?,?)",
                             (self.clock(), action, guild_id, operator_id, scope, message_id))
            await db.commit()


takeover_service = TakeoverService(os.getenv("TAKEOVER_DB_PATH"))
