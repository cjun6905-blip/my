# -*- coding: utf-8 -*-
"""
AI Provider 模块 - 支持多种 AI 服务后端
"""

from .base import (
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
from .gemini_provider import GeminiProvider, GeminiCustomProvider
from .deepseek_provider import DeepSeekProvider
from .openai_provider import OpenAICompatibleProvider
from .provider_format import ProviderFormat, MessageFormat

__all__ = [
    # 基类
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
    # 格式常量
    "ProviderFormat",
    "MessageFormat",
]
