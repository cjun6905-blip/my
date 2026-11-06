from src.chat.services.persona_media.cog import PersonaMediaCog
async def setup(bot):
 await bot.add_cog(PersonaMediaCog(bot))
