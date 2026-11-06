# -*- coding: utf-8 -*-
"""
测试故障转移时工具消息格式转换

模拟场景：
1. Gemini 返回 429 RESOURCE_EXHAUSTED 错误
2. 系统故障转移到 DeepSeek
3. 验证工具调用消息格式是否正确转换

问题根源：
- Gemini 使用 genai_types.Content 对象存储对话历史
- 当故障转移到 DeepSeek 时，这些对象需要被正确转换为 OpenAI 格式
- 特别是工具调用消息需要包含 tool_call_id 字段

运行方式：
    python scripts/test_fallback_tool_conversion.py
"""

import asyncio
import json
import logging
import sys
import os
from typing import Dict, Any, List, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


def create_mock_gemini_content_with_tool_call():
    """创建模拟的 Gemini Content 对象（包含工具调用）"""
    from google.genai import types as genai_types

    function_call = genai_types.FunctionCall(
        name="get_user_profile",
        args={"user_id": "12345"},
    )
    part = genai_types.Part(function_call=function_call)
    content = genai_types.Content(parts=[part], role="model")
    return content


def create_mock_gemini_content_with_tool_response():
    """创建模拟的 Gemini Content 对象（包含工具响应）"""
    from google.genai import types as genai_types

    function_response = genai_types.FunctionResponse(
        name="get_user_profile",
        response={"result": {"name": "测试用户", "level": 5}},
    )
    part = genai_types.Part(function_response=function_response)
    content = genai_types.Content(parts=[part], role="user")
    return content


def create_mock_conversation_history_with_gemini_objects():
    """创建包含 Gemini 原生对象的对话历史"""
    history = []

    # 1. 用户消息
    history.append({"role": "user", "content": "请查询用户12345的信息"})

    # 2. 模型的工具调用（Gemini Content 对象）
    history.append(create_mock_gemini_content_with_tool_call())

    # 3. 工具响应（Gemini Content 对象）
    history.append(create_mock_gemini_content_with_tool_response())

    # 4. 模型的文本回复
    history.append(
        {"role": "model", "content": "用户12345的信息如下：姓名是测试用户，等级是5级。"}
    )

    # 5. 用户继续提问
    history.append({"role": "user", "content": "这个用户的等级是多少？"})

    return history


