"""Fixed-window rate limiting.

Counters live in Redis (through the `limits` library) so that every API
process shares them. If Redis stops answering, counting switches to process
memory for `retry_primary_after` seconds and a warning is logged: limits stay
enforced (per process) instead of failing open or breaking requests. After
that window a single request probes Redis again; concurrent requests keep
using memory meanwhile. State changes carry a generation number: an attempt
publishes its outcome only if no other outcome was published since it began,
so a slow, stale failure cannot undo a later recovery (or vice versa).

The in-memory counter is our own: `limits`' MemoryStorage checks expiry
outside its increment lock and deletes keys from a background timer thread,
so it loses counts under the thread pool that runs FastAPI endpoints.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from limits import RateLimitItem, parse
from limits.storage import Storage, storage_from_string
from limits.strategies import FixedWindowRateLimiter
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Failures that mean "storage unavailable". Anything else is a bug and raises.
STORAGE_ERRORS = (RedisError, OSError)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until the window resets (0 when allowed)


class InMemoryFixedWindow:
    """Thread-safe fixed-window counter: read, reset and increment happen
    under one lock. Expired windows are pruned every `prune_every` hits, in
    the calling thread (no background threads). Memory grows with the
    number of distinct keys whose windows are still open, plus expired
    entries not yet pruned (a documented limitation of a per-process
    fallback)."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        prune_every: int = 1000,
    ) -> None:
        self._clock = clock
        self._prune_every = prune_every
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}  # key -> (ends_at, hits)
        self._hits_since_prune = 0

    def hit(self, item: RateLimitItem, key: str) -> Decision:
        full_key = item.key_for(key)  # includes namespace, amount and period
        with self._lock:
            now = self._clock()
            ends_at, hits = self._windows.get(full_key, (0.0, 0))
            if now >= ends_at:
                ends_at, hits = now + item.get_expiry(), 0
            self._maybe_prune(now)
            if hits >= item.amount:
                return Decision(
                    allowed=False, retry_after=max(1, math.ceil(ends_at - now))
                )
            self._windows[full_key] = (ends_at, hits + 1)
            return Decision(allowed=True, retry_after=0)

    def size(self) -> int:
        with self._lock:
            return len(self._windows)

    def _maybe_prune(self, now: float) -> None:
        self._hits_since_prune += 1
        if self._hits_since_prune >= self._prune_every:
            self._hits_since_prune = 0
            expired = [k for k, (ends_at, _) in self._windows.items() if now >= ends_at]
            for k in expired:
                del self._windows[k]


class RateLimiter:
    def __init__(
        self,
        storage_uri: str,
        *,
        retry_primary_after: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        primary_storage: Storage | None = None,
        fallback: InMemoryFixedWindow | None = None,
    ) -> None:
        """`primary_storage` replaces the storage built from the URI and is
        always treated as remote; `fallback` replaces the memory counter."""
        self._memory_primary: InMemoryFixedWindow | None = None
        self._primary: FixedWindowRateLimiter | None = None
        if primary_storage is None and storage_uri.startswith("memory://"):
            self._memory_primary = InMemoryFixedWindow()
        else:
            self._primary = FixedWindowRateLimiter(
                primary_storage or _storage_from_uri(storage_uri)
            )
        self._fallback = fallback or InMemoryFixedWindow()
        self._probe_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._retry_primary_after = retry_primary_after
        self._clock = clock
        self._primary_down_until = 0.0
        self._generation = 0

    def hit(self, limit: str | RateLimitItem, key: str) -> Decision:
        item = parse(limit) if isinstance(limit, str) else limit
        if self._memory_primary is not None:
            return self._memory_primary.hit(item, key)
        with self._state_lock:
            down_until, generation = self._primary_down_until, self._generation
        if self._clock() >= down_until:
            decision = self._try_primary(item, key, down_until, generation)
            if decision is not None:
                return decision
        return self._fallback.hit(item, key)

    def _try_primary(
        self, item: RateLimitItem, key: str, down_until: float, generation: int
    ) -> Decision | None:
        assert self._primary is not None
        if down_until == 0.0:
            # Healthy: no probe coordination; a failure starts the backoff.
            try:
                return _hit(self._primary, item, key)
            except STORAGE_ERRORS as exc:
                self._publish(generation, exc)
                return None
        # Recovering: one probe at a time.
        if not self._probe_lock.acquire(blocking=False):
            return None
        try:
            with self._state_lock:
                if generation != self._generation or (
                    self._clock() < self._primary_down_until
                ):
                    return None  # another outcome was published meanwhile
            try:
                decision = _hit(self._primary, item, key)
            except STORAGE_ERRORS as exc:
                self._publish(generation, exc)
                return None
            self._publish(generation, None)
            return decision
        finally:
            self._probe_lock.release()

    def _publish(self, generation: int, failure: Exception | None) -> None:
        """Records an attempt's outcome unless a newer one was recorded."""
        with self._state_lock:
            if generation != self._generation:
                return  # stale: something happened after this attempt began
            self._generation += 1
            if failure is None:
                self._primary_down_until = 0.0
                logger.warning("rate limit storage recovered")
            else:
                self._primary_down_until = self._clock() + self._retry_primary_after
                logger.warning(
                    "rate limit storage unavailable (%s); counting in memory "
                    "for %.0f s",
                    type(failure).__name__,
                    self._retry_primary_after,
                )


def _storage_from_uri(uri: str) -> Storage:
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
