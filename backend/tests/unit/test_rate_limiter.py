import threading
import time

import pytest
from limits import parse
from limits.storage import MemoryStorage
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.infrastructure.rate_limiter import InMemoryFixedWindow, RateLimiter
from app.infrastructure.settings import RateLimitSettings

UNREACHABLE = "redis://127.0.0.1:1/0"


class SlowWindow(InMemoryFixedWindow):
    """Pauses between reading a counter and writing it back (pruning runs
    there). Without the lock, several threads read the same count and are
    all admitted."""

    def _maybe_prune(self, now: float) -> None:
        time.sleep(0.05)
        super()._maybe_prune(now)


class BrokenStorage(MemoryStorage):
    def __init__(self, error: Exception, delay: float = 0.0) -> None:
        super().__init__()
        self.error = error
        self.delay = delay
        self.calls = 0
        self._count_lock = threading.Lock()

    def incr(self, *args: object, **kwargs: object) -> int:
        with self._count_lock:
            self.calls += 1
        time.sleep(self.delay)
        raise self.error


def run_concurrently(n: int, target: object) -> list[object]:
    barrier = threading.Barrier(n)
    results: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        value = target()  # type: ignore[operator]
        with lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_hits_on_the_memory_fallback_are_not_lost() -> None:
    limiter = RateLimiter(
        UNREACHABLE,
        primary_storage=BrokenStorage(RedisConnectionError("down")),
        fallback=SlowWindow(),
    )
    limiter.hit("1/minute", "warm-up")  # marks the primary as down

    results = run_concurrently(8, lambda: limiter.hit("1/minute", "login:ip").allowed)

    assert results.count(True) == 1


def test_only_one_request_probes_redis_after_the_retry_window() -> None:
    now = [0.0]
    broken = BrokenStorage(RedisConnectionError("down"), delay=0.2)
    limiter = RateLimiter(
        UNREACHABLE,
        primary_storage=broken,
        retry_primary_after=30,
        clock=lambda: now[0],
    )
    limiter.hit("5/minute", "k")
    assert broken.calls == 1

    now[0] = 31.0
    run_concurrently(6, lambda: limiter.hit("100/minute", "k"))

    assert broken.calls == 2


def test_programming_errors_are_not_swallowed() -> None:
    limiter = RateLimiter(UNREACHABLE, primary_storage=BrokenStorage(TypeError("bug")))

    with pytest.raises(TypeError):
        limiter.hit("5/minute", "k")


def test_window_resets_after_its_period() -> None:
    limiter = RateLimiter("memory://")

    assert limiter.hit("1/second", "k").allowed
    blocked = limiter.hit("1/second", "k")
    assert not blocked.allowed and blocked.retry_after >= 1

    time.sleep(1.05)

    assert limiter.hit("1/second", "k").allowed


class TestSettings:
    @pytest.mark.parametrize(
        "value",
        [
            "100/second; 5/minute",
            "5/minute, 1/second",
            "0/minute",
            "5/0 seconds",
            "5 per 0 minute",
            "abc",
            "",
        ],
    )
    def test_ambiguous_or_degenerate_limits_are_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError):
            RateLimitSettings(storage_uri="memory://", login=value)

    @pytest.mark.parametrize(
        "value",
        [
            "5/minute",
            "120 per minute",
            "10/5 seconds",
            "5/MINUTE",
            "5/month",
            "5/2seconds",
        ],
    )
    def test_single_positive_limits_are_accepted(self, value: str) -> None:
        assert RateLimitSettings(storage_uri="memory://", api=value).api == value


class FlakyStorage(MemoryStorage):
    """Fails while `down` is set, then behaves like memory storage."""

    def __init__(self) -> None:
        super().__init__()
        self.down = True

    def incr(self, *args: object, **kwargs: object) -> int:
        if self.down:
            raise RedisConnectionError("down")
        return super().incr(*args, **kwargs)  # type: ignore[arg-type]


def test_redis_is_used_again_once_it_recovers() -> None:
    now = [0.0]
    flaky = FlakyStorage()
    limiter = RateLimiter(
        UNREACHABLE, primary_storage=flaky, retry_primary_after=30, clock=lambda: now[0]
    )
    limiter.hit("5/minute", "k")  # fails over to memory

    flaky.down = False
    now[0] = 10.0
    limiter.hit("5/minute", "k")
    assert flaky.storage == {}  # still inside the window: memory only

    now[0] = 31.0
    limiter.hit("5/minute", "k")
    limiter.hit("5/minute", "k")
    assert sum(flaky.storage.values()) == 2  # both counted in the primary


def test_memory_counter_has_no_background_cleanup_thread() -> None:
    # limits' MemoryStorage deletes expired keys from a timer thread that
    # bypasses any caller lock; the in-memory counter must not do that.
    before = threading.active_count()
    window = InMemoryFixedWindow()
    for i in range(50):
        window.hit(parse("1/second"), f"k{i}")

    assert threading.active_count() == before


def test_expired_windows_are_pruned() -> None:
    now = [0.0]
    window = InMemoryFixedWindow(clock=lambda: now[0], prune_every=10)
    for i in range(10):
        window.hit(parse("1/second"), f"k{i}")
    now[0] = 5.0
    for i in range(10):
        window.hit(parse("1/second"), f"new{i}")

    assert window.size() <= 10


def test_a_newer_failure_stops_a_pending_probe() -> None:
    # Simulates another thread's failed probe landing between this request's
    # time check and its probe: the probe must re-check the deadline.
    broken = BrokenStorage(RedisConnectionError("down"))
    limiter: RateLimiter
    reads = [0]

    def clock() -> float:
        # Reads: 1 time check and 2 failure mark (first hit), 3 time check and
        # 4 re-check inside the probe (second hit).
        reads[0] += 1
        if reads[0] == 4:
            limiter._primary_down_until = 61.0  # another probe just failed
        return 0.0 if reads[0] <= 2 else 31.0

    limiter = RateLimiter(UNREACHABLE, primary_storage=broken, clock=clock)
    limiter.hit("5/minute", "k")
    assert broken.calls == 1

    limiter.hit("5/minute", "k")

    assert broken.calls == 1