class TestDeepSeekMessageConversion:
    """测试 DeepSeek Provider 的消息转换"""

    def __init__(self):
        from src.chat.services.ai.providers.deepseek_provider import DeepSeekProvider

        self.provider = DeepSeekProvider(api_key="test_key", provider_name="deepseek")

    def test_convert_gemini_content_with_tool_call(self):
        """测试转换包含工具调用的 Gemini Content 对象"""
        log.info("=" * 60)
        log.info("测试：转换包含工具调用的 Gemini Content 对象")
        log.info("=" * 60)

        gemini_content = create_mock_gemini_content_with_tool_call()
        result = self.provider._convert_gemini_content_object(gemini_content)

        log.info(f"转换结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

        assert result is not None, "转换结果不应为 None"
        assert result["role"] == "assistant", (
            f"角色应为 assistant，实际为 {result['role']}"
        )
        assert "tool_calls" in result, "应包含 tool_calls 字段"
        assert len(result["tool_calls"]) > 0, "tool_calls 不应为空"

        tool_call = result["tool_calls"][0]
        assert "id" in tool_call, "tool_call 应包含 id 字段"
        assert "type" in tool_call, "tool_call 应包含 type 字段"
        assert "function" in tool_call, "tool_call 应包含 function 字段"

        log.info("✅ 测试通过：Gemini 工具调用转换正确")
        return True

    def test_convert_gemini_content_with_tool_response(self):
        """测试转换包含工具响应的 Gemini Content 对象"""
        log.info("\n" + "=" * 60)
        log.info("测试：转换包含工具响应的 Gemini Content 对象")
        log.info("=" * 60)

        gemini_content = create_mock_gemini_content_with_tool_response()
        result = self.provider._convert_gemini_content_object(gemini_content)

        log.info(f"转换结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

        assert result is not None, "转换结果不应为 None"
        assert result["role"] == "tool", f"角色应为 tool，实际为 {result['role']}"
        assert "tool_call_id" in result, "应包含 tool_call_id 字段"
        assert "content" in result, "应包含 content 字段"

        log.info("✅ 测试通过：Gemini 工具响应转换正确")
        return True

    def test_convert_full_conversation_history(self):
        """测试转换完整的对话历史"""
        log.info("\n" + "=" * 60)
        log.info("测试：转换完整的对话历史")
        log.info("=" * 60)

        history = create_mock_conversation_history_with_gemini_objects()
        converted = self.provider._convert_messages_to_openai_format(history)

        log.info(f"原始历史长度: {len(history)}, 转换后长度: {len(converted)}")

        for i, msg in enumerate(converted):
            role = msg.get("role")
            log.info(f"消息 {i + 1}: role={role}")

            if role == "tool":
                if "tool_call_id" not in msg:
                    log.error(f"❌ 工具消息缺少 tool_call_id: {msg}")
                    return False
                log.info(f"  tool_call_id: {msg['tool_call_id']}")
            elif role == "assistant" and "tool_calls" in msg:
                for call in msg["tool_calls"]:
                    if "id" not in call:
                        log.error(f"❌ 工具调用缺少 id: {call}")
                        return False
                    log.info(f"  tool_call id: {call['id']}")

        log.info("✅ 测试通过：完整对话历史转换正确")
        return True

    def test_missing_tool_call_id_bug(self):
        """测试原始 Bug：缺少 tool_call_id"""
        log.info("\n" + "=" * 60)
        log.info("测试：验证 Bug 修复 - tool_call_id 字段")
        log.info("=" * 60)

        gemini_response = create_mock_gemini_content_with_tool_response()
        converted = self.provider._convert_gemini_content_object(gemini_response)

        if converted and "tool_call_id" in converted:
            log.info(
                f"✅ 修复验证通过：转换后的消息包含 tool_call_id: {converted['tool_call_id']}"
            )
            return True
        else:
            log.error(f"❌ 修复验证失败：转换后的消息缺少 tool_call_id: {converted}")
            return False

    def run_all_tests(self):
        """运行所有测试"""
        log.info("\n" + "=" * 60)
        log.info("开始运行故障转移工具转换测试")
        log.info("=" * 60)

        results = []

        try:
            results.append(
                ("工具调用转换", self.test_convert_gemini_content_with_tool_call())
            )
        except Exception as e:
            log.error(f"❌ 工具调用转换测试失败: {e}")
            results.append(("工具调用转换", False))

        try:
            results.append(
                ("工具响应转换", self.test_convert_gemini_content_with_tool_response())
            )
        except Exception as e:
            log.error(f"❌ 工具响应转换测试失败: {e}")
            results.append(("工具响应转换", False))

        try:
            results.append(
                ("完整历史转换", self.test_convert_full_conversation_history())
            )
        except Exception as e:
            log.error(f"❌ 完整历史转换测试失败: {e}")
            results.append(("完整历史转换", False))

        try:
            results.append(("Bug 修复验证", self.test_missing_tool_call_id_bug()))
        except Exception as e:
            log.error(f"❌ Bug 修复验证失败: {e}")
            results.append(("Bug 修复验证", False))

        # 打印总结
        log.info("\n" + "=" * 60)
        log.info("测试结果总结")
        log.info("=" * 60)

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for name, result in results:
            status = "✅ 通过" if result else "❌ 失败"
            log.info(f"  {name}: {status}")

        log.info(f"\n总计: {passed}/{total} 测试通过")

        return passed == total


async def test_fallback_scenario_mock():
    """模拟完整的故障转移场景"""
    log.info("\n" + "=" * 60)
    log.info("模拟完整故障转移场景")
    log.info("=" * 60)

    from src.chat.services.ai.providers.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test_key", provider_name="deepseek")

    # 模拟从 Gemini 对话中获取的历史
    gemini_history = create_mock_conversation_history_with_gemini_objects()

    log.info(f"原始对话历史长度: {len(gemini_history)}")
    log.info("原始历史包含 Gemini 原生 Content 对象")

    # 转换为 DeepSeek 兼容格式
    converted_history = provider._convert_messages_to_openai_format(gemini_history)

    log.info(f"\n转换后历史长度: {len(converted_history)}")

    # 验证所有消息都是有效格式
    for i, msg in enumerate(converted_history):
        role = msg.get("role")
        log.info(f"\n消息 {i + 1}: role={role}")

        if role == "tool":
            if "tool_call_id" not in msg:
                log.error(f"❌ 工具消息缺少 tool_call_id: {msg}")
                return False
            log.info(f"  tool_call_id: {msg['tool_call_id']}")
        elif role == "assistant" and "tool_calls" in msg:
            for call in msg["tool_calls"]:
                if "id" not in call:
                    log.error(f"❌ 工具调用缺少 id: {call}")
                    return False
                log.info(f"  tool_call id: {call['id']}")

    # 构建请求体
    request_body = {
        "model": "deepseek-chat",
        "messages": converted_history,
    }

    log.info("\n构建的 API 请求体（消息部分）:")
    log.info(json.dumps(request_body["messages"], ensure_ascii=False, indent=2))

    # 验证请求体可以被 JSON 序列化
    try:
        json.dumps(request_body, ensure_ascii=False)
        log.info("\n✅ 请求体可以成功序列化为 JSON")
    except Exception as e:
        log.error(f"\n❌ 请求体序列化失败: {e}")
        return False

    # 模拟 DeepSeek API 验证
    for i, msg in enumerate(converted_history):
        if msg.get("role") == "tool":
            if not msg.get("tool_call_id"):
                log.error(f"\n❌ DeepSeek API 会拒绝：消息 {i} 缺少 tool_call_id")
                return False

    log.info("\n✅ 所有消息格式正确，DeepSeek API 应该能接受")
    log.info("✅ 故障转移场景测试通过")

    return True


def main():
    """主函数"""
    log.info("=" * 60)
    log.info("故障转移工具转换测试脚本")
    log.info("=" * 60)
    log.info("")
    log.info("此脚本用于测试 Gemini -> DeepSeek 故障转移时的工具消息格式转换")
    log.info("原始错误: missing field `tool_call_id`")
    log.info("")

    # 运行同步测试
    tester = TestDeepSeekMessageConversion()
    sync_passed = tester.run_all_tests()

    # 运行异步测试
    loop = asyncio.get_event_loop()
    async_passed = loop.run_until_complete(test_fallback_scenario_mock())

    # 最终结果
    log.info("\n" + "=" * 60)
    log.info("最终结果")
    log.info("=" * 60)

    if sync_passed and async_passed:
        log.info("✅ 所有测试通过！故障转移工具转换功能正常。")
        return 0
    else:
        log.error("❌ 部分测试失败，请检查上述日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
