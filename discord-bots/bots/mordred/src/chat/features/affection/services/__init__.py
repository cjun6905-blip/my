# -*- coding: utf-8 -*-
"""
Affection 模块的服务层
"""

from src.chat.features.affection.services.user_command_settings_service import (
    user_command_settings_service,
    UserCommandSettingsService,
    CONFIGURABLE_COMMANDS,
)

__all__ = [
    "user_command_settings_service",
    "UserCommandSettingsService",
    "CONFIGURABLE_COMMANDS",
]
