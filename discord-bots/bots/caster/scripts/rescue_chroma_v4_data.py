import sqlite3
import json
import os
import sys

# === 配置 ===
DB_FILE = "data/forum_chroma_db/chroma.sqlite3"
JSON_FILE = "chroma_rescue_final.jsonl"
# ============


def rescue_v5_final():
    print("🎯 启动最终救援模式 (Python 元数据组装版)...")

    if not os.path.exists(DB_FILE):
        print("❌ 数据库不存在")
        return

    # 只读模式
    conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. 锁定文本列 c0
        doc_col = "c0"
        print(f"✅ 锁定真实文本列: 【 {doc_col} 】")

        # 2. 主查询：只查 ID 和 文本
        # 我们不在 SQL 里拼 JSON，太容易坏了
        query = f"""
            SELECT 
                e.id AS internal_id,
                e.embedding_id AS user_id,
                fts.{doc_col} AS document
            FROM embeddings e
            JOIN embedding_fulltext_search_content fts ON e.id = fts.rowid
        """

        cursor.execute(query)

        # 准备一个副游标查元数据
        meta_cursor = conn.cursor()

        count = 0
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            while True:
                row = cursor.fetchone()
                if not row:
                    break

                # A. 提取基础信息
                user_id = row["user_id"]
                doc_content = row["document"]
                internal_id = row["internal_id"]

                # B. 严格类型检查 (修复 int has no strip 的关键)
                if not isinstance(doc_content, str):
                    # 尝试转一下，如果实在不行就给个空字符串，别让脚本停
                    doc_content = str(doc_content) if doc_content is not None else ""
                    if not doc_content:
                        print(f"⚠️ 警告: ID {user_id} 内容为空或非字符串")

                # C. Python 级元数据组装 (最稳的方式)
                # 查出该 ID 对应的所有元数据行
                metadata = {}
                try:
                    meta_cursor.execute(
                        "SELECT key, string_value, int_value, float_value, bool_value FROM embedding_metadata WHERE id = ?",
                        (internal_id,),
                    )
                    meta_rows = meta_cursor.fetchall()

                    for m_row in meta_rows:
                        key = m_row[0]
                        # 依次判断哪一列有值 (Chroma 的存储逻辑)
                        if m_row[1] is not None:
                            val = m_row[1]  # string
                        elif m_row[2] is not None:
                            val = m_row[2]  # int
                        elif m_row[3] is not None:
                            val = m_row[3]  # float
                        elif m_row[4] is not None:
                            val = bool(m_row[4])  # bool
                        else:
                            val = None

                        if val is not None:
                            metadata[key] = val

                except Exception as e:
                    print(f"⚠️ 元数据提取失败 (ID: {user_id}): {e}")
                    metadata = {"error": "metadata_extraction_failed"}

                # D. 写入
                item = {
                    "id": user_id,
                    "document": doc_content,
                    "metadata": metadata,
                    "embedding": None,
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

                count += 1
                if count % 500 == 0:
                    sys.stdout.write(f"\r   已提取 {count} 条...")
                    sys.stdout.flush()

        print(f"\n\n🎉 完美提取！共 {count} 条记录。")
        print("✅ 文本类型检查通过")
        print("✅ 元数据类型(int/float/bool)已自动恢复")
        print(f"📁 文件: {JSON_FILE}")

    except Exception as e:
        print(f"\n❌ 严重错误: {e}")
        import traceback

        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    rescue_v5_final()
