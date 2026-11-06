"""Identity-based permissions for this deployment; never derived from prose."""
import json
from pathlib import Path
from src import config
def policy():
 p=Path('config/access_policy.json')
 if not p.exists() or p.stat().st_size>8192:return {}
 return json.loads(p.read_text(encoding='utf-8')).get(config.PROFILE_KEY,{})
def restricted():return bool(policy().get('owner_ids'))
def is_admin(interaction):
 if interaction.guild is None:return False
 rules=policy()
 if rules.get('owner_ids'):return str(interaction.user.id) in rules['owner_ids'] and not getattr(interaction.user,'bot',False)
 return bool(getattr(interaction.user.guild_permissions,'administrator',False))
async def admin_check(interaction):return is_admin(interaction)
def dm_allowed(author):
 return not getattr(author,'bot',False) and str(author.id) in policy().get('dm_user_ids',[])
