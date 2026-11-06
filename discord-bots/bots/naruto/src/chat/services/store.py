"""Small SQLite state. Channel history stays in bounded RAM, not permanent logs."""
import asyncio
import json
import time
from pathlib import Path
import aiosqlite
from src.config import DATA_DIR


class Store:
    def __init__(self, path=None):
        self.path = Path(path or Path(DATA_DIR) / "whale.db")
        self.db = None
        self.lock = asyncio.Lock()
        self.init_lock = asyncio.Lock()

    async def initialize(self):
        if self.db:
            return
        async with self.init_lock:
            if self.db:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = await aiosqlite.connect(self.path)
            await self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=5000;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory(guild_id INTEGER,user_id INTEGER,facts TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,updated REAL NOT NULL,
            PRIMARY KEY(guild_id,user_id));
        CREATE TABLE IF NOT EXISTS events(key TEXT PRIMARY KEY,at REAL NOT NULL);
        """)
            await self.db.commit()
            self.path.chmod(0o600)

    async def get(self, key, default=None):
        await self.initialize()
        row = await (await self.db.execute("SELECT value FROM settings WHERE key=?", (key,))).fetchone()
        return json.loads(row[0]) if row else default

    async def set(self, key, value):
        await self.initialize()
        async with self.lock:
            await self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
            await self.db.commit()

    async def memory(self, guild_id, user_id):
        await self.initialize()
        row = await (await self.db.execute("SELECT facts,enabled,updated FROM memory WHERE guild_id=? AND user_id=?", (guild_id, user_id))).fetchone()
        if not row:
            return [], True
        facts = json.loads(row[0]) if row[2] > time.time() - 30 * 86400 else []
        return facts, bool(row[1])

    async def remember(self, guild_id, user_id, fact):
        fact = str(fact).strip()[:160]
        if not fact:
            return
        async with self.lock:
            facts, enabled = await self.memory(guild_id, user_id)
            if not enabled:
                return
            facts = [f for f in facts if f != fact][-7:] + [fact]
            await self.db.execute("INSERT OR REPLACE INTO memory VALUES (?,?,?,?,?)", (guild_id, user_id, json.dumps(facts, ensure_ascii=False), 1, time.time()))
            await self.db.commit()

    async def forget(self, guild_id, user_id, enabled=False):
        await self.initialize()
        async with self.lock:
            await self.db.execute("INSERT OR REPLACE INTO memory VALUES (?,?,?,?,?)", (guild_id, user_id, "[]", int(enabled), time.time()))
            await self.db.commit()

    async def claim(self, key):
        await self.initialize()
        async with self.lock:
            cursor = await self.db.execute("INSERT OR IGNORE INTO events VALUES (?,?)", (key, time.time()))
            claimed = cursor.rowcount == 1
            await self.db.execute("DELETE FROM events WHERE at<?", (time.time() - 7 * 86400,))
            await self.db.commit()
            return claimed

    async def close(self):
        if self.db:
            await self.db.close()
            self.db = None


store = Store()
