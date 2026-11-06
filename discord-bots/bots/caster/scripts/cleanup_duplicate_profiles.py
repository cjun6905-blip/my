# -*- coding: utf-8 -*-
import os
import sys
import sqlite3
import asyncio
import json
import argparse
from collections import defaultdict
import logging
import time

# --- 步骤 1: 关键路径设置 ---
# 将项目根目录添加到 sys.path，以便能正确导入 'src' 目录下的模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- 路径设置结束 ---


# --- 步骤 2: 环境变量加载 (核心修复) ---
# **必须**在导入任何自定义模块 (如 config, services) 之前执行
# 这样可以确保所有服务在初始化时都能访问到 .env 文件中定义的配置
from dotenv import load_dotenv

load_dotenv()
# --- 环境变量加载结束 ---


# --- 步骤 3: 导入项目模块 ---
# 现在可以安全地导入依赖环境变量的服务了
from src import config
from src.chat.features.world_book.services.incremental_rag_service import (
    incremental_rag_service,
)
# --- 模块导入结束 ---


# --- 数据库配置与连接 ---
DB_PATH = os.path.join(config.DATA_DIR, "world_book.sqlite3")


# --- 日志配置 ---
def setup_logging():
    """配置日志记录器，使其同时输出到控制台和文件。"""
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(log_dir, f"cleanup_report_{timestamp}.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 清除任何可能存在的旧处理器
    if logger.hasHandlers():
        logger.handlers.clear()

    # 控制台处理器
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stream_handler)

    # 文件处理器
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)

    # 返回配置好的记录器实例
    return logger


log = setup_logging()
log.info(
    f"✅ 日志报告将保存在: logs/cleanup_report_{time.strftime('%Y%m%d_%H%M%S')}.log"
)
# --- 日志配置结束 ---


