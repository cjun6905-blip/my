# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import sys
import shutil
import discord
import argparse
import json
import time  # 新增：用于冷却
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

# ... (导入路径保持不变) ...
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import config as main_config

# ... (日志配置保持不变) ...
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

DB_DIR = os.path.join(main_config.DATA_DIR, "forum_chroma_db")
DB_STATUS_FILE = os.path.join(main_config.DATA_DIR, "forum_sync_status.db")


# ... (clear_existing_database 函数保持不变) ...
def clear_existing_database():
    log.info("开始清空旧的论坛索引数据库...")
    try:
        if os.path.exists(DB_DIR):
            shutil.rmtree(DB_DIR)
            log.info(f"成功删除目录: {DB_DIR}")

        if os.path.exists(DB_STATUS_FILE):
            os.remove(DB_STATUS_FILE)
            log.info(f"成功删除文件: {DB_STATUS_FILE}")

        return True
    except Exception as e:
        log.error(f"清理数据库时发生错误: {e}", exc_info=True)
        return False


async def restore_from_jsonl(jsonl_file: str):
    """
    【优化版】从 JSONL 文件恢复索引。
    特点：内存占用低，包含 API 速率限制保护。
    """
    log.info(f"🔥 开始从备份文件 '{jsonl_file}' 恢复索引...")

    # 1. 强制清理数据库
    if not clear_existing_database():
        return

    if not os.path.exists(jsonl_file):
        log.error(f"错误: 备份文件 '{jsonl_file}' 不存在。")
        return

    # 2. 延迟导入服务，确保在数据库清理后执行
    from src.chat.features.forum_search.services.forum_search_service import (
        forum_search_service,
    )

    try:
        if hasattr(forum_search_service, "init_async"):
            await forum_search_service.init_async()
        log.info("搜索服务初始化完成。")
    except Exception as e:
        log.error(f"服务初始化失败: {e}")

    # 3. 流式读取 + 批量处理
    batch_size = 20  # ⬇️ 调小一点，防止 Gemini 429 错误
    current_batch = []

    try:
        # 先扫一遍获取总行数用于进度条 (这一步很快)
        with open(jsonl_file, "r", encoding="utf-8") as f:
            total_lines = sum(1 for _ in f)

        log.info(f"共找到 {total_lines} 条记录，准备开始...")

        with open(jsonl_file, "r", encoding="utf-8") as f:
            pbar = tqdm(total=total_lines, desc="恢复进度")

            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    item = json.loads(line)
                    current_batch.append(item)
                except json.JSONDecodeError:
                    continue

                # 凑够一批，发送处理
                if len(current_batch) >= batch_size:
                    await process_batch(current_batch)
                    pbar.update(len(current_batch))
                    current_batch = []

                    # 🛌 关键：休息一下！
                    # 既为了 Gemini 不报 429，也为了硬盘 I/O 能喘口气
                    # 如果你的 VPS 很卡，建议改为 2.0 或 3.0
                    await asyncio.sleep(1.5)

            # 处理剩余的尾巴
            if current_batch:
                await process_batch(current_batch)
                pbar.update(len(current_batch))

            pbar.close()

        log.info(f"🎉 恢复完成！所有 {total_lines} 条记录已重新处理。")

    except Exception as e:
        log.error(f"恢复过程中发生严重错误: {e}", exc_info=True)


async def process_batch(batch_items):
    """辅助函数：处理一个批次"""
    ids = [item["id"] for item in batch_items if item.get("id")]
    documents = [item["document"] for item in batch_items if item.get("document")]
    metadatas = [item.get("metadata", {}) for item in batch_items]

    if not ids or not documents:
        return

    # 延迟导入服务
    from src.chat.features.forum_search.services.forum_search_service import (
        forum_search_service,
    )

    try:
        await forum_search_service.add_documents_batch(
            ids=ids, documents=documents, metadatas=metadatas
        )
    except Exception as e:
        log.error(f"批量写入失败: {e}")


