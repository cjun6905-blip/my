"""Keep this underage original character's images and literal speech nonsexual."""
import re
EXPLICIT=re.compile(r'色情|全裸|裸体|脱光|乳头|阴部|自慰|做爱|性交|性行为|潮吹|淫荡|露点|强奸|porn|nude|naked|nsfw|masturbat|sexual|sex\s*(?:scene|act)|erotic',re.I)
def inappropriate_media(text):return bool(EXPLICIT.search(text or ''))
