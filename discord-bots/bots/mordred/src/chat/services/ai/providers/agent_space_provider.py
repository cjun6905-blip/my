# -*- coding: utf-8 -*-
"""Agent.Space provider using its advertised Responses/Anthropic protocols."""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .base import (
    FinishReason,
    GenerationConfig,
    GenerationError,
    GenerationResult,
    ProviderNotAvailableError,
)
from .openai_provider import OpenAICompatibleProvider

log = logging.getLogger(__name__)


class AgentSpaceProvider(OpenAICompatibleProvider):
    """Route each Agent.Space model through its live advertised protocol."""

    provider_type = "openai_compatible"

    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        provider_name: str,
        models: Optional[List[str]] = None,
        default_model: Optional[str] = None,
        model_protocols: Optional[Dict[str, List[str]]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            provider_name=provider_name,
            models=models,
            default_model=default_model,
        )
        self.model_protocols = model_protocols or {}
        self._anthropic_client: Optional[httpx.AsyncClient] = None
        log.info(
            "AgentSpaceProvider '%s' initialized with %d protocol mappings",
            provider_name,
            len(self.model_protocols),
        )

    def _protocol_for_model(self, model: str) -> str:
        protocols = self.model_protocols.get(model, [])
        if isinstance(protocols, str):
            protocols = [protocols]
        if "openai.responses" in protocols:
            return "openai.responses"
        if "anthropic.messages" in protocols:
            return "anthropic.messages"
        if "openai.images" in protocols:
            return "openai.images"

        # Safe compatibility fallback for old records without discovery metadata.
        if model.startswith("claude-") or model.startswith("glm-"):
            return "anthropic.messages"
        if model.startswith("gpt-image-"):
            return "openai.images"
        return "openai.responses"

    @staticmethod
    def _tool_name_and_schema(tool: Any) -> Tuple[str, str, Dict[str, Any]]:
        if not isinstance(tool, dict):
            raise ValueError(f"Unsupported tool declaration: {type(tool)!r}")
        function = tool.get("function", tool)
        name = str(function.get("name", "")).strip()
        if not name:
            raise ValueError("Tool declaration is missing a name")
        description = str(function.get("description", ""))
        parameters = function.get("parameters") or function.get("input_schema") or {
            "type": "object",
            "properties": {},
        }
        return name, description, parameters

    def _responses_tools(self, tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
        result = []
        for tool in tools or []:
            name, description, parameters = self._tool_name_and_schema(tool)
            result.append(
                {
                    "type": "function",
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                }
            )
        return result

    def _anthropic_tools(self, tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
        result = []
        for tool in tools or []:
            name, description, parameters = self._tool_name_and_schema(tool)
            result.append(
                {
                    "name": name,
                    "description": description,
                    "input_schema": parameters,
                }
            )
        return result

    @staticmethod
    def _json_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    def _responses_input(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted = self._convert_messages_to_openai_format(messages)
        result: List[Dict[str, Any]] = []
        for message in converted:
            role = message.get("role", "user")
            content = message.get("content", "")

            if role == "tool":
                result.append(
                    {
                        "role": "user",
                        "content": (
                            f"Tool result ({message.get('name', 'tool')}): "
                            f"{self._json_text(content)}"
                        ),
                    }
                )
                continue

            if isinstance(content, list):
                parts: List[Dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        parts.append({"type": "input_text", "text": str(part)})
                        continue
                    part_type = part.get("type")
                    if part_type == "text":
                        parts.append(
                            {"type": "input_text", "text": str(part.get("text", ""))}
                        )
                    elif part_type == "image_url":
                        image = part.get("image_url", {})
                        url = image.get("url", "") if isinstance(image, dict) else image
                        if url:
                            parts.append({"type": "input_image", "image_url": url})
                content = parts or ""

            result.append({"role": role, "content": content or ""})
        return result

    def _anthropic_messages(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        converted = self._convert_messages_to_openai_format(messages)
        system_parts: List[str] = []
        result: List[Dict[str, Any]] = []

        def append(role: str, content: Any) -> None:
            if result and result[-1]["role"] == role:
                previous = result[-1]["content"]
                if isinstance(previous, str) and isinstance(content, str):
                    result[-1]["content"] = previous + "\n\n" + content
                else:
                    if isinstance(previous, str):
                        previous = [{"type": "text", "text": previous}]
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    result[-1]["content"] = list(previous) + list(content)
            else:
                result.append({"role": role, "content": content})

        for message in converted:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role in ("system", "developer"):
                system_parts.append(self._json_text(content))
                continue

            if role == "tool":
                append(
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id", ""),
                            "content": self._json_text(content),
                        }
                    ],
                )
                continue

            blocks: Any = content
            if isinstance(content, list):
                blocks = []
                for part in content:
                    if not isinstance(part, dict):
                        blocks.append({"type": "text", "text": str(part)})
                        continue
                    part_type = part.get("type")
                    if part_type == "text":
                        blocks.append({"type": "text", "text": str(part.get("text", ""))})
                    elif part_type == "image_url":
                        image = part.get("image_url", {})
                        url = image.get("url", "") if isinstance(image, dict) else image
                        if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                            header, data = url.split(",", 1)
                            media_type = header[5:].split(";", 1)[0]
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": data,
                                    },
                                }
                            )
                        elif url:
                            blocks.append(
                                {"type": "image", "source": {"type": "url", "url": url}}
                            )

            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                if isinstance(blocks, str):
                    blocks = ([{"type": "text", "text": blocks}] if blocks else [])
                for call in tool_calls:
                    function = call.get("function", call)
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except Exception:
                            arguments = {"raw": arguments}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id", ""),
                            "name": function.get("name", ""),
                            "input": arguments,
                        }
                    )

            append("assistant" if role == "assistant" else "user", blocks or "")

        return "\n\n".join(x for x in system_parts if x), result

    def _safe_http_error(self, response: httpx.Response) -> str:
        text = response.text[:1000]
        if self.api_key:
            text = text.replace(self.api_key, "[REDACTED]")
        return f"HTTP {response.status_code}: {text}"

    def _get_anthropic_client(self) -> httpx.AsyncClient:
        if self._anthropic_client is None:
            self._anthropic_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key or "",
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._anthropic_client

    async def _post(self, path: str, body: Dict[str, Any], anthropic: bool = False) -> Dict[str, Any]:
        client = self._get_anthropic_client() if anthropic else self._get_client()
        response = await client.post(path, json=body)
        if response.is_error:
            raise GenerationError(
                f"Agent.Space API error ({self._safe_http_error(response)})",
                provider_type=self.provider_type,
            )
        try:
            return response.json()
        except Exception as exc:
            raise GenerationError(
                "Agent.Space returned a non-JSON response",
                provider_type=self.provider_type,
                original_error=exc,
            ) from exc

    async def _responses_request(
        self,
        model: str,
        input_items: Any,
        config: GenerationConfig,
        tools: Optional[List[Any]],
        previous_response_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model,
            "input": input_items,
            "max_output_tokens": config.max_output_tokens,
        }
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        converted_tools = self._responses_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools
        return await self._post("responses", body)

    async def _anthropic_request(
        self,
        model: str,
        system: str,
        messages: List[Dict[str, Any]],
        config: GenerationConfig,
        tools: Optional[List[Any]],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "temperature": config.temperature,
        }
        if system:
            body["system"] = system
        if config.stop_sequences:
            body["stop_sequences"] = config.stop_sequences
        converted_tools = self._anthropic_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools
        return await self._post("messages", body, anthropic=True)

    @staticmethod
    def _responses_result(data: Dict[str, Any], model: str) -> GenerationResult:
        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                arguments = item.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except Exception:
                        arguments = {"raw": arguments}
                tool_calls.append(
                    {
                        "id": item.get("call_id") or item.get("id") or "",
                        "name": item.get("name", ""),
                        "arguments": arguments,
                    }
                )
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    text_parts.append(str(part.get("text", "")))
        usage = data.get("usage") or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        finish = FinishReason.TOOL_CALL if tool_calls else FinishReason.STOP
        if data.get("status") == "incomplete" and not tool_calls:
            finish = FinishReason.MAX_TOKENS
        return GenerationResult(
            content="".join(text_parts),
            model_used=model,
            tokens_used=usage.get("total_tokens") or (input_tokens or 0) + (output_tokens or 0),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish,
            tool_calls=tool_calls or None,
            raw_response=data,
        )

    @staticmethod
    def _anthropic_result(data: Dict[str, Any], model: str) -> GenerationResult:
        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for block in data.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input") or {},
                    }
                )
        usage = data.get("usage") or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        reason = data.get("stop_reason")
        finish = FinishReason.TOOL_CALL if tool_calls else FinishReason.STOP
        if reason == "max_tokens" and not tool_calls:
            finish = FinishReason.MAX_TOKENS
        return GenerationResult(
            content="".join(text_parts),
            model_used=model,
            tokens_used=(input_tokens or 0) + (output_tokens or 0),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish,
            tool_calls=tool_calls or None,
            raw_response=data,
        )

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        config: Optional[GenerationConfig] = None,
        tools: Optional[List[Any]] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> GenerationResult:
        if not self.api_key:
            raise ProviderNotAvailableError("Agent.Space API key is not configured")
        config = config or GenerationConfig()
        model_name = model or self.default_model
        protocol = self._protocol_for_model(model_name)
        try:
            if protocol == "openai.responses":
                data = await self._responses_request(
                    model_name,
                    self._responses_input(messages),
                    config,
                    tools,
                )
                return self._responses_result(data, model_name)
            if protocol == "anthropic.messages":
                system, anthropic_messages = self._anthropic_messages(messages)
                data = await self._anthropic_request(
                    model_name, system, anthropic_messages, config, tools
                )
                return self._anthropic_result(data, model_name)
            raise GenerationError(
                f"Model {model_name} only supports image generation and cannot be used for chat",
                provider_type=self.provider_type,
            )
        except GenerationError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise GenerationError(
                f"Agent.Space request failed: {exc}",
                provider_type=self.provider_type,
                original_error=exc,
            ) from exc

    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        config: Optional[GenerationConfig] = None,
        tools: Optional[List[Any]] = None,
        tool_executor: Optional[Any] = None,
        max_iterations: int = 25,
        model: Optional[str] = None,
        **kwargs,
    ) -> GenerationResult:
        config = config or GenerationConfig()
        model_name = model or self.default_model
        if not tools or not tool_executor:
            return await self.generate(messages, config, tools, model_name, **kwargs)

        protocol = self._protocol_for_model(model_name)
        if protocol == "openai.images":
            return await self.generate(messages, config, tools, model_name, **kwargs)

        if protocol == "openai.responses":
            response_input = self._responses_input(messages)
            data = await self._responses_request(
                model_name, response_input, config, tools
            )
            for iteration in range(max_iterations):
                result = self._responses_result(data, model_name)
                if not result.tool_calls:
                    return result
                log.info(
                    "Agent.Space Responses tool loop: %d/%d (%d calls)",
                    iteration + 1,
                    max_iterations,
                    len(result.tool_calls),
                )
                outputs = []
                for call in result.tool_calls:
                    try:
                        value = await tool_executor(call, **kwargs)
                    except Exception as exc:
                        log.error("Agent.Space tool %s failed: %s", call["name"], exc)
                        value = {"error": str(exc)}
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call["id"],
                            "output": self._json_text(value),
                        }
                    )
                response_input.extend(data.get("output", []) or [])
                response_input.extend(outputs)
                data = await self._responses_request(
                    model_name,
                    response_input,
                    config,
                    tools if iteration + 1 < max_iterations else None,
                )
            return self._responses_result(data, model_name)

        system, conversation = self._anthropic_messages(messages)
        for iteration in range(max_iterations):
            data = await self._anthropic_request(
                model_name, system, conversation, config, tools
            )
            result = self._anthropic_result(data, model_name)
            if not result.tool_calls:
                return result
            log.info(
                "Agent.Space Anthropic tool loop: %d/%d (%d calls)",
                iteration + 1,
                max_iterations,
                len(result.tool_calls),
            )
            conversation.append({"role": "assistant", "content": data.get("content", [])})
            tool_results = []
            for call in result.tool_calls:
                try:
                    value = await tool_executor(call, **kwargs)
                    is_error = isinstance(value, dict) and "error" in value
                except Exception as exc:
                    log.error("Agent.Space tool %s failed: %s", call["name"], exc)
                    value = {"error": str(exc)}
                    is_error = True
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": self._json_text(value),
                        "is_error": is_error,
                    }
                )
            conversation.append({"role": "user", "content": tool_results})
            if iteration + 1 == max_iterations:
                data = await self._anthropic_request(
                    model_name, system, conversation, config, None
                )
                return self._anthropic_result(data, model_name)

        raise GenerationError(
            "Agent.Space tool loop ended unexpectedly",
            provider_type=self.provider_type,
        )

    async def close(self):
        await super().close()
        if self._anthropic_client is not None:
            await self._anthropic_client.aclose()
            self._anthropic_client = None
