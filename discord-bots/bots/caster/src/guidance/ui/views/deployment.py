# -*- coding: utf-8 -*-

import discord
from discord.ui import View, Button
import logging
from typing import Dict, Tuple

from src.guidance.utils.database import guidance_db_manager as db_manager
from src.guidance.ui.views.ui_elements import BackButton
from src import config as root_config
from src.guidance.services.deployment_service import deploy_all_panels

log = logging.getLogger(__name__)


class DeploymentView(View):
    """处理部署和重置引导消息的视图"""

    def __init__(self, main_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.main_interaction = main_interaction
        self.guild = main_interaction.guild
        self.checks_passed = False
        self.check_results = {}
        self.has_deployment = False

    async def async_init(self):
        """异步初始化，运行检查并设置组件。"""
        self.clear_items()
        (
            self.checks_passed,
            self.check_results,
            self.has_deployment,
        ) = await self.run_pre_deployment_checks()

        # 添加返回按钮
        self.add_item(BackButton())

        # 添加部署和重置按钮
        self.add_item(DeployAllButton(disabled=not self.checks_passed))
        self.add_item(ResetDeploymentButton(disabled=not self.has_deployment))

    async def run_pre_deployment_checks(
        self,
    ) -> Tuple[bool, Dict[str, Tuple[bool, str]], bool]:
        """执行部署前的所有检查。"""
        guild_id = self.guild.id
        results = {}

        # 检查 1: 是否至少有一个配置好的永久消息
        channel_configs = await db_manager.get_all_channel_messages(guild_id)
        valid_configs = [c for c in channel_configs if c.get("permanent_message_data")]
        results["channel_configs"] = (
            bool(valid_configs),
            f"{len(valid_configs)} 个地点已配置永久消息",
        )

        # 检查 2: 机器人是否拥有必要的权限
        perms = self.guild.me.guild_permissions
        has_perms = perms.send_messages and perms.embed_links and perms.manage_messages
        results["permissions"] = (
            has_perms,
            "基本权限充足" if has_perms else "缺少关键权限",
        )

        # 检查 3: 是否已有部署存在
        deployed_messages = [c for c in channel_configs if c.get("deployed_message_id")]
        has_deployment = bool(deployed_messages)

        overall_result = all(res[0] for res in results.values())
        return overall_result, results, has_deployment

    async def get_embed(self) -> discord.Embed:
        """生成部署视图的 Embed"""
        if self.checks_passed:
            title = "✅ 准备就绪，可以部署或更新"
            description = (
                "所有前置检查均已通过。\n"
                "▶️ **一键部署**: 向所有已配置的地点部署或更新引导消息。\n"
                "🔄 **重置部署**: 从所有地点删除已部署的引导消息。"
            )
            color = root_config.EMBED_COLOR_PRIMARY
        else:
            title = "⚠️ 部署前检查失败"
            description = "部分条件不满足，无法进行部署。请根据以下提示完成配置后重试。"
            color = root_config.EMBED_COLOR_PRIMARY

        embed = discord.Embed(title=title, description=description, color=color)

        check_map = {
            "channel_configs": "📝 地点消息配置",
            "permissions": "🤖 机器人权限",
        }
        for key, (passed, status_text) in self.check_results.items():
            emoji = "✅" if passed else "❌"
            embed.add_field(
                name=f"{emoji} {check_map.get(key, key)}",
                value=f"状态: {status_text}",
                inline=False,
            )

        embed.set_footer(text="部署或重置过程可能需要一些时间，请耐心等待。")
        return embed


# --- UI 组件 ---


class DeployAllButton(Button):
    """确认部署所有频道消息的按钮"""

    def __init__(self, disabled: bool):
        super().__init__(
            label="🚀 一键部署/更新",
            style=discord.ButtonStyle.success,
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        success_count, fail_count, report_lines = await deploy_all_panels(guild)

        report_embed = discord.Embed(
            title="部署完成",
            description=f"**总览: {success_count} 个成功, {fail_count} 个失败**",
            color=root_config.EMBED_COLOR_PRIMARY,
        )

        current_chunk = ""
        field_count = 1
        if not report_lines:
            report_embed.add_field(name="详细报告", value="无详细信息。", inline=False)
        else:
            for line in report_lines:
                if len(current_chunk) + len(line) + 2 > 1024:  # +2 for \n
                    report_embed.add_field(
                        name=f"详细报告 (第 {field_count} 部分)",
                        value=current_chunk,
                        inline=False,
                    )
                    current_chunk = ""
                    field_count += 1
                current_chunk += line + "\n"

            if current_chunk:
                report_embed.add_field(
                    name=f"详细报告 (第 {field_count} 部分)",
                    value=current_chunk,
                    inline=False,
                )

        await interaction.followup.send(embed=report_embed, ephemeral=True)

        # 刷新主视图
        await self.view.async_init()
        new_embed = await self.view.get_embed()
        await self.view.main_interaction.edit_original_response(
            embed=new_embed, view=self.view
        )


class ResetDeploymentButton(Button):
    """重置所有部署的按钮"""

    def __init__(self, disabled: bool):
        super().__init__(
            label="🔄 重置所有部署",
            style=discord.ButtonStyle.danger,
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        all_configs = await db_manager.get_all_channel_messages(guild.id)

        deploy_targets = [c for c in all_configs if c.get("deployed_message_id")]

        if not deploy_targets:
            await interaction.followup.send(
                "ℹ️ 当前没有任何已部署的消息可供重置。", ephemeral=True
            )
            return

        success_count, fail_count, report_lines = 0, 0, []

        for config_item in deploy_targets:
            channel_id = config_item["channel_id"]
            message_id = config_item["deployed_message_id"]
            channel = guild.get_channel_or_thread(channel_id)

            if not channel:
                report_lines.append(
                    f"⚠️ **未知地点 (ID: {channel_id})**: 无法删除消息，但已从数据库清除记录。"
                )
                await db_manager.update_channel_deployment_id(channel_id, None)
                fail_count += 1
                continue

            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
                await db_manager.update_channel_deployment_id(channel_id, None)
                report_lines.append(f"✅ **#{channel.name}**: 已成功删除部署的消息。")
                success_count += 1
            except discord.NotFound:
                await db_manager.update_channel_deployment_id(channel_id, None)
                report_lines.append(
                    f"ℹ️ **#{channel.name}**: 消息已被删除，已从数据库清除记录。"
                )
            except discord.Forbidden:
                report_lines.append(f"❌ **#{channel.name}**: 权限不足，无法删除消息。")
                fail_count += 1
            except Exception as e:
                log.error(f"重置地点 {channel_id} 时出错: {e}", exc_info=True)
                report_lines.append(f"❌ **#{channel.name}**: 发生未知错误。")
                fail_count += 1

        report_embed = discord.Embed(
            title="重置完成",
            description=f"**总览: {success_count} 个成功, {fail_count} 个失败/警告**",
            color=root_config.EMBED_COLOR_PRIMARY,
        )

        current_chunk = ""
        field_count = 1
        if not report_lines:
            report_embed.add_field(name="详细报告", value="无详细信息。", inline=False)
        else:
            for line in report_lines:
                if len(current_chunk) + len(line) + 2 > 1024:  # +2 for \n
                    report_embed.add_field(
                        name=f"详细报告 (第 {field_count} 部分)",
                        value=current_chunk,
                        inline=False,
                    )
                    current_chunk = ""
                    field_count += 1
                current_chunk += line + "\n"

            if current_chunk:
                report_embed.add_field(
                    name=f"详细报告 (第 {field_count} 部分)",
                    value=current_chunk,
                    inline=False,
                )

        await interaction.followup.send(embed=report_embed, ephemeral=True)

        # 刷新主视图
        await self.view.async_init()
        new_embed = await self.view.get_embed()
        await self.view.main_interaction.edit_original_response(
            embed=new_embed, view=self.view
        )
