"""One deadline covers nested generation, retries, tools and provider fallbacks."""
import asyncio
import contextvars
import functools
import logging
import time

log = logging.getLogger(__name__)
_generation_active = contextvars.ContextVar("generation_active", default=False)
GENERATION_TIMEOUT = 140.0


def bounded_generation(func):
    @functools.wraps(func)
    async def wrapped(*args, **kwargs):
        if _generation_active.get():
            return await func(*args, **kwargs)
        token = _generation_active.set(True)
        started = time.monotonic()
        outcome = "failed"
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), GENERATION_TIMEOUT)
            outcome = "ok"
            return result
        except asyncio.TimeoutError:
            outcome = "deadline"
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            _generation_active.reset(token)
            log.info("Generation timing: method=%s status=%s seconds=%.2f",
                     func.__name__, outcome, time.monotonic() - started)
    return wrapped
