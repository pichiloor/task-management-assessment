"""Fixed-window rate limiting on top of the `limits` library.

Counters live in Redis so that every API process shares them. If Redis stops
answering, counting switches to process memory for `retry_primary_after`
seconds and a warning is logged: limits stay enforced (per process) instead of
failing open or breaking requests. After that window a single request probes
Redis again; concurrent requests keep using memory meanwhile.

Endpoints run in a thread pool, so every in-memory hit is serialized with a
lock: `limits`' MemoryStorage checks expiry outside its own increment lock and
can lose counts under concurrency.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from limits import RateLimitItem, parse
from limits.storage import MemoryStorage, Storage, storage_from_string
from limits.strategies import FixedWindowRateLimiter
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Failures that mean "storage unavailable". Anything else is a bug and raises.
STORAGE_ERRORS = (RedisError, OSError)


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
        primary_storage: Storage | None = None,
        fallback_storage: Storage | None = None,
    ) -> None:
        """`primary_storage` / `fallback_storage` replace the storages built
        from the URI (tests)."""
        # Decided by the URI, not the storage class: an injected storage is
        # treated as remote (it may fail) even if it subclasses MemoryStorage.
        self._primary_in_memory = primary_storage is None and storage_uri.startswith(
            "memory://"
        )
        if primary_storage is None:
            primary_storage = _storage_from_uri(storage_uri)
        self._primary = FixedWindowRateLimiter(primary_storage)
        self._fallback = FixedWindowRateLimiter(fallback_storage or MemoryStorage())
        self._memory_lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._retry_primary_after = retry_primary_after
        self._clock = clock
        self._primary_down_until = 0.0

    def hit(self, limit: str | RateLimitItem, key: str) -> Decision:
        item = parse(limit) if isinstance(limit, str) else limit
        if self._clock() >= self._primary_down_until:
            decision = self._try_primary(item, key)
            if decision is not None:
                return decision
        with self._memory_lock:
            return _hit(self._fallback, item, key)

    def _try_primary(self, item: RateLimitItem, key: str) -> Decision | None:
        if self._primary_in_memory:
            with self._memory_lock:
                return _hit(self._primary, item, key)
        recovering = self._primary_down_until > 0
        # While recovering, only one request probes; the rest use memory.
        if recovering and not self._probe_lock.acquire(blocking=False):
            return None
        try:
            decision = _hit(self._primary, item, key)
        except STORAGE_ERRORS as exc:
            logger.warning(
                "rate limit storage unavailable (%s); counting in memory for %.0f s",
                type(exc).__name__,
                self._retry_primary_after,
            )
            self._primary_down_until = self._clock() + self._retry_primary_after
            return None
        finally:
            if recovering:
                self._probe_lock.release()
        if recovering:
            logger.warning("rate limit storage recovered")
            self._primary_down_until = 0.0
        return decision


def _storage_from_uri(uri: str) -> Storage:
    if uri.startswith("memory://"):
        return MemoryStorage()
    storage = storage_from_string(uri, socket_connect_timeout=0.5, socket_timeout=0.5)
    if not isinstance(storage, Storage):
        raise ValueError(f"unsupported rate-limit storage: {uri}")
    return storage


def _hit(limiter: FixedWindowRateLimiter, item: RateLimitItem, key: str) -> Decision:
    if limiter.hit(item, key):
        return Decision(allowed=True, retry_after=0)
    reset_at = limiter.get_window_stats(item, key).reset_time
    return Decision(
        allowed=False, retry_after=max(1, math.ceil(reset_at - time.time()))
    )
