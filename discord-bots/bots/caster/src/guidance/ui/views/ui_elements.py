# -*- coding: utf-8 -*-

import discord
from discord.ui import Button

class BackButton(Button):
    """一个通用的返回主菜单按钮"""
    def __init__(self, row: int = 4):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.grey, emoji="↩️", row=row)

    async def callback(self, interaction: discord.Interaction):
        # 延迟导入以避免循环依赖
        from .main_panel import MainPanelView
        
        # 确保 self.view.main_interaction 存在
        if not hasattr(self.view, 'main_interaction'):
            await interaction.response.send_message("发生错误，无法返回主菜单。", ephemeral=True)
            return

        await interaction.response.defer()
        view = MainPanelView(self.view.main_interaction)
        embed = await view.get_main_embed()
        await self.view.main_interaction.edit_original_response(embed=embed, view=view)