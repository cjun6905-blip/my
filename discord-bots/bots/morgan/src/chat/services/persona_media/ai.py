from src.chat.services.ai.service import ai_service as original
from src.chat.services.ai.providers.base import GenerationError as ModelError
from src.chat.features.chat_settings.services.chat_settings_service import chat_settings_service
class Adapter:
 async def generate(self,messages,config,traffic='interactive'):
  model=await chat_settings_service.get_current_ai_model()
  return await original.generate(messages=messages,config=config,model=model,tools=None,fallback=False)
ai_service=Adapter()
