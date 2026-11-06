from src.chat.config.aesc_persona import build_aesc_system_prompt
from src.chat.config.prompts import PERSONA_VARIANTS, PROMPT_CONFIG, SYSTEM_PROMPT
from src.config import BOT_NAME, CURRENCY_NAME, MASCOT_TITLE


def test_aesc_identity_config_is_active():
    assert BOT_NAME == "雨之魔女梣"
    assert CURRENCY_NAME == "雨滴"
    assert MASCOT_TITLE == "雨之魔女"


def test_aesc_prompt_contains_required_relationships():
    prompt = build_aesc_system_prompt()

    for name in ("摩根", "阿尔托莉雅·潘德拉贡", "阿尔托莉雅·卡斯特", "莫德雷德"):
        assert name in prompt

    assert "雨之国的记忆" in prompt
    assert "泛人类史" in prompt
    assert "不把未来阶段的全部经历冒充为自己的亲历" in prompt


def test_aesc_prompt_keeps_the_rain_witch_lively():
    prompt = build_aesc_system_prompt()

    for trait in (
        "年轻魔女对新世界的强烈好奇",
        "不是安静到没有起伏的优等生",
        "好，出发吧！",
        "交给头脑派魔女吧",
        "不要始终保持同一种温吞语气",
    ):
        assert trait in prompt

    assert "不要说成冷峻女王摩根" in prompt
    assert "不要变成只会温柔附和的通用助手" in prompt


def test_all_model_and_style_prompts_use_aesc():
    prompts = [
        config["SYSTEM_PROMPT"]
        for config in PROMPT_CONFIG.values()
        if isinstance(config, dict) and "SYSTEM_PROMPT" in config
    ]
    prompts.extend(
        model_config["SYSTEM_PROMPT"]
        for variants in PERSONA_VARIANTS.values()
        for model_config in variants.values()
        if "SYSTEM_PROMPT" in model_config
    )

    assert SYSTEM_PROMPT == PROMPT_CONFIG["default"]["SYSTEM_PROMPT"]
    assert prompts
    assert all("名称: 雨之魔女梣" in prompt for prompt in prompts)
    assert all("- 莫德雷德:" in prompt for prompt in prompts)
