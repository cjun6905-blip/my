"""Persistent, time-limited server nickname punishments."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class NicknamePunishment:
    guild_id: int
    user_id: int
    nickname: str
    original_nick: str | None
    expires_at: float
    operator_id: int


class NicknamePunishmentService:
    def __init__(self, path="data/nickname_punishments.db", clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._init_lock = asyncio.Lock()
        self._ready = False

    async def initialize(self):
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.path) as db:
                await db.execute("""CREATE TABLE IF NOT EXISTS nickname_punishments (
                    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    nickname TEXT NOT NULL, original_nick TEXT,
                    expires_at REAL NOT NULL, operator_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id))""")
                await db.execute("CREATE INDEX IF NOT EXISTS nickname_punishments_expiry "
                                 "ON nickname_punishments(expires_at)")
                await db.commit()
            self.path.chmod(0o600)
            self._ready = True

    async def get(self, guild_id: int, user_id: int) -> NicknamePunishment | None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT guild_id,user_id,nickname,original_nick,expires_at,operator_id "
                "FROM nickname_punishments WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )).fetchone()
        return NicknamePunishment(*row) if row else None

    async def all(self, guild_id: int | None = None) -> list[NicknamePunishment]:
        await self.initialize()
        query = ("SELECT guild_id,user_id,nickname,original_nick,expires_at,operator_id "
                 "FROM nickname_punishments")
        params = () if guild_id is None else (guild_id,)
        if guild_id is not None:
            query += " WHERE guild_id=?"
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(query, params)).fetchall()
        return [NicknamePunishment(*row) for row in rows]

    async def due(self) -> list[NicknamePunishment]:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                "SELECT guild_id,user_id,nickname,original_nick,expires_at,operator_id "
                "FROM nickname_punishments WHERE expires_at<=?", (self.clock(),)
            )).fetchall()
        return [NicknamePunishment(*row) for row in rows]

    async def save(self, punishment: NicknamePunishment):
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR REPLACE INTO nickname_punishments VALUES (?,?,?,?,?,?)",
                             (punishment.guild_id, punishment.user_id, punishment.nickname,
                              punishment.original_nick, punishment.expires_at, punishment.operator_id))
            await db.commit()

    async def remove(self, guild_id: int, user_id: int):
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM nickname_punishments WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))
            await db.commit()


nickname_punishment_service = NicknamePunishmentService(
    os.getenv("NICKNAME_PUNISHMENT_DB_PATH", "data/nickname_punishments.db")
)
