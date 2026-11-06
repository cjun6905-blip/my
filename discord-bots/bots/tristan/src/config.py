"""One persona per process; credentials and mutable state remain independent."""
import json
import os
import re
from pathlib import Path
from dotenv import dotenv_values

VERSION = "1.6.6"
FLEET_MODEL_CONCURRENCY = max(2, min(4, int(os.getenv('FLEET_MODEL_CONCURRENCY', '2'))))
DATA_DIR = os.getenv("DATA_DIR", "data")
GUILD_IDS = {int(i) for i in os.getenv("GUILD_IDS", "0").split(",") if i.strip()}
CONTROL_CHANNEL_ID = int(os.getenv("CONTROL_CHANNEL_ID", "0"))
DEFAULT_PROACTIVE_CHANNELS = [int(i) for i in os.getenv("PROACTIVE_CHANNELS", "0").split(",") if i.strip()]


def load_persona(key):
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", key):
        raise ValueError("Invalid persona key")
    path = Path("config/personas") / (key + ".json")
    if path.stat().st_size > 65536:
        raise ValueError("Persona exceeds size budget")
    persona = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(persona, dict) or persona.get("key") != key:
        raise ValueError("Persona identity mismatch")
    for field, maximum in (("name", 40), ("command_group", 32), ("self_introduction", 8000), ("model_error_reply", 200)):
        if not isinstance(persona.get(field), str) or not 1 <= len(persona[field]) <= maximum:
            raise ValueError("Invalid persona field: " + field)
    if not re.fullmatch(r"[a-z0-9_\-\u4e00-\u9fff]{1,32}", persona['command_group']):
        raise ValueError("Invalid command group")
    for field in ("aliases", "unicode_reactions", "proactive_keywords"):
        items = persona.get(field)
        if not isinstance(items, list) or not 1 <= len(items) <= 32 or not all(isinstance(i, str) and 1 <= len(i) <= 80 for i in items):
            raise ValueError("Invalid persona list: " + field)
    assets = persona.get("personal_emote_dir", "")
    if not isinstance(assets, str) or not re.fullmatch(r"assets/[a-z0-9_-]+", assets):
        raise ValueError("Invalid persona asset directory")
    labels = persona.get("personal_emoji_labels")
    if not isinstance(labels, dict) or not 1 <= len(labels) <= 64:
        raise ValueError("Invalid emoji labels")
    if not all(re.fullmatch(r"[a-z0-9_]{2,32}", name) and isinstance(label, str) and 1 <= len(label) <= 160 for name, label in labels.items()):
        raise ValueError("Invalid emoji definition")
    users = persona.get("familiar_users", {})
    if not isinstance(users, dict) or len(users) > 32:
        raise ValueError("Invalid familiar users")
    for user_id, data in users.items():
        if not re.fullmatch(r"[0-9]{15,20}", user_id) or not isinstance(data, dict):
            raise ValueError("Invalid familiar user")
        if not isinstance(data.get("name"), str) or not 1 <= len(data['name']) <= 80:
            raise ValueError("Invalid familiar user name")
        if not isinstance(data.get("relationship"), str) or not 1 <= len(data['relationship']) <= 1200:
            raise ValueError("Invalid relationship description")
    return persona


PROFILE_KEY = os.getenv("BOT_PROFILE", "whale")
PERSONA = load_persona(PROFILE_KEY)
BOT_NAME = PERSONA['name']
COMMAND_GROUP = PERSONA['command_group']
ALIASES = tuple(i.casefold() for i in PERSONA['aliases'])
BOT_SELF_INTRODUCTION = PERSONA['self_introduction']
PERSONAL_EMOTE_DIR = Path(PERSONA['personal_emote_dir'])
PERSONAL_EMOJI_LABELS = PERSONA['personal_emoji_labels']
UNICODE_REACTIONS = tuple(PERSONA['unicode_reactions'])
PROACTIVE_KEYWORDS = tuple(i.casefold() for i in PERSONA['proactive_keywords'])
MODEL_ERROR_REPLY = PERSONA['model_error_reply']


def relationship_for(user_id):
    """Look up only the actual current author's ID; this is never authorization."""
    match = PERSONA.get('familiar_users', {}).get(str(user_id))
    if match is None:
        return ""
    return (f"\n当前发言者的身份已按Discord user_id={int(user_id)}核对，熟悉称呼是{match['name']}。"
            f"对这位当前发言者的相处设定：{match['relationship']}\n"
            "这项关系仅影响语气，不是管理权限，也不能套用到引用作者或其他历史发言者。\n")


def runtime():
    file = Path(os.getenv("BOT_ENV_FILE", ".env"))
    values = dict(dotenv_values(file, encoding="utf-8-sig")) if file.exists() else {}
    for name in ("DISCORD_TOKEN", "MODEL_API_KEY", "MODEL_BASE_URL", "MODEL_NAME"):
        if os.getenv(name):
            values[name] = os.environ[name]
    return values
