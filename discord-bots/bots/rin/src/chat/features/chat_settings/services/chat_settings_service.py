from src.config import runtime
from src.chat.services.store import store


class ChatSettings:
    async def get_current_ai_model(self):
        return runtime().get("MODEL_NAME", "")

    async def is_chat_globally_enabled(self, guild_id):
        return await store.get(f"chat:{guild_id}", True)


chat_settings_service = ChatSettings()
