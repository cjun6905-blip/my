# -*- coding: utf-8 -*-

import discord
from discord.ui import Modal, TextInput
import logging

from src.guidance.utils.database import guidance_db_manager as db_manager

log = logging.getLogger(__name__)

class StageRoleModal(Modal):
    """用于设置阶段身份组ID的模态框"""

    def __init__(self, stage: str, parent_view: discord.ui.View):
        self.stage = stage
        self.parent_view = parent_view
        
        title = f"设置{'缓冲区' if stage == 'buffer' else '已验证'}身份组"
        super().__init__(title=title, timeout=300)

        self.role_id_input = TextInput(
            label="身份组 ID",
            placeholder="请输入身份组的数字ID。留空则为清除设置。",
            required=False,
            max_length=30
        )
        self.add_item(self.role_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        role_id_str = self.role_id_input.value.strip()
        role_id = None

        if role_id_str:
            if not role_id_str.isdigit():
                await interaction.followup.send("❌ ID 必须是纯数字。", ephemeral=True)
                return
            role_id = int(role_id_str)
            
            # 验证身份组是否存在
            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.followup.send(f"❌ 在本服务器中找不到 ID 为 `{role_id}` 的身份组。", ephemeral=True)
                return

        try:
            await db_manager.set_stage_role(
                guild_id=interaction.guild_id,
                stage=self.stage,
                role_id=role_id
            )
            await interaction.followup.send(f"✅ {'缓冲区' if self.stage == 'buffer' else '已验证'}身份组已成功更新！", ephemeral=True)
            
            # 刷新父视图以显示更新
            if hasattr(self.parent_view, 'refresh'):
                await self.parent_view.refresh()

        except Exception as e:
            log.error(f"设置阶段身份组时出错: {e}", exc_info=True)
            await interaction.followup.send("❌ 保存失败，发生了一个内部错误。", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"处理阶段身份组模态框时发生错误: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("处理您的请求时发生错误。", ephemeral=True)
        else:
            await interaction.followup.send("处理您的请求时发生错误。", ephemeral=True)