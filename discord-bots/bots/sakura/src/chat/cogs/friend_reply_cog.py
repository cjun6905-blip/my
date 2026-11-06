from discord.ext import commands
from src.chat.services.friend_reply import friend_reply


class FriendReplyCog(commands.Cog):
    def __init__(self, bot): self.bot = bot
    async def cog_load(self): await friend_reply.initialize()
    async def cog_unload(self): await friend_reply.close()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        friend_reply.invalidate(payload.channel_id, {payload.message_id})

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        friend_reply.invalidate(payload.channel_id, payload.message_ids)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if 'content' in payload.data:
            friend_reply.invalidate(payload.channel_id, {payload.message_id})
