import chromadb
import os
import argparse
import sqlite3
from src.chat.config import chat_config
from src import config as app_config # 仍然需要它来获取 SQLite 路径

# --- 配置 ---
# 使用与主程序完全相同的配置源
CHROMA_DB_PATH = chat_config.VECTOR_DB_PATH
COLLECTION_NAME = chat_config.VECTOR_DB_COLLECTION_NAME
SQLITE_DB_PATH = os.path.join(app_config.DATA_DIR, 'world_book.sqlite3')
TABLES_TO_CLEAR = ["general_knowledge", "pending_entries", "community_members"]

# --- 连接 ChromaDB ---
try:
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    print(f"✅ 成功连接到 ChromaDB")
    print(f"   - 数据库路径: {CHROMA_DB_PATH}")
except Exception as e:
    print(f"❌ 连接 ChromaDB 失败: {e}")
    exit()

# --- 功能函数 ---
def query_all_data():
    """获取并打印集合中的所有数据"""
    try:
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        print(f"✅ 成功获取集合 '{COLLECTION_NAME}'")
        print(f"   - 集合中共有 {collection.count()} 个条目")
        print("-" * 30)

        results = collection.get(include=["metadatas", "documents"])
        
        if not results or not results['ids']:
            print("ℹ️  集合中没有数据。")
            return

        print(f"🔍 集合 '{COLLECTION_NAME}' 中的所有数据 ({len(results['ids'])} 条):")
        for i, item_id in enumerate(results['ids']):
            doc = results['documents'][i]
            meta = results['metadatas'][i]
            print(f"\n--- 条目 ID: {item_id} ---")
            print(f"  📄 文档内容: {doc}")
            print(f"  🏷️ 元数据: {meta}")
        
    except Exception as e:
        print(f"❌ 查询数据时出错: {e}")

def clear_collection():
    """清空指定的集合"""
    try:
        print(f"⚠️  警告: 即将删除并重建集合 '{COLLECTION_NAME}'...")
        client.delete_collection(name=COLLECTION_NAME)
        new_collection = client.create_collection(name=COLLECTION_NAME)
        print(f"✅ 成功清空并重建集合 '{COLLECTION_NAME}'。")
        print(f"   - 当前集合中共有 {new_collection.count()} 个条目。")
    except Exception as e:
        # 如果集合不存在，删除会报错，这是正常的。我们直接尝试创建。
        try:
            print(f"ℹ️  集合 '{COLLECTION_NAME}' 可能不存在，尝试直接创建...")
            client.create_collection(name=COLLECTION_NAME)
            print(f"✅ 成功创建新集合 '{COLLECTION_NAME}'。")
        except Exception as inner_e:
            print(f"❌ 清空或创建集合时出错: {inner_e}")

def clear_sqlite_tables():
    """清空 SQLite 数据库中的指定表"""
    try:
        print("\n--- 正在清空 SQLite 数据表 ---")
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        print(f"✅ 成功连接到 SQLite 数据库: {SQLITE_DB_PATH}")

        for table in TABLES_TO_CLEAR:
            try:
                print(f"   - 正在清空数据表 '{table}'...")
                cursor.execute(f"DELETE FROM {table};")
                # 可选：重置自增ID (适用于 SQLite)
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}';")
                conn.commit()
                print(f"   ✅ 成功清空 '{table}'。")
            except sqlite3.Error as e:
                print(f"   ❌ 清空表 '{table}' 时出错: {e}")
        
        conn.close()
    except sqlite3.Error as e:
        print(f"❌ 操作 SQLite 数据库时出错: {e}")


# --- 主程序 ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChromaDB 和 SQLite 数据清理脚本")
    parser.add_argument(
        '--clear-chroma',
        action='store_true',
        help=f"仅清空并重建 ChromaDB 的 '{COLLECTION_NAME}' 集合"
    )
    parser.add_argument(
        '--clear-sqlite',
        action='store_true',
        help=f"仅清空 SQLite 数据库中的指定数据表"
    )
    parser.add_argument(
        '--clear-all',
        action='store_true',
        help="同时清空 ChromaDB 集合和 SQLite 数据表"
    )
    args = parser.parse_args()

    if args.clear_all:
        clear_collection()
        clear_sqlite_tables()
    elif args.clear_chroma:
        clear_collection()
    elif args.clear_sqlite:
        clear_sqlite_tables()
    else:
        query_all_data()


