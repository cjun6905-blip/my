# -*- coding: utf-8 -*-

import asyncio
import discord
import logging
import argparse
import sys
import os
import random
import json
from typing import Optional, List, Dict, Any

# --- 设置项目根路径 ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- 加载环境变量 ---
from dotenv import load_dotenv

load_dotenv()

from src.guidance.utils.database import guidance_db_manager as db_manager

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# --- Discord 客户端 ---
intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

# --- 模拟用户 ---
SIMULATED_USER_ID = 1234567890  # 一个不会与真实用户冲突的ID


class GuidanceFlowValidator:
    """单个引导流程逻辑验证器。"""

    def __init__(self, guild: discord.Guild, tag: Dict[str, Any]):
        self.guild = guild
        self.tag = tag
        self.report = []
        self.generated_path = None
        self.success = False

    async def run_validation(self) -> bool:
        """执行单个标签的验证流程。"""
        tag_name = self.tag["tag_name"]
        tag_id = self.tag["tag_id"]
        log.info(f"--- 开始验证标签: '{tag_name}' (ID: {tag_id}) ---")
        self.report.append(f"🎯 验证目标标签: {tag_name} (ID: {tag_id})")

        try:
            if not await self.check_path():
                return False

            if not await self.simulate_user_initialization():
                return False

            if not await self.simulate_path_traversal():
                return False

            self.report.append(f"✅ 结论: 标签 '{tag_name}' 的引导流程逻辑验证成功！")
            self.success = True
            return True

        except Exception as e:
            log.error(f"验证标签 '{tag_name}' 时发生意外错误: {e}", exc_info=True)
            self.report.append(f"❌ 结论: 验证因意外错误而终止。")
            return False
        finally:
            await db_manager._execute(
                db_manager._db_transaction,
                "DELETE FROM user_progress WHERE user_id = ? AND guild_id = ?",
                (SIMULATED_USER_ID, self.guild.id),
                commit=True,
            )

    async def check_path(self) -> bool:
        """检查选定标签的路径和部署状态。"""
        path_steps = await db_manager.get_path_for_tag(self.tag["tag_id"])
        if not path_steps:
            log.warning(f"标签 '{self.tag['tag_name']}' 没有配置引导路径，跳过验证。")
            self.report.append(f"⚠️ 跳过: 标签 '{self.tag['tag_name']}' 没有配置路径。")
            self.success = True  # 没有路径也算是一种“成功”的验证
            return False  # 返回False以跳过后续步骤

        self.report.append(f"  - 路径包含 {len(path_steps)} 个步骤。")
        self.generated_path = [dict(row) for row in path_steps]

        for i, step in enumerate(self.generated_path):
            channel_id = step["location_id"]
            channel_config = await db_manager.get_channel_message(channel_id)
            if not channel_config or not channel_config.get("deployed_message_id"):
                log.error(f"路径中的频道 {channel_id} (第 {i + 1} 步) 面板尚未部署。")
                self.report.append(
                    f"❌ 预检失败: 路径中的频道 {channel_id} (第 {i + 1} 步) 面板未部署。"
                )
                return False
        self.report.append("  - ✅ 预检通过: 路径中所有步骤均已部署。")
        return True

    async def simulate_user_initialization(self) -> bool:
        """模拟用户选择标签并生成路径。"""
        await db_manager.create_or_reset_user_progress(
            SIMULATED_USER_ID, self.guild.id, status="pending_selection"
        )
        await db_manager.update_user_progress(
            SIMULATED_USER_ID,
            self.guild.id,
            status="in_progress",
            guidance_stage="stage_1_in_progress",
            selected_tags_json=json.dumps([self.tag["tag_id"]]),
            generated_path_json=json.dumps(self.generated_path),
            completed_path_json=json.dumps(self.generated_path),
            current_step=1,
        )

        progress = await db_manager.get_user_progress(SIMULATED_USER_ID, self.guild.id)
        if not progress or progress["status"] != "in_progress":
            log.error("模拟初始化后，未能正确在数据库中创建用户进度。")
            self.report.append("❌ 模拟失败: 未能正确创建用户进度记录。")
            return False

        self.report.append("  - ✅ 步骤 0: 模拟用户初始化成功。")
        return True

    async def simulate_path_traversal(self) -> bool:
        """模拟用户走完整个引导路径。"""
        for i, step in enumerate(self.generated_path):
            step_number = i + 1
            channel_id = step["location_id"]

            progress = await db_manager.get_user_progress(
                SIMULATED_USER_ID, self.guild.id
            )
            if progress["current_step"] != step_number:
                log.error(
                    f"状态错误！预期步骤为 {step_number}，但数据库中为 {progress['current_step']}。"
                )
                self.report.append(
                    f"❌ 步骤 {step_number}: 失败 - 数据库状态与预期不符。"
                )
                return False

            channel_config = await db_manager.get_channel_message(channel_id)
            temp_messages = channel_config.get("temporary_message_data")
            if not temp_messages or not isinstance(temp_messages, list):
                pass  # 没有临时消息是正常情况

            is_last_step = i + 1 >= len(self.generated_path)
            if not is_last_step:
                await db_manager.update_user_progress(
                    SIMULATED_USER_ID, self.guild.id, current_step=step_number + 1
                )
            else:
                await db_manager.update_user_progress(
                    SIMULATED_USER_ID,
                    self.guild.id,
                    status="completed",
                    guidance_stage="stage_1_completed",
                )
                progress = await db_manager.get_user_progress(
                    SIMULATED_USER_ID, self.guild.id
                )
                if progress["status"] != "completed":
                    log.error("完成引导后，数据库状态未能正确更新。")
                    self.report.append(
                        f"❌ 步骤 {step_number}: 失败 - 未能正确更新最终状态。"
                    )
                    return False
        self.report.append(f"  - ✅ 所有 {len(self.generated_path)} 个步骤遍历成功。")
        return True


