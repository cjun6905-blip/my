# -*- coding: utf-8 -*-

import discord
from discord.ui import Modal, TextInput
import logging
from typing import Optional

from src.guidance.utils.database import guidance_db_manager

log = logging.getLogger(__name__)

class TagModal(Modal):
    """用于新增或编辑标签的模态窗口。"""

    def __init__(self, guild_id: int, existing_tag: Optional[dict] = None):
        self.guild_id = guild_id
        self.existing_tag = existing_tag
        self.callback_view = None # 用于接收父视图以进行回调刷新
        title = "编辑标签" if existing_tag else "新增标签"
        super().__init__(title=title)

        self.tag_name_input = TextInput(
            label="标签名称",
            placeholder="例如：游戏爱好者、技术宅、萌新",
            required=True,
            max_length=50,
            default=existing_tag['tag_name'] if existing_tag else None
        )
        self.add_item(self.tag_name_input)

        self.description_input = TextInput(
            label="标签描述 (可选)",
            style=discord.TextStyle.long,
            placeholder="这个标签是给哪一类用户准备的？",
            required=False,
            max_length=500,
            default=existing_tag['description'] if existing_tag else None
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # 先延迟响应
        tag_name = self.tag_name_input.value
        description = self.description_input.value

        try:
            if self.existing_tag:
                # 编辑逻辑
                await guidance_db_manager.update_tag(self.existing_tag['tag_id'], tag_name, description)
                await interaction.followup.send(f"✅ 成功更新标签：**{tag_name}**", ephemeral=True)
            else:
                # 新增逻辑
                await guidance_db_manager.add_tag(self.guild_id, tag_name, description)
                await interaction.followup.send(f"✅ 成功新增标签：**{tag_name}**", ephemeral=True)
            
            # 如果设置了回调视图，则调用其 refresh 方法
            if self.callback_view:
                # 调用父视图的 refresh 方法，不需要传递 interaction
                await self.callback_view.refresh()

        except Exception as e:
            log.error(f"处理标签模态窗口时出错: {e}", exc_info=True)
            await interaction.followup.send(f"❌ 操作失败，可能是因为标签名称 “{tag_name}” 已存在。", ephemeral=True)