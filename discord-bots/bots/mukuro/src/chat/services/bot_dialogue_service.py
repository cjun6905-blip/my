# -*- coding: utf-8 -*-
"""Persistent bounds and replay protection for explicitly invited bot conversations."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

import aiosqlite
from src.config import DATA_DIR


@dataclass(frozen=True)
class BotDialogue:
    channel_id: int
    guild_id: int
    target_id: int
    operator_id: int
    topic: str
    limit: int
    sent: int
    last_our_id: int
    last_target_id: int
    expires_at: float
    session_id: str = ""

    def active(self, now: float) -> bool:
        return self.expires_at > now and self.sent < self.limit


class BotDialogueService:
    def __init__(self, path=None, clock=time.time):
        self.path = Path(path or os.getenv("BOT_DIALOGUE_DB_PATH") or Path(DATA_DIR) / "bot_dialogues.db")
        self.clock = clock
        self._lock = asyncio.Lock()
        self._ready = False

    async def initialize(self):
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.path) as db:
                await db.execute("""CREATE TABLE IF NOT EXISTS bot_dialogues (
                    channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL, operator_id INTEGER NOT NULL,
                    topic TEXT NOT NULL, turn_limit INTEGER NOT NULL,
                    sent INTEGER NOT NULL, last_our_id INTEGER NOT NULL,
                    last_target_id INTEGER NOT NULL DEFAULT 0,
                    expires_at REAL NOT NULL, session_id TEXT NOT NULL DEFAULT '')""")
                columns = await (await db.execute("PRAGMA table_info(bot_dialogues)")).fetchall()
                if "session_id" not in {row[1] for row in columns}:
                    await db.execute("ALTER TABLE bot_dialogues ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
                await db.execute("""CREATE TABLE IF NOT EXISTS bot_dialogue_invites (
                    session_id TEXT PRIMARY KEY, received_at REAL NOT NULL)""")
                await db.commit()
            self.path.chmod(0o600)
            self._ready = True

    async def get(self, channel_id: int) -> BotDialogue | None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT channel_id,guild_id,target_id,operator_id,topic,turn_limit,sent,"
                "last_our_id,last_target_id,expires_at,session_id FROM bot_dialogues WHERE channel_id=?",
                (channel_id,),
            )).fetchone()
        return BotDialogue(*row) if row else None

    async def start(self, session: BotDialogue) -> bool:
        """Claim an invitation once, including across restarts and completed sessions."""
        await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                if session.session_id:
                    cursor = await db.execute(
                        "INSERT OR IGNORE INTO bot_dialogue_invites VALUES (?,?)",
                        (session.session_id, self.clock()),
                    )
                    if cursor.rowcount != 1:
                        await db.rollback()
                        return False
                await db.execute("""INSERT OR REPLACE INTO bot_dialogues
                    (channel_id,guild_id,target_id,operator_id,topic,turn_limit,sent,
                    last_our_id,last_target_id,expires_at,session_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (session.channel_id, session.guild_id, session.target_id,
                     session.operator_id, session.topic, session.limit, session.sent,
                     session.last_our_id, session.last_target_id, session.expires_at, session.session_id))
                # Expired invitation tokens cannot pass the timestamp check in the cog.
                await db.execute("DELETE FROM bot_dialogue_invites WHERE received_at<?",
                                 (self.clock() - 86400,))
                await db.commit()
                return True

    async def reserve(self, session: BotDialogue, target_id: int) -> BotDialogue | None:
        """Consume the turn before generation/send, so crashes cannot exceed the cap."""
        await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("""UPDATE bot_dialogues SET sent=sent+1,last_target_id=?
                    WHERE channel_id=? AND session_id=? AND sent=? AND sent<turn_limit
                    AND last_our_id=? AND last_target_id=? AND expires_at>?
                    AND last_target_id<?""",
                    (target_id, session.channel_id, session.session_id, session.sent,
                     session.last_our_id, session.last_target_id, self.clock(), target_id))
                await db.commit()
                return replace(session, sent=session.sent + 1, last_target_id=target_id) if cursor.rowcount == 1 else None

    async def complete(self, reserved: BotDialogue, our_id: int) -> bool:
        await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("""UPDATE bot_dialogues SET last_our_id=? WHERE
                    channel_id=? AND session_id=? AND sent=? AND last_target_id=? AND expires_at>?""",
                    (our_id, reserved.channel_id, reserved.session_id, reserved.sent,
                     reserved.last_target_id, self.clock()))
                await db.commit()
                return cursor.rowcount == 1

    async def stop(self, channel_id: int):
        await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("UPDATE bot_dialogues SET expires_at=? WHERE channel_id=?",
                                 (self.clock(), channel_id))
                await db.commit()

    async def stop_session(self, channel_id: int, session_id: str):
        """An old failed request must never stop a replacement conversation."""
        await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute(
                    "UPDATE bot_dialogues SET expires_at=? WHERE channel_id=? AND session_id=? AND expires_at>?",
                    (self.clock(), channel_id, session_id, self.clock()))
                await db.commit()
                return cursor.rowcount == 1


bot_dialogue_service = BotDialogueService()
