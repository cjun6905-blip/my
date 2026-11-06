# -*- coding: utf-8 -*-

"""
This file makes the 'views' directory a Python package and exposes key View classes
for easier importing elsewhere in the application.
"""

from src.guidance.ui.views.main_panel import MainPanelView
from src.guidance.ui.views.tag_management import TagManagementView
from src.guidance.ui.views.path_configuration import PathConfigurationView
from src.guidance.ui.views.role_configuration import RoleConfigurationView
from src.guidance.ui.views.message_templates import MessageTemplatesView
from src.guidance.ui.views.deployment import DeploymentView
from src.guidance.ui.views.guidance_panel import GuidancePanelView
from src.guidance.ui.views.channel_message_config import ChannelMessageConfigView
from src.guidance.ui.views.channel_panel import PermanentPanelView
from src.guidance.ui.views.ui_elements import BackButton

__all__ = [
    "MainPanelView",
    "TagManagementView",
    "PathConfigurationView",
    "RoleConfigurationView",
    "MessageTemplatesView",
    "DeploymentView",
    "GuidancePanelView",
    "ChannelMessageConfigView",
    "PermanentPanelView",
    "BackButton"
]