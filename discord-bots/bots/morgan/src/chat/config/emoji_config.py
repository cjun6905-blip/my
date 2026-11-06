# -*- coding: utf-8 -*-

"""
表情符号配置文件
用于定义AI输出文本到Discord自定义表情符号的映射关系
使用正则表达式进行匹配和替换
"""

import re

# 定义表情符号映射
# 格式: [(正则表达式, Discord表情符号), ...]
EMOJI_MAPPINGS = [
    (re.compile(r"\<(?:微笑|开心|乖巧)\>"), ["<:morgan_smile:0>"]),
    (re.compile(r"\<(?:得意|傲娇|无语|鄙视)\>"), ["<:morgan_proud:0>"]),
    (re.compile(r"\<(?:生气|愤怒)\>"), ["<:morgan_angry:0>"]),
    (re.compile(r"\<害羞\>"), ["<:morgan_shy:0>"]),
    (re.compile(r"\<(?:思考|疑惑|好奇)\>"), ["<:morgan_thinking:0>"]),
    (re.compile(r"\<惊讶\>"), ["<:morgan_surprised:0>"]),
    (re.compile(r"\<(?:偷笑|大笑)\>"), ["<:morgan_laugh:0>"]),
    (re.compile(r"\<(?:委屈|伤心)\>"), ["<:morgan_pout:0>"]),
    (re.compile(r"\<(?:眨眼|鬼脸)\>"), ["<:morgan_wink:0>"]),
    (re.compile(r"\<(?:比心|抱抱)\>"), ["<:morgan_love:0>"]),
    (re.compile(r"\<(?:困倦|晚安)\>"), ["<:morgan_sleepy:0>"]),
    (re.compile(r"\<(?:施法|赞)\>"), ["<:morgan_magic:0>"]),
    (re.compile(r"\<(?:无奈|叹气)\>"), ["<:morgan_resigned:0>"]),
    (re.compile(r"\<嫌弃\>"), ["<:morgan_disdain:0>"]),
    (re.compile(r"\<(?:哭泣|哭了)\>"), ["<:morgan_cry:0>"]),
    (re.compile(r"\<(?:害怕|惊慌)\>"), ["<:morgan_scared:0>"]),
    (re.compile(r"\<(?:喝茶|品茶)\>"), ["<:morgan_tea:0>"]),
    (re.compile(r"\<(?:甜点|蛋糕|嘴馋)\>"), ["<:morgan_cake:0>"]),
    (re.compile(r"\<安慰\>"), ["<:morgan_comfort:0>"]),
    (re.compile(r"\<(?:加油|鼓励)\>"), ["<:morgan_cheer:0>"]),
    (re.compile(r"\<(?:早安|早上好)\>"), ["<:morgan_morning:0>"]),
    (re.compile(r"\<(?:胜利|庆祝)\>"), ["<:morgan_victory:0>"]),
    (re.compile(r"\<(?:扶额|尴尬)\>"), ["<:morgan_facepalm:0>"]),
    (re.compile(r"\<(?:命令|严肃)\>"), ["<:morgan_command:0>"]),
]

# --- 活动专属表情 ---

# 万圣节 2025 - 幽灵派系
_HALLOWEEN_GHOST_EMOJI_MAPPINGS = [
    (re.compile(r"\<害羞\>"), ["<:hai_xiu:0>"]),
    (re.compile(r"\<害怕\>"), ["<:hai_pa:0>"]),
    (re.compile(r"\<开心\>"), ["<:kai_xin:0>"]),
    (re.compile(r"\<紧张\>"), ["<:jing_zhang:0>"]),
    (re.compile(r"\<鲜花\>"), ["<:xian_hua:0>"]),
    (re.compile(r"\<生气\>"), ["<:sheng_qi:0>"]),
    (re.compile(r"\<呆\>"), ["<:dai:0>"]),
]

# 万圣节 2025 - 吸血鬼派系
_HALLOWEEN_VAMPIRE_EMOJI_MAPPINGS = [
    (re.compile(r"\<得意\>"), ["<:de_yi_x:0>"]),
    (re.compile(r"\<害羞\>"), ["<:hai_xiu_x:0>"]),
    (re.compile(r"\<生气\>"), ["<:sheng_qi_x:0>"]),
    (re.compile(r"\<惊慌\>"), ["<:jing_huang:0>"]),
    (re.compile(r"\<思考\>"), ["<:si_kao_x:0>"]),
    (re.compile(r"\<无奈\>"), ["<:wu_nai:0>"]),
    (re.compile(r"\<挑衅\>"), ["<:tiao_xing:0>"]),
    (re.compile(r"\<坏笑\>"), ["<:huai_xiao:0>"]),
]

