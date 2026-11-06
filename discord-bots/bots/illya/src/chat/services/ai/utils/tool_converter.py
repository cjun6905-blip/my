# -*- coding: utf-8 -*-
"""
工具格式转换器

在不同的 AI Provider 之间转换工具声明格式。
支持 Gemini、OpenAI、Claude 等格式。
"""

import logging
from typing import Any, Dict, List, Union

# 导入 Google Gemini types（用于 Gemini 格式转换）
from google.genai import types as genai_types

# 导入通用工具声明
from src.chat.features.tools.tool_declaration import ToolDeclaration
from src.chat.services.ai.providers.provider_format import ProviderFormat

log = logging.getLogger(__name__)


class ToolConverter:
    """
    工具格式转换器

    在不同的 AI Provider 之间转换工具声明格式。
    支持以下格式：
    - Gemini: google.genai.types.Tool
    - OpenAI: OpenAI Function Calling 格式
    - Claude: Claude Tools 格式
    - 通用: ToolDeclaration
    """

    # ==================== Gemini 格式转换 ====================

    @staticmethod
    def to_gemini_tool(declaration: ToolDeclaration) -> genai_types.Tool:
        """
        将 ToolDeclaration 转换为 Gemini Tool 格式

        Args:
            declaration: 通用工具声明

        Returns:
            genai_types.Tool: Gemini 格式的工具
        """
        # 构建 FunctionDeclaration
        function_declaration = genai_types.FunctionDeclaration(
            name=declaration.name,
            description=declaration.description,
            parameters=ToolConverter._convert_schema_to_gemini(declaration.parameters),  # type: ignore
        )

        return genai_types.Tool(function_declarations=[function_declaration])

    @staticmethod
    def to_gemini_tools(declarations: List[ToolDeclaration]) -> List[genai_types.Tool]:
        """
        批量转换为 Gemini Tool 格式

        Args:
            declarations: 通用工具声明列表

        Returns:
            List[genai_types.Tool]: Gemini 格式的工具列表
        """
        return [ToolConverter.to_gemini_tool(d) for d in declarations]

    @staticmethod
    def _convert_schema_to_gemini(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 JSON Schema 转换为 Gemini 兼容格式

        Gemini 对 schema 有一些特殊要求：
        1. 不支持某些 JSON Schema 关键字
        2. 需要特定的格式

        Args:
            schema: 标准 JSON Schema

        Returns:
            Dict: Gemini 兼容的 schema
        """
        # Gemini 基本兼容标准 JSON Schema，但需要清理一些不支持的属性
        result = {}

        if "type" in schema:
            result["type"] = schema["type"]

        if "description" in schema:
            result["description"] = schema["description"]

        if "properties" in schema:
            result["properties"] = {}
            for key, value in schema["properties"].items():
                result["properties"][key] = ToolConverter._convert_schema_to_gemini(
                    value
                )

        if "required" in schema:
            result["required"] = schema["required"]

        if "enum" in schema:
            result["enum"] = schema["enum"]

        if "items" in schema:
            result["items"] = ToolConverter._convert_schema_to_gemini(schema["items"])

        # 处理嵌套的 additionalProperties（用于 dict 类型）
        if "additionalProperties" in schema:
            additional = schema["additionalProperties"]
            if isinstance(additional, dict):
                result["additionalProperties"] = (
                    ToolConverter._convert_schema_to_gemini(additional)
                )

        return result

    # ==================== OpenAI 格式转换 ====================

    @staticmethod
    def to_openai_tool(declaration: ToolDeclaration) -> Dict[str, Any]:
        """
        将 ToolDeclaration 转换为 OpenAI Tool 格式

        注意：工具格式应该在 ToolService 层根据 provider_type 处理好。
        此方法主要用于向后兼容或特殊情况。

        Args:
            declaration: 通用工具声明

        Returns:
            Dict: OpenAI 格式的工具
        """
        return declaration.to_openai_format()

    @staticmethod
    def to_openai_tools(declarations: List[ToolDeclaration]) -> List[Dict[str, Any]]:
        """
        批量转换为 OpenAI Tool 格式

        注意：工具格式应该在 ToolService 层根据 provider_type 处理好。
        此方法主要用于向后兼容或特殊情况。

        Args:
            declarations: 通用工具声明列表

        Returns:
            List[Dict]: OpenAI 格式的工具列表
        """
        return [ToolConverter.to_openai_tool(d) for d in declarations]

    # ==================== Claude 格式转换 ====================

    @staticmethod
    def to_claude_tool(declaration: ToolDeclaration) -> Dict[str, Any]:
        """
        将 ToolDeclaration 转换为 Claude Tool 格式

        Args:
            declaration: 通用工具声明

        Returns:
            Dict: Claude 格式的工具
        """
        return declaration.to_claude_format()

    @staticmethod
    def to_claude_tools(declarations: List[ToolDeclaration]) -> List[Dict[str, Any]]:
        """
        批量转换为 Claude Tool 格式

        Args:
            declarations: 通用工具声明列表

        Returns:
            List[Dict]: Claude 格式的工具列表
        """
        return [ToolConverter.to_claude_tool(d) for d in declarations]

    # ==================== 工具调用结果转换 ====================

    @staticmethod
    def tool_result_to_gemini_part(
        tool_name: str, result: Dict[str, Any], is_error: bool = False
    ) -> genai_types.Part:
        """
        将工具执行结果转换为 Gemini Part 格式

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            is_error: 是否是错误结果

        Returns:
            genai_types.Part: Gemini 格式的 Part
        """
        if is_error:
            response = {"error": result.get("error", "Unknown error")}
        else:
            response = {"result": result}

        return genai_types.Part.from_function_response(
            name=tool_name,
            response=response,
        )

    @staticmethod
    def _serialize_for_json(obj: Any) -> Any:
        """
        递归转换对象为 JSON 可序列化格式

        处理 Gemini Part 对象等特殊类型
        """
        if obj is None:
            return None
        elif isinstance(obj, str | int | float | bool):
            return obj
        elif isinstance(obj, genai_types.Part):
            # Gemini Part 对象转换为文本
            if hasattr(obj, "text") and obj.text:
                return obj.text
            elif hasattr(obj, "function_response"):
                return {
                    "function_response": {
                        "name": getattr(obj.function_response, "name", ""),
                        "response": dict(
                            getattr(obj.function_response, "response", {})
                        ),
                    }
                }
            elif hasattr(obj, "function_call"):
                return {
                    "function_call": {
                        "name": getattr(obj.function_call, "name", ""),
                        "args": dict(getattr(obj.function_call, "args", {})),
                    }
                }
            return str(obj)
        elif isinstance(obj, dict):
            return {k: ToolConverter._serialize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ToolConverter._serialize_for_json(item) for item in obj]
        elif hasattr(obj, "__dict__"):
            # 其他对象尝试转换为字典
            return {
                k: ToolConverter._serialize_for_json(v)
                for k, v in vars(obj).items()
                if not k.startswith("_")
            }
        else:
            return str(obj)

    @staticmethod
    def tool_result_to_openai_message(
        tool_call_id: str,
        tool_name: str,
        result: Dict[str, Any],
        is_error: bool = False,
    ) -> Dict[str, Any]:
        """
        将工具执行结果转换为 OpenAI 消息格式

        Args:
            tool_call_id: 工具调用 ID
            tool_name: 工具名称
            result: 工具执行结果
            is_error: 是否是错误结果

        Returns:
            Dict: OpenAI 格式的工具结果消息
        """
        import json

        # 先转换结果中的非 JSON 可序列化对象
        serializable_result = ToolConverter._serialize_for_json(result)

        if is_error:
            content = json.dumps(
                {"error": serializable_result.get("error", "Unknown error")},
                ensure_ascii=False,
            )
        else:
            content = json.dumps(serializable_result, ensure_ascii=False)

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content,
        }

    # ==================== 工具调用解析 ====================

    @staticmethod
    def parse_gemini_function_calls(
        response: genai_types.GenerateContentResponse,
    ) -> List[Dict[str, Any]]:
        """
        从 Gemini 响应中解析函数调用

        Args:
            response: Gemini 响应对象

        Returns:
            List[Dict]: 函数调用列表，每个包含 name 和 args
        """
        function_calls = []

        if hasattr(response, "function_calls") and response.function_calls:
            for call in response.function_calls:
                function_calls.append(
                    {
                        "id": getattr(call, "id", None),
                        "name": call.name,
                        "arguments": dict(call.args) if call.args else {},
                    }
                )

        return function_calls

    @staticmethod
    def parse_openai_function_calls(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从 OpenAI 响应中解析函数调用

        Args:
            response: OpenAI 响应对象

        Returns:
            List[Dict]: 函数调用列表，每个包含 id、name 和 arguments
        """
        import json

        function_calls = []

        message = response.get("choices", [{}])[0].get("message", {})
        tool_calls = message.get("tool_calls") or []

        for call in tool_calls:
            if call.get("type") == "function":
                function_info = call.get("function", {})
                arguments_str = function_info.get("arguments", "{}")

                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError:
                    arguments = {}

                function_calls.append(
                    {
                        "id": call.get("id"),
                        "name": function_info.get("name"),
                        "arguments": arguments,
                    }
                )

        return function_calls

    # ==================== Schema 格式转换 ====================

    @staticmethod
    def convert_schema_to_openai_format(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 Gemini 格式的 Schema 转换为 OpenAI 兼容格式

        主要转换：
        - 类型名大写 -> 小写 (STRING -> string, OBJECT -> object)
        - any_of -> anyOf
        - 移除 Gemini 特有字段

        Args:
            schema: Gemini 格式的 Schema

        Returns:
            Dict: OpenAI 兼容格式的 Schema
        """
        if not isinstance(schema, dict):
            return schema

        result = {}

        # 类型名映射（大写 -> 小写）
        type_map = {
            "STRING": "string",
            "INTEGER": "integer",
            "NUMBER": "number",
            "BOOLEAN": "boolean",
            "ARRAY": "array",
            "OBJECT": "object",
        }

        # 转换 type 字段
        if "type" in schema:
            schema_type = schema["type"]
            if isinstance(schema_type, str):
                result["type"] = type_map.get(schema_type, schema_type.lower())
            else:
                result["type"] = schema_type

        # 复制标准字段
        for key in ["description", "default", "enum", "required", "nullable"]:
            if key in schema:
                result[key] = schema[key]

        # 转换 any_of -> anyOf
        if "any_of" in schema:
            result["anyOf"] = [
                ToolConverter.convert_schema_to_openai_format(item)
                for item in schema["any_of"]
            ]

        # 处理 anyOf（已经是小写格式）
        if "anyOf" in schema:
            result["anyOf"] = [
                ToolConverter.convert_schema_to_openai_format(item)
                for item in schema["anyOf"]
            ]

        # 递归处理 properties
        if "properties" in schema:
            result["properties"] = {}
            for key, value in schema["properties"].items():
                result["properties"][key] = (
                    ToolConverter.convert_schema_to_openai_format(value)
                )

        # 递归处理 items
        if "items" in schema:
            result["items"] = ToolConverter.convert_schema_to_openai_format(
                schema["items"]
            )

        # 递归处理 additionalProperties
        if "additionalProperties" in schema:
            result["additionalProperties"] = (
                ToolConverter.convert_schema_to_openai_format(
                    schema["additionalProperties"]
                )
            )

        return result

    # ==================== 通用转换方法 ====================

    @staticmethod
    def convert_for_provider(
        declarations: List[ToolDeclaration], provider_type: str
    ) -> Union[List[genai_types.Tool], List[Dict[str, Any]]]:
        """
        根据 Provider 类型自动转换工具声明

        Args:
            declarations: 通用工具声明列表
            provider_type: Provider 类型 (gemini, openai, deepseek, claude 等)

        Returns:
            转换后的工具列表
        """
        # 使用统一的 ProviderFormat 判断工具类型
        if ProviderFormat.is_gemini_provider(provider_type.lower()):
            return ToolConverter.to_gemini_tools(declarations)
        elif provider_type.lower() in ["claude"]:
            return ToolConverter.to_claude_tools(declarations)
        else:
            # OpenAI 兼容 Provider（包括 deepseek, openai_compatible）和未知类型
            if not ProviderFormat.is_openai_compatible_provider(provider_type.lower()):
                log.warning(f"未知的 Provider 类型 '{provider_type}'，使用 OpenAI 格式")
            return ToolConverter.to_openai_tools(declarations)
