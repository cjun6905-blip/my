"""One small external-model client. Never log credentials, prompts or bodies."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import aiohttp
from src.config import runtime, FLEET_MODEL_CONCURRENCY
from src.chat.services.fleet_budget import fleet_budget, BudgetError
from .providers.base import GenerationConfig, GenerationResult

log = logging.getLogger(__name__)


class ModelError(RuntimeError):
    def __init__(self, message, *, code="request_failed", status=None, retryable=False):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable


REQUEST_TIMEOUT = 90
GENERATION_TIMEOUT = 120
INTERACTIVE_QUEUE_WAIT = 125
DIALOGUE_QUEUE_WAIT = 30
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class AIService:
    def __init__(self):
        self.session = None
        self.slots = asyncio.Semaphore(FLEET_MODEL_CONCURRENCY)
        self.calls = 0
        self.failures = 0

    @asynccontextmanager
    async def _traffic_slot(self, traffic):
        if traffic == "interactive":
            yield True
        else:
            # Automated conversation may occupy only one of the two model slots.
            async with fleet_budget.slot('automated-model', 1,
                    wait=DIALOGUE_QUEUE_WAIT if traffic == 'dialogue' else 0) as admitted:
                yield admitted

    async def generate(self, messages, config=None, model=None, tools=None, traffic="interactive", **kwargs):
        if traffic not in {"interactive", "dialogue", "background"}:
            raise ValueError("Unknown model traffic class")
        started = time.monotonic()
        try:
            async with self._traffic_slot(traffic) as admitted:
                if not admitted:
                    raise ModelError("Automated model request capacity reached", code="busy")
                queue_wait = INTERACTIVE_QUEUE_WAIT if traffic == 'interactive' else (
                    DIALOGUE_QUEUE_WAIT if traffic == 'dialogue' else 0)
                async with fleet_budget.slot('model', FLEET_MODEL_CONCURRENCY, wait=queue_wait,
                        priority=traffic == 'interactive') as admitted:
                    if not admitted:
                        raise ModelError("Fleet model request capacity reached", code="busy")
                    queued = time.monotonic() - started
                    result = await self._generate_local(messages, config, model, tools, **kwargs)
                    log.info('model_request_complete traffic=%s queue=%.2f generation=%.2f',
                        traffic, queued, time.monotonic() - started - queued)
                    return result
        except BudgetError:
            raise ModelError("Fleet model request capacity unavailable", code="budget_unavailable") from None
        except ModelError as exc:
            report = log.info if exc.code == 'busy' and traffic == 'background' else log.warning
            report("model_request_failed code=%s status=%s traffic=%s elapsed=%.2f",
                exc.code, exc.status, traffic, time.monotonic() - started)
            raise

    async def _generate_local(self, messages, config=None, model=None, tools=None, **kwargs):
        if tools:
            raise ModelError("This lightweight client does not execute model tools", code="tools_disabled")
        credentials = runtime()
        base = (credentials.get("MODEL_BASE_URL") or "").rstrip("/")
        key = credentials.get("MODEL_API_KEY") or ""
        model = model or credentials.get("MODEL_NAME")
        if not base or not key or not model or urlsplit(base).scheme != "https":
            raise ModelError("External model configuration is incomplete", code="configuration")
        config = config or GenerationConfig()
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=10),
                connector=aiohttp.TCPConnector(limit=4, ttl_dns_cache=300))
        # Bound queued work as well as concurrent generation.
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=5)
        except asyncio.TimeoutError:
            raise ModelError("Model request capacity reached", code="busy") from None
        try:
            # One overall deadline also bounds a retry after a slow attempt.
            async with asyncio.timeout(GENERATION_TIMEOUT):
                for attempt in range(2):
                    self.calls += 1
                    try:
                        async with self.session.post(base + "/chat/completions",
                            headers={"Authorization": "Bearer " + key},
                            json={"model": model, "messages": messages,
                                  "temperature": config.temperature,
                                  "max_tokens": min(config.max_output_tokens, 2048)}) as response:
                            if response.status != 200:
                                raise ModelError("Model HTTP status " + str(response.status),
                                    code="http_status", status=response.status,
                                    retryable=response.status in RETRY_STATUSES)
                            # Refuse unbounded outputs from a misconfigured upstream.
                            raw = bytearray()
                            async for chunk in response.content.iter_chunked(16384):
                                raw.extend(chunk)
                                if len(raw) > 1024 * 1024:
                                    raise ModelError("Model response exceeded size budget", code="response_size")
                            try:
                                payload = json.loads(raw)
                                text = payload["choices"][0]["message"].get("content") or ""
                            except (ValueError, KeyError, IndexError, TypeError):
                                raise ModelError("Invalid model response", code="invalid_response", retryable=True) from None
                            if not isinstance(text, str) or not text.strip():
                                raise ModelError("Empty model response", code="empty_response", retryable=True)
                            return GenerationResult(text.strip(), model)
                    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        failure = ModelError("Model request failed", code="timeout" if isinstance(exc, asyncio.TimeoutError)
                                             else "connection", retryable=True)
                    except ModelError as exc:
                        failure = exc
                    if attempt == 0 and failure.retryable:
                        log.info("model_request_retry code=%s status=%s", failure.code, failure.status)
                        await asyncio.sleep(1)
                        continue
                    raise failure from None
        except asyncio.TimeoutError:
            self.failures += 1
            raise ModelError("Model generation deadline reached", code="timeout") from None
        except ModelError:
            self.failures += 1
            raise
        finally:
            self.slots.release()

    async def close(self):
        if self.session:
            await self.session.close()


ai_service = AIService()
