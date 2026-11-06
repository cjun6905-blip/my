# -*- coding: utf-8 -*-
"""伊莉雅的 Discord 应用表情及对话占位符映射。"""

import re


ILLYA_EMOJIS = {
    "微笑": "<:illya_smile:0>",
    "开心": "<:illya_happy:0>",
    "得意": "<:illya_smug:0>",
    "生气": "<:illya_angry:0>",
    "委屈": "<:illya_sad:0>",
    "害羞": "<:illya_shy:0>",
    "惊讶": "<:illya_surprised:0>",
    "疑惑": "<:illya_confused:0>",
    "思考": "<:illya_thinking:0>",
    "偷笑": "<:illya_giggle:0>",
    "乖巧": "<:illya_good:0>",
    "抱抱": "<:illya_hug:0>",
}

# 兼容旧提示词可能产出的占位符，全部指向本应用的伊莉雅表情。
ALIASES = {
    "伤心": "委屈",
    "无语": "疑惑",
    "好奇": "疑惑",
    "尴尬赞": "乖巧",
    "赞": "乖巧",
    "吃瓜": "偷笑",
    "鬼脸": "偷笑",
    "鄙视": "得意",
    "比心": "抱抱",
}

EMOJI_MAPPINGS = [
    (re.compile(re.escape(f"<{name}>")), [value])
    for name, value in ILLYA_EMOJIS.items()
]
EMOJI_MAPPINGS.extend(
    (re.compile(re.escape(f"<{alias}>")), [ILLYA_EMOJIS[target]])
    for alias, target in ALIASES.items()
)

# 旧角色的活动派系表情不适用于伊莉雅。
FACTION_EMOJI_MAPPINGS = {}
