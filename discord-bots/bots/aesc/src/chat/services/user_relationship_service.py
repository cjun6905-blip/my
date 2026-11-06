"""A small per-user tone overlay; never used for authorization or point changes."""
import json
import logging
from pathlib import Path

_path = Path('config/persona_relationships.json')
try:
    if _path.stat().st_size > 65536:
        raise ValueError('Relationship configuration exceeds size limit')
    _relationships = json.loads(_path.read_text(encoding='utf-8'))['familiar_users']
except (OSError, ValueError, KeyError, TypeError):
    logging.getLogger(__name__).warning('Persona relationship configuration unavailable')
    _relationships = {}


def with_user_relationship(author, affection_status):
    """Match only the authenticated current author, preserving the original status."""
    if getattr(author, 'bot', False):
        return affection_status
    user_id = getattr(author, 'id', None)
    if type(user_id) is not int:
        return affection_status
    relation = _relationships.get(str(user_id))
    if not isinstance(relation, dict) or not isinstance(relation.get('relationship'), str):
        return affection_status
    result = dict(affection_status or {})
    result['prompt'] = str(result.get('prompt', '')) + '\n' + relation['relationship']
    return result