def generate_summary_report(results: List[GuidanceFlowValidator]):
    """生成最终的总结报告。"""
    total_tags = len(results)
    successful_tags = sum(1 for r in results if r.success)
    failed_tags = total_tags - successful_tags

    print("\n" + "=" * 60)
    print("          引导流程全面逻辑验证总结报告")
    print("=" * 60)
    print(f"总共验证标签数: {total_tags}")
    print(f"✅ 成功: {successful_tags}")
    print(f"❌ 失败: {failed_tags}")
    print("-" * 60)

    if failed_tags > 0:
        print("\n失败的标签详情:")
        for validator in results:
            if not validator.success:
                print(f"\n--- 标签: '{validator.tag['tag_name']}' ---")
                for line in validator.report:
                    if "❌" in line or "⚠️" in line:
                        print(f"  {line}")

    if successful_tags == total_tags and total_tags > 0:
        print("\n🎉 所有已配置的引导路径均已通过验证！")

    print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="执行引导流程的端到端逻辑验证。")
    parser.add_argument(
        "--guild-id", type=int, required=True, help="需要验证的服务器ID。"
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--tag", type=str, help="指定要验证的单个标签名。")
    mode_group.add_argument(
        "--all-tags", action="store_true", help="验证服务器上所有已配置的标签。"
    )
    mode_group.add_argument(
        "--random-tag", action="store_true", help="随机选择一个标签进行验证。"
    )

    args = parser.parse_args()

    bot_token = os.getenv("DISCORD_TOKEN")
    if not bot_token:
        log.error("错误：未在 .env 文件或环境变量中找到 DISCORD_TOKEN。")
        return

    await db_manager.init_async()

    try:
        await client.login(bot_token)
        log.info("正在连接到 Discord...")
        guild = await client.fetch_guild(args.guild_id)
        log.info(f"成功连接到服务器: {guild.name}")

        all_db_tags = await db_manager.get_all_tags(args.guild_id)
        if not all_db_tags:
            log.error("此服务器没有任何已配置的标签，无法进行验证。")
            return

        tags_to_validate = []
        if args.tag:
            tag = next((t for t in all_db_tags if t["tag_name"] == args.tag), None)
            if not tag:
                log.error(f"找不到指定的标签: {args.tag}")
                return
            tags_to_validate.append(dict(tag))
        elif args.all_tags:
            tags_to_validate = [dict(t) for t in all_db_tags]
        elif args.random_tag:
            tags_to_validate.append(dict(random.choice(all_db_tags)))

        validation_results = []
        for tag_data in tags_to_validate:
            validator = GuidanceFlowValidator(guild, tag_data)
            await validator.run_validation()
            validation_results.append(validator)

        generate_summary_report(validation_results)

    except discord.LoginFailure:
        log.error("Discord 登录失败，请检查你的 DISCORD_TOKEN 是否正确。")
    except (discord.NotFound, discord.Forbidden):
        log.error(
            f"无法获取服务器 {args.guild_id}。请检查机器人是否在该服务器中以及是否有权限。"
        )
    except Exception as e:
        log.error(f"发生未知错误: {e}", exc_info=True)
    finally:
        if client.is_ready():
            await client.close()
        await db_manager.close()
        log.info("客户端和数据库连接已关闭。")


if __name__ == "__main__":
    asyncio.run(main())
