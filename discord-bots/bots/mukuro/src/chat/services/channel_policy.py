"""Shared policy for unsolicited text; directed replies and reactions stay available."""
import json
from functools import lru_cache
from pathlib import Path

DEFAULT_BLOCKED_CHANNELS = frozenset({0})
POLICY_PATH = Path('config/channel_policy.json')


@lru_cache(maxsize=4)
def _load(path, stamp):
    try:
        values = json.loads(Path(path).read_text(encoding='utf-8'))['proactive_blocked_channel_ids']
        if not isinstance(values, list) or len(values) > 256:
            raise ValueError('Invalid channel policy')
        result = frozenset(int(value) for value in values)
        if any(value <= 0 or value >= 2**64 for value in result):
            raise ValueError('Invalid channel ID')
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return DEFAULT_BLOCKED_CHANNELS


def may_send_automatic_message(channel):
    """Match the text channel itself and threads underneath it."""
    try:
        stat = POLICY_PATH.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    blocked = _load(str(POLICY_PATH.resolve()), stamp)
    ids = {getattr(channel, key, None) for key in ('id', 'parent_id')}
    return not any(isinstance(value, int) and value in blocked for value in ids)
