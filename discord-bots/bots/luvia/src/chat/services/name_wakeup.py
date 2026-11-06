"""Cheap, explicit forms of address; no model request for wake-up detection."""
import re
import unicodedata
from src import config

_SEPARATORS = r"[\s,，。.!！?？:：;；、~～…]*"
_GREETING = r"(?:(?:喂|嘿|嗨|诶|欸|哎|你好呀?|那个|早上好|晚上好|hello|hi)" + _SEPARATORS + r")?"
_QUOTED = re.compile(r'`[^`\n]*`|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*"')


def _patterns():
    if config.PROFILE_KEY != 'mukuro':
        return ()
    names = sorted({unicodedata.normalize('NFKC', x).casefold()
                    for x in config.PERSONA['aliases']}, key=len, reverse=True)
    aliases = '|'.join(re.escape(n) + (r'(?![a-z0-9_])' if n.isascii() else '')
                       for n in names)
    # Beginning of a message/clause, or a vocative at the end after a separator.
    return (re.compile(r'(?:^|[，,。.!！?？;；\n])' + _SEPARATORS + _GREETING + r'(?:' + aliases + r')'),
            re.compile(r'[\s，,:：、](?:' + aliases + r')' + _SEPARATORS + r'$'))


_PATTERNS = _patterns()


def called_by_name(content):
    if not _PATTERNS or not isinstance(content, str):
        return False
    lines = []
    fence = None
    for line in content[:8000].splitlines():
        stripped = line.lstrip()
        if stripped.startswith('>>>'):
            break  # Discord's multi-line quotation consumes the remaining message.
        marker = stripped[:3]
        if marker in ('```', '~~~'):
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence or stripped.startswith('>'):
            continue
        # Replace quoted spans with a non-name marker, preserving address boundaries.
        lines.append(_QUOTED.sub(' [引用] ', stripped).replace('**', '').replace('__', ''))
    text = unicodedata.normalize('NFKC', '\n'.join(lines)).casefold()
    return any(pattern.search(text) is not None for pattern in _PATTERNS)
