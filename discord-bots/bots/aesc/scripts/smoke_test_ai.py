#!/usr/bin/env python3
"""Pre-deployment smoke test for configured OpenAI-compatible models.

The test performs a real request with a tool schema for every configured model,
then runs the response through the same tool-call parser used by the bot.  It
never prints credentials or the full upstream response.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import urllib.error
import urllib.request

DEFAULT_MODELS = ("gemini-3.7-flash-high", "gemini-3.8-flash-high")

SMOKE_TOOL = {
    "type": "function",
    "function": {
        "name": "diagnostic_noop",
        "description": "Only for checking tool-call response compatibility.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def request_model(
    base_url: str, api_key: str, model: str, system_prompt: str | None = None
) -> dict:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(
        {
            "role": "user",
            "content": (
                "请用两三句话向新朋友介绍自己，然后听说远处正在举办热闹节日，邀请对方一起出发。不要解释设定。"
                if system_prompt
                else "这是上线前连通性测试。请只回复 AESC_SMOKE_OK，不要调用工具。"
            ),
        }
    )
    payload = {
        "model": model,
        "messages": messages,
        "tools": [SMOKE_TOOL],
        "temperature": 0,
        "max_tokens": 64,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AescPredeploySmoke/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


async def test_project_service(models: list[str], persona: bool = False) -> bool:
    from src.chat.services.ai.service import ai_service
    from src.chat.config.aesc_persona import build_aesc_system_prompt

    failed = False
    try:
        await ai_service.initialize()
        for model in models:
            try:
                if persona:
                    messages = [
                        {"role": "system", "content": build_aesc_system_prompt()},
                        {
                            "role": "user",
                            "content": "请用两三句话向新朋友介绍自己，然后听说远处正在举办热闹节日，邀请对方一起出发。不要解释设定。",
                        },
                    ]
                else:
                    messages = [
                        {
                            "role": "user",
                            "content": "这是项目服务冒烟测试。请只回复 AESC_SERVICE_OK，不调用工具。",
                        }
                    ]
                result = await ai_service.generate_with_tools(
                    messages=messages,
                    model=model,
                    tools=[SMOKE_TOOL],
                    max_iterations=2,
                    fallback=False,
                )
                content_ok = isinstance(result.content, str) and bool(result.content.strip())
                calls = result.tool_calls or []
                identity_ok = not persona or (
                    "梣" in result.content and "类脑娘" not in result.content
                )
                print(
                    f"project_service_model={model} status=ok "
                    f"content={'present' if content_ok else 'missing'} "
                    f"tool_calls={len(calls)} identity={'ok' if identity_ok else 'failed'}"
                )
                if persona and content_ok:
                    preview = " ".join(result.content.split())[:220]
                    print(
                        f"persona_preview_{model}="
                        + json.dumps(preview, ensure_ascii=True)
                    )
                failed = failed or (not content_ok and not calls) or not identity_ok
            except Exception as exc:
                failed = True
                print(f"project_service_model={model} status=failed error={exc}")
    finally:
        await ai_service.close()
    return failed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--project-service", action="store_true")
    parser.add_argument("--persona", action="store_true")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_COMPATIBLE_URL", "").strip()
    if not api_key or not base_url:
        raise SystemExit("OPENAI_COMPATIBLE_API_KEY/URL is not configured")

    failed = False
    if args.persona:
        from src.chat.config.aesc_persona import build_aesc_system_prompt

        system_prompt = build_aesc_system_prompt()
    else:
        system_prompt = None

    for model in args.models:
        try:
            data = request_model(base_url, api_key, model, system_prompt=system_prompt)
            choices = data.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            raw_calls = message.get("tool_calls") or []
            content = message.get("content")
            content_ok = isinstance(content, str) and bool(content.strip())
            identity_ok = not args.persona or (
                content_ok and "梣" in content and "类脑娘" not in content
            )
            print(
                "model={} status={} content={} raw_tool_calls={} parsed_tool_calls={}".format(
                    model,
                    "ok" if choices else "invalid_response",
                    "present" if content_ok else "missing",
                    type(message.get("tool_calls")).__name__,
                    len(raw_calls),
                )
            )
            if args.persona and content_ok:
                preview = " ".join(content.split())[:220]
                print(
                    f"raw_persona_preview_{model}="
                    + json.dumps(preview, ensure_ascii=True)
                )
            failed = (
                failed
                or not choices
                or (not content_ok and not raw_calls)
                or not identity_ok
            )
        except Exception as exc:
            failed = True
            print(f"model={model} status=failed error={exc}")

    if args.project_service:
        failed = asyncio.run(
            test_project_service(list(args.models), persona=args.persona)
        ) or failed

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