# 万圣节 2025 - 教会派系
_HALLOWEEN_CHURCH_EMOJI_MAPPINGS = [
    (re.compile(r"\<开心\>"), ["<:kai_xin_church:0>"]),
    (re.compile(r"\<得意\>"), ["<:de_yi_church:0>"]),
    (re.compile(r"\<嘴馋\>"), ["<:zui_chan:0>"]),
    (re.compile(r"\<期待\>"), ["<:qi_dai:0>"]),
    (re.compile(r"\<满足\>"), ["<:man_zu:0>"]),
    (re.compile(r"\<生气\>"), ["<:sheng_qi_church:0>"]),
    (re.compile(r"\<感谢\>"), ["<:gan_xie:0>"]),
    (re.compile(r"\<祈祷\>"), ["<:qi_dao:0>"]),
    (re.compile(r"\<饿了\>"), ["<:e_le:0>"]),
]

# 万圣节 2025 - 僵尸派系
_HALLOWEEN_JIANGSHI_EMOJI_MAPPINGS = [
    (re.compile(r"\<无聊\>"), ["<:wu_liao:0>"]),
    (re.compile(r"\<馋了\>"), ["<:chan_le_jiangshi:0>"]),
    (re.compile(r"\<得意\>"), ["<:de_yi_jiangshi:0>"]),
    (re.compile(r"\<期待\>"), ["<:qi_dai_jiangshi:0>"]),
    (
        re.compile(r"\<急了\>"),
        ["<:ji_le:0>", "<:ji_le_2:0>"],
    ),
    (re.compile(r"\<躺平\>"), ["<:tang_ping:0>"]),
    (re.compile(r"\<懵懂\>"), ["<:meng_dong:0>"]),
]

# 万圣节 2025 - 女巫派系
_HALLOWEEN_WITCH_EMOJI_MAPPINGS = [
    (re.compile(r"\<委屈\>"), ["<:wei_qu:0>"]),
    (re.compile(r"\<得意\>"), ["<:de_yi_witch:0>"]),
    (re.compile(r"\<期待\>"), ["<:qi_dai_witch:0>"]),
    (re.compile(r"\<开心\>"), ["<:kai_xin_witch:0>"]),
    (re.compile(r"\<吐舌\>"), ["<:tu_shetou:0>"]),
    (re.compile(r"\<眨眼\>"), ["<:zha_yan:0>"]),
    (re.compile(r"\<不满\>"), ["<:bu_man:0>"]),
    (re.compile(r"\<施法\>"), ["<:shi_fa:0>"]),
    (re.compile(r"\<坏笑\>"), ["<:huai_xiao_witch:0>"]),
    (re.compile(r"\<呆呆\>"), ["<:dai_dai:0>"]),
]

# 万圣节 2025 - 狼人派系
_HALLOWEEN_WEREWOLF_EMOJI_MAPPINGS = [
    (re.compile(r"\<生气\>"), ["<:sheng_qi_wolf:0>"]),
    (re.compile(r"\<得意\>"), ["<:de_yi_wolf:0>"]),
    (re.compile(r"\<激动\>"), ["<:ji_dong_wolf:0>"]),
    (re.compile(r"\<开心\>"), ["<:ji_dong_wolf:0>"]),
    (
        re.compile(r"\<委屈\>"),
        ["<:wei_qu_wolf1:0>", "<:wei_qu_wolf2:0>"],
    ),
    (re.compile(r"\<大笑\>"), ["<:da_xiao:0>"]),
    (re.compile(r"\<馋\>"), ["<:can_wolf:0>"]),
    (re.compile(r"\<无语\>"), ["<:wuyu_wolf:0>"]),
]

