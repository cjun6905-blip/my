"""Bounded literal symbols from sanitized owner samples; never a prompt or command."""
import re
from collections import Counter

CUSTOM = re.compile(r'<a?:[A-Za-z0-9_]{1,64}:([0-9]{15,20})>')
_BASE = r'[\U0001F300-\U0001FAFF\u2600-\u27BF]'
_MOD = r'(?:\ufe0f|[\U0001F3FB-\U0001F3FF])?'
UNICODE = re.compile(r'(?:[\U0001F1E6-\U0001F1FF]{2}|[0-9#*]\ufe0f?\u20e3|'+_BASE+_MOD+r'(?:\u200d'+_BASE+_MOD+r')*)')
_BRACKET_FACE = re.compile(r'[（(][\s￣ー▽∀ωДд﹏︿‿ᴥ_\^≧≦ＴT╥ಠಥ；;´`･・°｡つノヽづっ>＜<>д︶︵˘oO0-9.\-~～]{1,24}[）)]')
_TEXT_FACE = re.compile(r'(?<![A-Za-z])(?:QAQ|QwQ|qwq|TwT|TAT|T_T|UwU|OwO|>_<|\^_\^)(?![A-Za-z])')


def symbols(text):
    custom = [m.group(0) for m in CUSTOM.finditer(text)]
    plain = CUSTOM.sub('', text)
    faces = [m.group(0) for m in _BRACKET_FACE.finditer(plain)
             if re.search(r'ω|∀|▽|Д|д|﹏|︿|‿|ᴥ|_|￣|╥|ಠ|ಥ', m.group(0))]
    faces += _TEXT_FACE.findall(_BRACKET_FACE.sub(' ', plain))
    return custom, UNICODE.findall(plain), faces


def summarize(samples):
    custom, unicode, faces = Counter(), Counter(), Counter()
    total = styled = 0
    for text in samples:
        total += 1
        a, b, c = symbols(text)
        styled += bool(a or b or c)
        # One copied emoji wall should not overwhelm hundreds of real messages.
        custom.update(set(a)); unicode.update(set(b)); faces.update(set(c))
    return {'sample_messages': total, 'symbol_messages': styled,
            'observed_message_ratio': round(styled / total, 3) if total else 0,
            'custom': dict(custom.most_common(16)), 'unicode': dict(unicode.most_common(8)),
            'kaomoji': dict(faces.most_common(8))}


def custom_weights(profile):
    weights = {}
    for code, count in profile.get('custom', {}).items():
        match = CUSTOM.fullmatch(code)
        if match and type(count) is int and count > 0:
            weights[int(match.group(1))] = count
    return weights


def usable_reference(profile, candidates):
    weights = custom_weights(profile)
    custom = {}
    for code in candidates:
        match = CUSTOM.fullmatch(code)
        if match and int(match.group(1)) in weights:
            custom[code] = weights[int(match.group(1))]
    return {'sample_messages': profile.get('sample_messages', 0),
            'symbol_messages': profile.get('symbol_messages', 0),
            'observed_message_ratio': profile.get('observed_message_ratio', 0),
            'custom': custom, 'unicode': dict(profile.get('unicode', {})),
            'kaomoji': dict(profile.get('kaomoji', {}))}
