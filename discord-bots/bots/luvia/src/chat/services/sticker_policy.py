"""Occasional context-matched character stickers without extra model calls."""
import logging
import re
import time
from collections import OrderedDict, deque
from src import config
from src.chat.services.channel_policy import may_send_automatic_message
from src.chat.services.conversation import sticker_candidates

log = logging.getLogger(__name__)
EXPLICIT = re.compile(r'(?:发|来|给我|看看|看下|想看|用|回复|换|send|show).{0,10}(?:表情包|大图表情|贴纸|sticker|emote)|^(?:表情包|贴纸|sticker|emote)[！!。？?\s]*$|(?:发|来|给我|看看).{0,8}表情', re.I)
VETO = re.compile(r'(?:不要|不用|别|不必|停止).{0,2}(?:发|用|贴).{0,5}(?:表情|贴纸|sticker)|只要文字|纯文字|文字就好|别刷(?:图|屏)', re.I)
SERIOUS = re.compile(r'```|代码|报错|异常|解释一下|详细解释|教程|作业|严肃|认真回答|急救|报警|住院|受伤|生病|去世|自杀|自残|难过|焦虑|抑郁|失恋|道歉|对不起|抱歉')
CUES = [
    (re.compile(r'早安|早上好|起床'), ('goodmorning', 'hello')),
    (re.compile(r'晚安|睡觉|困了'), ('goodnight', 'sleepy')),
    (re.compile(r'回来啦|回来了|到家'), ('welcome', 'smile')),
    (re.compile(r'再见|拜拜|走啦'), ('bye', 'hello')),
    (re.compile(r'你好|嗨|哈喽|hello|\bhi\b', re.I), ('hello', 'smile')),
    (re.compile(r'谢谢|感谢'), ('grateful', 'smile')),
    (re.compile(r'哈哈|嘿嘿|笑死|好玩|逗你|笨蛋'), ('tease', 'laugh', 'wink')),
    (re.compile(r'(?:饼干|烘焙|蛋糕|甜点).{0,8}(?:成功|做好|烤好)'), ('proudwork', 'cheer')),
    (re.compile(r'开心|高兴|成功|太棒|好耶|赢了|做到'), ('laugh', 'cheer', 'smug')),
    (re.compile(r'可爱|夸你|喜欢你|想你'), ('blush', 'wink', 'fluster')),
    (re.compile(r'加油|努力|可以的'), ('cheer', 'agree')),
    (re.compile(r'哼|得意|不服'), ('smug', 'sulk', 'pout')),
]


class ChatStickers:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.channels = OrderedDict()
        self.preferences = OrderedDict()

    def _state(self, channel_id):
        if channel_id not in self.channels:
            self.channels[channel_id] = {'last': -1e20, 'turns': 2, 'recent': deque(maxlen=3)}
        self.channels.move_to_end(channel_id)
        while len(self.channels) > 128:
            self.channels.popitem(last=False)
        return self.channels[channel_id]

    def plan(self, message, mode, candidates, *, speech=False, image_input=False):
        if config.PROFILE_KEY != 'mukuro':
            return None
        text = message.content or ''
        explicit = mode == 'direct' and bool(EXPLICIT.search(text))
        key = (message.channel.id, message.author.id)
        if VETO.search(text):
            self.preferences[key] = False
        elif explicit:
            self.preferences[key] = True
        if key in self.preferences:
            self.preferences.move_to_end(key)
        while len(self.preferences) > 512:
            self.preferences.popitem(last=False)
        permitted = (not getattr(message.author, 'bot', False) and not VETO.search(text)
                     and self.preferences.get(key, True) and not speech)
        casual = (permitted and mode in ('direct', 'proactive') and not image_input
                  and len(text) <= 260 and not SERIOUS.search(text)
                  and (mode == 'direct' or may_send_automatic_message(message.channel)))
        state = self._state(message.channel.id)
        available = list(sticker_candidates(candidates))
        choices = []
        for pattern, codes in CUES:
            if pattern.search(text):
                choices = ['yzk_' + code for code in codes if 'yzk_' + code in available]
                break
        return {'explicit_requested': bool(explicit and permitted),
                'automatic_allowed': bool(casual and state['turns'] >= 2 and self.clock() - state['last'] >= 45),
                'recommended_names': [name for name in choices if name not in state['recent']],
                'recent_names': list(state['recent']), 'casual_turn': bool(casual),
                'available_names': available}

    def choose(self, rule, reply, message_id):
        if not rule:
            return ''
        if rule['explicit_requested']:
            return reply.sticker if reply.sticker in rule['available_names'] else ''
        if (not rule['automatic_allowed'] or not reply.reply.strip()
                or len(reply.reply) > 300 or SERIOUS.search(reply.reply)):
            return ''
        if reply.sticker in rule['available_names'] and reply.sticker not in rule['recent_names']:
            return reply.sticker
        # Only a clear emotional cue gets a deterministic fallback. Neutral
        # conversations remain free to use text when the model selects none.
        choices = rule['recommended_names']
        return choices[message_id % len(choices)] if choices else ''

    def delivered(self, channel_id, rule, sticker):
        if not rule:
            return
        state = self._state(channel_id)
        if sticker:
            state['last'], state['turns'] = self.clock(), 0
            state['recent'].append(sticker)
            log.info('chat_sticker_sent name=%s automatic=%s', sticker, not rule['explicit_requested'])
        elif rule['casual_turn']:
            state['turns'] = min(3, state['turns'] + 1)
