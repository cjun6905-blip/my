"""Bounded Discord image input. Image bytes stay in memory for one request only."""
import asyncio
import base64
import io
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import aiohttp
from PIL import Image, ImageOps
from src.chat.services.fleet_budget import fleet_budget

MAX_IMAGES, MAX_BYTES, MAX_PIXELS = 3, 8 * 1024 * 1024, 16_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
HOSTS = {'cdn.discordapp.com', 'media.discordapp.net', 'images-ext-1.discordapp.net', 'images-ext-2.discordapp.net'}
IMAGE_QUESTION = re.compile(r'识图|识别|看.{0,10}(图|照片|这|刚|上)|(?:图|照片|表情|贴纸).{0,8}(里|上|什么|啥|意思|内容|颜色)|这(?:张|幅)|这(?:个)?是(什么|啥)|刚才(?:的|那).{0,3}(图|照片)|image|picture|photo', re.I)


def sequence(obj, name):
    value = getattr(obj, name, ())
    return value if isinstance(value, (list, tuple)) else ()


def safe_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and url.hostname in HOSTS and url.port in (None, 443) and not url.username
    except ValueError:
        return False


def image_sources(message):
    if message is None:
        return []
    sources = []
    for item in sequence(message, 'attachments'):
        mime = getattr(item, 'content_type', '') or ''
        name = getattr(item, 'filename', '') or ''
        if (isinstance(mime, str) and mime.startswith('image/')) or (isinstance(name, str) and name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif'))):
            sources.append((getattr(item, 'url', ''), getattr(item, 'proxy_url', '')))
    for item in sequence(message, 'embeds'):
        # Only Discord's image proxy is fetched, never an arbitrary embedded site.
        for key in ('image', 'thumbnail'):
            proxy = getattr(getattr(item, key, None), 'proxy_url', None)
            if safe_url(proxy):
                sources.append((proxy,))
    for sticker in sequence(message, 'stickers'):
        sources.append((str(getattr(sticker, 'url', '')),))
    content = getattr(message, 'content', '')
    if isinstance(content, str):
        for emoji_id in re.findall(r'<a?:[^:\s<>]+:(\d{15,20})>', content):
            sources.append((f'https://cdn.discordapp.com/emojis/{emoji_id}.png?size=256',))
    return list(dict.fromkeys(sources))


def normalize(raw):
    with Image.open(io.BytesIO(raw), formats=('JPEG', 'PNG', 'WEBP', 'GIF')) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('pixel_limit')
        image.seek(0)  # Animated inputs use their first frame.
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        frame = ImageOps.exif_transpose(image).convert('RGBA')
        background = Image.new('RGB', frame.size, 'white')
        background.paste(frame, mask=frame.getchannel('A'))
        output = io.BytesIO()
        background.save(output, 'JPEG', quality=85, exif=b'', icc_profile=None)
        encoded = output.getvalue()
        if len(encoded) > 1536 * 1024:
            output = io.BytesIO()
            background.save(output, 'JPEG', quality=65, exif=b'', icc_profile=None)
            encoded = output.getvalue()
        if len(encoded) > 1536 * 1024:
            raise ValueError('encoded_limit')
        return 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode('ascii')


class VisionService:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)
        self.decode_slot = asyncio.Semaphore(1)
        self.inflight = asyncio.Semaphore(2)

    @asynccontextmanager
    async def processing(self, needed):
        # Hold this lease until model generation completes, so queued images
        # cannot accumulate while the provider is slow.
        if needed:
            try:
                await asyncio.wait_for(self.inflight.acquire(), timeout=3)
            except asyncio.TimeoutError:
                yield False
                return
        try:
            if needed:
                # Cover download (25s), model queue (125s) and generation (120s).
                async with fleet_budget.slot('vision', 1, wait=3, ttl=300) as admitted:
                    yield admitted
            else:
                yield True
        finally:
            if needed:
                self.inflight.release()

    async def download(self, http, urls):
        for url in urls:
            if not safe_url(url):
                continue
            try:
                async with http.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        continue
                    if response.content_length is not None and response.content_length > MAX_BYTES:
                        raise ValueError('byte_limit')
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ValueError('byte_limit')
                    return bytes(raw)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue
        raise ValueError('image_unavailable')

    async def load(self, message, reference=None):
        sources = [('当前消息', urls) for urls in image_sources(message)]
        sources += [('引用或刚才的消息', urls) for urls in image_sources(reference)]
        unique, seen = [], set()
        for origin, urls in sources:
            if urls and urls[0] not in seen:
                unique.append((origin, urls)); seen.add(urls[0])
        result = {'images': [], 'unavailable': [], 'omitted': max(0, len(unique) - MAX_IMAGES)}
        if not unique:
            return result
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=3)
        except asyncio.TimeoutError:
            result['unavailable'] = ['图片处理正忙，请稍后重试']
            return result
        try:
            async with asyncio.timeout(25), aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), trust_env=False) as http:
                for index, (origin, urls) in enumerate(unique[:MAX_IMAGES], 1):
                    label = f'图{index}（{origin}）'
                    try:
                        raw = await self.download(http, urls)
                        async with self.decode_slot:
                            uri = await asyncio.to_thread(normalize, raw)
                        result['images'].append({'label': label, 'url': uri})
                    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                        result['unavailable'].append(label + '读取失败：链接不可用、格式不支持或图片过大')
            return result
        except asyncio.TimeoutError:
            result['unavailable'].append('图片读取超时，请重新发送')
            return result
        finally:
            self.slots.release()


vision_service = VisionService()
