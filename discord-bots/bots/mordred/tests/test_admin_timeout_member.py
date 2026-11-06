import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import discord

from src.chat.features.tools.functions.admin_timeout_member import (
    AdminTimeoutMemberParams,
    _parse_target_id,
    _resolve_target_id,
    admin_timeout_member,
)
from src.chat.features.tools.schema_utils import extract_function_schema
from src.chat.features.tools.services.tool_service import _convert_dict_to_pydantic
from src.chat.services.chat_service import ChatService
from src.chat.services.context_service_test import ContextServiceTest


def test_parse_target_id_accepts_discord_mentions():
    assert _parse_target_id("<@0>") == 0
    assert _parse_target_id("<@!0>") == 0


def test_parse_target_id_rejects_names():
    assert _parse_target_id("some-user") is None


def test_admin_timeout_schema_exposes_real_fields():
    schema = extract_function_schema(admin_timeout_member)
    properties = schema["parameters"]["properties"]
    params_schema = properties["params"]

    assert params_schema["type"] == "OBJECT"
    assert {"target_user_id", "duration_minutes", "reason"} <= set(
        params_schema["properties"]
    )


def test_admin_timeout_arguments_are_converted_to_model():
    converted = _convert_dict_to_pydantic(
        {
            "target_user_id": "0",
            "duration_minutes": 1,
            "reason": "管理员功能测试",
            "user_id": "0",
        },
        admin_timeout_member,
    )

    assert isinstance(converted["params"], AdminTimeoutMemberParams)
    assert converted["params"].target_user_id == "0"
    assert converted["params"].duration_minutes == 1
    assert converted["user_id"] == "0"


def _message(content, mentions=()):
    return SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=10),
        content=content,
        mentions=list(mentions),
        reference=None,
    )


def _member(member_id, name):
    return SimpleNamespace(
        id=member_id,
        display_name=name,
        name=name,
        global_name=None,
        bot=False,
    )


def test_admin_timeout_resolves_a_single_mention_without_id_argument():
    target = _member(0, "Target")
    guild = SimpleNamespace(id=1, members=[target])
    resolved, error = asyncio.run(
        _resolve_target_id(guild, _message("请禁言 <@0>", [target]), "")
    )
    assert (resolved, error) == (target.id, None)


def test_admin_timeout_resolves_unique_name_but_rejects_ungrounded_id():
    target = _member(0, "Target")
    guild = SimpleNamespace(id=1, members=[target])
    resolved, error = asyncio.run(
        _resolve_target_id(guild, _message("请禁言 Target"), "Target")
    )
    assert (resolved, error) == (target.id, None)
    resolved, error = asyncio.run(
        _resolve_target_id(guild, _message("请禁言这个人"), str(target.id))
    )
    assert resolved is None
    assert "当前消息" in error


def test_admin_timeout_rejects_ambiguous_mentions():
    first = _member(0, "First")
    second = _member(0, "Second")
    guild = SimpleNamespace(id=1, members=[first, second])
    resolved, error = asyncio.run(
        _resolve_target_id(guild, _message("禁言他们", [first, second]), "")
    )
    assert resolved is None
    assert "多名成员" in error


def test_admin_timeout_resolves_replied_to_member_without_id_argument():
    target = _member(0, "Target")
    guild = SimpleNamespace(id=1, members=[target])
    replied = Mock(spec=discord.Message)
    replied.guild = guild
    replied.author = target
    message = _message("禁言这个人")
    message.reference = SimpleNamespace(message_id=99, resolved=replied)
    resolved, error = asyncio.run(_resolve_target_id(guild, message, ""))
    assert (resolved, error) == (target.id, None)


def test_admin_timeout_returns_validation_error_instead_of_crashing_on_dict():
    result = asyncio.run(admin_timeout_member({"reason": ""}))
    assert "禁言参数无效" in result["error"]


def test_mentions_reach_ai_with_id_and_return_as_real_mentions():
    target = _member(0, "Target")
    target.mention = "<@0>"
    guild = SimpleNamespace(get_member=lambda user_id: target if user_id == target.id else None)
    prompt_text = ContextServiceTest.clean_message_content(
        None, "请叫 <@0> 来", guild
    )
    assert "@Target (<@0>)" in prompt_text
    response = ChatService._format_ai_response(None, "@Target 来一下", [target])
    assert response == "<@0> 来一下"
