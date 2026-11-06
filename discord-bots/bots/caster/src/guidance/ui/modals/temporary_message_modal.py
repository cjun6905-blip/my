# -*- coding: utf-8 -*-

import discord
from discord.ui import Modal, TextInput
from typing import Optional, Dict, Any

import uuid

class TemporaryMessageModal(Modal):
    """
    用于添加或编辑单条临时消息的模态框。
    """
    def __init__(self, parent_view: discord.ui.View, existing_data: Optional[Dict[str, Any]] = None):
        super().__init__(title="编辑临时消息")
        self.parent_view = parent_view
        self.existing_data = existing_data

        self.title_input = TextInput(
            label="临时消息标题",
            placeholder="例如：第一步：了解我们的社区",
            default=existing_data.get('title') if existing_data else "",
            max_length=256,
            required=True
        )
        self.add_item(self.title_input)

        self.content_input = TextInput(
            label="临时消息内容",
            placeholder="详细介绍内容。在最后一条消息中，你可以使用 {next_step_url} 来指引用户。",
            default=existing_data.get('description') if existing_data else (existing_data.get('content') if existing_data else ""),
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer() # 立即响应，避免超时
        
        submitted_data = {
            "title": self.title_input.value,
            "description": self.content_input.value
        }

        if self.existing_data:
            # 编辑现有消息
            self.existing_data.update(submitted_data)
        else:
            # 添加新消息
            new_msg = dict(submitted_data, internal_id=str(uuid.uuid4()))
            self.parent_view.messages.append(new_msg)
            self.parent_view.selected_message_id = new_msg['internal_id']

        # 无论添加还是编辑，都保存并刷新父视图
        await self.parent_view.update_view(save=True)
        self.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        # 交互已经被 defer，所以总是使用 followup
        await interaction.followup.send(f"❌ 处理临时消息时出错: {error}", ephemeral=True)