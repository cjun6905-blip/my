# -*- coding: utf-8 -*-

import discord
from discord.ui import Modal, TextInput
from typing import Dict, Optional, Any

class TemplateMessageItemModal(Modal):
    """
    用于在 TemplateMessagesEditView 中添加或编辑单条消息的模态框。
    """
    def __init__(self, parent_view: discord.ui.View, existing_data: Optional[Dict[str, Any]] = None):
        self.parent_view = parent_view
        self.existing_data = existing_data
        
        title = "编辑消息" if existing_data else "添加新消息"
        super().__init__(title=title, timeout=300)

        self.add_item(TextInput(
            label="Embed 标题",
            placeholder="卡片标题，支持 {user_name}, {server_name} 等变量。",
            default=self.existing_data.get("title") if self.existing_data else None,
            max_length=256,
            required=True
        ))
        self.add_item(TextInput(
            label="Embed 描述",
            placeholder="卡片的主要内容。支持 Markdown 和所有变量。",
            default=self.existing_data.get("description") if self.existing_data else None,
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
        ))
        self.add_item(TextInput(
            label="Embed 底部文字",
            placeholder="显示在卡片底部的小字。",
            default=self.existing_data.get("footer_text") if self.existing_data else None,
            max_length=2048,
            required=False
        ))
        self.add_item(TextInput(
            label="Embed 大图 URL",
            placeholder="可选，在卡片底部显示一张大图的图片URL。",
            default=self.existing_data.get("image_url") if self.existing_data else None,
            required=False
        ))
        self.add_item(TextInput(
            label="Embed 缩略图 URL",
            placeholder="可选，在卡片右上角显示的小图URL。",
            default=self.existing_data.get("thumbnail_url") if self.existing_data else None,
            required=False
        ))

    async def on_submit(self, interaction: discord.Interaction):
        new_data = {
            "title": self.children[0].value,
            "description": self.children[1].value,
            "footer_text": self.children[2].value,
            "image_url": self.children[3].value,
            "thumbnail_url": self.children[4].value,
        }

        if self.existing_data:
            # 编辑现有消息
            for msg in self.parent_view.messages:
                if msg['internal_id'] == self.existing_data['internal_id']:
                    msg.update(new_data)
                    break
        else:
            # 添加新消息
            import uuid
            new_data['internal_id'] = str(uuid.uuid4())
            self.parent_view.messages.append(new_data)

        # 更新父视图
        await self.parent_view.update_view(interaction, save=True)