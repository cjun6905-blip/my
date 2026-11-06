# -*- coding: utf-8 -*-
"""
AI 服务模块 - 多端点支持的统一 AI 服务

此模块提供统一的 AI 服务接口，支持多种后端：
- Gemini 官方 API
- Gemini 自定义端点
- DeepSeek API
- OpenAI 兼容端点
"""

from .service import AIService, ai_service
from .providers.base import (
    BaseProvider,
    GenerationConfig,
    GenerationResult,
    FinishReason,
    ToolCall,
    ProviderInfo,
    AIServiceError,
    ProviderNotAvailableError,
    ModelNotSupportedError,
    GenerationError,
)
from .providers import (
    GeminiProvider,
    GeminiCustomProvider,
    DeepSeekProvider,
    OpenAICompatibleProvider,
)
from .config.providers import ProviderConfig, get_provider_configs
from .config.models import ModelConfig, get_model_configs, FALLBACK_PRIORITY

__all__ = [
    # 核心服务
    "AIService",
    "ai_service",
    # 基类和数据类
    "BaseProvider",
    "GenerationConfig",
    "GenerationResult",
    "FinishReason",
    "ToolCall",
    "ProviderInfo",
    # 错误类
    "AIServiceError",
    "ProviderNotAvailableError",
    "ModelNotSupportedError",
    "GenerationError",
    # Provider 实现
    "GeminiProvider",
    "GeminiCustomProvider",
    "DeepSeekProvider",
    "OpenAICompatibleProvider",
    # 配置
    "ProviderConfig",
    "get_provider_configs",
    "ModelConfig",
    "get_model_configs",
    "FALLBACK_PRIORITY",
]
