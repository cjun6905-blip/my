"""Single-process lightweight Discord service. No HTTP admin server is exposed."""
import asyncio
import json
import logging
import os
import time
from pathlib import Path
import discord
from discord.ext import commands
from src import config
from src.chat.services.store import store
from src.chat.services.ai.service import ai_service
from src.chat.cogs.social_cog import SocialCog
from src.chat.cogs.settings_cog import SettingsCog
from src.chat.cogs.takeover_cog import TakeoverCog
from src.chat.cogs.bot_dialogue_cog import BotDialogueCog

log = logging.getLogger(__name__)


class WhaleBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = intents.members = intents.message_content = True
        intents.messages = intents.reactions = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
            member_cache_flags=discord.MemberCacheFlags.none(), chunk_guilds_at_startup=False,
            max_messages=64, allowed_mentions=discord.AllowedMentions.none())
        self.health_task = None
        self.personal_reactions = {}

    async def setup_hook(self):
        await store.initialize()
        try:
            emojis = await self.fetch_application_emojis()
            # Application emojis have no guild; Emoji.is_usable() is for guild emojis.
            self.personal_reactions = {str(e): config.PERSONAL_EMOJI_LABELS[e.name]
                for e in emojis if e.available and e.name in config.PERSONAL_EMOJI_LABELS}
            log.info("personal_emojis_loaded count=%s", len(self.personal_reactions))
        except discord.HTTPException:
            log.warning("personal_emojis_unavailable")
        if config.PROFILE_KEY in ('sasuke', 'naruto'):
            from src.chat.cogs.owner_proxy_cog import OwnerProxyCog
            await self.add_cog(OwnerProxyCog(self))
        await self.add_cog(SocialCog(self))
        await self.add_cog(SettingsCog(self))
        await self.add_cog(TakeoverCog(self))
        await self.add_cog(BotDialogueCog(self))
        # Sync only the explicitly allowed guild; no duplicate global commands.
        for guild_id in config.GUILD_IDS:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
                log.info("commands_synced guild=%s count=%s", guild_id, len(synced))
            except (discord.Forbidden, discord.NotFound):
                log.warning("guild_invitation_pending guild=%s", guild_id)
        self.health_task = asyncio.create_task(self._health())

    async def _health(self):
        path = Path(config.DATA_DIR) / "health.json"
        while not self.is_closed():
            tmp = path.with_suffix(".new")
            tmp.write_text(json.dumps({"at": time.time(), "ready": self.is_ready(),
                "guilds": [g.id for g in self.guilds], "version": config.VERSION,
                "profile": config.PROFILE_KEY, "bot_id": self.user.id if self.user else None}))
            tmp.replace(path)
            await asyncio.sleep(10)

    async def on_ready(self):
        for guild in list(self.guilds):
            if guild.id not in config.GUILD_IDS:
                await guild.leave()
        log.info("whale_ready bot_id=%s guild_count=%s profile=%s", self.user.id, len(self.guilds), config.PROFILE_KEY)

    async def on_guild_join(self, guild):
        if guild.id not in config.GUILD_IDS:
            await guild.leave()
            return
        self.tree.copy_global_to(guild=discord.Object(id=guild.id))
        await self.tree.sync(guild=discord.Object(id=guild.id))
        log.info("whale_joined guild=%s", guild.id)

    async def on_message(self, message):
        # Cogs handle conversation events; this application uses slash commands.
        # The default prefix handler treats natural @ replies as unknown commands
        # and writes fragments of their contents into error logs.
        pass

    async def on_error(self, event, *args, **kwargs):
        # Third-party exceptions sometimes include a request URL or payload.
        log.error("discord_event_failed event=%s", event)

    async def close(self):
        if config.PROFILE_KEY in ('sasuke', 'naruto'):
            from src.chat.services.owner_proxy import owner_proxy
            await owner_proxy.close()
        if self.health_task:
            self.health_task.cancel()
            await asyncio.gather(self.health_task, return_exceptions=True)
        await ai_service.close()
        await store.close()
        await super().close()


async def main():
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    while True:
        runtime = config.runtime()
        missing = [k for k in ("DISCORD_TOKEN", "MODEL_API_KEY", "MODEL_BASE_URL", "MODEL_NAME") if not runtime.get(k)]
        if not missing:
            break
        log.warning("waiting_for_credentials missing_fields=%s", ",".join(missing))
        await asyncio.sleep(30)
    async with WhaleBot() as bot:
        await bot.start(runtime["DISCORD_TOKEN"], reconnect=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log.error("whale_start_failed type=%s", type(exc).__name__)
        raise SystemExit(1) from None
