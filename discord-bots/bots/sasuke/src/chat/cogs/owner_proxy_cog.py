import discord
from discord.ext import commands
from src.chat.services.owner_proxy import owner_proxy, OWNER


class OwnerProxyCog(commands.Cog):
    def __init__(self,bot):self.bot=bot

    async def cog_load(self):await owner_proxy.start(self.bot)

    async def cog_unload(self):await owner_proxy.close()

    @commands.Cog.listener()
    async def on_raw_message_delete(self,payload):
        await owner_proxy.deleted([payload.message_id]);owner_proxy.cancel(payload.channel_id)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self,payload):
        await owner_proxy.deleted(payload.message_ids);owner_proxy.cancel(payload.channel_id)

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        # Partial updates may omit the author; only fetch an existing own sample.
        author=payload.data.get('author',{}).get('id')
        if author and str(author)!=str(OWNER):return
        if not author:
            import aiosqlite
            async with aiosqlite.connect(owner_proxy.path) as db:
                known=await (await db.execute('SELECT 1 FROM samples WHERE id=?',(str(payload.message_id),))).fetchone()
            if not known:return
        channel=self.bot.get_channel(payload.channel_id)
        if not channel:return
        try:message=await channel.fetch_message(payload.message_id)
        except discord.HTTPException:return
        if message.author.id==OWNER:
            await owner_proxy.deleted([message.id]);await owner_proxy.collect(message)
