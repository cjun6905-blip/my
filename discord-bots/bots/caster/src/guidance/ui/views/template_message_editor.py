# -*- coding: utf-8 -*-

import discord
from discord.ui import View, Button, Select
from typing import List, Dict, Optional, Any
import uuid

from src.guidance.utils.database import guidance_db_manager as db_manager
from src.guidance.ui.modals.template_message_item_modal import TemplateMessageItemModal
from src.guidance import config as guidance_config
from src import config as root_config

class TemplateMessagesEditView(View):
    """
    一个用于编辑、添加、删除多条模板消息的视图。
    """
    def __init__(self, parent_interaction: discord.Interaction, main_view: View, template_name: str, existing_data: List[Dict[str, Any]]):
        super().__init__(timeout=300)
        self.parent_interaction = parent_interaction
        self.main_view = main_view # 保存对主菜单视图的引用
        self.template_name = template_name
        # 确保 existing_data 是一个列表
        if not isinstance(existing_data, list):
            existing_data = [existing_data] if existing_data else []

        # 为每个消息添加一个唯一的内部ID，以便于跟踪
        self.messages = [dict(item, internal_id=str(uuid.uuid4())) for item in existing_data]
        self.selected_message_id: Optional[str] = None

        self.create_components()

    def create_components(self):
        """动态创建或更新视图组件。"""
        self.clear_items()
        
        self.add_item(self.MessageSelect(self.messages, self.selected_message_id))
        
        self.add_item(self.AddButton())
        self.add_item(self.EditButton(disabled=self.selected_message_id is None))
        self.add_item(self.DeleteButton(disabled=self.selected_message_id is None))
        self.add_item(self.BackButton())

    async def update_view(self, interaction: discord.Interaction, save: bool = False):
        """
        根据当前状态刷新整个视图。
        :param interaction: 用于响应的交互。
        :param save: 如果为 True，则在刷新前将更改保存到数据库。
        """
        if save:
            await self._save_changes(interaction.guild_id)

        self.create_components()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def create_embed(self) -> discord.Embed:
        """创建或更新用于显示消息列表的 Embed。"""
        template_label = guidance_config.TEMPLATE_TYPES.get(self.template_name, {}).get("label", self.template_name)
        
        embed = discord.Embed(
            title=f"正在编辑: {template_label}",
            description="在这里管理该模板下的多条消息。用户将会看到一个带按钮的消息，可以顺序浏览它们。",
            color=root_config.EMBED_COLOR_INFO
        )

        if not self.messages:
            embed.add_field(name="当前没有消息", value="点击“添加新消息”来创建第一条。", inline=False)
        else:
            msg_list = ""
            for i, msg in enumerate(self.messages):
                is_selected = "🔹" if msg['internal_id'] == self.selected_message_id else "▪️"
                msg_list += f"{i+1}. {is_selected} **{msg.get('title', '无标题')}**\n"
            embed.add_field(name="消息顺序", value=msg_list, inline=False)
        
        embed.set_footer(text="使用下拉菜单选择一条消息以进行编辑或删除。")
        return embed

    async def _save_changes(self, guild_id: int):
        """将当前的消息列表保存到数据库。"""
        data_to_save = [{k: v for k, v in msg.items() if k != 'internal_id'} for msg in self.messages]
        
        # 如果只有一个消息，则存为字典，否则存为列表
        # 关键修复：始终将数据保存为列表，即使只有一个元素。
        # 这确保了从数据库读取数据时类型的一致性。
        final_data = data_to_save

        await db_manager.set_message_template(
            guild_id=guild_id,
            template_name=self.template_name,
            template_data=final_data
        )

    # --- 子组件定义 ---

    class MessageSelect(Select):
        def __init__(self, messages: List[Dict[str, Any]], selected_id: Optional[str]):
            options = []
            if not messages:
                options.append(discord.SelectOption(label="没有可选择的消息", value="placeholder", emoji="🤷"))
            else:
                for i, msg in enumerate(messages):
                    options.append(discord.SelectOption(
                        label=f"{i+1}. {msg.get('title', '无标题')}",
                        value=msg['internal_id'],
                        default=msg['internal_id'] == selected_id
                    ))
            
            super().__init__(
                placeholder="选择一条消息进行操作...",
                min_values=1,
                max_values=1,
                options=options,
                row=0,
                disabled=not messages
            )

        async def callback(self, interaction: discord.Interaction):
            self.view.selected_message_id = self.values[0]
            await self.view.update_view(interaction)

    class AddButton(Button):
        def __init__(self):
            super().__init__(label="添加新消息", style=discord.ButtonStyle.success, emoji="➕", row=1)

        async def callback(self, interaction: discord.Interaction):
            modal = TemplateMessageItemModal(parent_view=self.view)
            await interaction.response.send_modal(modal)

    class EditButton(Button):
        def __init__(self, disabled: bool):
            super().__init__(label="编辑所选消息", style=discord.ButtonStyle.primary, emoji="✏️", row=1, disabled=disabled)

        async def callback(self, interaction: discord.Interaction):
            selected_msg = next((m for m in self.view.messages if m['internal_id'] == self.view.selected_message_id), None)
            if not selected_msg:
                await interaction.response.send_message("❌ 错误：找不到所选消息。", ephemeral=True)
                return

            modal = TemplateMessageItemModal(existing_data=selected_msg, parent_view=self.view)
            await interaction.response.send_modal(modal)

    class DeleteButton(Button):
        def __init__(self, disabled: bool):
            super().__init__(label="删除所选消息", style=discord.ButtonStyle.danger, emoji="🗑️", row=1, disabled=disabled)

        async def callback(self, interaction: discord.Interaction):
            self.view.messages = [m for m in self.view.messages if m['internal_id'] != self.view.selected_message_id]
            self.view.selected_message_id = None
            await self.view.update_view(interaction, save=True)

    class BackButton(Button):
        def __init__(self):
            super().__init__(label="保存并返回", style=discord.ButtonStyle.grey, emoji="↩️", row=2)

        async def callback(self, interaction: discord.Interaction):
            #  defer() 确保交互不会超时，并向用户确认操作已收到
            await interaction.response.defer()

            # 1. 保存更改
            await self.view._save_changes(interaction.guild.id)

            # 2. 停止当前视图，将控制权交还给父视图
            self.view.stop()