# --- 派系表情总配置 ---
# 结构: { "event_id": { "faction_id": MAPPING_LIST } }
FACTION_EMOJI_MAPPINGS = {
    "halloween_2025": {
        "ghost": _HALLOWEEN_GHOST_EMOJI_MAPPINGS,
        "vampire": _HALLOWEEN_VAMPIRE_EMOJI_MAPPINGS,
        "church": _HALLOWEEN_CHURCH_EMOJI_MAPPINGS,
        "jiangshi": _HALLOWEEN_JIANGSHI_EMOJI_MAPPINGS,
        "witch": _HALLOWEEN_WITCH_EMOJI_MAPPINGS,
        "werewolf": _HALLOWEEN_WEREWOLF_EMOJI_MAPPINGS,
    },
    "christmas_2025": {
        "before_christmas": [
            (
                re.compile(r"\<乖巧\>"),
                [
                    "<:Christmas_guaiqiao_1:0>",
                    "<:Christmas_guaiqiao_2:0>",
                    "<:Christmas_guaiqiao_3:0>",
                ],
            ),
            (
                re.compile(r"\<害羞\>"),
                [
                    "<:Christmas_shy_1:0>",
                    "<:Christmas_shy_2:0>",
                ],
            ),
            (re.compile(r"\<微笑\>"), ["<:Christmas_smile:0>"]),
            (
                re.compile(r"\<赞\>"),
                [
                    "<:Christmas_zan_1:0>",
                    "<:Christmas_zan_2:0>",
                ],
            ),
            (
                re.compile(r"\<鬼脸\>"),
                [
                    "<:Christmas_ghost_face_1:0>",
                    "<:Christmas_ghost_face_2:0>",
                ],
            ),
            (
                re.compile(r"\<偷笑\>"),
                [
                    "<:Christmas_touxiao_1:0>",
                    "<:Christmas_touxiao_2:0>",
                ],
            ),
            (re.compile(r"\<吃瓜\>"), ["<:Christmas_chigua:0>"]),
            (re.compile(r"\<尴尬赞\>"), ["<:Christmas_ganga_zan:0>"]),
            (re.compile(r"\<得意\>"), ["<:Christmas_aojiao:0>"]),
            (
                re.compile(r"\<生气\>"),
                [
                    "<:Christmas_anger_1:0>",
                    "<:Christmas_anger_2:0>",
                ],
            ),
            (re.compile(r"\<伤心\>"), ["<:Christmas_sad:0>"]),
            (re.compile(r"\<呆\>"), ["<:Christmas_dai:0>"]),
            (
                re.compile(r"\<嫌弃\>"),
                [
                    "<:Christmas_xianqi_1:0>",
                    "<:Christmas_xianqi_2:0>",
                ],
            ),
        ],
        "christmas_eve": [
            (
                re.compile(r"\<乖巧\>"),
                [
                    "<:Christmas_guaiqiao_1:0>",
                    "<:Christmas_guaiqiao_2:0>",
                    "<:Christmas_guaiqiao_3:0>",
                ],
            ),
            (
                re.compile(r"\<害羞\>"),
                [
                    "<:Christmas_shy_1:0>",
                    "<:Christmas_shy_2:0>",
                ],
            ),
            (re.compile(r"\<微笑\>"), ["<:Christmas_smile:0>"]),
            (
                re.compile(r"\<赞\>"),
                [
                    "<:Christmas_zan_1:0>",
                    "<:Christmas_zan_2:0>",
                ],
            ),
            (
                re.compile(r"\<鬼脸\>"),
                [
                    "<:Christmas_ghost_face_1:0>",
                    "<:Christmas_ghost_face_2:0>",
                ],
            ),
            (
                re.compile(r"\<偷笑\>"),
                [
                    "<:Christmas_touxiao_1:0>",
                    "<:Christmas_touxiao_2:0>",
                ],
            ),
            (re.compile(r"\<吃瓜\>"), ["<:Christmas_chigua:0>"]),
            (re.compile(r"\<尴尬赞\>"), ["<:Christmas_ganga_zan:0>"]),
            (re.compile(r"\<得意\>"), ["<:Christmas_aojiao:0>"]),
            (
                re.compile(r"\<生气\>"),
                [
                    "<:Christmas_anger_1:0>",
                    "<:Christmas_anger_2:0>",
                ],
            ),
            (re.compile(r"\<伤心\>"), ["<:Christmas_sad:0>"]),
            (re.compile(r"\<呆\>"), ["<:Christmas_dai:0>"]),
            (
                re.compile(r"\<嫌弃\>"),
                [
                    "<:Christmas_xianqi_1:0>",
                    "<:Christmas_xianqi_2:0>",
                ],
            ),
        ],
        "christmas_day": [
            (
                re.compile(r"\<乖巧\>"),
                [
                    "<:Christmas_guaiqiao_1:0>",
                    "<:Christmas_guaiqiao_2:0>",
                    "<:Christmas_guaiqiao_3:0>",
                ],
            ),
            (
                re.compile(r"\<害羞\>"),
                [
                    "<:Christmas_shy_1:0>",
                    "<:Christmas_shy_2:0>",
                ],
            ),
            (re.compile(r"\<微笑\>"), ["<:Christmas_smile:0>"]),
            (
                re.compile(r"\<赞\>"),
                [
                    "<:Christmas_zan_1:0>",
                    "<:Christmas_zan_2:0>",
                ],
            ),
            (
                re.compile(r"\<鬼脸\>"),
                [
                    "<:Christmas_ghost_face_1:0>",
                    "<:Christmas_ghost_face_2:0>",
                ],
            ),
            (
                re.compile(r"\<偷笑\>"),
                [
                    "<:Christmas_touxiao_1:0>",
                    "<:Christmas_touxiao_2:0>",
                ],
            ),
            (re.compile(r"\<吃瓜\>"), ["<:Christmas_chigua:0>"]),
            (re.compile(r"\<尴尬赞\>"), ["<:Christmas_ganga_zan:0>"]),
            (re.compile(r"\<得意\>"), ["<:Christmas_aojiao:0>"]),
            (
                re.compile(r"\<生气\>"),
                [
                    "<:Christmas_anger_1:0>",
                    "<:Christmas_anger_2:0>",
                ],
            ),
            (re.compile(r"\<伤心\>"), ["<:Christmas_sad:0>"]),
            (re.compile(r"\<呆\>"), ["<:Christmas_dai:0>"]),
            (
                re.compile(r"\<嫌弃\>"),
                [
                    "<:Christmas_xianqi_1:0>",
                    "<:Christmas_xianqi_2:0>",
                ],
            ),
        ],
    },
    "spring_festival_2026": {
        "spring_festival_eve": [
            (re.compile(r"\<做鬼脸1\>"), ["<:zuoguilian:0>"]),
            (re.compile(r"\<做鬼脸2\>"), ["<:zuoguilian2:0>"]),
            (re.compile(r"\<做鬼脸3\>"), ["<:zuoguilian3:0>"]),
            (re.compile(r"\<赞1\>"), ["<:zan:0>"]),
            (re.compile(r"\<赞2\>"), ["<:zan2:0>"]),
            (re.compile(r"\<优雅\>"), ["<:youya:0>"]),
            (re.compile(r"\<嫌弃1\>"), ["<:xianqi:0>"]),
            (re.compile(r"\<嫌弃2\>"), ["<:xianqi2:0>"]),
            (re.compile(r"\<无语1\>"), ["<:wuyu:0>"]),
            (re.compile(r"\<无语2\>"), ["<:wuyu2:0>"]),
            (re.compile(r"\<微笑\>"), ["<:weixiao:0>"]),
            (re.compile(r"\<偷笑\>"), ["<:touxiao:0>"]),
            (re.compile(r"\<生气1\>"), ["<:shengqi:0>"]),
            (re.compile(r"\<生气2\>"), ["<:shengqi2:0>"]),
            (re.compile(r"\<可爱\>"), ["<:keai:0>"]),
            (re.compile(r"\<坏笑\>"), ["<:huaixiao:0>"]),
            (re.compile(r"\<害羞1\>"), ["<:haixiu:0>"]),
            (re.compile(r"\<害羞2\>"), ["<:haixiu2:0>"]),
            (re.compile(r"\<乖巧1\>"), ["<:guaiqiao:0>"]),
            (re.compile(r"\<乖巧2\>"), ["<:guaiqiao2:0>"]),
            (re.compile(r"\<乖巧3\>"), ["<:guaiqiao3:0>"]),
            (re.compile(r"\<尴尬赞\>"), ["<:gangazan:0>"]),
            (re.compile(r"\<吃瓜1\>"), ["<:chigua:0>"]),
            (re.compile(r"\<吃瓜2\>"), ["<:chigua2:0>"]),
            (re.compile(r"\<得意\>"), ["<:aojiao:0>"]),
        ],
        "spring_festival_day": [
            (re.compile(r"\<做鬼脸1\>"), ["<:zuoguilian:0>"]),
            (re.compile(r"\<做鬼脸2\>"), ["<:zuoguilian2:0>"]),
            (re.compile(r"\<做鬼脸3\>"), ["<:zuoguilian3:0>"]),
            (re.compile(r"\<赞1\>"), ["<:zan:0>"]),
            (re.compile(r"\<赞2\>"), ["<:zan2:0>"]),
            (re.compile(r"\<优雅\>"), ["<:youya:0>"]),
            (re.compile(r"\<嫌弃1\>"), ["<:xianqi:0>"]),
            (re.compile(r"\<嫌弃2\>"), ["<:xianqi2:0>"]),
            (re.compile(r"\<无语1\>"), ["<:wuyu:0>"]),
            (re.compile(r"\<无语2\>"), ["<:wuyu2:0>"]),
            (re.compile(r"\<微笑\>"), ["<:weixiao:0>"]),
            (re.compile(r"\<偷笑\>"), ["<:touxiao:0>"]),
            (re.compile(r"\<生气1\>"), ["<:shengqi:0>"]),
            (re.compile(r"\<生气2\>"), ["<:shengqi2:0>"]),
            (re.compile(r"\<可爱\>"), ["<:keai:0>"]),
            (re.compile(r"\<坏笑\>"), ["<:huaixiao:0>"]),
            (re.compile(r"\<害羞1\>"), ["<:haixiu:0>"]),
            (re.compile(r"\<害羞2\>"), ["<:haixiu2:0>"]),
            (re.compile(r"\<乖巧1\>"), ["<:guaiqiao:0>"]),
            (re.compile(r"\<乖巧2\>"), ["<:guaiqiao2:0>"]),
            (re.compile(r"\<乖巧3\>"), ["<:guaiqiao3:0>"]),
            (re.compile(r"\<尴尬赞\>"), ["<:gangazan:0>"]),
            (re.compile(r"\<吃瓜1\>"), ["<:chigua:0>"]),
            (re.compile(r"\<吃瓜2\>"), ["<:chigua2:0>"]),
            (re.compile(r"\<得意\>"), ["<:aojiao:0>"]),
        ],
        "spring_festival_generic_day": [
            (re.compile(r"\<做鬼脸1\>"), ["<:zuoguilian:0>"]),
            (re.compile(r"\<做鬼脸2\>"), ["<:zuoguilian2:0>"]),
            (re.compile(r"\<做鬼脸3\>"), ["<:zuoguilian3:0>"]),
            (re.compile(r"\<赞1\>"), ["<:zan:0>"]),
            (re.compile(r"\<赞2\>"), ["<:zan2:0>"]),
            (re.compile(r"\<优雅\>"), ["<:youya:0>"]),
            (re.compile(r"\<嫌弃1\>"), ["<:xianqi:0>"]),
            (re.compile(r"\<嫌弃2\>"), ["<:xianqi2:0>"]),
            (re.compile(r"\<无语1\>"), ["<:wuyu:0>"]),
            (re.compile(r"\<无语2\>"), ["<:wuyu2:0>"]),
            (re.compile(r"\<微笑\>"), ["<:weixiao:0>"]),
            (re.compile(r"\<偷笑\>"), ["<:touxiao:0>"]),
            (re.compile(r"\<生气1\>"), ["<:shengqi:0>"]),
            (re.compile(r"\<生气2\>"), ["<:shengqi2:0>"]),
            (re.compile(r"\<可爱\>"), ["<:keai:0>"]),
            (re.compile(r"\<坏笑\>"), ["<:huaixiao:0>"]),
            (re.compile(r"\<害羞1\>"), ["<:haixiu:0>"]),
            (re.compile(r"\<害羞2\>"), ["<:haixiu2:0>"]),
            (re.compile(r"\<乖巧1\>"), ["<:guaiqiao:0>"]),
            (re.compile(r"\<乖巧2\>"), ["<:guaiqiao2:0>"]),
            (re.compile(r"\<乖巧3\>"), ["<:guaiqiao3:0>"]),
            (re.compile(r"\<尴尬赞\>"), ["<:gangazan:0>"]),
            (re.compile(r"\<吃瓜1\>"), ["<:chigua:0>"]),
            (re.compile(r"\<吃瓜2\>"), ["<:chigua2:0>"]),
            (re.compile(r"\<得意\>"), ["<:aojiao:0>"]),
        ],
    },
}
