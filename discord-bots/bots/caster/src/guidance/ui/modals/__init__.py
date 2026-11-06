# -*- coding: utf-8 -*-

"""
This file makes the 'modals' directory a Python package and exposes key Modal classes
for easier importing elsewhere in the application.
"""

from src.guidance.ui.modals.tag_modal import TagModal
from src.guidance.ui.modals.path_modal import PathModal
from src.guidance.ui.modals.template_modal import TemplateModal

__all__ = [
    "TagModal",
    "PathModal",
    "TemplateModal"
]