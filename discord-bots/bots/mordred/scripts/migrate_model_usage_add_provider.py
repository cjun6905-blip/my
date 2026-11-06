#!/usr/bin/env python3
"""
迁移模型使用统计数据，为现有数据添加 provider_name 字段

使用方法:
    python scripts/migrate_model_usage_add_provider.py
"""

import sqlite3
import os
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_model_provider_mapping() -> dict:
    """
    获取模型名称到 Provider 的映射。

    Returns:
        {"gemini-2.5-flash": "gemini_official", ...}
    """
    # 先尝试从配置文件获取（不依赖 ai_service 实例）
    try:
        from src.chat.services.ai.config.models import get_model_configs

        model_configs = get_model_configs()
        mapping = {}
        for model_name, config in model_configs.items():
            if hasattr(config, "provider") and config.provider:
                mapping[model_name] = config.provider
        if mapping:
            print(f"从模型配置获取到 {len(mapping)} 个映射")
            return mapping
    except Exception as e:
        print(f"警告: 无法从模型配置获取映射: {e}")

    # 再尝试从 ai_service 获取
    try:
        from src.chat.services.ai import ai_service

        mapping = ai_service._model_to_provider.copy()
        if mapping:
            print(f"从 AIService 获取到 {len(mapping)} 个映射")
            return mapping
    except Exception as e:
        print(f"警告: 无法从 AIService 获取模型映射: {e}")

    # 返回一个基于已知模型的默认映射
    print("使用硬编码的默认映射")
    return {
        "gemini-2.5-flash": "gemini_official",
        "gemini-flash-latest": "gemini_official",
        # 自定义端点模型 - 从环境变量动态生成
        "gemini-2.5-flash-custom": "gemini_custom_2.5_flash",
        "gemini-3-pro-preview-custom": "gemini_custom_3_pro_preview",
        "gemini-2.5-pro-custom": "gemini_custom_2.5_pro",
        "gemini-3-flash-custom": "gemini_custom_3_flash",
        # DeepSeek
        "deepseek-chat": "deepseek",
        "deepseek-reasoner": "deepseek",
    }


def migrate():
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chat.db"
    )

    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        return False

    print(f"连接数据库: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 获取模型到 Provider 的映射
    model_provider_map = get_model_provider_mapping()
    print(f"已加载 {len(model_provider_map)} 个模型的 Provider 映射")

    try:
        # 检查是否已有 provider_name 列
        cursor.execute("PRAGMA table_info(ai_model_usage)")
        columns = [row[1] for row in cursor.fetchall()]

        if "provider_name" not in columns:
            print("添加 provider_name 列到 ai_model_usage...")
            cursor.execute("ALTER TABLE ai_model_usage ADD COLUMN provider_name TEXT")
        else:
            print("ai_model_usage 已有 provider_name 列")

        cursor.execute("PRAGMA table_info(daily_model_usage)")
        columns = [row[1] for row in cursor.fetchall()]

        if "provider_name" not in columns:
            print("添加 provider_name 列到 daily_model_usage...")
            cursor.execute(
                "ALTER TABLE daily_model_usage ADD COLUMN provider_name TEXT"
            )
        else:
            print("daily_model_usage 已有 provider_name 列")

        # 更新现有数据的 provider_name（包括已设置为 unknown 的记录）
        print("\n更新 ai_model_usage 表的 provider_name...")

        cursor.execute(
            "SELECT model_name FROM ai_model_usage WHERE provider_name IS NULL OR provider_name = 'unknown'"
        )
        rows = cursor.fetchall()

        updated_count = 0
        for row in rows:
            model_name = row[0]
            provider_name = model_provider_map.get(model_name, "unknown")

            cursor.execute(
                "UPDATE ai_model_usage SET provider_name = ? WHERE model_name = ?",
                (provider_name, model_name),
            )
            print(f"  {model_name} -> {provider_name}")
            updated_count += 1

        print(f"ai_model_usage 更新了 {updated_count} 条记录")

        print("\n更新 daily_model_usage 表的 provider_name...")

        cursor.execute(
            "SELECT DISTINCT model_name FROM daily_model_usage WHERE provider_name IS NULL OR provider_name = 'unknown'"
        )
        rows = cursor.fetchall()

        updated_count = 0
        for row in rows:
            model_name = row[0]
            provider_name = model_provider_map.get(model_name, "unknown")

            cursor.execute(
                "UPDATE daily_model_usage SET provider_name = ? WHERE model_name = ?",
                (provider_name, model_name),
            )
            print(f"  {model_name} -> {provider_name}")
            updated_count += 1

        print(f"daily_model_usage 更新了 {updated_count} 个模型的记录")

        conn.commit()
        print("\n✅ 迁移完成！")
        return True

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 迁移失败: {e}")
        return False

    finally:
        conn.close()


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