def get_db_connection():
    """建立并返回一个新的 SQLite 数据库连接，启用行工厂以便按列名访问。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        log.error(f"❌ 错误：无法连接到数据库: {e}")
        return None


# --- 核心功能函数 ---


async def find_and_process_duplicates(view_only: bool):
    """
    查找并处理（查看或删除）重复的社区成员档案。

    重复项的判断标准：
    1. 优先使用 `discord_number_id` 字段。
    2. 如果 `discord_number_id` 为空，则尝试从 `content_json` 中解析 `discord_id`。

    保留策略：
    - 对于同一用户的一组重复档案，保留主键 `id` 最大的那一个，因为它通常是最新创建的。
    """
    log.info("\n--- 任务: 查找并处理重复的用户档案 ---")
    if view_only:
        log.info("--- 模式: 预览 (仅列出重复项，不修改任何数据) ---\n")
    else:
        log.info("--- 模式: 执行 (将永久删除重复数据和关联的RAG索引) ---\n")
        log.info("⚠️ 警告：操作将在 3 秒后开始...")
        await asyncio.sleep(3)

    conn = get_db_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, discord_number_id, title, content_json FROM community_members"
        )
        all_members = cursor.fetchall()

        # 按用户ID对所有档案进行分组
        profiles_by_user = defaultdict(list)
        for member in all_members:
            member_dict = dict(member)
            user_id = None
            if member_dict.get("discord_number_id"):
                user_id = member_dict["discord_number_id"]
            elif member_dict.get("content_json"):
                try:
                    content = json.loads(member_dict["content_json"])
                    if isinstance(content, dict) and content.get("discord_id"):
                        user_id = str(content["discord_id"])
                except (json.JSONDecodeError, TypeError):
                    pass  # JSON解析失败则忽略

            if user_id:
                profiles_by_user[user_id].append(member_dict)

        # 找出所有重复的档案并确定要删除的列表
        duplicates_to_delete_ids = []
        total_duplicates = 0
        for user_id, profiles in profiles_by_user.items():
            if len(profiles) > 1:
                total_duplicates += len(profiles) - 1
                log.info(f"🔎 发现用户 ID '{user_id}' 拥有 {len(profiles)} 个档案。")
                profiles.sort(key=lambda p: p["id"], reverse=True)
                profile_to_keep = profiles[0]
                old_profiles = profiles[1:]
                log.info(
                    f"  - [保留] 最新档案: ID = {profile_to_keep['id']} (标题: '{profile_to_keep['title']}')"
                )
                for old in old_profiles:
                    log.info(
                        f"  - [待删除] 陈旧档案: ID = {old['id']} (标题: '{old['title']}')"
                    )
                    duplicates_to_delete_ids.append(old["id"])

        if not duplicates_to_delete_ids:
            log.info("\n✅ 未发现重复档案，数据库很干净！")
            return

        log.info("\n--- 总结 ---")
        log.info(f"总计发现 {total_duplicates} 个可删除的重复档案。")
        if view_only:
            log.info("预览模式结束。")
            return
        log.info("\n--- 开始执行删除操作 ---")
        log.info("\n步骤 1/3: 从向量数据库中删除索引...")
        for entry_id in duplicates_to_delete_ids:
            log.info(f"  - 正在删除 {entry_id} 的向量...")
            if await incremental_rag_service.delete_entry(entry_id):
                log.info("    ...成功。")
            else:
                log.warning("    ...⚠️ 失败或未找到。")
        log.info("\n步骤 2/3: 从 'member_discord_nicknames' 表中删除关联数据...")
        cursor.executemany(
            "DELETE FROM member_discord_nicknames WHERE member_id = ?",
            [(entry_id,) for entry_id in duplicates_to_delete_ids],
        )
        log.info(f"  - 已删除 {cursor.rowcount} 条关联昵称记录。")
        log.info("\n步骤 3/3: 从 'community_members' 主表中删除档案...")
        cursor.executemany(
            "DELETE FROM community_members WHERE id = ?",
            [(entry_id,) for entry_id in duplicates_to_delete_ids],
        )
        log.info(f"  - 已删除 {cursor.rowcount} 条主档案记录。")
        conn.commit()
        log.info("\n✅ 所有删除操作已完成，数据库更改已提交。")
    except Exception as e:
        log.error(f"\n❌ 处理过程中发生严重错误: {e}", exc_info=True)
        if not view_only:
            conn.rollback()
            log.error("--- ‼️ 由于发生错误，所有数据库更改已被回滚。 ---")
    finally:
        if conn:
            conn.close()


async def find_and_fix_titles(view_only: bool):
    """
    查找、修复并重新RAG处理带有特定前缀的社区成员档案标题。
    """
    log.info("\n--- 任务: 修复档案标题并重新生成RAG索引 ---")
    if view_only:
        log.info("--- 模式: 预览 (仅列出将要修复的标题，不修改任何数据) ---\n")
    else:
        log.info("--- 模式: 执行 (将永久修改标题并重新生成RAG索引) ---\n")
        log.info("⚠️ 警告：操作将在 3 秒后开始...")
        await asyncio.sleep(3)

    conn = get_db_connection()
    if not conn:
        return

    prefixes = ["社区成员档案-", "用户档案-", "社区成员档案 - ", "用户档案 - "]

    try:
        cursor = conn.cursor()
        query = "SELECT id, title FROM community_members WHERE " + " OR ".join(
            ["title LIKE ?"] * len(prefixes)
        )
        params = [f"{p}%" for p in prefixes]
        cursor.execute(query, params)
        entries_to_fix = cursor.fetchall()

        if not entries_to_fix:
            log.info("\n✅ 未发现需要修复的档案标题。")
            return

        log.info(f"🔎 发现 {len(entries_to_fix)} 个需要修复的档案标题:")

        fixed_entries = []
        for entry in entries_to_fix:
            original = entry["title"]
            clean = original
            for p in prefixes:
                if clean.startswith(p):
                    clean = clean[len(p) :].strip()

            if original != clean:
                log.info(f"  - 档案 ID: {entry['id']}")
                log.info(f"    - 原标题: '{original}'")
                log.info(f"    - 新标题: '{clean}'")
                fixed_entries.append({"id": entry["id"], "new_title": clean})

        if view_only:
            log.info("\n预览模式结束。")
            return

        log.info("\n--- 开始执行修复与重RAG操作 ---")

        for item in fixed_entries:
            entry_id, new_title = item["id"], item["new_title"]
            log.info(f"\n处理档案 ID: {entry_id}")

            log.info(f"  - 步骤 1/3: 更新数据库标题为 '{new_title}'...")
            cursor.execute(
                "UPDATE community_members SET title = ? WHERE id = ?",
                (new_title, entry_id),
            )
            log.info("    ...成功。")

            log.info("  - 步骤 2/3: 从向量数据库删除旧索引...")
            if await incremental_rag_service.delete_entry(entry_id):
                log.info("    ...成功。")
            else:
                log.warning("    ...⚠️ 失败或未找到。")

            log.info("  - 步骤 3/3: 基于新标题重新生成索引...")
            if await incremental_rag_service.process_community_member(entry_id):
                log.info("    ...成功。")
            else:
                log.error("    ...❌ 失败！请检查服务日志。")

        conn.commit()
        log.info("\n✅ 所有修复操作已完成，数据库更改已提交。")

    except Exception as e:
        log.error(f"\n❌ 处理过程中发生严重错误: {e}", exc_info=True)
        if not view_only:
            conn.rollback()
            log.error("--- ‼️ 由于发生错误，所有数据库更改已被回滚。 ---")
    finally:
        if conn:
            conn.close()


async def main():
    """脚本主入口，负责解析命令行参数并调用核心函数。"""
    parser = argparse.ArgumentParser(
        description="奥德赛世界书数据库维护工具",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--view-duplicates",
        action="store_true",
        help="推荐首先运行此命令。\n预览将要被删除的重复用户档案，不执行任何实际操作。",
    )
    parser.add_argument(
        "--delete-duplicates",
        action="store_true",
        help="警告：危险操作！\n查找并永久删除所有重复的用户档案及其RAG索引。",
    )
    parser.add_argument(
        "--view-titles",
        action="store_true",
        help="预览将要被修复格式的用户档案标题，不执行任何实际操作。",
    )
    parser.add_argument(
        "--fix-titles",
        action="store_true",
        help="警告：危险操作！\n修复所有带有多余前缀的标题，并为它们重新生成RAG索引。",
    )

    args = parser.parse_args()

    log.info("✅ 已加载 .env 文件中的环境变量。")
    if args.view_duplicates:
        await find_and_process_duplicates(view_only=True)
    elif args.delete_duplicates:
        log.info("\n‼️ 您正在准备执行永久性删除操作 ‼️")
        confirm = input('请输入 "DELETE" 以确认: ')
        if confirm == "DELETE":
            await find_and_process_duplicates(view_only=False)
        else:
            log.info("确认失败，已取消操作。")
    elif args.view_titles:
        await find_and_fix_titles(view_only=True)
    elif args.fix_titles:
        log.info("\n‼️ 您正在准备执行永久性数据库修改和RAG重建操作 ‼️")
        confirm = input('请输入 "FIX" 以确认: ')
        if confirm == "FIX":
            await find_and_fix_titles(view_only=False)
        else:
            log.info("确认失败，已取消操作。")
    else:
        log.error("错误：请提供一个有效的运行参数。")
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
