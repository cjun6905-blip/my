"""Small cross-container concurrency and background budgets, containing no chat data."""
import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import aiosqlite


class BudgetError(RuntimeError):
    pass


class FleetBudget:
    def __init__(self, path=None, clock=time.time):
        self.path = path if path is not None else os.getenv('FLEET_BUDGET_DB', '')
        self.clock = clock

    @asynccontextmanager
    async def database(self):
        path = Path(self.path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(path, timeout=1) as db:
                await db.execute('PRAGMA busy_timeout=1000')
                await db.execute('CREATE TABLE IF NOT EXISTS leases (token TEXT PRIMARY KEY, resource TEXT NOT NULL, expires REAL NOT NULL)')
                await db.execute('CREATE INDEX IF NOT EXISTS leases_resource ON leases(resource)')
                await db.execute('CREATE TABLE IF NOT EXISTS background (channel INTEGER PRIMARY KEY, window INTEGER NOT NULL, attempts INTEGER NOT NULL, last REAL NOT NULL)')
                await db.execute('CREATE TABLE IF NOT EXISTS background_pacing (channel INTEGER PRIMARY KEY, credits REAL NOT NULL, updated REAL NOT NULL)')
                await db.execute('CREATE TABLE IF NOT EXISTS background_sent (event TEXT PRIMARY KEY, channel INTEGER NOT NULL, at REAL NOT NULL)')
                await db.execute('CREATE INDEX IF NOT EXISTS background_sent_channel ON background_sent(channel, at)')
                await db.commit()
                path.chmod(0o600)
                yield db
        except (OSError, aiosqlite.Error):
            raise BudgetError('Fleet budget unavailable') from None

    async def acquire(self, resource, limit, ttl, priority=False):
        async with self.database() as db:
            await db.execute('BEGIN IMMEDIATE')
            now = self.clock()
            await db.execute('DELETE FROM leases WHERE expires<=?', (now,))
            count = (await (await db.execute('SELECT COUNT(*) FROM leases WHERE resource=?', (resource,))).fetchone())[0]
            preferred = not priority and await (await db.execute(
                'SELECT 1 FROM leases WHERE resource=? LIMIT 1', ('waiting:' + resource,))).fetchone()
            token = uuid.uuid4().hex if count < limit and not preferred else None
            if token:
                await db.execute('INSERT INTO leases VALUES (?,?,?)', (token, resource, now + ttl))
            await db.commit()
            return token

    async def release(self, token):
        async with self.database() as db:
            await db.execute('DELETE FROM leases WHERE token=?', (token,))
            await db.commit()

    @asynccontextmanager
    async def slot(self, resource, limit, wait=5, ttl=240, priority=False, queue_limit=8):
        if not self.path:
            yield True
            return
        deadline = time.monotonic() + wait
        token = waiting = None
        try:
            if priority:
                waiting = await self.acquire('waiting:' + resource, queue_limit, wait + 30, priority=True)
                if not waiting:
                    yield False
                    return
            while True:
                token = await self.acquire(resource, limit, ttl, priority=priority)
                if token or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
            if waiting:
                await asyncio.shield(self.release(waiting))
                waiting = None
            yield token is not None
        finally:
            if waiting:
                await asyncio.shield(self.release(waiting))
            if token:
                await asyncio.shield(self.release(token))

    async def allow_background(self, channel_id, message_id):
        if not self.path:
            return True
        # Store only channel/event IDs and counts, never message content.
        async with self.database() as db:
            await db.execute('BEGIN IMMEDIATE')
            now = self.clock()
            await db.execute('DELETE FROM leases WHERE expires<=?', (now,))
            event = 'background-event:' + str(message_id)
            seen = await (await db.execute('SELECT 1 FROM leases WHERE resource=?', (event,))).fetchone()
            row = await (await db.execute('SELECT window,attempts,last FROM background WHERE channel=?', (channel_id,))).fetchone()
            window = int(now // 3600)
            attempts = row[1] if row and row[0] == window else 0
            # Each admitted decision consumes the shared hourly quota, including
            # silent/model-busy results. Delivery records are statistics only.
            # Two initial credits, then one every two minutes, spread decisions
            # throughout the hour instead of spending everything in a few minutes.
            pacing = await (await db.execute('SELECT credits,updated FROM background_pacing WHERE channel=?', (channel_id,))).fetchone()
            credits = min(2.0, pacing[0] + max(0, now - pacing[1]) / 120) if pacing else 2.0
            allowed = not seen and attempts < 16 and credits >= 1 and (not row or now - row[2] >= 45)
            if allowed:
                await db.execute('INSERT OR REPLACE INTO background VALUES (?,?,?,?)', (channel_id, window, attempts + 1, now))
                await db.execute('INSERT OR REPLACE INTO background_pacing VALUES (?,?,?)', (channel_id, credits - 1, now))
                await db.execute('INSERT INTO leases VALUES (?,?,?)', (uuid.uuid4().hex, event, now + 7 * 86400))
            await db.execute('DELETE FROM background WHERE last<?', (now - 7 * 86400,))
            await db.execute('DELETE FROM background_sent WHERE at<=?', (now - 3600,))
            await db.execute('DELETE FROM background_pacing WHERE updated<?', (now - 7 * 86400,))
            await db.commit()
            return bool(allowed)

    async def background_delivered(self, channel_id, message_id):
        """Record only successful automatic text delivery; no message bodies."""
        if not self.path:
            return
        async with self.database() as db:
            now = self.clock()
            await db.execute('INSERT OR IGNORE INTO background_sent VALUES (?,?,?)',
                (str(message_id), channel_id, now))
            await db.execute('DELETE FROM background_sent WHERE at<=?', (now - 3600,))
            await db.commit()


fleet_budget = FleetBudget()
