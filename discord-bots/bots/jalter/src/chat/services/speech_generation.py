"""On-demand, bounded cloud TTS. No voice-channel connection or local model."""
import asyncio
import io
import json
import logging
import os
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from dotenv import dotenv_values
from src import config
from src.chat.services.fleet_budget import fleet_budget, BudgetError
from src.chat.services.vision import decode_memory_available

log = logging.getLogger(__name__)
MAX_AUDIO = 6 * 1024 * 1024
TIMEOUT = 90
NEGATIVE = re.compile(r'(?:不要|不用|别|不必|取消|停止).{0,8}(?:语音|朗读|念出|读出|tts)', re.I)
LITERAL = re.compile(r'^(?:请|帮我|给我|麻烦你)?\s*(?:朗读|读出|念出|念一下|读一下|用语音说|用语音朗读)\s*[:：]\s*(.+)$', re.S)
VOICE = re.compile(r'(?:用语音(?:回复|回答|说|讲|念|读)|语音(?:回复|回答)|(?:发|来)(?:一)?(?:段|条|个)语音|(?:给我|帮我)发语音|(?:把|将).{0,12}(?:读出来|念出来)|用声音(?:说|回答)|朗读一下)')


class SpeechError(RuntimeError):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class SpeechRequest:
    # None means narrate the character's new answer, not the user's instruction.
    text: str | None = None


@dataclass(frozen=True)
class GeneratedSpeech:
    data: bytes
    seconds: float
    language: str = "Chinese"
    gloss: str = ""


def settings():
    try:
        path = Path('config/speech_generation.json')
        if path.stat().st_size > 16384:
            return {}
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def clean_text(text):
    text = re.sub(r'<(?:@!?|@&|#)\d+>|<a?:\w+:\d+>', '', text or '')
    text = re.sub(r'[`*_~]', '', text).strip()
    # StepAudio interprets ASCII parentheticals as instructions. Literal readings
    # should keep their words instead of turning user text into voice controls.
    return text.replace('(', '（').replace(')', '）')


def request_for(text, own_reference=None):
    if config.PROFILE_KEY not in settings().get('enabled_profiles', []):
        return None
    text = re.sub(r'<@!?\d+>', '', text or '').strip()
    if not text or len(text) > 3000 or NEGATIVE.search(text):
        return None
    literal = LITERAL.fullmatch(text)
    if literal:
        return SpeechRequest(clean_text(literal[1]))
    if not VOICE.search(text):
        return None
    if own_reference and re.search(r'这句|这段|刚才|上一句|再说|读出来|念出来', text):
        previous = clean_text(getattr(own_reference, 'content', ''))
        if previous:
            return SpeechRequest(previous)
    return SpeechRequest()


def with_speech_instruction(messages,request):
    if request:
        from src.chat.services.speech_decision import INSTRUCTIONS
        messages[0]['content'] += '\n'+INSTRUCTIONS
    return messages

def validate_audio(raw):
    try:
        if not raw or len(raw) > MAX_AUDIO or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
            raise ValueError()
        with wave.open(io.BytesIO(raw), 'rb') as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if (rate not in (8000, 16000, 22050, 24000, 48000) or wav.getnchannels() not in (1, 2)
                    or wav.getsampwidth() not in (1, 2, 3, 4) or not 0 < frames / rate <= 120):
                raise ValueError()
            if len(wav.readframes(frames)) != frames * wav.getnchannels() * wav.getsampwidth():
                raise ValueError()
            return GeneratedSpeech(bytes(raw), frames / rate)
    except (ValueError, wave.Error, EOFError):
        raise SpeechError('invalid_audio') from None


class SpeechGenerationService:
    async def enabled(self):
        return config.PROFILE_KEY in settings().get("enabled_profiles", [])

    async def generate(self, text, user_id):
        cfg = settings()
        if config.PROFILE_KEY not in cfg.get('enabled_profiles', []):
            raise SpeechError('disabled')
        text = clean_text(text)
        if not text or len(text) > 500:
            raise SpeechError('too_long')
        # Fixed trusted origin; no Discord URL/model/credential input.
        if cfg.get('base_url') != 'https://api.stepfun.com/step_plan/v1':
            raise SpeechError('configuration')
        path = Path(os.getenv('SPEECH_ENV_FILE', '/run/secrets/speech.env'))
        values = dotenv_values(path, encoding='utf-8-sig') if path.is_file() else {}
        key = values.get('STEPFUN_API_KEY')
        if not key or not fleet_budget.path:
            raise SpeechError('configuration')
        token, success, started = None, False, time.monotonic()
        try:
            async with fleet_budget.slot('speech-generation', 1, wait=0, ttl=TIMEOUT + 30) as admitted:
                if not admitted or not decode_memory_available():
                    raise SpeechError('busy')
                token = await fleet_budget.acquire('speech-user:' + str(int(user_id)), 1, 10)
                if not token:
                    raise SpeechError('cooldown')
                payload = {'model': cfg.get('model', 'stepaudio-2.5-tts'), 'input': text,
                    'voice': cfg.get('voices', {}).get(config.PROFILE_KEY, 'lively-girl'),
                    'language': 'zh', 'response_format': 'wav', 'sample_rate': 24000,
                    'speed': 1.0, 'instruction': cfg.get('instructions', {}).get(config.PROFILE_KEY, '')}
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT, connect=10),
                        connector=aiohttp.TCPConnector(limit=1)) as session:
                    async with session.post(cfg['base_url'] + '/audio/speech', json=payload,
                            headers={'Authorization': 'Bearer ' + key}, allow_redirects=False) as response:
                        if response.status != 200:
                            raise SpeechError('upstream', response.status)
                        if response.content_length and response.content_length > MAX_AUDIO:
                            raise SpeechError('oversize')
                        raw = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            if len(raw) + len(chunk) > MAX_AUDIO:
                                raise SpeechError('oversize')
                            raw.extend(chunk)
                audio = validate_audio(raw)
                success = True
                log.info('speech_complete profile=%s bytes=%s seconds=%.2f',
                    config.PROFILE_KEY, len(audio.data), time.monotonic() - started)
                return audio
        except asyncio.TimeoutError:
            raise SpeechError('timeout') from None
        except aiohttp.ClientError:
            raise SpeechError('connection') from None
        except BudgetError:
            raise SpeechError('busy') from None
        finally:
            if token and not success:
                try:
                    await asyncio.shield(fleet_budget.release(token))
                except BudgetError:
                    log.warning('speech_cooldown_release_failed')


speech_generation = SpeechGenerationService()
