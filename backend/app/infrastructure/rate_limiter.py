"""Fixed-window rate limiting on top of the `limits` library.

Counters live in Redis so that every API process shares them. If Redis stops
answering, counting switches to process memory for `retry_after` seconds and
a warning is logged: limits stay enforced (per process) instead of failing
open or breaking requests.
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from limits import RateLimitItem, parse
from limits.storage import MemoryStorage, Storage, storage_from_string
from limits.strategies import FixedWindowRateLimiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until the window resets (0 when allowed)


class RateLimiter:
    def __init__(
        self,
        storage_uri: str,
        *,
        retry_primary_after: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if storage_uri.startswith("memory://"):
            primary: Storage = MemoryStorage()
        else:
            storage = storage_from_string(
                storage_uri, socket_connect_timeout=0.5, socket_timeout=0.5
            )
            if not isinstance(storage, Storage):
                raise ValueError(f"unsupported rate-limit storage: {storage_uri}")
            primary = storage
        self._primary = FixedWindowRateLimiter(primary)
        self._fallback = FixedWindowRateLimiter(MemoryStorage())
        self._retry_primary_after = retry_primary_after
        self._clock = clock
        self._primary_down_until = 0.0

    def hit(self, limit: str | RateLimitItem, key: str) -> Decision:
        item = parse(limit) if isinstance(limit, str) else limit
        if self._clock() >= self._primary_down_until:
            try:
                return self._hit(self._primary, item, key)
            except Exception as exc:  # any storage failure: degrade, not 500
                logger.warning(
                    "rate limit storage unavailable (%s); counting in memory "
                    "for %.0f s",
                    type(exc).__name__,
                    self._retry_primary_after,
                )
                self._primary_down_until = self._clock() + self._retry_primary_after
        return self._hit(self._fallback, item, key)

    @staticmethod
    def _hit(
        limiter: FixedWindowRateLimiter, item: RateLimitItem, key: str
    ) -> Decision:
        if limiter.hit(item, key):
            return Decision(allowed=True, retry_after=0)
        reset_at = limiter.get_window_stats(item, key).reset_time
        return Decision(
            allowed=False, retry_after=max(1, math.ceil(reset_at - time.time()))
        )
