# -*- coding: utf-8 -*-

import discord
from discord.ui import View, Select, Button
import logging
from typing import Optional

from src.guidance.utils.database import guidance_db_manager as db_manager
from src.guidance.ui.modals.path_modal import PathModal
from src.guidance.ui.views.ui_elements import BackButton
from src import config as root_config

log = logging.getLogger(__name__)


class PathConfigurationView(View):
    """路径配置界面的视图"""

    def __init__(
        self,
        main_interaction: discord.Interaction,
        selected_tag_id: Optional[int] = None,
    ):
        super().__init__(timeout=180)
        self.main_interaction = main_interaction
        self.guild_id = main_interaction.guild.id
        self.selected_tag_id = selected_tag_id
        self.tags = []
        self.paths = []

        self.add_item(BackButton())
        # 其他项目将在 async_init 中添加

    async def async_init(self):
        """异步加载数据并填充视图。"""
        self.tags = await db_manager.get_all_tags(self.guild_id)
        self.add_item(TagSelect(self))
        await self.populate_dynamic_items()
        return self

    async def populate_dynamic_items(self):
        """加载或刷新动态按钮（添加路径、路径步骤）"""
        for item in self.children[:]:
            if isinstance(item, (AddPathButton, PathButton)):
                self.remove_item(item)

        if self.selected_tag_id:
            self.paths = await db_manager.get_path_for_tag(self.selected_tag_id)
            self.add_item(AddPathButton(self.selected_tag_id))
            for path in self.paths:
                self.add_item(PathButton(path))

    def get_embed(self) -> discord.Embed:
        """生成路径配置的 Embed"""
        embed = discord.Embed(
            title="🗺️ 路径设置",
            description="请先从下方的下拉菜单中选择一个标签，然后为其添加、删除或排序引导路径点。",
            color=root_config.EMBED_COLOR_INFO,
        )
        if self.selected_tag_id:
            tag = next(
                (t for t in self.tags if t["tag_id"] == self.selected_tag_id), None
            )
            if tag:
                embed.title = f"🗺️ 路径设置: {tag['tag_name']}"
                if not self.paths:
                    embed.description = "这个标签还没有设置任何路径点。\n点击“添加路径点”来创建第一个吧！"
                else:
                    guild = self.main_interaction.guild
                    path_list = []
                    for step in self.paths:
                        location = guild.get_channel_or_thread(step["location_id"])
                        loc_mention = (
                            location.mention
                            if location
                            else f"未知位置 (ID: {step['location_id']})"
                        )
                        msg = f"\n> {step['message']}" if step["message"] else ""
                        path_list.append(
                            f"**{step['step_number']}.** {loc_mention}{msg}"
                        )
                    embed.description = "\n\n".join(path_list)
        return embed

    async def refresh(self):
        """刷新视图"""
        self.tags = await db_manager.get_all_tags(self.guild_id)
        await self.populate_dynamic_items()
        embed = self.get_embed()
        await self.main_interaction.edit_original_response(embed=embed, view=self)


# --- UI 组件 ---


class TagSelect(Select):
    """选择标签的下拉菜单"""

    def __init__(self, parent_view: PathConfigurationView):
        self.parent_view = parent_view
        if parent_view.tags:
            options = [
                discord.SelectOption(label=tag["tag_name"], value=str(tag["tag_id"]))
                for tag in parent_view.tags
            ]
            placeholder = "选择一个标签来配置路径..."
            disabled = False
        else:
            options = [
                discord.SelectOption(label="无可用标签", value="no_tags_placeholder")
            ]
            placeholder = "请先在“标签管理”中创建标签"
            disabled = True
        super().__init__(
            placeholder=placeholder, options=options, row=1, disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.values or self.values[0] == "no_tags_placeholder":
            return
        self.view.selected_tag_id = int(self.values[0])
        await self.view.refresh()


class AddPathButton(Button):
    """添加路径点的按钮"""

    def __init__(self, tag_id: int):
        super().__init__(
            label="添加路径点", style=discord.ButtonStyle.success, emoji="➕", row=2
        )
        self.tag_id = tag_id

    async def callback(self, interaction: discord.Interaction):
        modal = PathModal(guild_id=interaction.guild_id, tag_id=self.tag_id)
        modal.callback_view = self.view
        await interaction.response.send_modal(modal)


class PathButton(Button):
    """代表一个路径点的按钮，用于删除"""

    def __init__(self, path: dict):
        location_id = path["location_id"]
        # 这里我们不能在 init 中获取频道名，因为 bot 可能还没缓存
        # 所以我们只显示 ID 和类型
        super().__init__(
            label=f"步骤 {path['step_number']}: {path['location_type']} {location_id}",
            style=discord.ButtonStyle.secondary,
            emoji="🗑️",
        )
        self.path = path

    async def callback(self, interaction: discord.Interaction):
        # 删除逻辑
        try:
            # 简单的实现：直接从数据库删除该步骤
            # 注意：这会导致 step_number 不连续，需要一个函数来重新排序
            await db_manager.remove_path_step(
                self.path["id"]
            )  # 假设有这个函数，需要去实现
            await interaction.response.send_message(
                f"✅ 已删除路径点：**{self.label}**", ephemeral=True
            )
            await self.view.refresh()
        except Exception as e:
            log.error(f"删除路径点时出错: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ 删除路径点时发生错误。", ephemeral=True
            )