async def reindex_forums(rebuild: bool, restore_from: str = None):
    """连接到Discord并执行重新索引任务，或从备份恢复。"""
    if restore_from:
        await restore_from_jsonl(restore_from)
        return

    # --- 以下是原始的从 Discord 抓取逻辑 ---
    intents = discord.Intents.default()
    intents.guilds = True
    intents.message_content = True
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info(f"机器人已作为 {client.user} 登录，准备开始索引。")

        if rebuild:
            if not clear_existing_database():
                log.error("数据库清理失败，索引任务已中止。")
                await client.close()
                return
        else:
            log.info("将执行更新/增量索引（跳过数据库清理）。")

        # 延迟导入，确保服务在需要时才初始化
        from src.chat.config import chat_config
        from src.chat.features.forum_search.services.forum_search_service import (
            forum_search_service,
        )

        channel_ids = chat_config.FORUM_SEARCH_CHANNEL_IDS
        if not channel_ids:
            log.warning("没有在配置中找到任何论坛频道ID。")
            await client.close()
            return

        log.info(f"将要处理的频道ID: {channel_ids}")

        for channel_id in channel_ids:
            channel = client.get_channel(channel_id)
            if not isinstance(channel, discord.ForumChannel):
                log.warning(f"ID {channel_id} 不是一个有效的论坛频道，已跳过。")
                continue

            log.info(f"--- 开始处理频道: {channel.name} ({channel.id}) ---")
            try:
                active_threads = channel.threads
                archived_threads_iterator = channel.archived_threads(limit=100)
                archived_threads = [t async for t in archived_threads_iterator]

                all_threads_dict = {t.id: t for t in active_threads}
                all_threads_dict.update({t.id: t for t in archived_threads})

                sorted_threads = sorted(
                    all_threads_dict.values(),
                    key=lambda t: t.created_at,
                    reverse=True,
                )
                threads_to_process = sorted_threads[:100]
                log.info(f"找到 {len(threads_to_process)} 个帖子准备处理。")

                semaphore = asyncio.Semaphore(chat_config.FORUM_POLL_CONCURRENCY)
                tasks = []

                async def process_with_semaphore(thread):
                    async with semaphore:
                        await forum_search_service.process_thread(thread)

                for thread in threads_to_process:
                    tasks.append(process_with_semaphore(thread))

                for f in tqdm_asyncio.as_completed(
                    tasks, desc=f"索引频道 {channel.name}"
                ):
                    await f

            except Exception as e:
                log.error(f"处理频道 {channel.name} 时发生错误: {e}", exc_info=True)

        log.info("所有频道的索引任务已完成。机器人将自动关闭。")
        await client.close()

    try:
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            log.critical("错误: DISCORD_TOKEN 未在 .env 文件中设置！")
            return
        await client.start(token)
    except discord.LoginFailure:
        log.error("机器人令牌无效，请检查您的 .env 文件配置。")
    except Exception as e:
        log.error(f"启动机器人时发生未知错误: {e}", exc_info=True)


async def main():
    parser = argparse.ArgumentParser(description="手动重新索引Discord论坛帖子。")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="如果设置此标志，将完全清空并重建索引数据库。否则，将执行更新/增量索引。",
    )
    parser.add_argument(
        "--restore-from",
        type=str,
        default=None,
        help="提供一个 JSONL 文件的路径，将从该文件恢复索引，而不是从 Discord 抓取。",
    )
    args = parser.parse_args()

    # 如果提供了 restore_from，则 rebuild 标志自动为 True，因为恢复总是需要一个干净的环境
    should_rebuild = args.rebuild or args.restore_from is not None

    await reindex_forums(rebuild=should_rebuild, restore_from=args.restore_from)


if __name__ == "__main__":
    from dotenv import load_dotenv

    # 确保 .env 文件已加载
    load_dotenv()
    asyncio.run(main())
