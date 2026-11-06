# -*- coding: utf-8 -*-

import discord
from discord.ui import View, Select, Button
import logging

from src.guidance.utils.database import guidance_db_manager as db_manager
from src.guidance.ui.views.ui_elements import BackButton
from src import config as root_config
from src.guidance.ui.modals.role_stage_modal import StageRoleModal

log = logging.getLogger(__name__)


class RoleConfigurationView(View):
    """身份组配置界面的视图"""

    def __init__(self, main_interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.main_interaction = main_interaction
        self.guild_id = main_interaction.guild.id
        self.guild_config = None
        self.trigger_roles = []
        self.selected_role_ids = None

        self.add_item(BackButton())
        # populate_items 将在 async_init 中被调用

    async def async_init(self):
        """异步加载所有必要的数据并填充视图。"""
        await self.populate_items()
        return self

    def get_embed(self) -> discord.Embed:
        """生成身份组配置的 Embed"""
        guild = self.main_interaction.guild
        embed = discord.Embed(
            title="🛂 身份组与引导阶段配置",
            description=(
                "在这里，您可以配置完整的、分阶段的引导流程。\n"
                "1. **触发身份组**: 用户获得其中**任一**身份组后，将**首次**触发引导。\n"
                "2. **阶段身份组**: 用于区分引导的不同阶段，必须是上面触发身份组的成员。"
            ),
            color=root_config.EMBED_COLOR_INFO,
        )

        # --- 显示触发身份组 ---
        current_roles_ids = [row["role_id"] for row in self.trigger_roles]
        if not current_roles_ids:
            trigger_role_info = "尚未配置。用户不会被自动引导。"
        else:
            role_mentions = []
            for role_id in current_roles_ids:
                role = guild.get_role(role_id)
                role_mentions.append(role.mention if role else f"`未知ID: {role_id}`")
            trigger_role_info = " ".join(role_mentions)
        embed.add_field(
            name="1️⃣ 触发身份组 (多选)", value=trigger_role_info, inline=False
        )

        # --- 显示阶段身份组 ---
        buffer_role_id = (
            self.guild_config["buffer_role_id"] if self.guild_config else None
        )
        verified_role_id = (
            self.guild_config["verified_role_id"] if self.guild_config else None
        )

        buffer_role = guild.get_role(buffer_role_id) if buffer_role_id else None
        verified_role = guild.get_role(verified_role_id) if verified_role_id else None

        buffer_role_info = buffer_role.mention if buffer_role else "⚠️ 未设置"
        verified_role_info = verified_role.mention if verified_role else "⚠️ 未设置"

        embed.add_field(
            name="阶段一：缓冲区身份组", value=buffer_role_info, inline=True
        )
        embed.add_field(
            name="阶段二：已验证身份组", value=verified_role_info, inline=True
        )

        embed.set_footer(
            text="提示：阶段身份组ID可通过右键点击身份组，选择“复制ID”获得。"
        )
        return embed

    async def populate_items(self):
        """加载或刷新动态组件"""
        # 清理旧组件
        for item in self.children[:]:
            if isinstance(item, (RoleSelect, SaveButton, SetStageRoleButton)):
                self.remove_item(item)

        # 加载新数据
        self.trigger_roles = await db_manager.get_trigger_roles(self.guild_id)
        self.guild_config = await db_manager.get_guild_config(self.guild_id)

        # 添加新组件
        self.add_item(RoleSelect(self))
        self.add_item(SaveButton())
        self.add_item(
            SetStageRoleButton(
                stage="buffer",
                label="设置缓冲区身份组",
                style=discord.ButtonStyle.secondary,
                row=3,
            )
        )
        self.add_item(
            SetStageRoleButton(
                stage="verified",
                label="设置已验证身份组",
                style=discord.ButtonStyle.primary,
                row=3,
            )
        )

    async def refresh(self):
        """刷新视图"""
        await self.populate_items()
        embed = self.get_embed()
        await self.main_interaction.edit_original_response(embed=embed, view=self)


# --- UI 组件 ---


class RoleSelect(Select):
    """选择身份组的多选下拉菜单"""

    def __init__(self, parent_view: View):
        self.parent_view = parent_view
        guild = parent_view.main_interaction.guild

        current_roles_ids = {str(row["role_id"]) for row in parent_view.trigger_roles}

        options = []
        sorted_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
        for role in sorted_roles:
            if role.is_default():
                continue

            is_default = str(role.id) in current_roles_ids

            options.append(
                discord.SelectOption(
                    label=role.name, value=str(role.id), emoji="👑", default=is_default
                )
            )

        if len(options) > 25:
            options = options[:25]
            placeholder = "选择触发身份组 (仅显示前25个)..."
        else:
            placeholder = "选择一个或多个触发身份组..."

        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=0,
            max_values=len(options),
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        # 将选择的 role_ids 存储在视图中，等待保存
        self.view.selected_role_ids = [int(v) for v in self.values]
        await interaction.response.defer()  # 仅确认交互，不做任何事


class SaveButton(Button):
    """保存“触发身份组”设置的按钮"""

    def __init__(self):
        super().__init__(
            label="保存触发身份组", style=discord.ButtonStyle.success, emoji="💾", row=2
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        selected_ids = getattr(self.view, "selected_role_ids", None)

        if selected_ids is None:
            await interaction.followup.send(
                "ℹ️ 触发身份组配置未发生变化，无需保存。", ephemeral=True
            )
            return

        try:
            await db_manager.set_trigger_roles(interaction.guild_id, selected_ids)
            await interaction.followup.send(
                "✅ 触发身份组配置已成功保存！", ephemeral=True
            )
            await self.view.refresh()
        except Exception as e:
            log.error(f"保存触发身份组配置时出错: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 保存失败，发生了一个内部错误。", ephemeral=True
            )


class SetStageRoleButton(Button):
    """设置阶段身份组的按钮"""

    def __init__(self, stage: str, label: str, style: discord.ButtonStyle, row: int):
        self.stage = stage
        super().__init__(label=label, style=style, row=row)

    async def callback(self, interaction: discord.Interaction):
        # 弹出模态框让用户输入ID
        modal = StageRoleModal(stage=self.stage, parent_view=self.view)
        await interaction.response.send_modal(modal)
