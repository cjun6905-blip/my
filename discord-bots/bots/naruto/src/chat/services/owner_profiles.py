"""Verified control identities for independent personal-avatar profiles."""
from src import config
PROFILES = {
    'sasuke': (0, 'aireck', '佐助', '冷静、简洁、克制'),
    'naruto': (0, 'mhxy', '鸣人', '热情、直率、有活力、关心同伴'),
}
OWNER, OWNER_NAME, ROLE_NAME, ROLE_TONE = PROFILES[config.PROFILE_KEY]
STATE_KEY = config.PROFILE_KEY + '_proxy'
