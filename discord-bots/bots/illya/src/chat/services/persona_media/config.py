import json,pathlib
VERSION='media-1.6.18'
settings=json.loads(pathlib.Path('config/persona_media.json').read_text(encoding='utf-8'))
PROFILE_KEY=settings['profile'];BOT_NAME=settings['name'];ALIASES=tuple(settings['aliases']);PERSONA={'aliases':ALIASES}
BOT_SELF_INTRODUCTION=settings['voice']+'\n你的外观：'+settings['appearance']+'\n保持当前角色个性。用户要求自拍是生成角色插画，未实际送出前不得声称已经完成。'
PERSONAL_EMOJI_LABELS={};UNICODE_REACTIONS=('😂','🐷','✨');PROACTIVE_KEYWORDS=ALIASES
DATA_DIR='data'
def relationship_for(user_id):
 try:
  from types import SimpleNamespace
  from src.chat.services.user_relationship_service import with_user_relationship
  return with_user_relationship(SimpleNamespace(id=int(user_id),bot=False),'') or ''
 except ImportError:return ''
