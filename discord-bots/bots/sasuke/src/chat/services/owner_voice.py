"""Evidence-balanced style and a small, separate cache of our delivered wording."""
import re
import time
import unicodedata
from collections import OrderedDict, deque

QUOTED = re.compile(r'[“「『‘"\u2018][^”」』’"\n]{1,80}[”」』’"\u2019]')


def abstract_style(style):
    result = {}
    for key, value in style.items():
        if key == 'common_phrases':
            # Legacy summaries promoted isolated quotations to global catchphrases.
            # Lexical examples are not a reusable response menu.
            result[key] = '按当前内容组织口语表达，不套固定开头、评价或句尾；不列举或复刻样本原句。' if value else ''
        else:
            value = QUOTED.sub('', value)
            value = re.sub(r'[（(]\s*如[^）)]*[）)]', '', value)
            result[key] = re.sub(r'如\s*[、，；）)]', '', value).strip()
    return result


def balanced_rows(rows, limit=60):
    """Chronologically spread distinct samples; copied variants get one vote."""
    unique = []; seen = set()
    for text, at in rows:
        key = re.sub(r'<a?:[^>]+>|[\W_]+', '', unicodedata.normalize('NFKC', text)).casefold()
        if not key or key in seen: continue
        seen.add(key); unique.append((text, at))
    unique.sort(key=lambda row: row[1])
    if len(unique) <= limit: return unique
    return [unique[i*(len(unique)-1)//(limit-1)] for i in range(limit)]


def normalized(text):
    text = re.sub(r'<a?:[^>]+>', '', text)
    return ''.join(c.casefold() for c in unicodedata.normalize('NFKC', text) if c.isalnum())


class VoiceGuard:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.rows = deque(maxlen=24)
        self.ids = OrderedDict()

    def record(self, mid, channel, text, at=None):
        at = self.clock() if at is None else at
        if not text or at < self.clock()-7200 or mid in self.ids: return
        if re.search(r'PRIVATE KEY|DISCORD_TOKEN|API_KEY|Bearer\s',text,re.I): return
        text = re.sub(r'<a?:[^>]+>|https?://\S+|<@!?\d+>', '', text)
        text = re.sub(r'\b(?:sk-|duck_|ghp_|github_pat_)[A-Za-z0-9_\-]+|[A-Za-z0-9_\-]{30,}(?:\.[A-Za-z0-9_\-]+)*','[已过滤]',text)
        self.ids[mid] = at
        self.ids = OrderedDict(sorted(self.ids.items(),key=lambda row:row[1])[-64:])
        self.rows = deque(sorted(list(self.rows)+[(at,channel,text[:400])])[-24:],maxlen=24)

    def recent(self, channel):
        rows = [r for r in self.rows if r[0] >= self.clock()-7200]
        local = [r for r in rows if r[1] == channel][-6:]
        return [r[2][:180] for r in sorted(local) if r[2]]

    def reason(self, channel, text, current):
        # Only short conversational output; don't rewrite factual/code answers.
        if not 5 <= len(text) <= 160 or re.search(r'https?://|```|\d|[=+*/]',text): return ''
        key = normalized(text)
        if len(key)<5 or key in normalized(current): return ''
        recent = self.recent(channel)
        old = [normalized(t) for t in recent]
        if key in old: return '重复了近期已经发出的短句'
        # Restrict motifs to the opening/ending of the short reply and require
        # two previous occurrences. Topic terms in the middle are not banned.
        for size in range(min(12,len(key)),4,-1):
            for motif in (key[:size],key[-size:]):
                if motif not in normalized(current) and sum(motif in r for r in old)>=2:
                    return '重复了近期多次使用的开头或收尾评价'
        return ''


voice_guard = VoiceGuard()
