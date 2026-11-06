#!/usr/bin/env python3
"""将 OpenAI 兼容 Provider 与模型从环境变量同步到 PostgreSQL。"""

import asyncio
import os

from src.database.database import AsyncSessionLocal
from src.database.services.ai_config_service import ai_config_service


PROVIDER_NAME = "openai_compatible"
MODELS = (
    {
        "model_name": "gemini-3.7-flash-high",
        "display_name": "Gemini 3.7 Flash High",
        "description": "雨之魔女梣的默认文本与工具调用模型",
    },
    {
        "model_name": "gemini-3.8-flash-high",
        "display_name": "Gemini 3.8 Flash High",
        "description": "雨之魔女梣的可选高性能文本与工具调用模型",
    },
)


async def main():
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_COMPATIBLE_URL", "").strip().rstrip("/")
    if not api_key or not base_url:
        raise SystemExit("OPENAI_COMPATIBLE_API_KEY/URL is not configured")

    async with AsyncSessionLocal() as session:
        provider = await ai_config_service.get_provider_by_name(session, PROVIDER_NAME)
        if provider is None:
            provider = await ai_config_service.create_provider(
                session,
                name=PROVIDER_NAME,
                provider_type="openai_compatible",
                display_name="Aireck Gemini",
                api_key=api_key,
                base_url=base_url,
                extra={"source": "managed-deployment"},
            )
            provider_action = "created"
        else:
            provider = await ai_config_service.update_provider(
                session,
                provider.id,
                provider_type="openai_compatible",
                display_name="Aireck Gemini",
                api_key=api_key,
                base_url=base_url,
                extra={"source": "managed-deployment"},
                enabled=1,
            )
            provider_action = "updated"

        # Service methods commit after each create/update.  SQLAlchemy expires
        # ORM instances on commit, so keep the scalar id before the model loop.
        provider_id = provider.id
        model_actions = []
        for index, model_spec in enumerate(MODELS):
            model = await ai_config_service.get_model_by_name(
                session, model_spec["model_name"]
            )
            generation_config = {
                "temperature": 0.8,
                "top_p": 0.95,
                "max_output_tokens": 8192,
            }
            if model is None:
                await ai_config_service.create_model(
                    session,
                    model_name=model_spec["model_name"],
                    display_name=model_spec["display_name"],
                    provider_id=provider_id,
                    actual_model=model_spec["model_name"],
                    description=model_spec["description"],
                    supports_vision=True,
                    supports_tools=True,
                    supports_thinking=False,
                    max_output_tokens=8192,
                    generation_config=generation_config,
                    prompt_config={"use_cache_optimized_build": False},
                )
                model_actions.append("created:{}".format(model_spec["model_name"]))
            else:
                await ai_config_service.update_model(
                    session,
                    model.id,
                    display_name=model_spec["display_name"],
                    provider_id=provider_id,
                    actual_model=model_spec["model_name"],
                    description=model_spec["description"],
                    supports_vision=True,
                    supports_tools=True,
                    supports_thinking=False,
                    max_output_tokens=8192,
                    generation_config=generation_config,
                    prompt_config={"use_cache_optimized_build": False},
                    enabled=1,
                )
                model_actions.append("updated:{}".format(model_spec["model_name"]))

        print("provider_action={}".format(provider_action))
        print("provider_name={}".format(PROVIDER_NAME))
        print("provider_has_key=true")
        print("model_actions={}".format(",".join(model_actions)))
        print("default_model={}".format(MODELS[0]["model_name"]))


if __name__ == "__main__":
    asyncio.run(main())
